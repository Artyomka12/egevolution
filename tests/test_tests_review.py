from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading
from unittest import mock

from features.tests import repository as repo, service
from features.tests.errors import TestsError
from tests_support import ReviewHTTPCase


class ReviewTests(ReviewHTTPCase):
    def test_snapshot_false_hides_references_before_and_after_manual_check(self):
        self.login(1)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        draft["document"]["show_correct_answers"] = False
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
                                  {"expected_revision": saved.json["revision"], "request_key": self.key()}).status_code, 200)
        attempt, questions = self.pending()
        for final in (False, True):
            if final:
                self.login(1)
                self.assertEqual(self.grade(attempt, questions[-1]["id"], 1).status_code, 200)
            self.login(2)
            response = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/result')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn('"reference"', response.text)
            self.assertNotIn('"reference_pending"', response.text)
            self.assertNotIn('"accepted_answers"', response.text)

    def test_real_review_html_and_admin_api_reference_access(self):
        from test_tests_integration import IntegrationTests
        attempt, questions = self.pending()
        with IntegrationTests.application(self) as application:
            client = application.test_client()
            with client.session_transaction() as session:
                session["user_id"] = 1
            page = client.get(f'/admin/tests/attempts/{attempt["attempt_id"]}/review')
            self.assertEqual(page.status_code, 200, page.text)
            self.assertIn('id="review-next"', page.text)
            self.assertIn('js/admin/tests/review.js', page.text)
            self.assertIn("no-store", page.headers["Cache-Control"])
            dto = client.get(f'/api/admin/tests/attempts/{attempt["attempt_id"]}')
            self.assertEqual(dto.status_code, 200, dto.text)
            self.assertIn("reference", dto.json["questions"][1])
            self.assertNotIn("reference", dto.json["questions"][2])
            with client.session_transaction() as session:
                session["user_id"] = 2
            self.assertEqual(client.get(f'/admin/tests/attempts/{attempt["attempt_id"]}/review').status_code, 403)

    def test_last_null_finalizes_reveals_reference_and_manual_has_no_reference(self):
        attempt, questions = self.pending()
        self.login(2)
        before = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/result')
        self.assertEqual(before.json["summary"]["pending_count"], 1)
        self.assertNotIn('"reference":', before.text)
        self.login(1)
        grade = self.grade(attempt, questions[2]["id"], 1)
        self.assertEqual(grade.status_code, 200, grade.text)
        self.assertEqual(grade.json["state"], "graded")
        self.assertEqual(grade.json["summary"]["earned"], 2)
        self.assertEqual(grade.json["pending_count"], 0)
        self.login(2)
        after = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/result')
        self.assertEqual(after.status_code, 200, after.text)
        self.assertIn("reference", after.json["questions"][0])
        self.assertIn("reference", after.json["questions"][1])
        self.assertNotIn("reference", after.json["questions"][2])
        self.assertNotIn("reference_pending", after.json["questions"][2])

    def test_binary_input_skip_always_zero_and_active_not_gradable(self):
        attempt = self.start()
        questions = self.questions(attempt)
        self.login(1)
        active = self.grade(attempt, questions[0]["id"], 0)
        self.assertEqual(active.status_code, 409)
        self.assertEqual(active.json["error"]["code"], "ATTEMPT_ACTIVE")
        self.login(2)
        self.assertEqual(self.submit(attempt, self.claim(attempt)).status_code, 200)
        self.login(1)
        for bad in (2, -1, True, False, "1", 1.0, None):
            with self.subTest(score=bad):
                self.assertEqual(self.grade(attempt, questions[0]["id"], bad, revision=1).status_code, 422)
        denied = self.grade(attempt, questions[2]["id"], 1, revision=1)
        self.assertEqual(denied.status_code, 422, denied.text)
        self.assertEqual(repo.get_answer(self.open(), attempt["attempt_id"], questions[2]["id"])["score"], 0)

    def test_grade_cas_replay_cross_question_key_and_immutable_answer_auto_score(self):
        attempt, questions = self.pending()
        db = self.open()
        question = questions[1]["id"]
        original = repo.get_answer(db, attempt["attempt_id"], question)
        changed = self.grade(attempt, question, 1, revision=1, key="same-grade")
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(self.grade(attempt, question, 1, revision=1, key="same-grade").status_code, 200)
        self.assertEqual(self.grade(attempt, question, 0, revision=1).status_code, 409)
        self.assertEqual(self.grade(attempt, question, 0, revision=1, key="same-grade").status_code, 409)
        cross = self.grade(attempt, questions[2]["id"], 1, key="same-grade")
        self.assertEqual(cross.status_code, 409)
        self.assertEqual(cross.json["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        back = self.grade(attempt, question, 0, revision=2)
        self.assertEqual(back.status_code, 200, back.text)
        final = repo.get_answer(db, attempt["attempt_id"], question)
        for field in ("answer", "answer_json", "revision", "auto_score", "saved_at"):
            self.assertEqual(final[field], original[field])
        events = db.execute("SELECT old_score,new_score,actor_user_id,actor_kind FROM test_grade_events WHERE attempt_id=? ORDER BY id", (attempt["attempt_id"],)).fetchall()
        self.assertEqual([tuple(row) for row in events], [(0, 1, 1, "admin"), (1, 0, 1, "admin")])

    def test_grade_transaction_failure_rolls_back_score_summary_audit_receipt(self):
        attempt, questions = self.pending()
        db = self.open()
        before = repo.get_attempt(db, attempt["attempt_id"])
        with mock.patch.object(repo, "add_grade_event_in_transaction", side_effect=RuntimeError("PRIVATE_AUDIT_FAILURE")):
            failed = self.grade(attempt, questions[2]["id"], 1, key="fault-grade")
        self.assertEqual(failed.status_code, 500, failed.text)
        self.assertNotIn("PRIVATE_AUDIT_FAILURE", failed.text)
        self.assertEqual(repo.get_attempt(db, attempt["attempt_id"]), before)
        self.assertIsNone(repo.get_answer(db, attempt["attempt_id"], questions[2]["id"])["score"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_grade_events").fetchone()[0], 0)
        self.assertEqual(self.grade(attempt, questions[2]["id"], 1, key="fault-grade").status_code, 200)

    def test_two_teachers_grade_race_one_cas_winner_one_audit(self):
        attempt, questions = self.pending()
        self.open().execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES(4,'synthetic-teacher','not-password',1)")
        barrier = threading.Barrier(2)

        def grade(actor):
            with closing(repo.connect(self.path)) as db:
                barrier.wait(timeout=3)
                try:
                    return service.grade_attempt_answer(db, attempt["attempt_id"], questions[2]["id"],
                        {"score": int(actor == 1), "expected_grade_revision": 0, "request_key": "race-"+str(actor)}, actor)
                except TestsError as error:
                    return error
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(grade, (1, 4)))
        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1, results)
        errors = [result for result in results if isinstance(result, TestsError)]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].code, "REVISION_CONFLICT")
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_grade_events").fetchone()[0], 1)

    def test_queue_pagination_history_and_admin_unrestricted_past_attempt(self):
        first, _ = self.pending(2)
        self.clock.advance(100)
        second, _ = self.pending(3)
        first_page = self.call("/api/admin/tests/review-queue?offset=0&limit=1")
        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(len(first_page.json["items"]), 1)
        self.assertEqual(first_page.json["next_offset"], 1)
        second_page = self.call("/api/admin/tests/review-queue?offset=1&limit=1")
        self.assertEqual(len(second_page.json["items"]), 1)
        self.assertIsNone(second_page.json["next_offset"])
        self.assertNotEqual(first_page.json["items"][0]["attempt_id"], second_page.json["items"][0]["attempt_id"])
        for query in ("offset=-1", "limit=0", "limit=true", "offset=1&offset=2", "other=1", "limit="+str(10**100)):
            self.assertEqual(self.call("/api/admin/tests/review-queue?"+query).status_code, 422)
        self.login(2)
        self.start()
        self.assertEqual(self.call(f'/api/tests/attempts/{first["attempt_id"]}/result').status_code, 403)
        self.login(1)
        response = self.call(f'/api/admin/tests/attempts/{first["attempt_id"]}')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("reference", response.json["questions"][0])

    def test_review_role_csrf_and_replay_current_admin(self):
        attempt, questions = self.pending()
        path = f'/api/admin/tests/attempts/{attempt["attempt_id"]}/grades/{questions[2]["id"]}'
        body = {"score": 1, "expected_grade_revision": 0, "request_key": "role-grade"}
        self.assertEqual(self.call(path, "PUT", body, csrf=False).status_code, 400)
        self.login(None)
        self.assertEqual(self.call(path, "PUT", body, csrf=False).status_code, 401)
        self.login(2)
        for url in ("/api/admin/tests/review-queue", f'/api/admin/tests/attempts/{attempt["attempt_id"]}', "/api/admin/users/2/tests"):
            self.assertEqual(self.call(url).status_code, 403)
        self.assertEqual(self.call(path, "PUT", body).status_code, 403)
        self.login(1)
        self.assertEqual(self.call(path, "PUT", body).status_code, 200)
        self.open().execute("UPDATE users SET is_admin=0 WHERE id=1")
        self.assertEqual(self.call(path, "PUT", body).status_code, 403)
