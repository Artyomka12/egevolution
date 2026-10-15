import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from thematic_support import DatabaseCase
from features.thematic import repository
from features.thematic.validation import make_snapshot, canonical_json, digest


class SchemaTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.db = self.open()

    def test_tables_and_foreign_keys_enabled(self):
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'thematic_%'")}
        self.assertEqual(len(names), 8)
        self.assertEqual([r['name'] for r in self.db.execute('PRAGMA table_info(thematic_variants)')], ['id'])
        self.assertEqual(self.db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(self.db.execute('PRAGMA recursive_triggers').fetchone()[0], 1)

    def test_duplicate_sources_at_both_layers_and_positions(self):
        variant,version,items=self.seed_version(self.db)
        self.assertEqual(len(items),2)
        draft={'items':[{'source_task_num':1,'source_task_id':1}]*2}
        with self.assertRaises(ValueError):
            repository.save_draft(self.db,variant,draft,expected_revision=0,actor_id=1,now=1)
        snapshots = [make_snapshot(1, {'id': 1, 'description': ['x'], 'correct_answer': '9'})] * 2
        with self.assertRaises(ValueError):
            repository.store_version(self.db, variant, 'Duplicate', '', snapshots, actor_id=1, now=1)
        # JSON storage must enforce the same duplicate-source invariant itself.
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            with repository.transaction(self.db):
                second = repository.insert(self.db, 'versions', dict(variant_id=variant, version_no=2,
                    title='x', description='', question_count=2, snapshot_schema_version=1,
                    grader_version='ordinary-binary-v1', content_hash=digest({'title':'x','description':'','items':snapshots}), published_at=0, sealed=0))
                for position in (1, 2):
                    repository.insert(self.db, 'version_items', dict(version_id=second, position=position,
                        source_task_num=1, source_task_id=1, task_type=snapshots[0]['task_type'],
                        snapshot_json=canonical_json(snapshots[0]), snapshot_hash=digest(snapshots[0])))
                repository.update(self.db, 'versions', second, sealed=1)

    def test_draft_cas_does_not_change_current_version(self):
        variant,version,_=self.seed_version(self.db)
        self.update_content(self.db, 'variants', variant, state='published', current_version_id=version)
        doc={'title':'Unfinished draft','items':[]}
        self.assertEqual(repository.save_draft(self.db,variant,doc,expected_revision=0,actor_id=1,now=1),1)
        with self.assertRaises(repository.Conflict):
            repository.save_draft(self.db,variant,doc,expected_revision=0,actor_id=1,now=2)
        self.assertEqual(repository.row(self.db, 'variants', variant)['current_version_id'],version)

    def test_sealed_versions_and_media_are_immutable(self):
        self.insert_content(self.db, 'media', id=1, storage_key='a'*64, sha256='a'*64,
                            mime_type='image/png', size_bytes=20, width=2, height=2, original_name='source.png', created_at=0)
        variant=self.insert_content(self.db, 'variants', created_at=0, updated_at=0)
        task={'id':1,'description':['condition'],'correct_answer':'42','images':[{'path':'source.png','alt':'old'}]}
        snap=make_snapshot(7,task,[{'role':'condition','position':1,'source_path':'source.png','media_id':1,'sha256':'a'*64}])
        version=repository.store_version(self.db,variant,'V1','',[snap],actor_id=1,now=1)
        item = repository.get_version(self.db, version)['items'][0]['id']
        for table, ident, changes in [
            ('versions', version, {'title':'changed'}), ('versions', version, {'sealed':0}),
            ('version_items', item, {'snapshot_json':'{}'}), ('version_items', item, None),
            ('versions', version, None), ('media', 1, {'storage_key':'different'}), ('media', 1, None),
            ('item_media', (item,'condition',1), None), ('item_media', (item,'condition',1), {'alt_text':'changed'})]:
            with self.assertRaises((ValueError, sqlite3.IntegrityError), msg=table):
                with repository.transaction(self.db):
                    if changes is None:
                        repository.content(self.db).delete('thematic_' + table, ident)
                    else:
                        repository.update(self.db, table, ident, **changes)
        task['correct_answer']='99';task['images'][0]['alt']='new'
        self.assertEqual(repository.get_version(self.db,version)['items'][0]['snapshot']['grading']['correct_answer'],'42')
        self.update_content(self.db, 'variants', variant, state='deleted', deleted_at=5)
        self.assertIsNotNone(repository.get_version(self.db,version))
        with self.assertRaises(repository.Conflict):repository.store_version(self.db,variant,'V2','',[snap],actor_id=1,now=6)

    def test_wrong_media_rolls_back_whole_assembly(self):
        variant=self.insert_content(self.db, 'variants', created_at=0, updated_at=0)
        snapshot=make_snapshot(1,{'id':1,'description':['x'],'correct_answer':'1','images':[{'path':'x.png'}]},
                               [{'role':'condition','position':1,'source_path':'x.png','media_id':99,'sha256':'a'*64}])
        with self.assertRaises(ValueError):repository.store_version(self.db,variant,'x','',[snapshot],actor_id=1,now=0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM thematic_versions').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM thematic_version_items').fetchone()[0],0)

    def test_cross_variant_and_cross_version_fk(self):
        a,v1,i1=self.seed_version(self.db)
        b,v2,i2=self.seed_version(self.db)
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            self.update_content(self.db, 'variants', a, current_version_id=v2)
        attempt=self.attempt(self.db,a,v1,i1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO thematic_answers(attempt_id,item_id,version_id) VALUES (?,?,?)',(attempt,i2[0],v2))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('UPDATE thematic_attempts SET version_id=? WHERE id=?',(v2,attempt))

    def test_attempts_history_binary_scores_and_final_freeze(self):
        variant,v1,items=self.seed_version(self.db)
        first=self.attempt(self.db,variant,v1,items)
        with self.assertRaises(sqlite3.IntegrityError):self.attempt(self.db,variant,v1,items,2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('UPDATE thematic_answers SET is_correct=2 WHERE attempt_id=?',(first,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE thematic_attempts SET state='finished',submitted_at=10,elapsed_ms=10,finish_reason='user',correct_count=0 WHERE id=?",(first,))
        self.db.execute("UPDATE thematic_answers SET is_correct=0,checked_revision=revision,final_status='skipped' WHERE attempt_id=?",(first,))
        self.db.execute("UPDATE thematic_attempts SET state='finished',submitted_at=10,elapsed_ms=10,finish_reason='user',correct_count=0 WHERE id=?",(first,))
        _,v2,items2=self.seed_version(self.db,count=3,variant_id=variant)
        self.attempt(self.db,variant,v2,items2,2)
        history=repository.list_attempts(self.db,1,variant)
        self.assertEqual([(a['version_id'],a['total_count']) for a in history],[(v1,2),(v2,3)])
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE thematic_answers SET answer_json='\"changed\"' WHERE attempt_id=?",(first,))
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('UPDATE thematic_attempts SET elapsed_ms=1 WHERE id=?',(first,))

    def test_hidden_intervals_and_idempotency_keys(self):
        variant,_,_=self.seed_version(self.db)
        self.db.execute('INSERT INTO thematic_visibility_intervals(variant_id,hidden_at,visible_at) VALUES (?,10,20)',(variant,))
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO thematic_visibility_intervals(variant_id,hidden_at,visible_at) VALUES (?,15,25)',(variant,))
        ident=self.db.execute('INSERT INTO thematic_visibility_intervals(variant_id,hidden_at) VALUES (?,20)',(variant,)).lastrowid
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO thematic_visibility_intervals(variant_id,hidden_at) VALUES (?,30)',(variant,))
        self.db.execute('UPDATE thematic_visibility_intervals SET visible_at=30 WHERE id=?',(ident,))
        self.db.execute('INSERT INTO thematic_visibility_intervals(variant_id,hidden_at) VALUES (?,40)',(variant,))
        values=(1,'start:1','key','a'*64,1,0)
        self.db.execute('INSERT INTO thematic_operation_keys VALUES (?,?,?,?,?,?)',values)
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO thematic_operation_keys VALUES (?,?,?,?,?,?)',values)

    def test_160_items_and_author_deletion_preserves_snapshots(self):
        variant,version,items=self.seed_version(self.db,count=160)
        self.assertEqual(len(items),160)
        self.db.execute('DELETE FROM users WHERE id=1')
        self.assertIsNone(repository.get_version(self.db,version)['published_by'])

    def test_two_connections_cannot_create_two_active_attempts(self):
        variant,version,items=self.seed_version(self.db)
        barrier=Barrier(2)
        def insert(number):
            with closing(repository.connect(self.path)) as db:
                barrier.wait(timeout=5)
                try:
                    with repository.transaction(db):
                        self.attempt(db,variant,version,items,number)
                    return 'created'
                except sqlite3.IntegrityError:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(insert,[1,2]))
        self.assertCountEqual(results,['created','conflict'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM thematic_attempts').fetchone()[0],1)
