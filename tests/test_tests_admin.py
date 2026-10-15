from features.tests import repository as repo
from copy import deepcopy
from unittest import mock

from tests_support import AdminHTTPCase, document


class AdminTests(AdminHTTPCase):
    def test_current_roles_guest_student_revoked_deleted_admin(self):
        surfaces = [("/admin/tests", "GET"), ("/admin/tests/new", "GET"),
                    ("/api/admin/tests", "GET"), ("/api/admin/tests", "POST"),
                    ("/api/admin/tests/1/draft", "GET"), ("/api/admin/tests/1/draft", "PUT"),
                    ("/api/admin/tests/1/publish", "POST"), ("/api/admin/tests/1/copy", "POST"),
                    ("/api/admin/tests/1/visibility", "PATCH"), ("/api/admin/tests/order", "PUT"),
                    ("/api/admin/tests/1", "DELETE"), ("/api/admin/tests/1/media/1", "GET")]
        self.login(2)
        with self.client.session_transaction() as session:
            session["is_admin"] = True
        for path, method in surfaces:
            with self.subTest(path=path, method=method):
                response = self.call(path, method, {} if method != "GET" else None)
                self.assertEqual(response.status_code, 403, response.text)
        self.login(None)
        self.assertEqual(self.call("/api/admin/tests").status_code, 401)
        self.assertEqual(self.call("/admin/tests").status_code, 302)
        self.login(1)
        db = self.open()
        db.execute("UPDATE users SET is_admin=0 WHERE id=1")
        self.assertEqual(self.call("/api/admin/tests").status_code, 403)
        db.execute("DELETE FROM users WHERE id=1")
        self.assertEqual(self.call("/api/admin/tests").status_code, 401)

    def test_csrf_all_json_mutations(self):
        paths = [("/api/admin/tests", "POST"), ("/api/admin/tests/1/draft", "PUT"),
                 ("/api/admin/tests/1/publish", "POST"), ("/api/admin/tests/1/visibility", "PATCH"),
                 ("/api/admin/tests/1/copy", "POST"), ("/api/admin/tests/order", "PUT"),
                 ("/api/admin/tests/1", "DELETE")]
        for path, method in paths:
            with self.subTest(path=path):
                self.assertEqual(self.call(path, method, {}, csrf=False).status_code, 400)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM tests").fetchone()[0], 0)

    def test_create_replay_and_reused_body_key(self):
        first = self.create("same-create")
        self.assertEqual(self.create("same-create")["id"], first["id"])
        saved = self.save(first, key="same-save")
        self.assertEqual(saved.status_code, 200, saved.text)
        replay = self.save(first, key="same-save")
        self.assertEqual(replay.status_code, 200, replay.text)
        changed = document()
        changed["title"] = "Another title"
        rejected = self.save(first, changed, key="same-save")
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM tests").fetchone()[0], 1)
        self.open().execute("UPDATE users SET is_admin=0 WHERE id=1")
        replay_without_rights = self.call("/api/admin/tests", "POST", {"request_key": "same-create"})
        self.assertEqual(replay_without_rights.status_code, 403)

    def test_partial_draft_publish_validation_and_stale_save(self):
        draft = self.create()
        response = self.call(f'/api/admin/tests/{draft["id"]}/publish', "POST",
                             {"expected_revision": draft["revision"], "request_key": self.key()})
        self.assertEqual(response.status_code, 422, response.text)
        incomplete = self.save(draft, {"title": "Work in progress", "questions": []})
        self.assertEqual(incomplete.status_code, 200, incomplete.text)
        stale = self.save(draft)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_versions").fetchone()[0], 0)

    def test_publication_visibility_replay_and_catalog_order(self):
        test, publication = self.published()
        body = {"published": False, "expected_revision": publication["revision"], "request_key": self.key()}
        hidden = self.call(f"/api/admin/tests/{test}/visibility", "PATCH", body)
        self.assertEqual(hidden.status_code, 200, hidden.text)
        self.assertEqual(self.call(f"/api/admin/tests/{test}/visibility", "PATCH", body).status_code, 200)
        stale = self.call(f"/api/admin/tests/{test}/visibility", "PATCH", {**body, "published": True, "request_key": self.key()})
        self.assertEqual(stale.status_code, 409)
        shown = self.call(f"/api/admin/tests/{test}/visibility", "PATCH",
                          {"published": True, "expected_revision": hidden.json["revision"], "request_key": self.key()})
        self.assertEqual(shown.status_code, 200, shown.text)
        second = self.create()
        catalog = self.call("/api/admin/tests").json
        for bad in ([test], [test, test], [test, 99999]):
            response = self.call("/api/admin/tests/order", "PUT",
                                 {"test_ids": bad, "expected_revision": catalog["revision"], "request_key": self.key()})
            self.assertEqual(response.status_code, 422, response.text)
        ordered = self.call("/api/admin/tests/order", "PUT",
                             {"test_ids": [second["id"], test], "expected_revision": catalog["revision"], "request_key": self.key()})
        self.assertEqual(ordered.status_code, 200, ordered.text)
        rows = repo.list_tests(self.open())
        self.assertEqual([row["id"] for row in rows], [second["id"], test])

    def test_schema_guard_write_flag_private_headers(self):
        self.app.config["TESTS_ADMIN_WRITES_ENABLED"] = False
        denied = self.call("/api/admin/tests", "POST", {"request_key": self.key()})
        self.assertEqual(denied.status_code, 503)
        response = self.call("/api/admin/tests")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])
        self.open().execute("DELETE FROM schema_migrations WHERE version='003_json_content.sql'")
        self.assertEqual(self.call("/api/admin/tests").status_code, 503)

    def test_catalog_uses_published_content_until_next_publication(self):
        test, _ = self.published()
        draft = self.call(f"/api/admin/tests/{test}/draft").json
        changed = document()
        changed.update(title="Unpublished title", time_limit_seconds=999)
        changed["questions"] = changed["questions"][:1]
        self.assertEqual(self.save(draft, changed).status_code, 200)
        item = self.call("/api/admin/tests").json["tests"][0]
        self.assertEqual(item["title"], "Synthetic test")
        self.assertEqual(item["question_count"], 3)
        self.assertEqual(item["time_limit_seconds"], 60)

    def test_unrepresentable_route_ids_fail_as_client_errors(self):
        for path in (f'/api/admin/tests/{10**100}/draft', f'/api/admin/tests/1/media/{10**100}'):
            response = self.call(path)
            self.assertIn(response.status_code, (400, 404, 422), response.text)

    def test_bad_payload_content_type_safe_errors_and_integer_representation(self):
        malformed = self.client.post("/api/admin/tests", data="[]", content_type="application/json",
                                     headers={"X-CSRFToken": self.csrf})
        self.assertEqual(malformed.status_code, 400)
        wrong = self.client.post("/api/admin/tests", data="x", headers={"X-CSRFToken": self.csrf})
        self.assertEqual(wrong.status_code, 415)
        draft = self.create()
        for field in ("time_limit_seconds", "attempt_limit"):
            bad = document()
            bad[field] = 10**100
            response = self.save(draft, bad)
            self.assertEqual(response.status_code, 422, response.text)
        with mock.patch("features.tests.service.admin_catalog", side_effect=RuntimeError("PRIVATE_SQL_PATH_TOKEN")):
            failed = self.call("/api/admin/tests")
        self.assertEqual(failed.status_code, 500)
        self.assertNotIn("PRIVATE_SQL_PATH_TOKEN", failed.text)
        self.assertIn("request_id", failed.json)

    def test_admin_html_escapes_user_content(self):
        draft = self.create()
        doc = document()
        doc["title"] = '<script>alert("injected")</script>'
        saved = self.save(draft, doc)
        self.assertEqual(saved.status_code, 200, saved.text)
        for path in ("/admin/tests", f'/admin/tests/{draft["id"]}/edit'):
            page = self.call(path)
            self.assertEqual(page.status_code, 200, page.text)
            self.assertNotIn('<script>alert("injected")</script>', page.text)
