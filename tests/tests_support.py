"""Synthetic test-domain fixtures. Never import app.py or read a working DB."""
import ast
import os
from unittest import mock
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest

from scripts.migrate import connect, migrate

ROOT = Path(__file__).resolve().parents[1]


def platform_database(path):
    """Extract only literal legacy CREATE statements without executing Python."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    init = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "init_db")
    with closing(sqlite3.connect(path)) as db:
        for node in ast.walk(init):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute" and node.args):
                arg = node.args[0]
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and arg.value.strip().startswith("CREATE TABLE")):
                    db.execute(arg.value)
        db.executemany("INSERT INTO users(id,username,password_hash,is_admin) VALUES (?,?,?,?)",
                       [(1, "synthetic-admin", "not-a-password", 1),
                        (2, "synthetic-student", "not-a-password", 0),
                        (3, "synthetic-other", "not-a-password", 0)])
        db.commit()


def backup(source, target):
    with closing(connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


class Clock:
    def __init__(self, now=1_700_000_000_000):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds
        return self.now


def document():
    return {"title": "Synthetic test", "description": "Synthetic description",
            "time_limit_seconds": 60, "attempt_limit": 2, "show_correct_answers": True,
            "questions": [
                {"title": "Single", "prompt_text": "Choose one", "question_type": "single_choice",
                 "options": [{"text": "First", "is_correct": True},
                             {"text": "Second", "is_correct": False}]},
                {"title": "Free", "prompt_text": "Type text", "question_type": "free_text",
                 "free_input_mode": "multiline", "accepted_answers": ["A\nB", "0"]},
                {"title": "Manual", "prompt_text": "Explain", "question_type": "free_text",
                 "grading_mode": "manual", "free_input_mode": "multiline"}]}


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.content_environment = mock.patch.dict(os.environ, {"EGEVOLUTION_CONTENT_ROOT": ""})
        self.content_environment.start()
        self.addCleanup(self.content_environment.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="ege-tests-qa-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "fixture.db"
        self.backup_path = self.root / "before.db"
        self.clock = Clock()
        platform_database(self.path)
        backup(self.path, self.backup_path)

    def apply(self):
        # Preserve the legacy fixture and build a separate candidate; never
        # install/replace an existing database from this test helper.
        directory = self.root / "legacy-migrations"
        directory.mkdir(exist_ok=True)
        for name in ("001_thematic.sql", "002_tests.sql"):
            shutil.copyfile(ROOT / "migrations" / name, directory / name)
        report = migrate(self.path, apply=True, backup=self.backup_path, offline=True, directory=directory)
        from scripts.json_content_migration import build_candidate
        candidate_temp = tempfile.TemporaryDirectory(prefix="ege-tests-json-")
        self.addCleanup(candidate_temp.cleanup)
        candidate = Path(candidate_temp.name) / "candidate"
        build_candidate(self.path, candidate)
        self.root = candidate.resolve()
        self.path = self.root / "users.db"
        report["applied"].append("003_json_content.sql")
        return report

    def open(self):
        db = connect(self.path, "rw")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db


class AdminHTTPCase(DatabaseCase):
    """Real guards/CSRF/routes, synthetic DB and private temp media; no app import."""
    def setUp(self):
        super().setUp()
        self.apply()
        from flask import Flask, jsonify
        from flask_wtf.csrf import CSRFProtect, generate_csrf
        from features.tests import repository
        from features.tests.routes_admin import register_admin
        from unittest import mock
        self.clock_patch = mock.patch("features.tests.service.now_ms", self.clock)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.media_root = self.root / "private-media"
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
        self.app.config.update(SECRET_KEY="synthetic-tests-secret", TESTING=True)
        CSRFProtect(self.app)
        self.app.add_url_rule("/login", "login", lambda: "login")
        self.app.add_url_rule("/fixture-csrf", "fixture_csrf", lambda: jsonify(token=generate_csrf()))
        register_admin(self.app, lambda: repository.connect(self.path), self.media_root)
        self.register_extra()
        self.client = self.app.test_client()
        self.login(1)
        self.csrf = self.client.get("/fixture-csrf").json["token"]
        self.key_sequence = 0

    def register_extra(self):
        pass

    def login(self, ident):
        with self.client.session_transaction() as session:
            if ident is None:
                session.pop("user_id", None)
            else:
                session["user_id"] = ident

    def key(self):
        self.key_sequence += 1
        return "synthetic-operation-" + str(self.key_sequence)

    def call(self, path, method="GET", body=None, csrf=True):
        response = self.client.open(path, method=method, json=body,
                                    headers={"X-CSRFToken": self.csrf} if csrf else {})
        self.addCleanup(response.close)
        return response

    def create(self, key=None):
        response = self.call("/api/admin/tests", "POST", {"request_key": key or self.key()})
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json

    def save(self, draft, doc=None, key=None):
        return self.call(f'/api/admin/tests/{draft["id"]}/draft', "PUT",
                         {"document": document() if doc is None else doc,
                          "expected_revision": draft["revision"], "request_key": key or self.key()})

    def published(self):
        draft = self.create()
        saved = self.save(draft)
        self.assertEqual(saved.status_code, 200, saved.text)
        response = self.call(f'/api/admin/tests/{draft["id"]}/publish', "POST",
                             {"expected_revision": saved.json["revision"], "request_key": self.key()})
        self.assertEqual(response.status_code, 200, response.text)
        return draft["id"], response.json


class StudentHTTPCase(AdminHTTPCase):
    def register_extra(self):
        from features.tests import repository
        from features.tests.routes_student import register_student
        self.app.config.update(TESTS_STARTS_ENABLED=True, TESTS_MEDIA_ROOT=str(self.media_root))
        register_student(self.app, lambda: repository.connect(self.path))

    def setUp(self):
        super().setUp()
        self.test_id, self.publication = self.published()
        self.login(2)

    def start(self, key=None):
        response = self.call(f"/api/tests/{self.test_id}/attempts", "POST", {"request_key": key or self.key()})
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json

    def claim(self, attempt, generation=None, client_id="synthetic-tab"):
        response = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}/claim', "POST",
                             {"expected_generation": attempt["generation"] if generation is None else generation,
                              "writer_client_id": client_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json

    def write(self, path, method, body, token):
        response = self.client.open(path, method=method, json=body,
                headers={"X-CSRFToken": self.csrf, "X-Test-Writer-Token": token})
        self.addCleanup(response.close)
        return response

    def save_answer(self, attempt, writer, question, answer, revision=0, key=None):
        return self.write(f'/api/tests/attempts/{attempt["attempt_id"]}/answers/{question}', "PUT",
                          {"answer": answer, "expected_revision": revision, "generation": writer["generation"],
                           "mutation_id": key or self.key()}, writer["writer_token"])

    def submit(self, attempt, writer, answers=None, key=None):
        body = {"generation": writer["generation"], "request_key": key or self.key()}
        if answers is not None:
            body["answers"] = answers
        return self.write(f'/api/tests/attempts/{attempt["attempt_id"]}/submit', "POST", body, writer["writer_token"])

    def questions(self, attempt):
        response = self.call(f'/api/tests/attempts/{attempt["attempt_id"]}')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json["questions"]


class ReviewHTTPCase(StudentHTTPCase):
    def pending(self, user=2):
        self.login(user)
        attempt = self.start()
        writer = self.claim(attempt)
        questions = self.questions(attempt)
        batch = [{"question_id": questions[0]["id"], "answer": questions[0]["options"][0]["id"], "expected_revision": 0},
                 {"question_id": questions[1]["id"], "answer": "wrong-original", "expected_revision": 0},
                 {"question_id": questions[2]["id"], "answer": "manual-original", "expected_revision": 0}]
        sent = self.submit(attempt, writer, batch)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json["state"], "pending_review")
        self.login(1)
        return attempt, questions

    def grade(self, attempt, question, score, revision=0, key=None):
        ident = attempt["attempt_id"] if isinstance(attempt, dict) else attempt
        return self.call(f"/api/admin/tests/attempts/{ident}/grades/{question}", "PUT",
                         {"score": score, "expected_grade_revision": revision, "request_key": key or self.key()})

    def grant(self, user=2, test=None, amount=1, key=None):
        return self.call(f'/api/admin/users/{user}/tests/{self.test_id if test is None else test}/grants', "POST",
                         {"amount": amount, "request_key": key or self.key()})
