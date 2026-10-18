"""Recovery refuses edits/duplicates and preserves 25 synthetic questions."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import tempfile
from unittest import mock

from core.content_store import Store
from features.tests import repository, service
from features.tests.validation import validate_draft
from scripts.migrate import fingerprint
from scripts.recover_test_draft import recover
from tests_support import DatabaseCase, document


class DraftRecoveryTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.source = self.root / 'synthetic-backup.json'
        self.doc = validate_draft(document())
        self.doc['questions'] = [deepcopy(self.doc['questions'][i % 3]) for i in range(25)]
        self.doc['questions'][7]['code_text'] = 'print("unchanged")\n  # exact spaces\n'
        self.source.write_text(json.dumps(self.doc), encoding='utf-8')
        self.backups = self.enterContext(tempfile.TemporaryDirectory(prefix='ege-recovery-backups-'))

    def recover(self, **kwargs):
        return recover(self.source, self.path, actor_id=1, **kwargs)

    def snapshot(self):
        with closing(repository.connect(self.path)) as db:
            logical = fingerprint(db)
        files = {str(p.relative_to(self.root)): p.read_bytes()
                 for p in (self.root / 'tests_content').rglob('*') if p.is_file()}
        return logical, files

    def test_restore_exact_repeat_and_reopen(self):
        before = self.snapshot()
        self.assertEqual(self.recover()['status'], 'ready')
        self.assertEqual(self.snapshot(), before)
        backup = Path(self.backups) / 'before'
        result = self.recover(apply=True, backup_directory=backup)
        self.assertEqual(result['questions'], 25)
        self.assertEqual(result['publication_state'], 'draft')
        after = self.snapshot()
        again = self.recover(apply=True, backup_directory=Path(self.backups) / 'unused')
        self.assertEqual(again['status'], 'already_restored')
        self.assertEqual(result['test_id'], again['test_id'])
        self.assertEqual(self.snapshot(), after)
        with closing(repository.connect(self.path)) as db:
            saved = json.loads(Store(db, 'tests').get('test_drafts', result['test_id'])['document_json'])
            self.assertEqual(saved, self.doc)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tests').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM test_versions').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertTrue(json.loads((backup / 'verification.json').read_text())['restore_verified'])

    def test_conflicting_partial_draft_is_not_overwritten(self):
        with closing(repository.connect(self.path)) as db:
            created = service.create_test(db, {'request_key': 'other-create'}, 1)
            service.save_draft(db, created['test_id'], {'request_key': 'other-save',
                'expected_revision': created['revision'], 'document': {'title': self.doc['title']}}, 1)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'partial'):
            self.recover(apply=True, backup_directory=Path(self.backups) / 'before')
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_save_rolls_back_creation_and_json(self):
        before = self.snapshot()
        save = repository.save_draft_in_transaction
        def fail_after_save(*args, **kwargs):
            save(*args, **kwargs)
            raise RuntimeError('synthetic failure')
        with mock.patch.object(repository, 'save_draft_in_transaction', side_effect=fail_after_save):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.recover(apply=True, backup_directory=Path(self.backups) / 'before')
        self.assertEqual(self.snapshot(), before)

    def test_no_normalization_or_nonadmin_recovery(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'administrator'):
            recover(self.source, self.path, actor_id=2, apply=True,
                    backup_directory=Path(self.backups) / 'before')
        self.doc['questions'][0]['code_text'] = 'one\r\ntwo'
        self.source.write_text(json.dumps(self.doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'change the backup'):
            self.recover(apply=True, backup_directory=Path(self.backups) / 'before')
        self.assertEqual(self.snapshot(), before)
