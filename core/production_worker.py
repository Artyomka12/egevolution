"""Private, database-bound heartbeat shared by independent Passenger processes."""
import json
import os
from pathlib import Path
import stat
import tempfile
import time


def private_directory(path):
    directory = Path(path).absolute()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Existing private runtime directory required')
    if os.name == 'posix':
        info = directory.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('Runtime directory must be owned by this user with mode 0700')
    return directory.resolve()


def write_heartbeat(path, database):
    path = Path(path)
    directory = private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.heartbeat-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'database': str(Path(database).resolve()), 'completed_at': time.time()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def heartbeat_fresh(path, database):
    try:
        path = Path(path)
        private_directory(path.parent)
        if path.is_symlink():
            return False
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            return False
        if os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            return False
        data = json.loads(path.read_text(encoding='utf-8'))
        age = time.time() - data['completed_at']
        return data['database'] == str(Path(database).resolve()) and 0 <= age <= 180
    except (OSError, ValueError, TypeError, KeyError):
        return False


def starts_enabled(app):
    # Presence of production configuration overrides even a stale in-memory True.
    path = os.environ.get('EGEVOLUTION_TESTS_HEARTBEAT')
    if path is not None:
        from database_config import resolve_database_path
        try:
            return heartbeat_fresh(path, resolve_database_path())
        except (OSError, ValueError, RuntimeError):
            return False
    return app.config['TESTS_STARTS_ENABLED']
