from unittest import mock

from features.tests import repository as repo
from tests_support import AdminHTTPCase, document


class VersionTests(AdminHTTPCase):
    def test_publication_cas_consumed_and_failure_rolls_back_version(self):
        draft = self.create()
        saved = self.save(draft)
        self.assertEqual(saved.status_code, 200, saved.text)
        body = {"expected_revision": saved.json["revision"], "request_key": self.key()}
        path = f'/api/admin/tests/{draft["id"]}/publish'
        with mock.patch.object(repo, "record_operation_in_transaction", side_effect=RuntimeError("synthetic fault")):
            failed = self.call(path, "POST", body)
        self.assertEqual(failed.status_code, 500, failed.text)
        db = self.open()
        self.assertIsNone(repo.get_test(db, draft["id"])["current_version_id"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_versions").fetchone()[0], 0)
        first = self.call(path, "POST", body)
        self.assertEqual(first.status_code, 200, first.text)
        stale = self.call(path, "POST", {**body, "request_key": self.key()})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_versions").fetchone()[0], 1)

    def test_published_snapshot_survives_new_draft_and_publication(self):
        test, published = self.published()
        db = self.open()
        old = repo.get_version(db, published["version_id"])
        with repo.transaction(db):
            attempt = repo.create_attempt_in_transaction(db, 2, test, old["id"], request_key="active", now=self.clock())
        draft = self.call(f"/api/admin/tests/{test}/draft").json
        changed = document()
        changed.update(title="Version two", time_limit_seconds=90, show_correct_answers=False)
        changed["questions"][1]["accepted_answers"] = ["new-reference"]
        saved = self.save(draft, changed)
        self.assertEqual(saved.status_code, 200, saved.text)
        body = {"expected_revision": saved.json["revision"], "request_key": self.key()}
        second = self.call(f"/api/admin/tests/{test}/publish", "POST", body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(self.call(f"/api/admin/tests/{test}/publish", "POST", body).json["version_id"], second.json["version_id"])
        self.assertEqual(repo.get_version(db, old["id"]), old)
        self.assertEqual(repo.get_attempt(db, attempt)["version_id"], old["id"])
        self.assertEqual(repo.get_attempt(db, attempt)["deadline_at"], self.clock()+60000)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_versions WHERE test_id=?", (test,)).fetchone()[0], 2)

    def test_copy_has_draft_but_no_attempts_versions_grants_history(self):
        test, published = self.published()
        db = self.open()
        with repo.transaction(db):
            repo.create_attempt_in_transaction(db, 2, test, published["version_id"], request_key="active", now=self.clock())
            repo.add_grant_in_transaction(db, 2, test, 2, actor_id=1, now=self.clock(), request_key="grant")
        response = self.call(f"/api/admin/tests/{test}/copy", "POST", {"request_key": self.key()})
        self.assertIn(response.status_code, (200, 201), response.text)
        copied = response.json["id"]
        self.assertNotEqual(copied, test)
        self.assertEqual(repo.get_test(db, copied)["publication_state"], "draft")
        self.assertIsNone(repo.get_test(db, copied)["current_version_id"])
        for table in ("test_versions", "test_attempts", "test_attempt_grants"):
            self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE test_id=?", (copied,)).fetchone()[0], 0)
        self.assertEqual(len(response.json["document"]["questions"]), 3)

    def test_delete_confirmation_atomicity_active_cascade_receipts_and_replay(self):
        test, published = self.published()
        db = self.open()
        with repo.transaction(db):
            attempt = repo.create_attempt_in_transaction(db, 2, test, published["version_id"], request_key="active", now=self.clock())
            repo.record_operation_in_transaction(db, 2, "start", "active", "a"*64, attempt, self.clock())
        body = {"confirmed": False, "expected_revision": published["revision"], "request_key": self.key()}
        self.assertEqual(self.call(f"/api/admin/tests/{test}", "DELETE", body).status_code, 422)
        body.update(confirmed=True, request_key=self.key())
        with mock.patch.object(repo, "record_operation_in_transaction", side_effect=RuntimeError("PRIVATE_DELETE_FAULT")):
            failed = self.call(f"/api/admin/tests/{test}", "DELETE", body)
        self.assertEqual(failed.status_code, 500, failed.text)
        self.assertNotIn("PRIVATE_DELETE_FAULT", failed.text)
        self.assertIsNotNone(repo.get_test(db, test))
        self.assertIsNotNone(repo.get_attempt(db, attempt))
        deleted = self.call(f"/api/admin/tests/{test}", "DELETE", body)
        self.assertIn(deleted.status_code, (200, 204), deleted.text)
        self.assertIsNone(repo.get_test(db, test))
        self.assertIsNone(repo.get_attempt(db, attempt))
        self.assertEqual(repo.get_answers(db, attempt), [])
        self.assertIsNotNone(repo.get_operation(db, 2, "start", "active"))
        replay = self.call(f"/api/admin/tests/{test}", "DELETE", body)
        self.assertIn(replay.status_code, (200, 204, 404), replay.text)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 0)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
