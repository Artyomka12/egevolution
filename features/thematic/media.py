"""Private content-addressed copies. No live-bank URL survives publication."""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import zipfile
import zlib
from io import BytesIO

MAX_BYTES = 64 * 1024 * 1024


def inspect_bytes(data, name, image=False):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Материал пуст или превышает 64 МБ')
    width = height = None
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 33 and data[12:16] == b'IHDR':
        mime = 'image/png'
        width, height = struct.unpack('>II', data[16:24])
        offset, ended, has_pixels = 8, False, False
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], 'big')
            end = offset + 12 + size
            if end > len(data):
                raise ValueError('Обрезанный PNG')
            chunk = data[offset + 4:offset + 8 + size]
            crc = int.from_bytes(data[offset + 8 + size:end], 'big')
            if zlib.crc32(chunk) != crc:
                raise ValueError('Повреждённый PNG')
            has_pixels = has_pixels or chunk[:4] == b'IDAT'
            offset = end
            if chunk[:4] == b'IEND':
                ended = size == 0 and offset == len(data)
                break
        if not ended or not has_pixels:
            raise ValueError('Незавершённый PNG')
    elif data.startswith((b'GIF87a', b'GIF89a')) and len(data) >= 13:
        mime = 'image/gif'
        width, height = struct.unpack('<HH', data[6:10])
    elif data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        mime = 'image/jpeg'
        # Read JPEG frame dimensions without introducing an image dependency.
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 255:
                break
            marker = data[offset + 1]
            if marker == 255:
                offset += 1
                continue
            if marker in {0xd8, 0xd9}:
                offset += 2
                continue
            size = int.from_bytes(data[offset + 2:offset + 4], 'big')
            if size < 2 or offset + 2 + size > len(data):
                break
            if marker in {0xc0, 0xc1, 0xc2} and size >= 8:
                height, width = struct.unpack('>HH', data[offset + 5:offset + 9])
                break
            offset += size + 2
        if width is None:
            raise ValueError('Не удалось прочитать размеры JPEG')
    elif not image:
        suffix = Path(name).suffix.lower()
        if suffix in {'.txt', '.csv'} and b'\0' not in data:
            mime = 'text/plain'
        elif suffix in {'.zip', '.xls', '.xlsx', '.ods', '.odt'} and zipfile.is_zipfile(BytesIO(data)):
            mime = 'application/octet-stream'
        elif suffix == '.xls' and data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            mime = 'application/octet-stream'
        elif suffix in {'.db', '.sqlite'} and data.startswith(b'SQLite format 3\0'):
            mime = 'application/octet-stream'
        else:
            raise ValueError('Неподдерживаемый формат вложения')
    else:
        raise ValueError('Разрешены только растровые изображения PNG, JPEG и GIF')
    if image and (not width or not height or width * height > 40_000_000):
        raise ValueError('Недопустимый размер изображения')
    return mime, width, height


def read_material(path, image=False):
    path = Path(path)
    before = path.stat()
    if before.st_size > MAX_BYTES:
        raise ValueError('Материал превышает 64 МБ')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Материал изменился во время чтения; повторите публикацию')
    mime, width, height = inspect_bytes(data, path.name, image)
    return data, {'sha256': hashlib.sha256(data).hexdigest(), 'mime_type': mime,
                  'size_bytes': len(data), 'width': width, 'height': height, 'original_name': path.name}


def stage(root, path, image=False):
    data, info = read_material(path, image)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = info['sha256']
    target = root / key
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != key:
            raise ValueError('Повреждена закрытая копия материала')
    else:
        # Complete bytes before exposing the content-addressed name. Concurrent
        # writers can replace only an identical hash, never another version.
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, prefix='.staging-', delete=False) as stream:
                temp = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    return dict(info, storage_key=key)


def register(db, info, now):
    from . import repository
    row = next((r for r in repository.rows(db, 'media') if r['storage_key'] == info['storage_key']), None)
    if row:
        if row['sha256'] != info['sha256']:
            raise ValueError('Несогласованные метаданные материала')
        return row['id']
    return repository.insert(db, 'media', dict(info, created_at=now))
