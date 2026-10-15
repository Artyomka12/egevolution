import hashlib
from io import BytesIO
from pathlib import Path
import shutil

from PIL import Image
from features.tests import repository as repo, service
from core.content_store import store_for
from tests_support import ReviewHTTPCase, backup


class RestoreTests(ReviewHTTPCase):
    def test_new_tests_sqlite_and_private_media_restore_preserves_receipts(self):
        self.login(1)
        pixels = BytesIO()
        Image.new("RGB", (4, 3), color="blue").save(pixels, format="PNG")
        uploaded = self.client.post(f"/api/admin/tests/{self.test_id}/media", data={
            "file": (BytesIO(pixels.getvalue()), "synthetic.png", "image/png"),
            "alt_text": "Restored diagram", "request_key": "restore-media"},
            headers={"X-CSRFToken": self.csrf})
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        draft["document"]["questions"][0]["media_id"] = uploaded.json["media_id"]
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
            {"expected_revision": saved.json["revision"], "request_key": "restore-publish"}).status_code, 200)
        attempt, questions = self.pending()
        grade = self.grade(attempt, questions[-1]["id"], 1, key="restore-grade")
        self.assertEqual(grade.status_code, 200, grade.text)
        grant = self.grant(amount=2, key="restore-grant")
        self.assertEqual(grant.status_code, 200, grant.text)
        before = self.call(f'/api/admin/tests/attempts/{attempt["attempt_id"]}').json
        self.login(3)
        active = self.start("restore-active")
        self.login(1)

        backup_path = self.root / "snapshot.db"
        restore_root = self.root / "restored-project"
        restore_root.mkdir()
        restored_path = restore_root / "users.db"
        backup(self.path, backup_path)
        backup(backup_path, restored_path)
        for directory in ("tests_content", "thematic_variants"):
            shutil.copytree(self.root / directory, restore_root / directory)
        saved_media = self.root / "snapshot-media"
        restored_media = self.root / "restored-media"
        shutil.copytree(self.media_root, saved_media)
        shutil.copytree(saved_media, restored_media)
        expected = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in self.media_root.iterdir()}
        self.assertTrue(expected)
        actual = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in restored_media.iterdir()}
        self.assertEqual(actual, expected)

        # Existing factories close over self.path, so all subsequent HTTP opens
        # target the restored synthetic database, not the original fixture.
        self.path = restored_path
        self.app.config["TESTS_MEDIA_ROOT"] = str(restored_media)
        db = self.open()
        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        for row in store_for(db, "tests").rows("test_media"):
            self.assertEqual(actual[row["storage_key"]], row["sha256"])
        after = self.call(f'/api/admin/tests/attempts/{attempt["attempt_id"]}')
        self.assertEqual(after.status_code, 200, after.text)
        self.assertEqual(after.json, before)
        restored_image = self.call(uploaded.json["url"])
        self.assertEqual(restored_image.status_code, 200)
        self.assertEqual(restored_image.data, pixels.getvalue())
        self.assertEqual(self.grade(attempt, questions[-1]["id"], 1, key="restore-grade").json, grade.json)
        self.assertEqual(self.grant(amount=2, key="restore-grant").json, grant.json)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_grade_events").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_attempt_grants").fetchone()[0], 1)
        self.login(3)
        self.assertEqual(self.start("restore-active")["attempt_id"], active["attempt_id"])
        self.clock.advance(60000)
        self.assertEqual(service.expire_attempts(db), 1)
        self.assertEqual(service.expire_attempts(db), 0)
        self.assertEqual(repo.get_attempt(db, active["attempt_id"])["result_revision"], 1)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
