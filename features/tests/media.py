"""Validated immutable private raster images. Never trust a supplied path."""
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import uuid
import warnings

from .errors import TestsError
from .validation import normalize_transport

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_FORMATS = {"PNG": ("image/png", {".png"}),
            "JPEG": ("image/jpeg", {".jpg", ".jpeg"}),
            "GIF": ("image/gif", {".gif"})}


def inspect_upload(upload, alt_text=""):
    """Fully decode the uploaded image, including each animation frame."""
    if upload is None or not isinstance(getattr(upload, "filename", None), str):
        raise TestsError("INVALID_IMAGE", 422, "Выберите изображение.")
    name = upload.filename
    if (not name or any(c in name for c in ("/", "\\", "\x00", ":"))
            or name in {".", ".."} or any(ord(c) < 32 for c in name)):
        raise TestsError("INVALID_IMAGE", 422, "Недопустимое имя изображения.")
    if not isinstance(alt_text, str):
        raise TestsError("INVALID_IMAGE", 422, "Подпись должна быть строкой.")
    try:
        alt_text.encode("utf-8")
    except UnicodeEncodeError:
        raise TestsError("INVALID_IMAGE", 422, "Некорректная подпись изображения.") from None
    data = upload.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise TestsError("MEDIA_TOO_LARGE", 413, "Изображение превышает 5 МБ.")
    if not data:
        raise TestsError("INVALID_IMAGE", 422, "Изображение пустое.")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise TestsError("IMAGE_DECODER_UNAVAILABLE", 503,
                         "Проверка изображений временно недоступна.") from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                if image_format not in _FORMATS:
                    raise TestsError("UNSUPPORTED_IMAGE", 415, "Разрешены PNG, JPEG и GIF.")
                mime, suffixes = _FORMATS[image_format]
                if upload.mimetype != mime or Path(name).suffix.lower() not in suffixes:
                    raise TestsError("IMAGE_TYPE_MISMATCH", 415,
                                     "Тип, расширение и содержимое изображения не совпадают.")
                width, height = image.size
                image.verify()
            with Image.open(BytesIO(data)) as image:
                for frame in range(getattr(image, "n_frames", 1)):
                    image.seek(frame)
                    image.load()
    except TestsError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise TestsError("INVALID_IMAGE", 422, "Не удалось прочитать изображение.") from None
    return data, {"mime_type": mime, "size_bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(), "width": width,
                  "height": height, "alt_text": normalize_transport(alt_text)}


def _target(root, storage_key):
    if not isinstance(storage_key, str) or not re.fullmatch(r"[0-9a-f]{32}", storage_key):
        raise TestsError("NOT_FOUND", 404, "Изображение не найдено.")
    root = Path(root).resolve()
    path = root / storage_key
    if path.is_symlink() or path.resolve().parent != root:
        raise TestsError("NOT_FOUND", 404, "Изображение не найдено.")
    return path


def stage_upload(root, upload, alt_text=""):
    """Write complete verified bytes before the caller starts its DB transaction."""
    data, descriptor = inspect_upload(upload, alt_text)
    root = Path(root).resolve()
    key = uuid.uuid4().hex
    target = _target(root, key)
    created = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if created:
            remove_staged(root, key)
        raise TestsError("MEDIA_STORAGE_UNAVAILABLE", 503,
                         "Не удалось сохранить изображение. Повторите запрос.") from None
    return dict(descriptor, storage_key=key)


def resolve_media_path(root, storage_key):
    path = _target(root, storage_key)
    if not path.is_file():
        raise TestsError("NOT_FOUND", 404, "Изображение не найдено.")
    return path


def remove_staged(root, storage_key):
    """Best-effort cleanup of a caller-owned unreferenced staging file only."""
    path = _target(root, storage_key)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # A leftover private orphan is safer than rolling back a committed link.
        return False
    return True
