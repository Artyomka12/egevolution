"""Actual Flask integration with synthetic DB, no dotenv/network/working writes."""
from contextlib import contextmanager
import importlib.util
import os
import sqlite3
from unittest import mock

from tests_support import DatabaseCase, ROOT, document


class IntegrationTests(DatabaseCase):
    @contextmanager
    def application(self):
        original = sqlite3.connect

        def guarded(database, *args, **kwargs):
            self.assertEqual(database, self.path.as_uri() + "?mode=rw")
            return original(database, *args, **kwargs)

        with mock.patch.dict(os.environ, {
            "SECRET_KEY": "synthetic-tests-integration", "SITE_PASSWORD": "synthetic",
            "ADMIN_USERNAME": "synthetic-admin", "ADMIN_PASSWORD": "synthetic",
            "EGEVOLUTION_LOCAL_CHECK": "1", "EGEVOLUTION_DB_PATH": str(self.path),
        }, clear=True), mock.patch("dotenv.load_dotenv", return_value=False), \
                mock.patch("sqlite3.connect", side_effect=guarded), \
                mock.patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            spec = importlib.util.spec_from_file_location("tests_isolated_real_app", ROOT / "app.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.EGE_RENUMBER_ARCHIVE = str(self.root / "empty-history.json")
            module.app.config.update(TESTING=True, TESTS_MEDIA_ROOT=str(self.root / "media"),
                                     THEMATIC_MEDIA_ROOT=str(self.root / "thematic-media"))
            yield module.app

    def test_admin_registration_csrf_and_legacy_pages(self):
        self.apply()
        with self.application() as app:
            client = app.test_client()
            self.assertEqual(client.get("/api/admin/tests").status_code, 401)
            with client.session_transaction() as session:
                session["user_id"] = 1
            for url in ("/admin", "/admin/tests", "/admin/tests/new", "/variants",
                        "/theory", "/preparation", "/tasks", "/profile", "/stats", "/constructor_gate"):
                with self.subTest(url=url):
                    self.assertEqual(client.get(url).status_code, 200)
            self.assertIn("/admin/tests", client.get("/admin").text)
            response = client.post("/api/admin/tests", json={"request_key": "csrf-test"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["error"]["code"], "CSRF_FAILED")
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertFalse((self.root / "media").exists())

    def test_missing_tests_schema_is_not_initialized_by_request(self):
        with self.application() as app:
            client = app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = 1
            response = client.get("/api/admin/tests")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json["error"]["code"], "SCHEMA_REQUIRED")
        self.assertFalse(self.open().execute("SELECT 1 FROM sqlite_master WHERE name='tests'").fetchone())

    def test_student_with_test_references_is_deleted(self):
        from features.tests import repository as repo
        self.apply()
        db = self.open()
        with repo.transaction(db):
            test = repo.create_test_in_transaction(db, document(), actor_id=1, now=self.clock())
            version = repo.store_version_in_transaction(db, test, document(), actor_id=1, now=self.clock())
            repo.publish_version_in_transaction(db, test, version, expected_revision=1, now=self.clock())
            attempt = repo.create_attempt_in_transaction(db, 2, test, version, request_key="account-check", now=self.clock())
        with self.application() as app:
            client = app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = 1
            # Authorization was already tested with real CSRF above; this check
            # targets the account deletion transaction specifically.
            app.config["WTF_CSRF_ENABLED"] = False
            self.assertEqual(client.post("/admin/delete_user/2").status_code, 302)
        self.assertIsNone(repo.get_attempt(db, attempt))
        self.assertIsNone(db.execute("SELECT id FROM users WHERE id=2").fetchone())
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
