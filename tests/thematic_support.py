import ast
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest
from scripts.migrate import migrate, connect
from features.thematic import repository
from features.thematic.validation import make_snapshot

ROOT = Path(__file__).resolve().parents[1]


def platform_database(path):
    """Actual legacy CREATE TABLE literals, with no app import or student data."""
    tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    init = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'init_db')
    with closing(sqlite3.connect(path)) as db:
        for node in ast.walk(init):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'execute' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.strip().startswith('CREATE TABLE'):
                    db.execute(arg.value)
        db.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (1,'synthetic','not-a-password',1)")
        db.commit()


def backup(source, target):
    with closing(connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ege-thematic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'fixture.db'
        self.backup_path = self.root / 'before.db'
        platform_database(self.path)
        backup(self.path, self.backup_path)

    def apply(self):
        from scripts.json_content_migration import build_candidate
        directory = self.root / 'legacy-migrations'
        directory.mkdir(exist_ok=True)
        for name in ('001_thematic.sql', '002_tests.sql'):
            shutil.copyfile(ROOT / 'migrations' / name, directory / name)
        report = migrate(self.path, apply=True, backup=self.backup_path, offline=True, directory=directory)
        candidate_temp = tempfile.TemporaryDirectory(prefix='ege-json-fixture-')
        self.addCleanup(candidate_temp.cleanup)
        candidate = Path(candidate_temp.name) / 'candidate'
        build_candidate(self.path, candidate)
        self.path = (candidate / 'users.db').resolve()
        return dict(report, applied=report['applied'] + ['003_json_content.sql'])

    def open(self):
        db = repository.connect(self.path)
        self.addCleanup(db.close)
        return db

    def seed_version(self, db, count=2, variant_id=None):
        if variant_id is None:
            variant_id = self.insert_content(db, 'variants', created_at=0, updated_at=0, created_by=1)
        snapshots = [make_snapshot(1, {'id': i, 'description': ['Synthetic condition'], 'correct_answer': '9'})
                     for i in range(1, count + 1)]
        version = repository.store_version(db, variant_id, 'Synthetic version', '', snapshots, actor_id=1, now=0)
        items = [r['id'] for r in repository.get_version(db, version)['items']]
        return variant_id, version, items

    def insert_content(self, db, table, **fields):
        with repository.transaction(db):
            return repository.insert(db, table, fields)

    def update_content(self, db, table, ident, **fields):
        with repository.transaction(db):
            repository.update(db, table, ident, **fields)

    def attempt(self, db, variant, version, items, number=1):
        ident = db.execute('''INSERT INTO thematic_attempts
            (user_id,variant_id,version_id,attempt_no,started_at,total_count,start_request_key)
            VALUES (1,?,?,?,?,?,?)''', (variant, version, number, 0, len(items), str(number)+'-'+str(variant))).lastrowid
        for item in items:
            db.execute('INSERT INTO thematic_answers(attempt_id,item_id,version_id) VALUES (?,?,?)', (ident,item,version))
        return ident
