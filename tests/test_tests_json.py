"""Curriculum must live in JSON; synthetic fixtures only."""
import json
from unittest import mock
from core.content_store import ContentError, store_for
from features.tests import repository as repo
from tests_support import AdminHTTPCase, document


class JSONContentTests(AdminHTTPCase):
    def test_constructor_writes_json_and_sql_contains_only_identities(self):
        test, publication = self.published()
        db = self.open()
        root = store_for(db, "tests").root
        material = json.loads((root / f"test_{test}" / "material.json").read_text(encoding="utf-8"))
        self.assertEqual(material["material"]["id"], test)
        version = root / f"test_{test}" / "versions" / f"{publication['version_id']}.json"
        content = json.loads(version.read_text(encoding="utf-8"))
        self.assertEqual(content["version"]["title"], "Synthetic test")
        self.assertEqual(len(content["tables"]["test_version_questions"]), 3)
        self.assertNotIn("title", [r[1] for r in db.execute("PRAGMA table_info(test_versions)")])
        self.assertNotIn("prompt_text", [r[1] for r in db.execute("PRAGMA table_info(test_version_questions)")])
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='test_accepted_answers'").fetchone())
        self.assertNotIn("synthetic-student", version.read_text(encoding="utf-8"))

    def test_corrupt_or_missing_json_fails_closed_preserving_attempts(self):
        test, publication = self.published()
        db = self.open()
        with repo.transaction(db):
            attempt = repo.create_attempt_in_transaction(db, 2, test, publication["version_id"], request_key="json-check", now=self.clock())
        before = repo.get_attempt(db, attempt)
        store = store_for(db, "tests")
        path = store.root / f"test_{test}" / "versions" / f"{publication['version_id']}.json"
        original = path.read_bytes()
        try:
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ContentError):
                repo.get_version(db, publication["version_id"])
            path.unlink()
            with self.assertRaises(ContentError):
                repo.get_version(db, publication["version_id"])
        finally:
            path.write_bytes(original)
        self.assertEqual(repo.get_attempt(db, attempt), before)
        self.assertIsNotNone(repo.get_version(db, publication["version_id"]))
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_file_replace_failure_rolls_back_sql_and_json(self):
        import core.content_store as storage
        draft = self.create()
        saved = self.save(draft)
        self.assertEqual(saved.status_code, 200)
        db = self.open()
        root = store_for(db, "tests").root
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}
        real_replace = storage.os.replace
        failed = []
        def replace(source, target):
            if not failed and "versions" in str(target):
                failed.append(True)
                raise OSError("synthetic atomic replace fault")
            return real_replace(source, target)
        with mock.patch.object(storage.os, "replace", side_effect=replace):
            response = self.call(f"/api/admin/tests/{draft['id']}/publish", "POST",
                {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertTrue(failed)
        self.assertEqual(response.status_code, 500)
        self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.json")}, before)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_versions").fetchone()[0], 0)
        self.assertIsNone(repo.get_test(db, draft["id"])["current_version_id"])

    def test_multiline_and_special_characters_round_trip_without_normalization(self):
        draft = self.create()
        doc = document()
        literal = "  <tag> & \"quoted\"\n\n    print('x')\n"
        doc["questions"][1]["prompt_text"] = literal
        doc["questions"][1]["accepted_answers"] = [literal]
        saved = self.save(draft, doc)
        self.assertEqual(saved.status_code, 200)
        reopened = self.call(f"/api/admin/tests/{draft['id']}/draft").json
        self.assertEqual(reopened["document"]["questions"][1]["accepted_answers"], [literal])
        published = self.call(f"/api/admin/tests/{draft['id']}/publish", "POST",
            {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertEqual(published.status_code, 200)
        version = repo.get_version(self.open(), published.json["version_id"])
        self.assertEqual(version["questions"][1]["accepted_answers"], [literal])

    def test_valid_json_tampering_with_sealed_version_is_rejected(self):
        test, publication = self.published()
        db = self.open()
        root = store_for(db, "tests").root
        path = root / f"test_{test}" / "versions" / f"{publication['version_id']}.json"
        original = path.read_bytes()
        changed = json.loads(original)
        changed["version"]["title"] = "Changed outside constructor"
        try:
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ContentError):
                repo.get_version(db, publication["version_id"])
        finally:
            path.write_bytes(original)
        self.assertEqual(repo.get_version(db, publication["version_id"])["title"], "Synthetic test")
