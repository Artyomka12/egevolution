import json
import os
import sqlite3
import time
import types
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

from core.production_worker import heartbeat_fresh, write_heartbeat
from features.tests import repository
from scripts.expire_tests_production import run_once
from tests_support import StudentHTTPCase, ROOT


class ProductionWorkerTests(StudentHTTPCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.heartbeat = self.runtime / 'heartbeat.json'
        self.environment = mock.patch.dict(os.environ, {
            'EGEVOLUTION_TESTS_HEARTBEAT': str(self.heartbeat),
            'EGEVOLUTION_DB_PATH': str(self.path),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def start_response(self):
        return self.call(f'/api/tests/{self.test_id}/attempts', 'POST', {'request_key': self.key()})

    def test_missing_stale_and_malformed_heartbeat_block_only_new_starts(self):
        self.assertEqual(self.start_response().status_code, 503)
        self.assertEqual(self.call('/api/tests').status_code, 200)
        self.assertEqual(self.client.get('/login').status_code, 200)
        for stamp in (time.time() - 181, time.time() + 60):
            self.heartbeat.write_text(json.dumps({'database': str(self.path), 'completed_at': stamp}))
            self.assertEqual(self.start_response().status_code, 503)
        self.heartbeat.write_text('invalid JSON')
        self.assertEqual(self.start_response().status_code, 503)

    def test_deadline_run_writes_heartbeat_and_is_idempotent(self):
        write_heartbeat(self.heartbeat, self.path)
        attempt = self.start()
        self.clock.advance(60000)
        self.assertEqual(run_once(self.path, self.heartbeat), 1)
        self.assertTrue(heartbeat_fresh(self.heartbeat, self.path))
        db = self.open()
        row = repository.get_attempt(db, attempt['attempt_id'])
        self.assertEqual(row['state'], 'graded')
        self.assertEqual(row['finish_reason'], 'timeout')
        self.assertEqual(row['submitted_at'], row['deadline_at'])
        self.assertEqual(run_once(self.path, self.heartbeat), 0)
        self.assertEqual(repository.get_attempt(db, attempt['attempt_id']), row)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_failure_does_not_publish_success(self):
        with mock.patch('features.tests.service.expire_attempts', side_effect=sqlite3.OperationalError('failure')):
            with self.assertRaises(sqlite3.OperationalError):
                run_once(self.path, self.heartbeat)
        self.assertFalse(self.heartbeat.exists())
        self.assertEqual(self.start_response().status_code, 503)

    def test_heartbeat_rechecked_and_active_attempt_remains_available(self):
        write_heartbeat(self.heartbeat, self.path)
        attempt = self.start()
        self.heartbeat.unlink()
        self.assertEqual(self.call(f'/api/tests/attempts/{attempt["attempt_id"]}').status_code, 200)
        self.login(3)
        self.assertEqual(self.start_response().status_code, 503)
        write_heartbeat(self.heartbeat, self.path)
        self.assertEqual(self.start_response().status_code, 201)

    def test_wrong_database_and_age_boundary(self):
        write_heartbeat(self.heartbeat, self.path)
        stamp = json.loads(self.heartbeat.read_text())['completed_at']
        with mock.patch('core.production_worker.time.time', return_value=stamp + 180):
            self.assertTrue(heartbeat_fresh(self.heartbeat, self.path))
        with mock.patch('core.production_worker.time.time', return_value=stamp + 180.001):
            self.assertFalse(heartbeat_fresh(self.heartbeat, self.path))
        self.assertFalse(heartbeat_fresh(self.heartbeat, self.root / 'other.db'))

    def test_cli_contending_lock_never_opens_database_or_writes_heartbeat(self):
        # Linux API contract test; not a substitute for native flock QA.
        from scripts import expire_tests_production as worker
        fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4,
            flock=mock.Mock(side_effect=BlockingIOError()))
        with mock.patch.dict('sys.modules', {'pysqlite3': sqlite3, 'fcntl': fake_fcntl}), \
                mock.patch.object(os, 'O_NOFOLLOW', 0, create=True), \
                mock.patch.object(worker, 'run_once') as run, redirect_stdout(io.StringIO()):
            self.assertEqual(worker.main(['--database', str(self.path), '--heartbeat', str(self.heartbeat)]), 0)
        run.assert_not_called()
        self.assertFalse(self.heartbeat.exists())

    def test_cli_missing_pysqlite3_fails_closed(self):
        from scripts import expire_tests_production as worker
        with mock.patch.dict('sys.modules', {'pysqlite3': None}), \
                mock.patch.object(worker, 'run_once') as run, redirect_stderr(io.StringIO()):
            self.assertEqual(worker.main(['--database', str(self.path), '--heartbeat', str(self.heartbeat)]), 1)
        run.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Native Linux flock/pysqlite3 acceptance runs on server only')
    def test_native_linux_cli_deadlines_and_exclusive_lock(self):
        import fcntl
        import pysqlite3
        self.assertGreaterEqual(pysqlite3.sqlite_version_info, (3, 26, 0))
        write_heartbeat(self.heartbeat, self.path)
        attempt = self.start()
        self.heartbeat.unlink()
        env = os.environ.copy()
        env.update(EGEVOLUTION_CONTENT_ROOT=str(self.root), EGEVOLUTION_DB_PATH=str(self.path),
                   PYTHONDONTWRITEBYTECODE='1')
        command = [sys.executable, '-B', str(ROOT / 'scripts/expire_tests_production.py'),
                   '--database', str(self.path), '--heartbeat', str(self.heartbeat)]
        for target in (self.runtime / 'tests-worker.internal.lock', self.path):
            with target.open('a+b' if target != self.path else 'rb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('already_running', result.stdout)
                self.assertFalse(self.heartbeat.exists())
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('finalized=1', result.stdout)
        self.assertTrue(heartbeat_fresh(self.heartbeat, self.path))
        self.assertEqual(self.heartbeat.stat().st_mode & 0o777, 0o600)
        db = self.open()
        self.assertEqual(repository.get_attempt(db, attempt['attempt_id'])['finish_reason'], 'timeout')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('finalized=0', result.stdout)
