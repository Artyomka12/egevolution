"""Windows direct-launch development runtime. No automatic copying or migration."""
from contextlib import closing
import hashlib
import os
import sqlite3
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parents[1]


def default_database():
    return ROOT / 'users.db'


def validate_database(database):
    """Read-only preflight, before legacy app initialization can write anything."""
    from scripts.migrate import migrate, MigrationError
    path = Path(database).resolve()
    if not path.is_file():
        raise RuntimeError('Prepared local database is missing: ' + str(path) +
                           '. Restore or prepare it explicitly; startup never creates or migrates a database.')
    try:
        report = migrate(path)
    except (MigrationError, OSError, ValueError, sqlite3.Error) as error:
        raise RuntimeError('Local database schema/integrity check failed. No migrations were run; '
                           'check EGEVOLUTION_DB_PATH and the migration audit.') from error
    if report['pending']:
        raise RuntimeError('Local database needs migrations: ' + ', '.join(report['pending']) +
                           '. No migrations were run. Check EGEVOLUTION_DB_PATH; '
                           'the prepared default is users.db.')
    return path


class DeadlineWorker:
    """One local process per DB; lock survives reloader/crash without stale PID rules."""
    def __init__(self, database, interval=1.0):
        self.database = Path(database).resolve()
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = None
        self.failed = False

    @property
    def healthy(self):
        return self.thread is not None and self.thread.is_alive() and not self.failed

    def tick(self):
        from features.tests import repository, service
        with closing(repository.connect(self.database)) as db:
            service.expire_attempts(db, batch_size=100)

    def start(self):
        import msvcrt
        key = hashlib.sha256(os.path.normcase(str(self.database)).encode('utf-8')).hexdigest()[:24]
        self.lock = (self.database.parent / ('.local-worker-' + key + '.lock')).open('a+b')
        self.lock.seek(0, 2)
        if self.lock.tell() == 0:
            self.lock.write(b'0')
            self.lock.flush()
        self.lock.seek(0)
        try:
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock.close()
            self.lock = None
            raise RuntimeError('A local instance already owns this database worker. '
                               'Stop that instance before restarting; it was not stopped automatically.') from None
        try:
            self.tick()
            self.thread = threading.Thread(target=self._run, name='ege-local-deadlines', daemon=True)
            self.thread.start()
        except BaseException:
            self.close()
            raise

    def _run(self):
        import sqlite3
        while not self.stop_event.wait(self.interval):
            try:
                self.tick()
            except sqlite3.OperationalError as error:
                if any(x in str(error).lower() for x in ('locked', 'busy')):
                    continue
                self.failed = True
                print('Local deadline worker failed; new test starts are disabled.', flush=True)
                return
            except Exception:
                self.failed = True
                print('Local deadline worker failed; new test starts are disabled.', flush=True)
                return

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                # Retain ownership until process exit rather than start another writer.
                return
        if self.lock is not None:
            import msvcrt
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.lock.close()
            self.lock = None


def run_local(app, database):
    worker = DeadlineWorker(database)
    worker.start()

    @app.before_request
    def worker_health():
        app.config['TESTS_STARTS_ENABLED'] = worker.healthy

    app.config['TESTS_STARTS_ENABLED'] = worker.healthy
    print('Local database: ' + str(database), flush=True)
    print('Local deadline worker active; automatic migrations disabled.', flush=True)
    try:
        # No second import/worker from the debugger reloader. Production imports never enter here.
        app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
    finally:
        app.config['TESTS_STARTS_ENABLED'] = False
        worker.close()