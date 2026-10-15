"""Database selection without importing Flask or opening a connection."""
import os
from pathlib import Path


def local_check_enabled():
    return os.environ.get("EGEVOLUTION_LOCAL_CHECK") == "1"


def resolve_database_path(*, default=None):
    root = Path(__file__).resolve().parent
    original = root / "users.db"
    configured = os.environ.get("EGEVOLUTION_DB_PATH")
    if configured is not None and not configured.strip():
        raise RuntimeError("EGEVOLUTION_DB_PATH must not be empty")
    path = Path(configured).expanduser() if configured is not None else (Path(default) if default is not None else original)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if local_check_enabled():
        if configured is None or not path.is_file():
            raise RuntimeError("Local checks require an existing separate EGEVOLUTION_DB_PATH")
        if path == original.resolve() or (original.exists() and path.samefile(original)):
            raise RuntimeError("Local checks must not use users.db or a link to it")
    return path
