"""Offline registration against SQLite copies with existing users and attempts."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import tempfile
from unittest import mock

from core.content_store import Store
from features.tests import repository
from scripts.migrate import connect, fingerprint
from scripts.register_test_content import register, file_hashes, content_at
from tests_support import ReviewHTTPCase, ROOT, backup


TARGET = 611958516266134


class TestContentTransferTests(ReviewHTTPCase):
    def setUp(self):
        super().setUp()
        self.pending()  # Existing student answers, grading state, grants/operation keys.
        self.area = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='ege-transfer-')))
        self.previous = self.area / 'previous'
        self.package = self.area / 'package'
        shutil.copytree(self.root / 'tests_content', self.previous / 'tests_content')
        shutil.copytree(self.root / 'tests_content', self.package / 'tests_content')
        shutil.copytree(ROOT / f'tests_content/test_{TARGET}', self.package / f'tests_content/test_{TARGET}')
        catalog = self.package / 'tests_content/catalog.json'
        data = json.loads(catalog.read_text(encoding='utf-8'))
        data['material_ids'].append(TARGET)
        data['catalog_state']['revision'] += 1
        catalog.write_text(json.dumps(data), encoding='utf-8')
        self.database = self.root / 'transfer-copy.db'
        backup(self.path, self.database)

    def run_transfer(self, **kwargs):
        return register(self.database, self.package, self.previous, TARGET, **kwargs)

    def snapshot(self):
        with closing(connect(self.database)) as db:
            return fingerprint(db), file_hashes(self.package), file_hashes(self.previous)

    def test_published_25_questions_existing_results_backup_and_repeat(self):
        before = self.snapshot()
        audit = self.run_transfer(backup_directory=self.area / 'preflight')
        self.assertEqual(audit['status'], 'ready')
        self.assertEqual(self.snapshot(), before)
        result = self.run_transfer(apply=True, confirm_offline=True, backup_directory=self.area / 'apply')
        self.assertEqual(result['status'], 'registered')
        self.assertEqual(result['publication_state'], 'published')
        self.assertEqual(result['questions'], 25)
        self.assertEqual(result['versions'], 2)
        self.assertEqual(result['current_version_id'], 4384689890600735)
        after = self.snapshot()
        self.assertEqual(self.run_transfer(apply=True, confirm_offline=True,
                         backup_directory=self.area / 'unused')['status'], 'already_registered')
        self.assertEqual(self.snapshot(), after)
        with closing(connect(self.database)) as db, content_at(self.package):
            store = Store(db, 'tests')
            actual = json.loads(store.get('test_drafts', TARGET)['document_json'])
            source = json.loads((ROOT / f'tests_content/test_{TARGET}/material.json').read_text(encoding='utf-8'))
            self.assertEqual(actual, json.loads(source['draft']['document_json']))
            self.assertEqual(sum(len(q['options']) for q in actual['questions']), 43)
            self.assertEqual(sum(o['is_correct'] for q in actual['questions'] for o in q['options']), 18)
            self.assertEqual(sum(len(q['accepted_answers']) for q in actual['questions']), 9)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            with closing(connect(self.path)) as original:
                for table in ('users', 'test_attempts', 'test_attempt_answers', 'test_operation_keys'):
                    self.assertEqual(db.execute('SELECT * FROM ' + table).fetchall(),
                                     original.execute('SELECT * FROM ' + table).fetchall())
        verified = json.loads((self.area / 'apply/verification.json').read_text())
        self.assertTrue(verified['restore_verified'])
        with closing(connect(self.area / 'apply/users-before.db')) as saved:
            self.assertEqual(fingerprint(saved), before[0])

    def test_draft_status_preserved(self):
        path = self.package / f'tests_content/test_{TARGET}/material.json'
        material = json.loads(path.read_text(encoding='utf-8'))
        material['material']['publication_state'] = 'draft'
        material['material']['current_version_id'] = None
        path.write_text(json.dumps(material), encoding='utf-8')
        result = self.run_transfer(apply=True, confirm_offline=True, backup_directory=self.area / 'backup')
        self.assertEqual(result['publication_state'], 'draft')
        self.assertIsNone(result['current_version_id'])

    def test_root_id_collision_is_not_adopted(self):
        with closing(connect(self.database, 'rw')) as db:
            db.execute('INSERT INTO tests(id) VALUES (?)', (TARGET,))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'ID conflict'):
            self.run_transfer(apply=True, confirm_offline=True, backup_directory=self.area / 'backup')
        self.assertEqual(self.snapshot(), before)

    def test_existing_json_drift_and_missing_test_fail_closed(self):
        path = self.package / f'tests_content/test_{self.test_id}/material.json'
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Existing test file differs'):
            self.run_transfer()
        self.assertEqual(self.snapshot(), before)
        path.write_bytes(original)
        catalog = self.package / 'tests_content/catalog.json'
        value = json.loads(catalog.read_text())
        value['material_ids'] = [TARGET]
        catalog.write_text(json.dumps(value), encoding='utf-8')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'unrelated tests'):
            self.run_transfer()
        self.assertEqual(self.snapshot(), before)

    def test_migration_mismatch_does_not_write(self):
        with closing(connect(self.database, 'rw')) as db:
            db.execute("UPDATE schema_migrations SET checksum='synthetic-mismatch' WHERE version='003_json_content.sql'")
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            self.run_transfer(apply=True, confirm_offline=True, backup_directory=self.area / 'backup')
        self.assertEqual(self.snapshot(), before)

    def test_version_id_collision(self):
        version_id = 4384689890600735
        with closing(connect(self.database, 'rw')) as db:
            db.execute('INSERT INTO test_versions(id,test_id) VALUES (?,?)', (version_id, self.test_id))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Conflicting stable JSON identity'):
            self.run_transfer()
        self.assertEqual(self.snapshot(), before)

    def test_apply_requires_explicit_offline_and_backup(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Apply requires'):
            self.run_transfer(apply=True)
        self.assertEqual(self.snapshot(), before)

    def test_late_failure_rolls_back_and_leaves_verified_backup(self):
        original = Store.register
        calls = []
        def fail_actual(store):
            original(store)
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('synthetic failure after registration')
        before = self.snapshot()
        with mock.patch.object(Store, 'register', fail_actual):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.run_transfer(apply=True, confirm_offline=True, backup_directory=self.area / 'backup')
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.area / 'backup/verification.json').is_file())
