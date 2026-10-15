from io import BytesIO
from unittest import mock

from PIL import Image
from werkzeug.datastructures import FileStorage
from features.tests import media, repository as repo
from features.tests.errors import TestsError
from tests_support import AdminHTTPCase, document


def image_bytes(fmt="PNG"):
    stream = BytesIO()
    Image.new("RGB", (3, 2), color=(20, 30, 40)).save(stream, format=fmt)
    return stream.getvalue()


class MediaTests(AdminHTTPCase):
    def upload(self, test, data=None, filename="image.png", mime="image/png", key=None, csrf=True, alt="Synthetic diagram"):
        return self.client.post(f"/api/admin/tests/{test}/media", data={
            "file": (BytesIO(image_bytes() if data is None else data), filename, mime),
            "alt_text": alt, "request_key": key or self.key()},
            headers={"X-CSRFToken": self.csrf} if csrf else {})

    def test_real_png_jpeg_gif_decoded_and_private_serving(self):
        draft = self.create()
        for fmt, ext, mime in (("PNG", "png", "image/png"), ("JPEG", "jpg", "image/jpeg"), ("GIF", "gif", "image/gif")):
            with self.subTest(fmt=fmt):
                data = image_bytes(fmt)
                uploaded = self.upload(draft["id"], data, "image."+ext, mime)
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                self.assertEqual((uploaded.json["width"], uploaded.json["height"]), (3, 2))
                response = self.call(uploaded.json["url"])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, data)
                self.assertEqual(response.mimetype, mime)
                self.assertIn("private", response.headers["Cache-Control"])
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_false_mime_svg_truncated_unknown_format_and_path_rejected(self):
        draft = self.create()
        invalid = [(image_bytes(), "image.jpg", "image/jpeg"),
                   (b"<svg onload=alert(1)></svg>", "image.svg", "image/svg+xml"),
                   (image_bytes()[:40], "image.png", "image/png"),
                   (image_bytes(), "../image.png", "image/png"),
                   (image_bytes(), "C:\\image.png", "image/png"),
                   (image_bytes("WEBP"), "image.webp", "image/webp")]
        for data, filename, mime in invalid:
            with self.subTest(filename=filename, mime=mime):
                response = self.upload(draft["id"], data, filename, mime)
                self.assertIn(response.status_code, (415, 422), response.text)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_media").fetchone()[0], 0)
        self.assertFalse(self.media_root.exists() and any(self.media_root.iterdir()))

    def test_byte_limit_and_decompression_warning_fail_closed(self):
        draft = self.create()
        response = self.upload(draft["id"], b"x"*(media.MAX_UPLOAD_BYTES+1))
        self.assertEqual(response.status_code, 413, response.text)
        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 4):
            response = self.upload(draft["id"])
        self.assertEqual(response.status_code, 422, response.text)

    def test_upload_csrf_current_role_and_other_test_ownership(self):
        draft = self.create()
        second = self.create()
        self.assertEqual(self.upload(draft["id"], csrf=False).status_code, 400)
        self.login(2)
        self.assertEqual(self.upload(draft["id"]).status_code, 403)
        self.login(1)
        uploaded = self.upload(draft["id"])
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        ident = uploaded.json["media_id"]
        self.assertEqual(self.call(f'/api/admin/tests/{second["id"]}/media/{ident}').status_code, 404)
        bad = document()
        bad["questions"][0]["media_id"] = ident
        saved = self.save(second, bad)
        self.assertEqual(saved.status_code, 422, saved.text)
        self.login(2)
        self.assertEqual(self.call(uploaded.json["url"]).status_code, 403)
        self.login(None)
        self.assertEqual(self.call(uploaded.json["url"]).status_code, 401)

    def test_idempotent_upload_one_file_changed_payload_rejected_cleanup(self):
        draft = self.create()
        first = self.upload(draft["id"], key="same-upload", alt="A\r\nB")
        self.assertEqual(first.status_code, 201, first.text)
        repeated = self.upload(draft["id"], key="same-upload", alt="A\r\nB")
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertEqual(repeated.json["media_id"], first.json["media_id"])
        self.assertEqual(repeated.json["alt_text"], "A\nB")
        changed = self.upload(draft["id"], key="same-upload", alt="Changed")
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_media").fetchone()[0], 1)
        self.assertEqual(len(list(self.media_root.iterdir())), 1)

    def test_media_original_survives_new_version_and_copy_parent_deletion(self):
        draft = self.create()
        first = self.upload(draft["id"])
        self.assertEqual(first.status_code, 201, first.text)
        doc = document()
        doc["questions"][0]["media_id"] = first.json["media_id"]
        saved = self.save(draft, doc)
        self.assertEqual(saved.status_code, 200, saved.text)
        pub = self.call(f'/api/admin/tests/{draft["id"]}/publish', "POST",
                        {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertEqual(pub.status_code, 200, pub.text)
        copied = self.call(f'/api/admin/tests/{draft["id"]}/copy', "POST", {"request_key": self.key()})
        self.assertEqual(copied.status_code, 201, copied.text)
        original = self.call(first.json["url"]).data
        deleted = self.call(f'/api/admin/tests/{draft["id"]}', "DELETE",
                           {"confirmed": True, "expected_revision": pub.json["revision"], "request_key": self.key()})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        linked = self.call(f'/api/admin/tests/{copied.json["id"]}/media/{first.json["media_id"]}')
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.data, original)

    def test_media_path_resolver_rejects_user_path(self):
        for key in ("../outside", "C:\\outside", "a"*32+".png", "f"*32+"/x"):
            with self.subTest(key=key), self.assertRaises(TestsError):
                media.resolve_media_path(self.media_root, key)
