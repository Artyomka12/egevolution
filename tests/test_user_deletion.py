"""Account deletion against the real Flask route and disposable migrated SQLite."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from flask_wtf.csrf import generate_csrf
from core.user_deletion import delete_user_data_in_transaction
from features.tests import repository as repo, service
from features.tests.errors import TestsError
from features.thematic import repository as thematic
from features.thematic.validation import make_snapshot
from tests_support import DatabaseCase, document
import test_tests_integration as integration


class UserDeletionTests(DatabaseCase):
    application = integration.IntegrationTests.application

    def setUp(self):
        super().setUp()
        self.apply()
        self.app = self.enterContext(self.application())
        self.app.add_url_rule('/fixture-csrf', 'deletion_csrf', lambda: {'token': generate_csrf()})
        self.client = self.app.test_client()
        self.db = self.open()
        self.enterContext(mock.patch('features.tests.service.now_ms', self.clock))
        self.media = self.root / 'media' / 'shared.png'
        self.media.parent.mkdir()
        self.media.write_bytes(b'synthetic shared immutable image')
        self.login(1)
        self.seed_public()

    def login(self, user, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            session.clear()
            if user is not None:
                session['user_id'] = user
        return client.get('/fixture-csrf').json['token'] if user is not None else None

    def delete(self, user=2, client=None):
        client = client or self.client
        token = client.get('/fixture-csrf').json['token']
        return client.post(f'/admin/delete_user/{user}', headers={'X-CSRFToken': token})

    def seed_public(self, actor=1):
        db = self.db
        with repo.transaction(db):
            doc = document()
            self.test = repo.create_test_in_transaction(db, doc, actor_id=actor, now=self.clock())
            media_key = f'{actor:032x}'
            media = repo.create_media_in_transaction(db, storage_key=media_key, mime_type='image/png',
                    size_bytes=10, sha256='a'*64, width=1, height=1, alt_text='', actor_id=actor, now=self.clock())
            repo.link_media_in_transaction(db, self.test, media)
            (self.media.parent / media_key).write_bytes(self.media.read_bytes())
            doc['questions'][0]['media_id'] = media
            self.version = repo.store_version_in_transaction(db, self.test, doc, actor_id=actor, now=self.clock())
            repo.publish_version_in_transaction(db, self.test, self.version, expected_revision=1, now=self.clock())
            self.variant = thematic.insert(db, 'variants', dict(created_by=actor, created_at=0, updated_at=0))
            stored_media = thematic.rows(db, 'media')
            media = stored_media[0]['id'] if stored_media else thematic.insert(db, 'media', dict(
                storage_key='a'*64, sha256='a'*64, mime_type='image/png', size_bytes=10, original_name='shared.png', created_at=0))
            snapshot = make_snapshot(1, {'id': 1, 'description': ['Synthetic'], 'correct_answer': '9',
                           'images': [{'path': 'shared.png'}]}, materials=[dict(role='condition',position=1,
                           source_path='shared.png',media_id=media,sha256='a'*64,alt_text='',display_metadata={})])
            self.tv = thematic.store_version_in_transaction(db, self.variant, 'Synthetic', '', [snapshot], actor_id=actor, now=0)
            thematic.update(db, 'variants', self.variant, state='published', current_version_id=self.tv)
            self.item = thematic.get_version(db, self.tv)['items'][0]['id']

    def legacy(self, user, category='all'):
        rows = {
            'user_results': dict(variant_num=1,score=3),
            'user_task_answers': dict(variant_num=1,task_id=1,user_answer='synthetic',attempt_date='2026-01-01'),
            'user_variant_progress': dict(variant_num=1,time_remaining=300,answers_json='{}'),
            'user_lesson_progress': dict(lesson_id=1,task_id=1),
            'user_theory_progress': dict(task_num=1,practice_task_id=1),
            'user_lesson_last_answer': dict(lesson_id=1,task_id=1,answer_json='"synthetic"'),
            'user_theory_last_answer': dict(task_num=1,practice_task_id=1,answer_json='"synthetic"'),
            'user_lesson_access': dict(lesson_id=1,is_unlocked=1),
            'user_theory_access': dict(task_num=1,is_unlocked=1),
        }
        with repo.transaction(self.db):
            for table, values in rows.items():
                if category == 'variants' and table not in ('user_results','user_task_answers','user_variant_progress'):
                    continue
                values = dict(user_id=user, **values)
                self.db.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))

    def attempt(self, user, state='active'):
        with repo.transaction(self.db):
            ident = repo.create_attempt_in_transaction(self.db, user, self.test, self.version,
                                                       request_key=f'{user}-{state}', now=self.clock())
            question = repo.get_answers(self.db, ident)[0]['question_id']
            repo.save_answer_in_transaction(self.db, ident, question, 1, expected_revision=0, now=self.clock())
            if state != 'active':
                if state == 'pending':
                    manual = repo.get_answers(self.db, ident)[2]['question_id']
                    repo.save_answer_in_transaction(self.db, ident, manual, 'synthetic explanation', expected_revision=0, now=self.clock())
                service.finalize_in_transaction(self.db, repo.get_attempt(self.db, ident), now=self.clock(), reason='manual')
                repo.add_grade_event_in_transaction(self.db, ident, question, old_score=None,new_score=0,
                    old_source=None,new_source='automatic',actor_id=None,actor_kind='system',now=self.clock(),
                    request_key=f'event-{ident}',result_revision=1)
            repo.record_operation_in_transaction(self.db, user, 'start', f'key-{ident}', 'a'*64, ident, self.clock())
        return ident

    def thematic_attempt(self, user, finished=False):
        db = self.db
        with repo.transaction(db):
            ident=db.execute('''INSERT INTO thematic_attempts(user_id,variant_id,version_id,attempt_no,started_at,total_count,start_request_key)
                            VALUES (?,?,?,1,0,1,?)''', (user,self.variant,self.tv,f'key-{user}')).lastrowid
            db.execute('INSERT INTO thematic_answers(attempt_id,item_id,version_id) VALUES (?,?,?)',(ident,self.item,self.tv))
            if finished:
                db.execute("UPDATE thematic_answers SET answer_json='9',revision=1,checked_revision=1,is_correct=1,checked_at=1,final_status='correct' WHERE attempt_id=?",(ident,))
                db.execute("UPDATE thematic_attempts SET state='finished',submitted_at=1,finish_reason='user',elapsed_ms=1,correct_count=1 WHERE id=?",(ident,))
            db.execute('INSERT INTO thematic_operation_keys VALUES (?,?,?,?,?,?)',(user,'start',f'key-{user}','a'*64,ident,0))
        return ident

    def snapshot(self):
        return {row[0]: [dict(r) for r in self.db.execute(f'SELECT * FROM "{row[0]}" ORDER BY rowid')]
                for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}

    def healthy(self):
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.media.read_bytes(), b'synthetic shared immutable image')
        self.assertIsNotNone(repo.get_version(self.db, self.version))
        self.assertIsNotNone(thematic.get_version(self.db, self.tv))

    def assert_deleted_only(self, before, user):
        test_ids={r['id'] for r in before['test_attempts'] if r['user_id']==user}
        thematic_ids={r['id'] for r in before['thematic_attempts'] if r['user_id']==user}
        expected={}
        for table, rows in before.items():
            expected[table]=[r for r in rows if not (
                (table=='users' and r['id']==user) or r.get('user_id')==user or
                (table in ('test_operation_keys','thematic_operation_keys') and r['actor_user_id']==user) or
                (table in ('test_attempt_answers','test_grade_events') and r['attempt_id'] in test_ids) or
                (table=='thematic_answers' and r['attempt_id'] in thematic_ids))]
        self.assertEqual(self.snapshot(),expected)
        for table in expected:
            for fk in self.db.execute(f'PRAGMA foreign_key_list("{table}")'):
                if fk['table']=='users':
                    self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{fk["from"]}"=?',(user,)).fetchone()[0],0)
        self.healthy()

    def test_history_scenarios_and_other_student_unchanged(self):
        self.legacy(3)
        self.attempt(3,'graded')
        self.attempt(3)
        self.thematic_attempt(3,True)
        for user, scenario in enumerate(['empty','variants','thematic','graded','active','grant','all','pending'],10):
            with self.subTest(scenario=scenario):
                self.db.execute('INSERT INTO users(id,username,password_hash) VALUES (?,?,?)',(user,f'synthetic-{user}','fake'))
                if scenario in ('variants','all'): self.legacy(user,'all' if scenario=='all' else 'variants')
                if scenario in ('thematic','all'): self.thematic_attempt(user,scenario=='all')
                if scenario in ('graded','all'): self.attempt(user,'graded')
                if scenario in ('active','all'): self.attempt(user)
                if scenario=='pending': self.attempt(user,'pending')
                if scenario in ('grant','all'):
                    with repo.transaction(self.db):repo.add_grant_in_transaction(self.db,user,self.test,2,actor_id=1,now=self.clock(),request_key=f'grant-{user}')
                before=self.snapshot()
                self.assertEqual(self.delete(user).status_code,302)
                self.assert_deleted_only(before,user)

    def test_error_mid_delete_rolls_back_every_table(self):
        self.legacy(2);self.attempt(2,'graded');self.thematic_attempt(2)
        self.db.execute("CREATE TRIGGER fail_user_delete BEFORE DELETE ON user_results WHEN OLD.user_id=2 BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        before=self.snapshot()
        with self.assertLogs(self.app.logger,level='ERROR'):
            self.assertEqual(self.delete().status_code,500)
        self.assertEqual(self.snapshot(),before);self.healthy()

    def test_permissions_csrf_self_admin_policy_and_repeat(self):
        before=self.snapshot()
        self.assertEqual(self.client.post('/admin/delete_user/2').status_code,400)
        self.login(3);self.assertEqual(self.delete().status_code,403)
        self.login(None);self.assertIn(self.client.post('/admin/delete_user/2').status_code,(302,400))
        self.login(1);self.assertEqual(self.delete(1).status_code,302)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.delete().status_code,302)
        after=self.snapshot();self.assertEqual(self.delete().status_code,404);self.assertEqual(self.snapshot(),after)
        self.db.execute('UPDATE users SET is_admin=1 WHERE id=3')
        self.attempt(3);before=self.snapshot()
        self.assertEqual(self.delete(3).status_code,409);self.assertEqual(self.snapshot(),before);self.healthy()

    def test_attribution_set_null_keeps_publications(self):
        # A student can be a former author; do not delete the shared resource.
        self.seed_public(actor=2)
        before=self.snapshot();self.assertEqual(self.delete().status_code,302)
        expected={table:[dict(row) for row in rows if not(table=='users' and row['id']==2)] for table,rows in before.items()}
        for table in expected:
            for fk in self.db.execute(f'PRAGMA foreign_key_list("{table}")'):
                if fk['table']=='users' and fk['on_delete']=='SET NULL':
                    for row in expected[table]:
                        if row[fk['from']]==2: row[fk['from']]=None
        self.assertEqual(self.snapshot(),expected);self.healthy()

    def test_stale_session_and_inflight_legacy_write_cannot_restore_rows(self):
        student=self.app.test_client();token=self.login(2,student)
        # An already-open legacy connection must enforce FK even after deletion.
        legacy=self.app.view_functions['delete_user'].__globals__['get_db']()
        self.addCleanup(legacy.close)
        self.assertEqual(legacy.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(self.delete().status_code,302)
        response=student.post('/api/variant_progress/1',json={'answers':{},'time_remaining':300},headers={'X-CSRFToken':token})
        self.assertEqual(response.status_code,401)
        with self.assertRaises(sqlite3.IntegrityError):
            legacy.execute("INSERT INTO user_variant_progress(user_id,variant_num,time_remaining) VALUES (2,1,300)")
        legacy.rollback();self.healthy()

    def test_helper_rejects_foreign_keys_off_or_no_transaction(self):
        with self.assertRaises(ValueError):delete_user_data_in_transaction(self.db,2)
        self.db.execute('PRAGMA foreign_keys=OFF')
        try:
            with repo.transaction(self.db):
                with self.assertRaises(ValueError):delete_user_data_in_transaction(self.db,2)
        finally:self.db.execute('PRAGMA foreign_keys=ON')
        self.assertIsNotNone(self.db.execute('SELECT 1 FROM users WHERE id=2').fetchone());self.healthy()

    def test_delete_competes_with_autosave_and_worker(self):
        for worker in (False,True):
            user=20+int(worker)
            self.db.execute('INSERT INTO users(id,username,password_hash) VALUES (?,?,?)',(user,f'racer-{user}','fake'))
            ident=self.attempt(user)
            writer=service.claim_attempt(self.db,ident,{'expected_generation':1,'writer_client_id':'synthetic-client'},user)
            question=repo.get_answers(self.db,ident)[1]['question_id']
            if worker:self.clock.advance(60001)
            barrier=threading.Barrier(2)
            def deleting():
                client=self.app.test_client();self.login(1,client)
                barrier.wait(timeout=5)
                return self.delete(user,client).status_code
            def competing():
                db=repo.connect(self.path)
                try:
                    barrier.wait(timeout=5)
                    if worker:return service.expire_attempts(db)
                    try:return service.save_answer(db,ident,question,{'answer':'0','expected_revision':0,'generation':writer['generation'],'mutation_id':'synthetic-race'},user,writer['writer_token'])
                    except TestsError as error:return error.status
                finally:db.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(deleting);b=pool.submit(competing)
                self.assertEqual(a.result(timeout=10),302);result=b.result(timeout=10)
                if not worker:self.assertTrue(isinstance(result,dict) or result in (401,404),result)
            self.assertIsNone(repo.get_attempt(self.db,ident));self.healthy()

    def test_late_fk_failure_rolls_back_without_disabling_constraints(self):
        self.legacy(2);self.attempt(2);self.thematic_attempt(2)
        self.db.execute('CREATE TABLE extra_reference (user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT)')
        self.db.execute('INSERT INTO extra_reference VALUES (2)')
        before=self.snapshot()
        with self.assertLogs(self.app.logger,level='ERROR'):
            self.assertEqual(self.delete().status_code,500)
        self.assertEqual(self.snapshot(),before);self.healthy()

    def test_worker_candidates_selected_before_deletion_are_rechecked(self):
        ident=self.attempt(2);self.clock.advance(60001)
        original=repo.expired_attempt_ids
        def selected_then_deleted(db,now,**kwargs):
            candidates=original(db,now,**kwargs)
            self.assertIn(ident,candidates)
            self.assertEqual(self.delete().status_code,302)
            return candidates
        with mock.patch.object(repo,'expired_attempt_ids',side_effect=selected_then_deleted):
            self.assertEqual(service.expire_attempts(self.db),0)
        self.assertIsNone(repo.get_attempt(self.db,ident));self.healthy()

    def test_waiting_submit_and_save_cannot_recreate_deleted_attempt(self):
        from features.thematic import attempts as thematic_attempts
        for operation in ('save','submit','thematic'):
            user={'save':30,'submit':31,'thematic':32}[operation]
            self.db.execute('INSERT INTO users(id,username,password_hash) VALUES (?,?,?)',(user,f'waiter-{user}','fake'))
            if operation=='thematic':
                ident=self.thematic_attempt(user)
            else:
                ident=self.attempt(user)
                writer=service.claim_attempt(self.db,ident,{'expected_generation':1,'writer_client_id':'waiting-client'},user)
                question=repo.get_answers(self.db,ident)[1]['question_id']
            entered=threading.Event();release=threading.Event();started=threading.Event()
            original=delete_user_data_in_transaction
            def hold_delete(db,target):
                original(db,target);entered.set()
                if not release.wait(5):raise RuntimeError('test synchronization timed out')
            def deleting():
                client=self.app.test_client();self.login(1,client)
                return self.delete(user,client).status_code
            def waiting():
                db=repo.connect(self.path)
                try:
                    started.set()
                    if operation=='save':
                        return service.save_answer(db,ident,question,{'answer':'0','expected_revision':0,'generation':writer['generation'],'mutation_id':'waiting-save'},user,writer['writer_token'])
                    if operation=='submit':
                        return service.submit_attempt(db,ident,{'request_key':'waiting-submit','generation':writer['generation']},user,writer['writer_token'])
                    return thematic_attempts.mutate(db,ident,self.item,{'answer':'9','expected_revision':0,'mutation_id':'waiting-thematic-key'},user)
                except (TestsError,thematic_attempts.AttemptError) as error:return error.status
                finally:db.close()
            with mock.patch('core.user_deletion.delete_user_data_in_transaction',side_effect=hold_delete):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    a=pool.submit(deleting)
                    try:
                        self.assertTrue(entered.wait(5));b=pool.submit(waiting);self.assertTrue(started.wait(5))
                    finally:release.set()
                    self.assertEqual(a.result(timeout=10),302)
                    self.assertIn(b.result(timeout=10),(401,404))
            self.healthy()
