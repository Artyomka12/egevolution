# Production test deadlines

## Status and safety gate

Prepared for GitHub. Native Linux acceptance is intentionally deferred to the
owner on REG.RU. DO NOT enable production cron or replace maintenance WSGI until
that acceptance passes. Windows tests do not prove native flock/pysqlite3 behavior.
No server action is performed by this change.

The worker imports pysqlite3 before services/SQLite consumers, never imports
app.py or reads .env, and never creates or migrates a database. Ordinary python
app.py does not import or start this worker. Local-worker protection is unchanged.

Every Passenger process reads the database-bound heartbeat on each test catalog,
detail and start request. Missing, corrupt, future, insecure, wrong-database or
older-than-180-seconds heartbeat blocks new attempts. Existing attempts may still
be continued; other sections remain available. There is no process-local cache.
The production environment variable must be set in every Passenger process.
Without it the existing local TESTS_STARTS_ENABLED behavior is preserved.

Use the same Unix account, DB and JSON content root for cron and Passenger.
The private runtime directory must be mode 0700, outside all document roots;
heartbeat is atomically replaced with mode 0600 after all expired batches finish.
Failures do not refresh it. Lock files must never be deleted while workers run.
External cron flock prevents overlapping cron jobs. Internal runtime and database
inode flocks also reject direct competing invocations, including a different
runtime directory. No schema changes or automatic migrations occur in the worker.

## Isolated Linux acceptance (run manually, not through production cron)

These are shell one-liners. They do not import the real app or open the working
users.db. Fixtures create fictitious users/content and prepare schemas exclusively
inside temporary directories. Existing databases are not migrated. The tests read
app.py as text to extract legacy CREATE statements; they do not execute app.py.
Use the deployed GitHub revision containing this file and the tests.

Check interpreter and flock first:

```sh
/var/www/u3541405/data/egevolution-venv312/bin/python -B -c 'import pysqlite3,fcntl; print(pysqlite3.sqlite_version); assert pysqlite3.sqlite_version_info >= (3,26,0)' && command -v flock && command -v crontab
```

Create a unique private temporary test root (same shell for subsequent commands):

```sh
umask 077; export QA_DIR="$(mktemp -d /var/www/u3541405/data/egevolution-backups/worker-qa-XXXXXXXX)"; test -n "$QA_DIR" && test -d "$QA_DIR" && chmod 700 "$QA_DIR"
```

Run production-worker tests with pysqlite3 installed as sqlite3 BEFORE imports.
Expected: 8 tests, OK, zero skips on Linux. This includes real CLI subprocesses,
real flock contention on both locks, deadlines, heartbeat permissions, fresh/stale
start gates, active access, DB integrity and idempotent rerun:

```sh
(cd /var/www/u3541405/data/www/egevolution.ru && TMPDIR="$QA_DIR" /var/www/u3541405/data/egevolution-venv312/bin/python -B -c 'import sys,pysqlite3,unittest; sys.modules["sqlite3"]=pysqlite3; sys.modules["sqlite3.dbapi2"]=pysqlite3.dbapi2; sys.path.insert(0,"tests"); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests",pattern="test_production_worker.py")); sys.exit(0 if r.wasSuccessful() and not r.skipped else 1)')
```

Verify external flock exclusivity without any database:

```sh
/usr/bin/flock -n "$QA_DIR/cron-check.lock" sh -c '/usr/bin/flock -n "$1" true; test "$?" -eq 1' sh "$QA_DIR/cron-check.lock"
```

Do not enable production if any command fails. Keep diagnostic output; do not
publish environment secrets. Tests clean their own fixtures; the outer QA_DIR
and its cron-check.lock may remain for inspection. No real DB is copied or read.

## Future production activation (NOT executed by Codex)

Only after Linux acceptance and owner approval. Paths below assume the working
DB is the project's root users.db and JSON lives in the project; verify that this
matches the current WSGI configuration before activation. SQLite 3.51.1 was
reported by the owner; the interpreter command above verifies the actual version.

Create a dedicated runtime directory outside the public tree:

```sh
install -d -m 700 /var/www/u3541405/data/egevolution-backups/tests-worker-runtime
```

First manual production pass (this DOES finalize real expired attempts; only
run after approval, never as an isolated test):

```sh
umask 077; EGEVOLUTION_CONTENT_ROOT=/var/www/u3541405/data/www/egevolution.ru /usr/bin/flock -n /var/www/u3541405/data/egevolution-backups/tests-worker-runtime/cron.lock /var/www/u3541405/data/egevolution-venv312/bin/python -B /var/www/u3541405/data/www/egevolution.ru/scripts/expire_tests_production.py --database /var/www/u3541405/data/www/egevolution.ru/users.db --heartbeat /var/www/u3541405/data/egevolution-backups/tests-worker-runtime/heartbeat.json
```

Use `crontab -e`, preserve existing jobs, add this line ONCE (do not replace the
entire crontab). Rotate the private log using the hosting account's log policy:

```cron
* * * * * umask 077; EGEVOLUTION_CONTENT_ROOT=/var/www/u3541405/data/www/egevolution.ru /usr/bin/flock -n /var/www/u3541405/data/egevolution-backups/tests-worker-runtime/cron.lock /var/www/u3541405/data/egevolution-venv312/bin/python -B /var/www/u3541405/data/www/egevolution.ru/scripts/expire_tests_production.py --database /var/www/u3541405/data/www/egevolution.ru/users.db --heartbeat /var/www/u3541405/data/egevolution-backups/tests-worker-runtime/heartbeat.json >> /var/www/u3541405/data/egevolution-backups/tests-worker-runtime/worker.log 2>&1
```

## Future Passenger WSGI configuration

Preserve the current virtualenv/sys.path and secret-loading configuration. Insert
this Python line BEFORE imports of app, services or sqlite3 in the production
WSGI entrypoint (not in the maintenance stub):

```python
import os, sys, pysqlite3; sys.modules['sqlite3'] = pysqlite3; sys.modules['sqlite3.dbapi2'] = pysqlite3.dbapi2; os.environ['EGEVOLUTION_DB_PATH'] = '/var/www/u3541405/data/www/egevolution.ru/users.db'; os.environ['EGEVOLUTION_CONTENT_ROOT'] = '/var/www/u3541405/data/www/egevolution.ru'; os.environ['EGEVOLUTION_TESTS_HEARTBEAT'] = '/var/www/u3541405/data/egevolution-backups/tests-worker-runtime/heartbeat.json'
```

Keep `from app import app as application`. Never start the local worker inside
Passenger or manually force TESTS_STARTS_ENABLED=True. Restart Passenger only by
the existing approved procedure after restoring production WSGI; do not restart
or disable maintenance as part of the isolated tests above.

Rollback: stop the new cron job, keep heartbeat configuration; new starts close
within 180 seconds. Do not roll back learner data or replace users.db.
