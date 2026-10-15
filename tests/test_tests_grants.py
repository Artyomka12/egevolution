from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading
from features.tests import repository as repo, service
from tests_support import ReviewHTTPCase


class GrantTests(ReviewHTTPCase):
    def test_concurrent_duplicate_grant_creates_one_history_record(self):
        barrier = threading.Barrier(2)
        def granting(_):
            with closing(repo.connect(self.path)) as db:
                barrier.wait(timeout=3)
                return service.grant_attempts(db, 2, self.test_id, {"amount": 2, "request_key": "race-grant"}, 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(granting, (1, 2)))
        self.assertEqual(results[0]["grant_id"], results[1]["grant_id"])
        self.assertEqual(repo.quota_usage(self.open(), 2, self.test_id)["grants"], 2)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_attempt_grants").fetchone()[0], 1)

    def test_grant_idempotency_pair_isolation_and_quota(self):
        self.login(1)
        other_test, _ = self.published()
        first = self.grant(amount=3, key="same-grant")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json["remaining_attempts"], 5)
        replay = self.grant(amount=3, key="same-grant")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json["grant_id"], first.json["grant_id"])
        changed = self.grant(amount=4, key="same-grant")
        self.assertEqual(changed.status_code, 409)
        for user, test in ((3, self.test_id), (2, other_test)):
            response = self.grant(user=user, test=test, amount=3, key="same-grant")
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        db = self.open()
        self.assertEqual(repo.quota_usage(db, 2, self.test_id), {"used": 0, "grants": 3})
        self.assertEqual(repo.quota_usage(db, 3, self.test_id), {"used": 0, "grants": 0})
        self.assertEqual(repo.quota_usage(db, 2, other_test), {"used": 0, "grants": 0})
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_attempt_grants").fetchone()[0], 1)

    def test_grants_current_limit_and_all_versions_count(self):
        for _ in range(2):
            self.login(2)
            attempt = self.start()
            self.assertEqual(self.submit(attempt, self.claim(attempt)).status_code, 200)
        denied = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": self.key()})
        self.assertEqual(denied.status_code, 409)
        self.login(1)
        added = self.grant(amount=1)
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(added.json["remaining_attempts"], 1)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        draft["document"]["attempt_limit"] = 1
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
                         {"expected_revision": saved.json["revision"], "request_key": self.key()}).status_code, 200)
        self.login(2)
        self.assertEqual(self.call(f"/api/tests/{self.test_id}").json["remaining_attempts"], 0)
        self.login(1)
        self.assertEqual(self.grant(amount=1).json["remaining_attempts"], 1)
        self.login(2)
        self.start()
        self.assertEqual(repo.quota_usage(self.open(), 2, self.test_id)["used"], 3)

    def test_grant_validation_roles_csrf_and_rollback(self):
        self.login(1)
        for amount in (0, -1, True, False, "2", 2.0, 10**100):
            self.assertEqual(self.grant(amount=amount).status_code, 422)
        self.assertEqual(self.grant(user=999).status_code, 404)
        self.assertEqual(self.grant(test=999).status_code, 404)
        path = f"/api/admin/users/2/tests/{self.test_id}/grants"
        self.assertEqual(self.call(path, "POST", {"amount": 1, "request_key": self.key()}, csrf=False).status_code, 400)
        self.login(None)
        self.assertEqual(self.call(path, "POST", {"amount": 1, "request_key": self.key()}, csrf=False).status_code, 401)
        self.login(2)
        self.assertEqual(self.grant().status_code, 403)
        self.login(1)
        with mock.patch.object(repo, "record_operation_in_transaction", side_effect=RuntimeError("synthetic grant failure")):
            self.assertEqual(self.grant(key="rollback-grant").status_code, 500)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_attempt_grants").fetchone()[0], 0)
        self.assertEqual(self.grant(key="rollback-grant").status_code, 200)

    def test_unlimited_quota_stays_unlimited_and_legacy_data_unchanged(self):
        db = self.open()
        db.execute("INSERT INTO user_results(user_id) VALUES(2)")
        before = [tuple(row) for row in db.execute("SELECT * FROM user_results")]
        self.login(1)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        draft["document"]["attempt_limit"] = None
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
                         {"expected_revision": saved.json["revision"], "request_key": self.key()}).status_code, 200)
        granted = self.grant(amount=1001)
        self.assertEqual(granted.status_code, 200, granted.text)
        self.assertIsNone(granted.json["remaining_attempts"])
        attempt, questions = self.pending()
        self.assertEqual(self.grade(attempt, questions[2]["id"], 1).status_code, 200)
        self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM user_results")], before)
