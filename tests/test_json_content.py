"""Independent filesystem/SQLite boundary checks; synthetic temporary databases only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core import content_store as content
from features.tests import repository as repo

ROOT = Path(__file__).resolve().parents[1]


def document():
    return {'title': 'Synthetic JSON test', 'description': 'Private source',
            'time_limit_seconds': 60, 'attempt_limit': None, 'show_correct_answers': True,
            'questions': [{'title': 'Text', 'prompt_text': 'Explain <>&',
                'code_text': 'for x in range(2):\n    print(x)\n', 'question_type': 'free_text',
                'free_input_mode': 'multiline', 'grading_mode': 'auto',
                'accepted_answers': ['Answer\n  exact'], 'options': []}]}


class JsonContentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ege-json-boundary-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop('EGEVOLUTION_CONTENT_ROOT', None)
        self.path = self.root / 'synthetic.db'
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        self.db.execute('INSERT INTO users VALUES(1)')
        # Empty, synthetic databases only. This suite isolates the storage layer
        # from the backup/export migration runner which has its own tests.
        from scripts.migrate import files
        from scripts.json_content_migration import expected_schema
        for sql in expected_schema(files(ROOT/'migrations')).values():
            self.db.execute(sql)
        self.db.execute('PRAGMA foreign_keys=ON')
        for domain in ('thematic','tests'):
            content.initialize(self.db, domain, {})

    def publish(self):
        with content.transaction(self.db):
            ident = repo.create_test_in_transaction(self.db, document(), actor_id=1, now=100)
            version = repo.store_version_in_transaction(self.db, ident, document(), actor_id=1, now=100)
            store = content.store_for(self.db,'tests')
            store.update('tests',ident,current_version_id=version,publication_state='published')
        return ident,version

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for folder in ('tests_content','thematic_variants') for p in (self.root/folder).rglob('*.json')}

    def test_existing_document_edit_persists_and_original_snapshot_is_detached(self):
        ident,_ = self.publish()
        with content.transaction(self.db):
            store = content.store_for(self.db,'tests')
            previous = deepcopy(store.original_files)
            store.update('tests',ident,publication_state='hidden')
            self.assertEqual(store.original_files,previous)
        self.assertEqual(content.store_for(self.db,'tests').get('tests',ident)['publication_state'],'hidden')

    def test_unicode_newlines_specials_and_author_redaction(self):
        ident,_ = self.publish()
        edited = document()
        edited['questions'][0]['accepted_answers'] = ['\n  Привет <script> & " \\u0000\n']
        with content.transaction(self.db):
            repo.save_draft_in_transaction(self.db,ident,edited,expected_revision=1,actor_id=1,now=101)
        self.assertEqual(repo.get_draft(self.db,ident)['document']['questions'][0]['accepted_answers'],edited['questions'][0]['accepted_answers'])
        data = json.loads((self.root/'tests_content'/f'test_{ident}'/'material.json').read_text(encoding='utf-8'))
        self.assertIsNone(data['draft']['updated_by'])
        self.assertEqual(repo.get_draft(self.db,ident)['document']['questions'][0]['code_text'],edited['questions'][0]['code_text'])

    def test_failed_transaction_restores_json_and_sql_rows(self):
        self.publish(); before = self.files()
        count = self.db.execute('SELECT COUNT(*) FROM tests').fetchone()[0]
        with self.assertRaisesRegex(RuntimeError,'synthetic'):
            with content.transaction(self.db):
                repo.create_test_in_transaction(self.db,document(),actor_id=1,now=100)
                raise RuntimeError('synthetic rollback')
        self.assertEqual(self.files(),before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM tests').fetchone()[0],count)

    def test_partial_file_write_failure_rolls_back_every_file(self):
        ident,_ = self.publish(); before = self.files()
        original = content._write
        replacements = []
        def fail_once(path,value):
            if path.name != 'journal.json':
                replacements.append(path)
                if len(replacements) == 2: raise OSError('synthetic disk failure')
            return original(path,value)
        with mock.patch.object(content,'_write',side_effect=fail_once):
            with self.assertRaises(OSError):
                with content.transaction(self.db):
                    store = content.store_for(self.db,'tests')
                    store.update('tests',ident,publication_state='hidden')
                    store.update('test_catalog_state',1,revision=store.get('test_catalog_state',1)['revision']+1)
        self.assertGreaterEqual(len(replacements),2)
        self.assertEqual(self.files(),before)
        self.assertFalse((self.root/'.content-runtime'/'journal.json').exists())

    def test_committed_journal_is_replayed_idempotently(self):
        self.publish()
        path = self.root/'tests_content'/'catalog.json'
        old = json.loads(path.read_text(encoding='utf-8')); new = deepcopy(old)
        new['catalog_state']['revision'] += 1
        runtime = self.root/'.content-runtime'
        content._write(runtime/'journal.json',{'id':'synthetic-committed','database':str(self.path.resolve()),
            'files':[{'path':'tests_content/catalog.json','old':old,'new':new}]})
        self.db.execute('INSERT INTO content_commits VALUES(?)',('synthetic-committed',))
        for _ in range(2):
            self.assertEqual(content.store_for(self.db,'tests').get('test_catalog_state',1)['revision'],new['catalog_state']['revision'])
        self.assertFalse((runtime/'journal.json').exists())

    def test_uncommitted_journal_rolls_back(self):
        self.publish()
        path = self.root/'tests_content'/'catalog.json'
        old = json.loads(path.read_text(encoding='utf-8')); new = deepcopy(old)
        new['catalog_state']['revision'] += 1
        content._write(self.root/'.content-runtime'/'journal.json',{'id':'synthetic-uncommitted','database':str(self.path.resolve()),
            'files':[{'path':'tests_content/catalog.json','old':old,'new':new}]})
        content._write(path,new)
        self.assertEqual(content.store_for(self.db,'tests').get('test_catalog_state',1)['revision'],old['catalog_state']['revision'])

    def test_parent_test_deletion_cascades_json_and_identity_rows(self):
        ident,version = self.publish()
        with content.transaction(self.db):
            content.store_for(self.db,'tests').delete('tests',ident)
            self.db.execute('DELETE FROM tests WHERE id=?',(ident,))
        store = content.store_for(self.db,'tests')
        for table in ('tests','test_versions','test_drafts','test_version_questions','test_accepted_answers','test_question_options','test_media_links'):
            self.assertEqual(store.rows(table),[])
        self.assertFalse((self.root/'tests_content'/f'test_{ident}'/'versions'/f'{version}.json').exists())
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_standalone_sealed_children_cannot_be_mutated(self):
        _,version = self.publish()
        question = repo.get_version(self.db,version)['questions'][0]['id']
        with content.transaction(self.db):
            store = content.store_for(self.db,'tests')
            answer = store.rows('test_accepted_answers')[0]
            for action in (lambda:store.insert('test_accepted_answers',dict(question_id=question,position=2,value='new')),
                           lambda:store.update('test_accepted_answers',answer['id'],value='new'),
                           lambda:store.delete('test_accepted_answers',answer['id']),
                           lambda:store.delete('test_versions',version)):
                with self.assertRaises(sqlite3.IntegrityError): action()

    def test_readers_fail_closed_on_invalid_json_missing_and_duplicate_keys(self):
        ident,_ = self.publish()
        path = self.root/'tests_content'/f'test_{ident}'/'material.json'
        original = path.read_bytes()
        for invalid in (b'{}',b'{broken',b'{"schema_version":1,"schema_version":1}',b'null'):
            path.write_bytes(invalid)
            with self.assertRaises(content.ContentError): content.store_for(self.db,'tests')
        path.unlink()
        with self.assertRaises(content.ContentError): content.store_for(self.db,'tests')
        path.write_bytes(original)
        self.assertIsNotNone(content.store_for(self.db,'tests').get('tests',ident))

    def test_snapshot_edit_with_recomputed_content_hash_still_rejected(self):
        ident,version = self.publish()
        path = self.root/'tests_content'/f'test_{ident}'/'versions'/f'{version}.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        changed = document(); changed['title'] = 'Substituted version'
        from features.tests.validation import validate_publication
        raw['version']['title'] = changed['title']
        raw['version']['content_hash'] = content.digest(validate_publication(changed))
        path.write_text(json.dumps(raw),encoding='utf-8')
        with self.assertRaises(content.ContentError): content.store_for(self.db,'tests')

    def test_invalid_positions_and_orphans_are_rejected(self):
        self.publish(); store = content.store_for(self.db,'tests')
        for change in (lambda s:s.data['test_version_questions'][0].update(position=2),
                       lambda s:s.data['test_versions'][0].update(question_count=2),
                       lambda s:s.data['test_accepted_answers'][0].update(question_id=999),
                       lambda s:s.data['test_versions'][0].update(time_limit_seconds=0)):
            original = deepcopy(store.data); change(store)
            with self.assertRaises(content.ContentError): store.validate()
            store.data = original

    def test_content_tables_contain_only_identifiers_and_hashes(self):
        self.publish()
        allowed = {'id','variant_id','version_id','test_id','question_id','json_hash','created_by'}
        for table in content.IDENTITIES:
            columns = {r[1] for r in self.db.execute('PRAGMA table_info('+table+')')}
            self.assertLessEqual(columns,allowed)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_safe_paths_reject_escape_and_windows_aliases(self):
        for path in ('../outside','C:/outside','/outside','tests_content\\..\\outside','x:stream'):
            with self.assertRaises(content.ContentError): content._safe(self.root,path)

    def test_recovery_never_writes_outside_content_json(self):
        self.publish()
        database_before = self.path.read_bytes()
        content._write(self.root/'.content-runtime'/'journal.json',{'id':'synthetic-invalid','database':str(self.path.resolve()),
            'files':[{'path':'synthetic.db','old':None,'new':{'damage':True}}]})
        with self.assertRaises(content.ContentError): content.store_for(self.db,'tests')
        self.assertEqual(self.path.read_bytes(),database_before)
        self.assertTrue((self.root/'.content-runtime'/'journal.json').exists())

    def test_stale_store_cannot_mutate_later_transaction(self):
        ident,_ = self.publish()
        old = content.store_for(self.db,'tests')
        with content.transaction(self.db):
            with self.assertRaises(content.ContentError): old.update('tests',ident,publication_state='hidden')

    def test_git_transferred_json_registers_references_without_material_migration(self):
        ident,version = self.publish()
        target = self.root/'independent-server'; target.mkdir()
        other = sqlite3.connect(target/'server.db',isolation_level=None)
        self.addCleanup(other.close)
        other.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        other.execute('INSERT INTO users VALUES(42)')
        from scripts.migrate import files
        from scripts.json_content_migration import expected_schema
        for sql in expected_schema(files(ROOT/'migrations')).values():
            other.execute(sql)
        other.execute('PRAGMA foreign_keys=ON')
        shutil.copytree(self.root/'tests_content',target/'tests_content')
        store = content.store_for(other,'tests')
        self.assertEqual(store.get('tests',ident)['current_version_id'],version)
        self.assertEqual(other.execute('SELECT id FROM users').fetchall(),[(42,)])
        self.assertEqual(other.execute('SELECT COUNT(*) FROM test_versions').fetchone()[0],1)
        self.assertEqual(other.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_process_crash_before_and_after_sqlite_commit_recovers_consistently(self):
        ident,_ = self.publish()
        code = '''import os, sqlite3, sys
from core import content_store as content
path, ident, stage = sys.argv[1], int(sys.argv[2]), sys.argv[3]
class Connection(sqlite3.Connection):
    def commit(self):
        super().commit()
        if stage == 'after': os._exit(17)
db = sqlite3.connect(path, isolation_level=None, factory=Connection)
db.execute('PRAGMA foreign_keys=ON')
original = content._write
def interrupted(path,value):
    original(path,value)
    if path.name != 'journal.json' and stage == 'before': os._exit(17)
content._write = interrupted
with content.transaction(db):
    store = content.store_for(db,'tests')
    store.update('tests',ident,publication_state='hidden')
    store.update('test_catalog_state',1,revision=store.get('test_catalog_state',1)['revision']+1)
'''
        for stage,expected in (('before','published'),('after','hidden')):
            result = subprocess.run([sys.executable,'-B','-c',code,str(self.path),str(ident),stage],
                                    cwd=ROOT,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,17,result.stderr.decode(errors='replace'))
            self.assertTrue((self.root/'.content-runtime'/'journal.json').exists())
            self.assertEqual(content.store_for(self.db,'tests').get('tests',ident)['publication_state'],expected)
            self.assertFalse((self.root/'.content-runtime'/'journal.json').exists())
            self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')


if __name__ == '__main__':
    unittest.main()
