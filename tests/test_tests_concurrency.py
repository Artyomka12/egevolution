from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading
import time
from unittest import mock

from features.tests import repository as repo, service
from features.tests.errors import TestsError
from tests_support import StudentHTTPCase


class ConcurrencyTests(StudentHTTPCase):
    def test_synthetic_concurrent_autosave_load_with_worker(self):
        db = self.open()
        clients = []
        for user in range(4, 12):
            db.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES(?,?,?,0)",
                       (user, "synthetic-load-"+str(user), "not-a-password"))
            attempt = service.start_attempt(db, self.test_id, {"request_key": "load-start-"+str(user)}, user, starts_enabled=True)
            writer = service.claim_attempt(db, attempt["attempt_id"], {"expected_generation": attempt["generation"], "writer_client_id": "load-"+str(user)}, user)
            question = repo.get_answers(db, attempt["attempt_id"])[1]["question_id"]
            clients.append((user, attempt, writer, question))
        timings = []

        def autosaves(connection, client):
            user, attempt, writer, question = client
            for revision in range(8):
                started = time.perf_counter()
                service.save_answer(connection, attempt["attempt_id"], question,
                    {"answer": str(revision), "expected_revision": revision, "generation": writer["generation"],
                     "mutation_id": f"load-{user}-{revision}"}, user, writer["writer_token"])
                timings.append((time.perf_counter()-started)*1000)
            return True
        results = self.race(*[lambda connection, client=client: autosaves(connection, client) for client in clients],
                            lambda connection: service.expire_attempts(connection))
        self.assertFalse(any(isinstance(result, Exception) for result in results), results)
        self.assertEqual(len(timings), 64)
        p95 = sorted(timings)[int(0.95*(len(timings)-1))]
        print(f"synthetic autosave load: clients=8 writes=64 p95_ms={p95:.2f} max_ms={max(timings):.2f}")
        for _, attempt, _, question in clients:
            row = repo.get_answer(db, attempt["attempt_id"], question)
            self.assertEqual((row["answer"], row["revision"]), ("7", 8))

    def race(self, *jobs):
        barrier = threading.Barrier(len(jobs))

        def run(job):
            with closing(repo.connect(self.path)) as db:
                barrier.wait(timeout=5)
                try:
                    return job(db)
                except TestsError as error:
                    return error
        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            return list(executor.map(run, jobs))

    def test_concurrent_start_has_one_attempt_and_repeat_receipts(self):
        results = self.race(*[lambda db, i=i: service.start_attempt(db, self.test_id,
                           {"request_key": "race-start-"+str(i)}, 2, starts_enabled=True) for i in range(2)])
        self.assertTrue(all(not isinstance(value, Exception) for value in results), results)
        self.assertEqual(self.open().execute("SELECT COUNT(*) FROM test_attempts").fetchone()[0], 1)
        self.assertEqual(len({value["attempt_id"] for value in results}), 1)

    def test_concurrent_claim_exactly_one_writer_generation(self):
        attempt = self.start()
        results = self.race(*[lambda db, i=i: service.claim_attempt(db, attempt["attempt_id"],
                            {"expected_generation": attempt["generation"], "writer_client_id": "tab-"+str(i)}, 2) for i in range(2)])
        successful = [value for value in results if not isinstance(value, Exception)]
        rejected = [value for value in results if isinstance(value, TestsError)]
        self.assertEqual(len(successful), 1, results)
        self.assertEqual(len(rejected), 1, results)
        self.assertEqual(rejected[0].status, 409)
        self.assertEqual(repo.get_attempt(self.open(), attempt["attempt_id"])["active_generation"], attempt["generation"]+1)

    def test_concurrent_save_cas_one_payload_persists(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        results = self.race(*[lambda db, value=value: service.save_answer(db, attempt["attempt_id"], question,
                    {"answer": value, "expected_revision": 0, "generation": writer["generation"], "mutation_id": "save-"+value},
                    2, writer["writer_token"]) for value in ("first", "second")])
        self.assertEqual(sum(not isinstance(value, Exception) for value in results), 1, results)
        self.assertEqual(sum(isinstance(value, TestsError) and value.code == "ANSWER_CONFLICT" for value in results), 1, results)
        answer = repo.get_answer(self.open(), attempt["attempt_id"], question)
        self.assertEqual(answer["revision"], 1)
        self.assertIn(answer["answer"], ("first", "second"))

    def test_submit_against_autosave_has_one_finalization_and_consistent_answer(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        results = self.race(
            lambda db: service.save_answer(db, attempt["attempt_id"], question,
                {"answer": "0", "expected_revision": 0, "generation": writer["generation"], "mutation_id": "racing-save"}, 2, writer["writer_token"]),
            lambda db: service.submit_attempt(db, attempt["attempt_id"],
                {"request_key": "racing-submit", "generation": writer["generation"]}, 2, writer["writer_token"]))
        self.assertFalse(isinstance(results[1], Exception), results)
        db = self.open()
        attempt_row = repo.get_attempt(db, attempt["attempt_id"])
        answer = repo.get_answer(db, attempt["attempt_id"], question)
        self.assertEqual(attempt_row["result_revision"], 1)
        self.assertEqual(attempt_row["state"], "graded")
        self.assertEqual(answer["score"], 1 if answer["answer"] == "0" else 0)

    def test_concurrent_worker_submit_finalize_exactly_once(self):
        attempt = self.start()
        writer = self.claim(attempt)
        self.clock.advance(60000)
        self.race(lambda db: service.expire_attempts(db),
                  lambda db: service.submit_attempt(db, attempt["attempt_id"],
                    {"request_key": "racing-expired-submit", "generation": writer["generation"]}, 2, writer["writer_token"]))
        row = repo.get_attempt(self.open(), attempt["attempt_id"])
        self.assertEqual(row["state"], "graded")
        self.assertEqual(row["result_revision"], 1)
        self.assertEqual(row["submitted_at"], row["deadline_at"])

    def test_deadline_checked_after_waiting_for_write_lock(self):
        attempt = self.start()
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        self.clock.advance(59999)
        entered = threading.Event()
        original_transaction = repo.transaction

        def observed_transaction(db):
            entered.set()
            return original_transaction(db)

        def saving():
            with closing(repo.connect(self.path)) as db:
                try:
                    return service.save_answer(db, attempt["attempt_id"], question,
                        {"answer": "0", "expected_revision": 0, "generation": writer["generation"], "mutation_id": "locked-save"}, 2, writer["writer_token"])
                except TestsError as error:
                    return error
        with closing(repo.connect(self.path)) as locker:
            locker.execute("BEGIN IMMEDIATE")
            with mock.patch.object(repo, "transaction", observed_transaction), ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(saving)
                self.assertTrue(entered.wait(3))
                self.clock.advance(1)
                locker.commit()
                result = future.result(timeout=6)
        self.assertIsInstance(result, TestsError)
        self.assertEqual(result.code, "DEADLINE_REACHED")
        row = repo.get_answer(self.open(), attempt["attempt_id"], question)
        self.assertIsNone(row["answer"])
        self.assertEqual(row["score"], 0)

    def test_delete_vs_save_worker_leaves_no_attempt_and_receipt_no_resurrection(self):
        attempt = self.start("delete-race-start")
        writer = self.claim(attempt)
        question = self.questions(attempt)[1]["id"]
        self.race(
            lambda db: service.delete_test(db, self.test_id,
                    {"confirmed": True, "expected_revision": self.publication["revision"], "request_key": "delete-race"}, 1),
            lambda db: service.save_answer(db, attempt["attempt_id"], question,
                    {"answer": "0", "expected_revision": 0, "generation": writer["generation"], "mutation_id": "delete-race-save"}, 2, writer["writer_token"]),
            lambda db: service.expire_attempts(db))
        db = self.open()
        self.assertIsNone(repo.get_test(db, self.test_id))
        self.assertIsNone(repo.get_attempt(db, attempt["attempt_id"]))
        self.assertEqual(repo.get_answers(db, attempt["attempt_id"]), [])
        replay = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": "delete-race-start"})
        self.assertEqual(replay.status_code, 404, replay.text)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM test_attempts").fetchone()[0], 0)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
