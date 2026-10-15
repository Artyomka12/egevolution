from copy import deepcopy
import json
import unittest

from features.tests.errors import TestsError
from features.tests.serializers import attempt_dto, result_dto, admin_attempt_dto, timing_dto


class SerializerTests(unittest.TestCase):
    def setUp(self):
        self.attempt = {"id": 10, "user_id": 2, "test_id": 1, "version_id": 20, "attempt_no": 1,
                        "state": "active", "active_generation": 1, "started_at": 1000, "deadline_at": 61000,
                        "submitted_at": None, "finalized_at": None, "finish_reason": None,
                        "time_limit_seconds_snapshot": 60, "show_correct_answers_snapshot": True,
                        "result_revision": 0, "writer_token_hash": "SENSITIVE_HASH", "writer_client_id": "PRIVATE_CLIENT"}
        self.version = {"title": "Synthetic", "question_count": 3, "content_hash": "PRIVATE_CONTENT_HASH", "questions": [
            {"id": 101, "position": 1, "title": "Choose", "prompt_text": "Condition", "question_type": "single_choice",
             "grading_mode": "auto", "options": [{"id": 5, "position": 1, "text": "Choice", "is_correct": 1}]},
            {"id": 102, "position": 2, "title": "Free", "prompt_text": "Condition", "question_type": "free_text",
             "grading_mode": "auto", "accepted_answers": ["PRIVATE_REFERENCE"], "media_id": 8},
            {"id": 103, "position": 3, "title": "Manual", "prompt_text": "Condition", "question_type": "free_text",
             "grading_mode": "manual", "accepted_answers": []}]}
        self.answers = [{"question_id": q, "answer": a, "revision": 1, "saved_at": 1500,
                         "was_unanswered": False, "score": s, "auto_score": s, "grade_revision": 0,
                         "grading_source": "automatic", "graded_by": 1}
                        for q, a, s in [(101, 5, 1), (102, "my answer", 0), (103, "manual answer", None)]]

    def finish(self, state="pending_review"):
        self.attempt.update(state=state, submitted_at=11000, finalized_at=11000, finish_reason="manual")

    def assert_private_fields_absent(self, dto):
        text = json.dumps(dto)
        for forbidden in ("SENSITIVE_HASH", "PRIVATE_CLIENT", "PRIVATE_CONTENT_HASH", '"is_correct"', '"auto_score"', '"graded_by"'):
            self.assertNotIn(forbidden, text)

    def test_active_allowlist_no_correctness_or_references(self):
        dto = attempt_dto(self.attempt, self.version, self.answers, now=2000,
                          media_by_id={8: {"storage_key": "PRIVATE_PATH", "alt_text": "Diagram", "width": 1, "height": 1}})
        self.assert_private_fields_absent(dto)
        text = json.dumps(dto)
        for forbidden in ('"score"', '"reference"', '"status"', "PRIVATE_REFERENCE", "PRIVATE_PATH"):
            self.assertNotIn(forbidden, text)
        self.assertEqual(dto["questions"][1]["media"]["url"], "/tests/attempts/10/media/8")
        with self.assertRaises(TestsError) as caught:
            result_dto(self.attempt, self.version, self.answers, now=2000)
        self.assertEqual(caught.exception.code, "ATTEMPT_ACTIVE")

    def test_pending_all_references_hidden_even_auto_questions(self):
        self.finish()
        dto = result_dto(self.attempt, self.version, self.answers, now=30000)
        self.assert_private_fields_absent(dto)
        text = json.dumps(dto)
        self.assertNotIn("PRIVATE_REFERENCE", text)
        self.assertNotIn('"reference":', text)
        self.assertIsNone(dto["summary"]["percentage"])
        self.assertIsNone(dto["summary"]["final_score"])
        self.assertTrue(dto["questions"][0]["reference_pending"])
        self.assertNotIn("reference_pending", dto["questions"][2])

    def test_graded_reference_requires_no_null_and_snapshot_flag(self):
        self.finish("graded")
        inconsistent = result_dto(self.attempt, self.version, self.answers, now=30000)
        self.assertNotIn("PRIVATE_REFERENCE", json.dumps(inconsistent))
        self.assertIsNone(inconsistent["summary"]["percentage"])
        self.answers[-1]["score"] = 1
        shown = result_dto(self.attempt, self.version, self.answers, now=30000)
        self.assertEqual(shown["questions"][1]["reference"]["accepted_answers"], ["PRIVATE_REFERENCE"])
        self.assertNotIn("reference", shown["questions"][2])
        self.attempt["show_correct_answers_snapshot"] = False
        hidden = result_dto(self.attempt, self.version, self.answers, now=30000)
        self.assertNotIn("PRIVATE_REFERENCE", json.dumps(hidden))
        self.assertNotIn("reference_pending", json.dumps(hidden))

    def test_admin_separate_entry_point_references_always_present(self):
        dto = admin_attempt_dto(self.attempt, self.version, self.answers, now=2000)
        self.assertFalse(dto["can_grade"])
        self.assertIn("PRIVATE_REFERENCE", json.dumps(dto))
        self.assertEqual(dto["user_id"], 2)
        self.finish()
        self.assertTrue(admin_attempt_dto(self.attempt, self.version, self.answers, now=30000)["can_grade"])

    def test_timing_boundary_freeze_and_timeout(self):
        self.assertEqual(timing_dto(self.attempt, 60999)["remaining_seconds"], 1)
        self.assertEqual(timing_dto(self.attempt, 61000)["remaining_seconds"], 0)
        self.finish()
        self.assertEqual(timing_dto(self.attempt, 999999)["remaining_seconds"], 50)
        self.assertEqual(timing_dto(self.attempt, 999999)["elapsed_seconds"], 10)
        self.attempt.update(finish_reason="timeout", submitted_at=61000, finalized_at=999999)
        self.assertEqual(timing_dto(self.attempt, 999999)["remaining_seconds"], 0)
        self.assertEqual(timing_dto(self.attempt, 999999)["elapsed_seconds"], 60)

    def test_missing_foreign_duplicate_rows_fail_closed_and_no_input_mutation(self):
        original = deepcopy((self.attempt, self.version, self.answers))
        attempt_dto(self.attempt, self.version, self.answers, now=2000)
        self.assertEqual((self.attempt, self.version, self.answers), original)
        for invalid in (self.answers[:-1], self.answers + [self.answers[0]],
                        self.answers[:-1] + [{**self.answers[-1], "question_id": 999}]):
            with self.assertRaises(ValueError):
                attempt_dto(self.attempt, self.version, invalid, now=2000)
