import json
import re
from io import BytesIO

from PIL import Image
from features.tests import repository as repo
from tests_support import StudentHTTPCase


class StudentRouteTests(StudentHTTPCase):
    def test_actual_html_bootstrap_hides_references_and_escapes_xss(self):
        from test_tests_integration import IntegrationTests
        self.login(1)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        draft["document"]["title"] = '</script><script>alert("synthetic-xss")</script>'
        draft["document"]["questions"][1]["accepted_answers"] = ["UNIQUE_HIDDEN_REFERENCE_SENTINEL"]
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200, saved.text)
        pub = self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
                       {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertEqual(pub.status_code, 200, pub.text)
        self.login(2)
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[-1]["id"]

        def inspect(path):
            with IntegrationTests.application(self) as application:
                client = application.test_client()
                with client.session_transaction() as session:
                    session["user_id"] = 2
                response = client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("UNIQUE_HIDDEN_REFERENCE_SENTINEL", response.text)
                self.assertNotIn('<script>alert("synthetic-xss")</script>', response.text)
                self.assertIn("no-store", response.headers["Cache-Control"])
                match = re.search(r'<script type="application/json" id="tests-bootstrap">(.*?)</script>', response.text, re.S)
                self.assertIsNotNone(match)
                bootstrap = json.loads(match[1])
                for forbidden in ('"accepted_answers"', '"is_correct"', '"reference"', '"writer_token"'):
                    self.assertNotIn(forbidden, json.dumps(bootstrap))
                return bootstrap
        active = inspect(f'/tests/attempts/{attempt["attempt_id"]}')
        self.assertNotIn('"score"', json.dumps(active))
        self.assertEqual(self.save_answer(attempt, writer, question, "pending manual").status_code, 200)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        pending = inspect(f'/tests/attempts/{attempt["attempt_id"]}/result')
        self.assertIsNone(pending["summary"]["percentage"])

    def test_real_application_guest_mutation_auth_before_csrf(self):
        # Reuse the Lead-owned audited app-import context without editing it.
        from test_tests_integration import IntegrationTests
        with IntegrationTests.application(self) as application:
            client = application.test_client()
            for path in ("/api/admin/tests", f"/api/tests/{self.test_id}/attempts"):
                response = client.post(path, json={"request_key": "synthetic-guest"})
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.json["error"]["code"], "AUTH_REQUIRED")
                self.assertIn("no-store", response.headers["Cache-Control"])
            with client.session_transaction() as session:
                session["user_id"] = 2
            response = client.post(f"/api/tests/{self.test_id}/attempts", json={"request_key": "synthetic-student"})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(response.json["error"]["code"], "CSRF_FAILED")

    def test_guest_mutation_without_csrf_returns_auth_required(self):
        self.login(None)
        response = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": self.key()}, csrf=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"]["code"], "AUTH_REQUIRED")

    def assert_no_references(self, response, active=False):
        self.assertEqual(response.status_code, 200, response.text)
        for forbidden in ('"is_correct"', '"accepted_answers"', '"reference"', '"writer_token_hash"', '"auto_score"'):
            self.assertNotIn(forbidden, response.text)
        if active:
            for forbidden in ('"score"', '"grading_source"'):
                self.assertNotIn(forbidden, response.text)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_actual_json_active_and_pending_hide_every_reference(self):
        attempt = self.start()
        self.assert_no_references(self.call("/api/tests"), active=True)
        self.assert_no_references(self.call(f"/api/tests/{self.test_id}"), active=True)
        self.assert_no_references(self.call(f'/api/tests/attempts/{attempt["attempt_id"]}'), active=True)
        result_path = f'/api/tests/attempts/{attempt["attempt_id"]}/result'
        self.assertEqual(self.call(result_path).status_code, 409)
        writer = self.claim(attempt)
        questions = self.questions(attempt)
        self.assertEqual(self.save_answer(attempt, writer, questions[-1]["id"], "manual pending").status_code, 200)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        result = self.call(result_path)
        self.assert_no_references(result)
        self.assertIsNone(result.json["summary"]["percentage"])
        self.assertEqual(result.json["summary"]["pending_count"], 1)
        self.assert_no_references(self.call(f'/api/tests/attempts/{attempt["attempt_id"]}'), active=True)

    def test_guest_foreign_and_latest_guards_all_api_and_replay(self):
        attempt = self.start("old-replay")
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        self.login(None)
        self.assertEqual(self.call("/api/tests").status_code, 401)
        self.login(3)
        paths = [f'/api/tests/attempts/{attempt["attempt_id"]}', f'/api/tests/attempts/{attempt["attempt_id"]}/result']
        for path in paths:
            self.assertEqual(self.call(path).status_code, 404)
        foreign = self.save_answer(attempt, writer, question, "foreign")
        self.assertEqual(foreign.status_code, 404)
        self.login(2)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        new = self.start()
        for path in paths:
            response = self.call(path)
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(response.json["error"]["code"], "RESULT_NOT_LATEST")
        replay = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": "old-replay"})
        self.assertEqual(replay.status_code, 403, replay.text)
        self.assertEqual(repo.latest_attempt(self.open(), 2, self.test_id)["id"], new["attempt_id"])

    def test_csrf_for_all_student_mutations_and_writer_token_required(self):
        attempt = self.start()
        question = self.questions(attempt)[0]["id"]
        for path, method in [(f"/api/tests/{self.test_id}/attempts", "POST"),
                             (f'/api/tests/attempts/{attempt["attempt_id"]}/claim', "POST"),
                             (f'/api/tests/attempts/{attempt["attempt_id"]}/heartbeat', "POST"),
                             (f'/api/tests/attempts/{attempt["attempt_id"]}/answers/{question}', "PUT"),
                             (f'/api/tests/attempts/{attempt["attempt_id"]}/submit', "POST")]:
            with self.subTest(path=path):
                self.assertEqual(self.call(path, method, {}, csrf=False).status_code, 400)
        writer = self.claim(attempt)
        denied = self.write(f'/api/tests/attempts/{attempt["attempt_id"]}/heartbeat', "POST",
                            {"generation": writer["generation"]}, "wrong-token")
        self.assertEqual(denied.status_code, 409, denied.text)

    def test_historical_and_foreign_media_denied_latest_media_allowed(self):
        self.login(1)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        stream = BytesIO()
        Image.new("RGB", (2, 2), color="red").save(stream, format="PNG")
        data = stream.getvalue()
        upload = self.client.post(f"/api/admin/tests/{self.test_id}/media", data={
            "file": (BytesIO(data), "image.png", "image/png"), "request_key": self.key()},
            headers={"X-CSRFToken": self.csrf})
        self.assertEqual(upload.status_code, 201, upload.text)
        media_id = upload.json["media_id"]
        draft["document"]["questions"][0]["media_id"] = media_id
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200, saved.text)
        published = self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
                              {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertEqual(published.status_code, 200, published.text)
        self.login(2)
        attempt = self.start()
        url = f'/tests/attempts/{attempt["attempt_id"]}/media/{media_id}'
        response = self.call(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, data)
        self.assertIn("private", response.headers["Cache-Control"])
        self.login(3)
        self.assertEqual(self.call(url).status_code, 404)
        self.login(2)
        writer = self.claim(attempt)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        self.start()
        self.assertEqual(self.call(url).status_code, 403)
