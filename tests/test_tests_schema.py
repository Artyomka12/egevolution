import sqlite3

from features.tests import repository as repo
from core.content_store import store_for, ContentError
from tests_support import DatabaseCase, document


class SchemaTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.db = self.open()

    def seed(self, doc=None):
        doc = document() if doc is None else doc
        with repo.transaction(self.db):
            test = repo.create_test_in_transaction(self.db, doc, actor_id=1, now=self.clock())
            version = repo.store_version_in_transaction(self.db, test, doc, actor_id=1, now=self.clock())
            repo.publish_version_in_transaction(self.db, test, version, expected_revision=1, now=self.clock())
        return test, version, repo.get_version(self.db, version)["questions"]

    def attempt(self, test, version, key="start", user=2):
        with repo.transaction(self.db):
            return repo.create_attempt_in_transaction(self.db, user, test, version, request_key=key, now=self.clock())

    def finish(self, attempt):
        with repo.transaction(self.db):
            self.db.execute("UPDATE test_attempt_answers SET score=0,auto_score=0,grading_source='automatic' WHERE attempt_id=?", (attempt,))
            repo.update_attempt_in_transaction(self.db, attempt, state="graded", submitted_at=self.clock(),
                                               finalized_at=self.clock(), finish_reason="manual", result_revision=1)

    def test_connection_enforces_fk_existing_file_only_and_transactions(self):
        db = repo.connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(db.execute("PRAGMA recursive_triggers").fetchone()[0], 1)
        with self.assertRaises(FileNotFoundError):
            repo.connect(self.root / "missing.db")
        with self.assertRaises(ValueError):
            repo.create_test_in_transaction(db, document(), actor_id=1, now=0)
        with repo.transaction(db), self.assertRaises(ValueError):
            with repo.transaction(db):
                pass

    def test_version_question_option_reference_immutable(self):
        test, version, questions = self.seed()
        store = store_for(self.db, "tests")
        option = questions[0]["options"][0]["id"]
        answer = next(r["id"] for r in store.rows("test_accepted_answers") if r["question_id"] == questions[1]["id"])
        operations = [("test_versions", version, {"title":"tampered"}),
            ("test_versions", version, {"sealed":0}),
            ("test_version_questions", questions[0]["id"], {"prompt_text":"tampered"}),
            ("test_question_options", option, {"is_correct":0}),
            ("test_accepted_answers", answer, {"value":"tampered"})]
        for table, ident, fields in operations:
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError), repo.transaction(self.db):
                store_for(self.db, "tests").update(table, ident, **fields)
            with self.subTest(delete=table), self.assertRaises(sqlite3.IntegrityError), repo.transaction(self.db):
                store_for(self.db, "tests").delete(table, ident)
        with self.assertRaises(sqlite3.IntegrityError), repo.transaction(self.db):
            store_for(self.db, "tests").insert("test_accepted_answers", dict(question_id=questions[1]["id"],position=99,value="injected"))

    def test_composite_foreign_keys_prevent_cross_test_and_cross_version(self):
        first, v1, q1 = self.seed()
        second, v2, q2 = self.seed()
        attempt = self.attempt(first, v1)
        with self.assertRaises((sqlite3.IntegrityError, ContentError)), repo.transaction(self.db):
            store_for(self.db, "tests").update("tests", first, current_version_id=v2)
        with self.assertRaises((sqlite3.IntegrityError, ContentError)), repo.transaction(self.db):
            store_for(self.db, "tests").update("test_drafts", first, based_on_version_id=v2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO test_attempt_answers(attempt_id,question_id,version_id) VALUES(?,?,?)", (attempt, q2[0]["id"], v1))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO test_attempt_answers(attempt_id,question_id,version_id) VALUES(?,?,?)", (attempt, q2[0]["id"], v2))
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_all_answer_rows_and_only_one_active_per_pair(self):
        test, version, questions = self.seed()
        attempt = self.attempt(test, version)
        self.assertEqual(len(repo.get_answers(self.db, attempt)), len(questions))
        with self.assertRaises(sqlite3.IntegrityError):
            self.attempt(test, version, key="second")
        other = self.attempt(test, version, key="third", user=3)
        self.assertNotEqual(attempt, other)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE test_attempts SET deadline_at=deadline_at+1 WHERE id=?", (attempt,))

    def test_grades_binary_bool_rejected_and_skip_cannot_override_one(self):
        test, version, questions = self.seed()
        attempt = self.attempt(test, version)
        for score in (True, False, 2, 1.0, "1"):
            with self.subTest(score=score), self.assertRaises(ValueError), repo.transaction(self.db):
                repo.set_answer_grade_in_transaction(self.db, attempt, questions[0]["id"], score=score)
        with self.assertRaises(sqlite3.IntegrityError), repo.transaction(self.db):
            repo.set_answer_grade_in_transaction(self.db, attempt, questions[0]["id"], score=1)

    def test_submitted_answer_and_auto_score_immutable_but_correction_allowed(self):
        test, version, questions = self.seed()
        attempt = self.attempt(test, version)
        question = questions[0]["id"]
        self.db.execute("UPDATE test_attempt_answers SET answer_json='12',was_unanswered=0 WHERE attempt_id=? AND question_id=?", (attempt, question))
        self.finish(attempt)
        before = repo.get_answer(self.db, attempt, question)
        for field, value in (("answer_json", "13"), ("revision", 2), ("auto_score", 1), ("was_unanswered", 1)):
            with self.subTest(field=field), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("UPDATE test_attempt_answers SET " + field + "=? WHERE attempt_id=? AND question_id=?", (value, attempt, question))
        for expected, score in enumerate((1, 0)):
            with repo.transaction(self.db):
                repo.set_answer_grade_in_transaction(self.db, attempt, question, expected_grade_revision=expected,
                                                      score=score, grade_revision=expected+1, grading_source="override")
            current = repo.get_answer(self.db, attempt, question)
            self.assertEqual(current["answer"], before["answer"])
            self.assertEqual(current["auto_score"], before["auto_score"])
        with self.assertRaises(repo.Conflict), repo.transaction(self.db):
            repo.set_answer_grade_in_transaction(self.db, attempt, question, expected_grade_revision=0, score=1)

    def test_draft_change_and_v2_does_not_mutate_v1(self):
        test, version, questions = self.seed()
        attempt = self.attempt(test, version)
        before = repo.get_version(self.db, version)
        changed = document()
        changed.update(title="New title", time_limit_seconds=120, show_correct_answers=False)
        changed["questions"][1]["accepted_answers"] = ["new"]
        with repo.transaction(self.db):
            repo.save_draft_in_transaction(self.db, test, changed,
                    expected_revision=repo.get_draft(self.db, test)["revision"], actor_id=1, now=self.clock())
            v2 = repo.store_version_in_transaction(self.db, test, changed, actor_id=1, now=self.clock())
            repo.publish_version_in_transaction(self.db, test, v2, expected_revision=3, now=self.clock())
        self.assertEqual(repo.get_version(self.db, version), before)
        self.assertEqual(repo.get_attempt(self.db, attempt)["version_id"], version)
        self.assertEqual(repo.get_attempt(self.db, attempt)["time_limit_seconds_snapshot"], 60)

    def test_delete_rollback_then_cascade_preserves_receipt_media_thematic(self):
        test, version, questions = self.seed()
        attempt = self.attempt(test, version)
        other, _, _ = self.seed()
        with repo.transaction(self.db):
            store_for(self.db, "thematic").insert("thematic_variants", dict(created_at=0, updated_at=0))
        with repo.transaction(self.db):
            media = repo.create_media_in_transaction(self.db, storage_key="a"*32, mime_type="image/png",
                    size_bytes=10, sha256="a"*64, width=1, height=1, alt_text="original", actor_id=1, now=0)
            repo.link_media_in_transaction(self.db, test, media)
            repo.link_media_in_transaction(self.db, other, media)
            repo.record_operation_in_transaction(self.db, 2, "start", "receipt", "a"*64, attempt, 0)
            repo.add_grant_in_transaction(self.db, 2, test, 1, actor_id=1, now=0, request_key="grant")
        with self.assertRaisesRegex(RuntimeError, "fault"), repo.transaction(self.db):
            repo.delete_test_in_transaction(self.db, test, expected_revision=2)
            raise RuntimeError("fault before commit")
        self.assertIsNotNone(repo.get_attempt(self.db, attempt))
        with repo.transaction(self.db):
            self.assertEqual(repo.delete_test_in_transaction(self.db, test, expected_revision=2), [media])
            self.assertFalse(repo.delete_unreferenced_media_in_transaction(self.db, media))
        self.assertIsNone(repo.get_test(self.db, test))
        self.assertIsNone(repo.get_attempt(self.db, attempt))
        self.assertEqual(repo.get_answers(self.db, attempt), [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM test_attempt_grants WHERE test_id=?", (test,)).fetchone()[0], 0)
        self.assertIsNotNone(repo.get_operation(self.db, 2, "start", "receipt"))
        self.assertIsNotNone(repo.get_media(self.db, media))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM thematic_variants").fetchone()[0], 1)
        new_test, new_version, new_questions = self.seed()
        new_attempt = self.attempt(new_test, new_version, key="new")
        self.assertNotEqual(new_test, test)
        self.assertNotEqual(new_version, version)
        self.assertGreater(new_attempt, attempt)
        self.assertNotIn(new_questions[0]["id"], [q["id"] for q in questions])
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_receipts_idempotent_conflicting_payload_rejected(self):
        with repo.transaction(self.db):
            first = repo.record_operation_in_transaction(self.db, 1, "create", "same", "a"*64, 10, 0)
            repeat = repo.record_operation_in_transaction(self.db, 1, "create", "same", "a"*64, 10, 1)
            self.assertEqual(first, repeat)
            with self.assertRaises(repo.Conflict):
                repo.record_operation_in_transaction(self.db, 1, "create", "same", "b"*64, 10, 2)

    def test_ready_media_metadata_immutable_and_requires_ownership(self):
        with repo.transaction(self.db):
            media = repo.create_media_in_transaction(self.db, storage_key="b"*32, mime_type="image/png",
                    size_bytes=10, sha256="b"*64, width=1, height=1, alt_text="original", actor_id=1, now=0)
        with self.assertRaises(sqlite3.IntegrityError), repo.transaction(self.db):
            store_for(self.db, "tests").update("test_media", media, alt_text="new")
        doc = document()
        doc["questions"][0]["media_id"] = media
        with self.assertRaises(sqlite3.IntegrityError):
            self.seed(doc)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 0)
