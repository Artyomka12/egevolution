import re
from features.tests import repository as repo
from tests_support import ReviewHTTPCase


class StatisticsTests(ReviewHTTPCase):
    def test_actual_user_stats_five_tabs_default_tasks_legacy_totals_and_xss(self):
        from test_tests_integration import IntegrationTests
        self.open().execute("UPDATE users SET name=? WHERE id=2", ('<img src=x onerror="synthetic-xss">',))

        def page():
            with IntegrationTests.application(self) as application:
                client = application.test_client()
                with client.session_transaction() as session:
                    session["user_id"] = 1
                response = client.get("/admin/user/2")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn('<img src=x onerror="synthetic-xss">', response.text)
                return response.text
        before = page()
        tabs = re.findall(r'<button\b[^>]*role="tab"[^>]*>([^<]+)</button>', before)
        self.assertEqual([name.strip() for name in tabs], ["Задания", "История решений", "Уроки", "Теория", "Тесты"])
        self.assertRegex(before, r'id="tab-0"\s+aria-controls="panel-0" aria-selected="true"')
        self.assertRegex(before, r'<section hidden[^>]*id="panel-4"')
        self.assertLess(before.index('class="stats-grid"'), before.index('class="user-stats-tabs"'))
        self.assertIn('id="tests-user-stats" data-user-id="2"', before)
        totals = re.findall(r'<div class="stat-value">([^<]+)</div>', before)
        self.assertEqual(len(totals), 3)
        attempt, questions = self.pending()
        self.assertEqual(self.grade(attempt, questions[-1]["id"], 1).status_code, 200)
        self.assertEqual(self.grant(amount=2).status_code, 200)
        after = page()
        self.assertEqual(re.findall(r'<div class="stat-value">([^<]+)</div>', after), totals)

    def publish_count(self, count):
        self.login(1)
        draft = self.call(f"/api/admin/tests/{self.test_id}/draft").json
        draft["document"]["questions"] = [{"title": f"Question {i}", "prompt_text": "Synthetic",
            "question_type": "free_text", "grading_mode": "auto", "free_input_mode": "singleline",
            "accepted_answers": ["correct"]} for i in range(count)]
        draft["document"]["attempt_limit"] = None
        saved = self.save(draft, draft["document"])
        self.assertEqual(saved.status_code, 200, saved.text)
        response = self.call(f"/api/admin/tests/{self.test_id}/publish", "POST",
                             {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertEqual(response.status_code, 200, response.text)

    def complete(self, earned):
        self.login(2)
        attempt = self.start()
        writer = self.claim(attempt)
        questions = self.questions(attempt)
        batch = [{"question_id": q["id"], "expected_revision": 0,
                  "answer": "correct" if index < earned else "wrong"} for index, q in enumerate(questions)]
        sent = self.submit(attempt, writer, batch)
        self.assertEqual(sent.status_code, 200, sent.text)
        return attempt, questions

    def test_best_fraction_across_versions_tiebreak_and_correction(self):
        self.publish_count(4)
        first, first_questions = self.complete(3)
        self.clock.advance(100)
        self.publish_count(8)
        second, _ = self.complete(5)
        catalog = self.call("/api/tests").json["tests"][0]
        self.assertEqual(catalog["best"], {"earned": 3, "total": 4, "percentage": 75.0})
        self.assertEqual(catalog["last_attempt_id"], second["attempt_id"])
        self.clock.advance(100)
        third, _ = self.complete(6)
        catalog = self.call("/api/tests").json["tests"][0]
        self.assertEqual(catalog["best"], {"earned": 6, "total": 8, "percentage": 75.0})
        self.login(1)
        grade = self.grade(first, first_questions[-1]["id"], 1, revision=1)
        self.assertEqual(grade.status_code, 200, grade.text)
        self.login(2)
        self.assertEqual(self.call("/api/tests").json["tests"][0]["best"], {"earned": 4, "total": 4, "percentage": 100.0})
        self.assertEqual(self.call(f'/api/tests/attempts/{first["attempt_id"]}/result').status_code, 403)
        self.login(1)
        stats = self.call("/api/admin/users/2/tests")
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertEqual(stats.json["tests"][0]["best"]["percentage"], 100.0)
        history = self.call(f"/api/admin/users/2/tests/{self.test_id}/attempts?limit=2")
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([row["attempt_id"] for row in history.json["items"]], [third["attempt_id"], second["attempt_id"]])
        self.assertEqual(history.json["next_offset"], 2)

    def test_pending_excluded_from_best_and_stats_counts_active_separately(self):
        attempt, questions = self.pending()
        stats = self.call("/api/admin/users/2/tests").json["tests"][0]
        self.assertEqual(stats["submitted_count"], 1)
        self.assertEqual(stats["active_count"], 0)
        self.assertIsNone(stats["best"])
        self.assertEqual(self.grade(attempt, questions[-1]["id"], 1).status_code, 200)
        self.login(2)
        self.start()
        self.login(1)
        stats = self.call("/api/admin/users/2/tests").json["tests"][0]
        self.assertEqual(stats["submitted_count"], 1)
        self.assertEqual(stats["active_count"], 1)
        self.assertEqual(stats["best"]["earned"], 2)
        other = self.call("/api/admin/users/3/tests").json["tests"][0]
        self.assertEqual(other["used_attempts"], 0)
        self.assertIsNone(other["best"])
