"""One production deadline pass. No app import, dotenv loading or migrations."""
import argparse
from contextlib import closing, ExitStack
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_once(database, heartbeat):
    from features.tests import repository, service
    from core.production_worker import write_heartbeat
    count = 0
    with closing(repository.connect(database)) as db:
        while True:
            batch = service.expire_attempts(db, batch_size=100)
            count += batch
            if batch < 100:
                break
    write_heartbeat(heartbeat, database)
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--heartbeat', required=True)
    args = parser.parse_args(argv)
    try:
        # Deliberately fail closed: production must never silently use old sqlite3.
        import pysqlite3
        sys.modules['sqlite3'] = pysqlite3
        sys.modules['sqlite3.dbapi2'] = pysqlite3.dbapi2
        import fcntl
        from core.production_worker import private_directory
        database = Path(args.database).resolve(strict=True)
        heartbeat = Path(args.heartbeat).absolute()
        directory = private_directory(heartbeat.parent)
        heartbeat = directory / heartbeat.name
        if directory == ROOT or ROOT in directory.parents:
            raise ValueError('Heartbeat must be outside the application/public tree')
        # Internal lock also protects against accidental direct runs without cron flock.
        fd = os.open(directory / 'tests-worker.internal.lock',
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with ExitStack() as stack:
            lock = stack.enter_context(os.fdopen(fd, 'a'))
            # Lock the database inode too: different runtime directories must not
            # permit duplicate workers. flock is independent of SQLite's locks.
            database_lock = stack.enter_context(database.open('rb'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(database_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('worker=already_running')
                return 0
            count = run_once(database, heartbeat)
        print(f'finalized={count}')
        return 0
    except Exception:
        # Do not disclose SQL, paths, answers or environment secrets in cron output.
        print('worker=failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
