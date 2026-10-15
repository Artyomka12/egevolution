from features.tests import repository as repo
from tests_support import StudentHTTPCase


class AttemptTests(StudentHTTPCase):
    def test_catalog_flag_does_not_disable_active_lifecycle(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        self.app.config["TESTS_CATALOG_ENABLED"] = False
        self.assertEqual(self.call("/api/tests").status_code, 503)
        self.assertEqual(self.call(f"/api/tests/{self.test_id}").status_code, 503)
        self.assertEqual(self.save_answer(attempt, writer, question, "0").status_code, 200)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        self.assertEqual(self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/result').status_code, 200)

    def test_closed_submit_new_key_is_receipted_and_cannot_change_payload(self):
        attempt = self.start()
        writer = self.claim(attempt)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        self.assertEqual(self.submit(attempt, writer, key="closed-key").status_code, 200)
        changed = self.submit(attempt, writer, answers=[], key="closed-key")
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(changed.json["error"]["code"], "IDEMPOTENCY_KEY_REUSED")

    def test_start_idempotency_active_receipt_replay_after_completion(self):
        first = self.start("original-start")
        second = self.start("resumed-start")
        self.assertEqual(first["attempt_id"], second["attempt_id"])
        writer = self.claim(first)
        self.assertEqual(self.submit(first, writer).status_code, 200)
        replay = self.start("resumed-start")
        self.assertEqual(replay["attempt_id"], first["attempt_id"])
        self.assertNotEqual(replay["state"], "active")
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_attempts").fetchone()[0], 1)
        new = self.start("new-start")
        self.assertNotEqual(new["attempt_id"], first["attempt_id"])

    def test_single_writer_claim_generation_and_old_replay_forbidden(self):
        attempt = self.start()
        question = self.questions(attempt)[1]["id"]
        first = self.claim(attempt)
        saved = self.save_answer(attempt, first, question, "old", key="old-save")
        self.assertEqual(saved.status_code, 200, saved.text)
        second = self.claim(attempt, generation=first["generation"], client_id="new-tab")
        self.assertGreater(second["generation"], first["generation"])
        for key in ("old-save", "different-old-save"):
            denied = self.save_answer(attempt, first, question, "old", key=key)
            self.assertEqual(denied.status_code, 409, denied.text)
            self.assertEqual(denied.json["error"]["code"], "SESSION_REPLACED")
        self.assertEqual(self.save_answer(attempt, second, question, "new", revision=1).status_code, 200)
        self.assertEqual(repo.get_answer(self.open(), attempt["attempt_id"], question)["answer"], "new")

    def test_answer_cas_replay_clear_transport_and_cross_question(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        first = self.save_answer(attempt, writer, question, " A\r\nB ", key="same-save")
        self.assertEqual(first.status_code, 200, first.text)
        replay = self.save_answer(attempt, writer, question, " A\r\nB ", key="same-save")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json["revision"], first.json["revision"])
        changed = self.save_answer(attempt, writer, question, "changed", key="same-save")
        self.assertEqual(changed.status_code, 409)
        stale = self.save_answer(attempt, writer, question, "stale", revision=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(repo.get_answer(self.open(), attempt["attempt_id"], question)["answer"], " A\nB ")
        clear = self.save_answer(attempt, writer, question, "", revision=1)
        self.assertEqual(clear.status_code, 200, clear.text)
        self.assertEqual(repo.get_answer(self.open(), attempt["attempt_id"], question)["answer"], "")
        foreign = self.save_answer(attempt, writer, 99999, "x")
        self.assertIn(foreign.status_code, (404, 422))

    def test_submit_batch_conflict_atomic_and_replay_once(self):
        attempt = self.start()
        writer = self.claim(attempt)
        questions = self.questions(attempt)
        self.assertEqual(self.save_answer(attempt, writer, questions[1]["id"], "saved").status_code, 200)
        batch = [{"question_id": questions[0]["id"], "expected_revision": 0, "answer": questions[0]["options"][0]["id"]},
                 {"question_id": questions[1]["id"], "expected_revision": 0, "answer": "late"}]
        conflict = self.submit(attempt, writer, batch)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        db = self.open()
        self.assertIsNone(repo.get_answer(db, attempt["attempt_id"], questions[0]["id"])["answer"])
        self.assertEqual(repo.get_attempt(db, attempt["attempt_id"])["state"], "active")
        batch[1]["expected_revision"] = 1
        sent = self.submit(attempt, writer, batch, key="same-submit")
        self.assertEqual(sent.status_code, 200, sent.text)
        replay = self.submit(attempt, writer, batch, key="same-submit")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(repo.get_attempt(db, attempt["attempt_id"])["result_revision"], 1)
        rejected = self.save_answer(attempt, writer, questions[1]["id"], "after", revision=2)
        self.assertEqual(rejected.status_code, 409, rejected.text)

    def test_hidden_active_continues_and_snapshot_stays_original(self):
        attempt = self.start()
        writer = self.claim(attempt)
        self.login(1)
        hidden = self.call(f"/api/admin/tests/{self.test_id}/visibility", "PATCH",
                          {"published": False, "expected_revision": self.publication["revision"], "request_key": self.key()})
        self.assertEqual(hidden.status_code, 200, hidden.text)
        self.login(2)
        question = self.questions(attempt)[1]["id"]
        self.assertEqual(self.save_answer(attempt, writer, question, "0").status_code, 200)
        self.assertEqual(self.submit(attempt, writer).status_code, 200)
        denied = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": self.key()})
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_quota_counts_all_started_and_new_start_gate_preserves_service(self):
        for _ in range(2):
            attempt = self.start()
            writer = self.claim(attempt)
            self.assertEqual(self.submit(attempt, writer).status_code, 200)
        denied = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": self.key()})
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json["error"]["code"], "LIMIT_REACHED")
        self.login(3)
        active = self.start()
        writer = self.claim(active)
        self.app.config["TESTS_STARTS_ENABLED"] = False
        question = self.questions(active)[1]["id"]
        self.assertEqual(self.save_answer(active, writer, question, "kept").status_code, 200)
        self.assertEqual(self.submit(active, writer).status_code, 200)
        self.assertEqual(self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": self.key()}).status_code, 503)
