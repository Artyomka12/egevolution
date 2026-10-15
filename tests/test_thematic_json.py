"""JSON persistence and historical-result safeguards, synthetic fixtures only."""
import json
from contextlib import closing
from thematic_support import DatabaseCase
from features.thematic import repository
from core.content_store import ContentError


class JsonContentTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.db = self.open()

    def test_json_is_source_and_sqlite_has_no_curriculum_columns(self):
        variant, version, items = self.seed_version(self.db)
        stored = repository.get_version(self.db, version)
        folder = repository.content(self.db).root / ('variant_' + str(variant))
        document = json.loads((folder / 'versions' / (str(version) + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(document['version']['title'], stored['title'])
        self.assertEqual(len(document['tables']['thematic_version_items']), len(items))
        self.assertIsNone(document['version']['published_by'])
        self.assertNotIn('title', [r['name'] for r in self.db.execute('PRAGMA table_info(thematic_versions)')])
        self.assertNotIn('snapshot_json', [r['name'] for r in self.db.execute('PRAGMA table_info(thematic_version_items)')])
        with closing(repository.connect(self.path)) as other:
            self.assertEqual(repository.get_version(other, version), stored)

    def test_missing_or_changed_historical_version_fails_closed(self):
        variant, version, _ = self.seed_version(self.db)
        path = repository.content(self.db).root / ('variant_' + str(variant)) / 'versions' / (str(version) + '.json')
        original = path.read_bytes()
        for damaged in (b'{ invalid json', b'{}'):
            path.write_bytes(damaged)
            with self.assertRaises(ContentError):
                repository.get_version(self.db, version)
            path.write_bytes(original)
        document = json.loads(original)
        document['version']['title'] = 'Changed after publication'
        path.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(ContentError):
            repository.get_version(self.db, version)
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(ContentError):
            repository.get_version(self.db, version)

    def test_rollback_leaves_json_and_identity_rows_unchanged(self):
        variant, version, _ = self.seed_version(self.db)
        root = repository.content(self.db).root
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*.json')}
        identities = self.db.execute('SELECT COUNT(*) FROM thematic_variants').fetchone()[0]
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with repository.transaction(self.db):
                repository.insert(self.db, 'variants', dict(created_at=1, updated_at=1))
                repository.update(self.db, 'variants', variant, sort_order=99)
                raise RuntimeError('injected')
        after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*.json')}
        self.assertEqual(after, before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM thematic_variants').fetchone()[0], identities)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_draft_unicode_and_special_characters_round_trip(self):
        variant, version, _ = self.seed_version(self.db)
        document = {'title': 'Учебный <пример> "№1"',
                    'description': 'Первая строка\n    Вторая строка & </textarea> \\', 'items': []}
        repository.save_draft(self.db, variant, document, expected_revision=0, actor_id=1, now=1)
        stored = repository.row(self.db, 'drafts', variant)
        self.assertEqual(json.loads(stored['document_json']), document)
        with closing(repository.connect(self.path)) as other:
            self.assertEqual(json.loads(repository.row(other, 'drafts', variant)['document_json']), document)
        self.assertEqual(repository.get_version(self.db, version)['title'], 'Synthetic version')
