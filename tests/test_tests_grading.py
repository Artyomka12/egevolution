from copy import deepcopy
import unittest

from features.tests.grading import grade_answer, summarize
from features.tests.statistics import best_attempt
from features.tests.validation import ValidationError, validate_answer, validate_publication
from tests_support import document


class GradingTests(unittest.TestCase):
    def choice(self, multiple=False):
        return {"question_type": "multiple_choice" if multiple else "single_choice",
                "grading_mode": "auto", "options": [
                    {"id": 11, "is_correct": True}, {"id": 12, "is_correct": multiple},
                    {"id": 13, "is_correct": False}]}

    def free(self, manual=False):
        return {"question_type": "free_text", "grading_mode": "manual" if manual else "auto",
                "accepted_answers": ["0", "Answer", " a ", "A\nB", "é"]}

    def test_T01_single_ids_and_foreign_rejection(self):
        question = self.choice()
        self.assertEqual(grade_answer(question, validate_answer(question, 11))["score"], 1)
        self.assertEqual(grade_answer(question, validate_answer(question, 12))["score"], 0)
        for invalid in (99, True, "11", [11]):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                validate_answer(question, invalid)

    def test_T02_exact_set_order_duplicates_foreign(self):
        question = self.choice(True)
        for answer, expected in [([11, 12], 1), ([12, 11], 1), ([11], 0), ([11, 12, 13], 0), ([], 0)]:
            with self.subTest(answer=answer):
                self.assertEqual(grade_answer(question, validate_answer(question, answer))["score"], expected)
        for invalid in ([11, 11], [99], [True], "11", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                validate_answer(question, invalid)

    def test_T03_literal_text_without_normalization_in_grader(self):
        question = self.free()
        for answer in question["accepted_answers"]:
            self.assertEqual(grade_answer(question, answer)["score"], 1)
        for answer in ("answer", "Answer ", "a", " a", "A\r\nB", "A\rB", "e\u0301", "00", "\u00a0a\u00a0"):
            with self.subTest(answer=answer):
                self.assertEqual(grade_answer(question, answer)["score"], 0)
        self.assertFalse(grade_answer(question, "0")["was_unanswered"])
        self.assertFalse(grade_answer(question, " ")["was_unanswered"])

    def test_transport_lf_both_author_and_student_preserves_spaces(self):
        source = document()
        source["questions"][1]["accepted_answers"] = [" A\r\nB\r "]
        published = validate_publication(source)
        self.assertEqual(published["questions"][1]["accepted_answers"], [" A\nB\n "])
        self.assertEqual(validate_answer(self.free(), " A\r\nB\r "), " A\nB\n ")
        self.assertEqual(source["questions"][1]["accepted_answers"], [" A\r\nB\r "])

    def test_unapproved_upper_caps_are_not_introduced(self):
        source = document()
        source.update(time_limit_seconds=1440*60+1, attempt_limit=1001)
        source["questions"][0]["prompt_text"] = "x"*20001
        source["questions"][0]["options"] = [{"text": "x"*2001, "is_correct": i == 0} for i in range(31)]
        source["questions"][1]["accepted_answers"] = [str(i) for i in range(51)]
        source["questions"] += [deepcopy(source["questions"][2]) for _ in range(198)]
        validated = validate_publication(source)
        self.assertEqual(len(validated["questions"]), 201)
        self.assertEqual(len(validate_answer(self.free(), "x"*20001)), 20001)

    def test_T04_manual_nonempty_pending_skips_zero(self):
        question = self.free(True)
        for answer in ("0", " ", "print('never executed')"):
            self.assertIsNone(grade_answer(question, answer)["score"])
        for question, answer in ((question, ""), (question, None), (self.choice(), None), (self.choice(True), [])):
            result = grade_answer(question, answer)
            self.assertTrue(result["was_unanswered"])
            self.assertEqual(result["score"], 0)
        for invalid in (2, True, False, 1.0, "1", -1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                summarize([{"score": invalid}], 1)

    def test_T05_pending_summary_and_final_percentage(self):
        answers = [{"score": score} for score in (1, 1, 1, 0, 0, 0, None, None)]
        self.assertEqual(summarize(answers, 8), {"earned": 3, "total": 8,
                         "checked_count": 6, "pending_count": 2, "final_score": None,
                         "percentage": None, "is_final": False})
        answers[-1]["score"] = answers[-2]["score"] = 1
        self.assertEqual(summarize(answers, 8)["percentage"], 62.5)
        for total in (7, 9, 0, True):
            with self.assertRaises(ValueError):
                summarize(answers, total)

    def attempt(self, ident, earned, total, submitted=100, state="graded"):
        return {"id": ident, "state": state, "submitted_at": submitted,
                "summary": summarize([{"score": int(i < earned)} for i in range(total)], total)}

    def test_T06_recalculation_preserves_grade_input(self):
        answers = [{"answer": "original", "auto_score": 0, "score": 0}]
        original = deepcopy(answers)
        for score in (0, 1, 0):
            answers[0]["score"] = score
            self.assertEqual(summarize(answers, 1)["earned"], score)
            self.assertEqual(answers[0]["answer"], original[0]["answer"])
            self.assertEqual(answers[0]["auto_score"], original[0]["auto_score"])

    def test_T07_best_uses_fraction_excludes_pending_and_stable_ties(self):
        older = self.attempt(1, 3, 4)
        newer = self.attempt(2, 5, 8, 200)
        pending = self.attempt(3, 8, 8, 300, "pending_review")
        self.assertIs(best_attempt([older, newer, pending]), older)
        self.assertIsNone(best_attempt([pending]))
        tie = self.attempt(4, 6, 8, 400)
        later_id = self.attempt(5, 3, 4, 400)
        self.assertIs(best_attempt([later_id, tie, older]), later_id)
        # Rounded display percentages may coincide; exact fractions must win.
        lower = self.attempt(6, 1000, 2001, 900)
        higher = self.attempt(7, 1001, 2003, 100)
        lower["summary"]["percentage"] = higher["summary"]["percentage"] = 50.0
        self.assertIs(best_attempt([lower, higher]), higher)
