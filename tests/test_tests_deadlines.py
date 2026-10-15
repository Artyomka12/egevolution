import os
import io
import sqlite3
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from features.tests import repository as repo, service
from tests_support import StudentHTTPCase, ROOT


class DeadlineTests(StudentHTTPCase):
    def test_worker_protected_database_aliases_rejected_before_connect(self):
        from scripts import expire_test_attempts as worker
        fake_root = self.root / "worker-project"
        (fake_root / ".local-data").mkdir(parents=True)
        for name in ("users.db", ".local-data/dev-users.db", ".local-data/thematic-stage13.db"):
            protected = fake_root / name
            protected.write_bytes(b"synthetic not a database")
            alias = self.root / (protected.name+".alias")
            alias.hardlink_to(protected)
            with mock.patch.object(worker, "ROOT", fake_root), mock.patch.object(repo, "connect", side_effect=AssertionError("must not connect")):
                for path in (protected, alias):
                    with self.assertRaises(ValueError):
                        worker.checked_database(path)

    def test_worker_busy_loop_retries_but_unsafe_database_errors_stop_safely(self):
        from scripts import expire_test_attempts as worker
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(service, "expire_attempts", side_effect=[sqlite3.OperationalError("database locked PRIVATE_SQL"), 0, KeyboardInterrupt]) as expire, \
                mock.patch.object(worker.time, "sleep") as sleep, redirect_stdout(output), redirect_stderr(errors):
            result = worker.main(["--database", str(self.path), "--loop", "--interval", "0.1"])
        self.assertEqual(result, 0)
        self.assertEqual(expire.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("error=DB_BUSY", errors.getvalue())
        self.assertNotIn("PRIVATE_SQL", errors.getvalue())
        errors = io.StringIO()
        with mock.patch.object(service, "expire_attempts", side_effect=sqlite3.OperationalError("PRIVATE_SCHEMA")), redirect_stderr(errors):
            result = worker.main(["--database", str(self.path)])
        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue().strip(), "error=DATABASE_UNAVAILABLE")

    def test_standalone_worker_process_without_app_and_restart(self):
        attempt = self.start()
        # The synthetic clock is in 2023; real worker time is after its deadline.
        environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
        environment.update(PYTHONDONTWRITEBYTECODE="1", EGEVOLUTION_LOCAL_CHECK="1",
                           EGEVOLUTION_DB_PATH=str(self.path))
        command = [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts/expire_test_attempts.py"),
                   "--database", str(self.path)]
        first = subprocess.run(command, env=environment, cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("finalized=1", first.stdout)
        db = self.open()
        before = repo.get_attempt(db, attempt["attempt_id"])
        self.assertEqual(before["state"], "graded")
        second = subprocess.run(command, env=environment, cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("finalized=0", second.stdout)
        self.assertEqual(repo.get_attempt(db, attempt["attempt_id"]), before)

    def test_exact_deadline_rejects_save_commits_timeout_with_saved_answers(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        self.clock.advance(59999)
        self.assertEqual(self.save_answer(attempt, writer, question, "0").status_code, 200)
        self.clock.advance(1)
        expired = self.save_answer(attempt, writer, question, "late", revision=1)
        self.assertEqual(expired.status_code, 409, expired.text)
        self.assertEqual(expired.json["error"]["code"], "DEADLINE_REACHED")
        db = self.open()
        persisted = repo.get_attempt(db, attempt["attempt_id"])
        self.assertEqual(persisted["state"], "graded")
        self.assertEqual(persisted["finish_reason"], "timeout")
        self.assertEqual(persisted["submitted_at"], persisted["deadline_at"])
        answer = repo.get_answer(db, attempt["attempt_id"], question)
        self.assertEqual(answer["answer"], "0")
        self.assertEqual(answer["score"], 1)
        self.assertEqual(persisted["result_revision"], 1)

    def test_expired_submit_ignores_final_batch_and_late_worker_keeps_deadline(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        self.clock.advance(90000)
        response = self.submit(attempt, writer, [{"question_id": question, "answer": "0", "expected_revision": 0}])
        self.assertIn(response.status_code, (200, 409), response.text)
        db = self.open()
        answer = repo.get_answer(db, attempt["attempt_id"], question)
        self.assertIsNone(answer["answer"])
        self.assertEqual(answer["score"], 0)
        persisted = repo.get_attempt(db, attempt["attempt_id"])
        self.assertEqual(persisted["submitted_at"], persisted["deadline_at"])
        self.assertEqual(persisted["finalized_at"], self.clock())
        result = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/result')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["remaining_seconds"], 0)
        self.assertEqual(result.json["elapsed_seconds"], 60)

    def test_get_fallback_and_worker_restart_finalize_once(self):
        attempt = self.start()
        self.clock.advance(61000)
        response = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}')
        self.assertEqual(response.status_code, 200, response.text)
        db = self.open()
        before = repo.get_attempt(db, attempt["attempt_id"])
        self.assertNotEqual(before["state"], "active")
        service.expire_attempts(db)
        service.expire_attempts(db)
        self.assertEqual(repo.get_attempt(db, attempt["attempt_id"]), before)

    def test_heartbeat_does_not_extend_deadline_and_finished_time_freezes(self):
        attempt = self.start()
        writer = self.claim(attempt)
        db = self.open()
        deadline = repo.get_attempt(db, attempt["attempt_id"])["deadline_at"]
        self.clock.advance(11000)
        beat = self.write(f'/api/tests/attempts/{attempt["attempt_id"]}/heartbeat', "POST",
                          {"generation": writer["generation"]}, writer["writer_token"])
        self.assertEqual(beat.status_code, 200, beat.text)
        self.assertEqual(repo.get_attempt(db, attempt["attempt_id"])["deadline_at"], deadline)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        self.clock.advance(1000000)
        result = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/result')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["remaining_seconds"], 49)
        self.assertEqual(result.json["elapsed_seconds"], 11)
