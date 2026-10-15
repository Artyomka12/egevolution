"""Migration acceptance: nonempty learner history survives independent export."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from thematic_support import ROOT, platform_database, backup
from scripts.migrate import migrate
from scripts.json_content_migration import build_candidate
from features.thematic.validation import make_snapshot, canonical_json, digest
from features.thematic import repository as thematic, student_views
from features.tests import repository as tests, serializers
from features.tests.validation import validate_publication


def insert(db, table, **values):
    return db.execute('INSERT INTO ' + table + ' (' + ','.join(values) + ') VALUES (' +
                      ','.join('?' for _ in values) + ')', tuple(values.values())).lastrowid


class MigrationHistoryTests(unittest.TestCase):
    def test_all_history_and_grades_survive_json_candidate(self):
        with tempfile.TemporaryDirectory(prefix='ege-history-source-') as source_dir, \
             tempfile.TemporaryDirectory(prefix='ege-history-target-') as target_dir:
            root = Path(source_dir).resolve()
            source = root / 'legacy.db'
            platform_database(source)
            backup(source, root / 'before.db')
            migrations = root / 'migrations'
            migrations.mkdir()
            for name in ('001_thematic.sql', '002_tests.sql'):
                shutil.copyfile(ROOT / 'migrations' / name, migrations / name)
            migrate(source, apply=True, backup=root / 'before.db', offline=True, directory=migrations)
            with closing(thematic.connect(source)) as db:
                insert(db, 'users', id=2, username='synthetic-history-student', password_hash='fixture-only', is_admin=0)
                insert(db, 'user_results', user_id=2, variant_num=1, score=17)
                insert(db, 'user_theory_progress', user_id=2, task_num=7, practice_task_id=1)
                self.seed_thematic(db)
                self.seed_test(db)
                tables = ('users', 'user_results', 'user_theory_progress', 'thematic_attempts',
                          'thematic_answers', 'thematic_visibility_intervals', 'thematic_operation_keys',
                          'test_attempts', 'test_attempt_answers', 'test_grade_events',
                          'test_attempt_grants', 'test_operation_keys')
                before = {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                          for table in tables}
            source_bytes = source.read_bytes()
            target = Path(target_dir) / 'candidate'
            build_candidate(source, target)
            self.assertEqual(source.read_bytes(), source_bytes)
            with closing(thematic.connect(target / 'users.db')) as db:
                after = {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                         for table in tables}
                self.assertEqual(after, before)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                thematic_result = student_views.finished_result(db, 101, 2)
                self.assertEqual(thematic_result['correct_count'], 1)
                self.assertEqual(thematic_result['questions'][0]['answer'], '9')
                self.assertEqual(thematic_result['questions'][0]['reference'], '9')
                result = serializers.result_dto(tests.get_attempt(db, 201), tests.get_version(db, 20),
                                                tests.get_answers(db, 201), now=5000)
                self.assertEqual(result['summary']['final_score'], 2)
                self.assertEqual([q['score'] for q in result['questions']], [1, 1])
                self.assertEqual(tests.get_attempt(db, 202)['state'], 'active')
                self.assertEqual(db.execute('SELECT state FROM thematic_attempts WHERE id=102').fetchone()[0], 'active')

    def seed_thematic(self, db):
        snapshot = make_snapshot(1, {'id': 1, 'description': ['Historical condition'], 'correct_answer': '9'})
        insert(db, 'thematic_variants', id=10, created_by=1, created_at=0, updated_at=0)
        insert(db, 'thematic_versions', id=10, variant_id=10, version_no=1, title='Historical thematic',
               description='', question_count=1, snapshot_schema_version=1, grader_version=snapshot['grader_version'],
               content_hash=digest({'title':'Historical thematic','description':'','items':[snapshot]}), published_by=1, published_at=0)
        insert(db, 'thematic_version_items', id=10, version_id=10, position=1, source_task_num=1,
               source_task_id=1, task_type=snapshot['task_type'], snapshot_json=canonical_json(snapshot), snapshot_hash=digest(snapshot))
        db.execute('UPDATE thematic_versions SET sealed=1 WHERE id=10')
        db.execute("UPDATE thematic_variants SET state='published',current_version_id=10 WHERE id=10")
        for ident, number in ((101, 1), (102, 2)):
            insert(db, 'thematic_attempts', id=ident, user_id=2, variant_id=10, version_id=10,
                   attempt_no=number, started_at=100, total_count=1, start_request_key=str(ident))
            insert(db, 'thematic_answers', attempt_id=ident, item_id=10, version_id=10,
                   answer_json='"9"', revision=1, saved_at=200)
            if ident == 101:
                db.execute("UPDATE thematic_answers SET checked_revision=1,is_correct=1,checked_at=300,final_status='correct' WHERE attempt_id=101")
                db.execute("UPDATE thematic_attempts SET state='finished',submitted_at=300,finish_reason='user',elapsed_ms=200,correct_count=1,result_revision=1 WHERE id=101")
        insert(db, 'thematic_visibility_intervals', variant_id=10, hidden_at=400, visible_at=450, hidden_by=1, visible_by=1)
        insert(db, 'thematic_operation_keys', actor_user_id=2, operation_scope='start:10', request_key='historical-start',
               request_hash='a'*64, resource_id=102, created_at=100)

    def seed_test(self, db):
        doc = validate_publication(dict(title='Historical test', description='', time_limit_seconds=60,
            attempt_limit=2, show_correct_answers=True, questions=[
                dict(title='Automatic', prompt_text='Enter nine', question_type='free_text', free_input_mode='singleline',
                     grading_mode='auto', accepted_answers=['9']),
                dict(title='Manual', prompt_text='Explain', question_type='free_text', free_input_mode='multiline',
                     grading_mode='manual')]))
        insert(db, 'tests', id=20, created_by=1, created_at=0, updated_at=0)
        insert(db, 'test_versions', id=20, test_id=20, version_no=1, title=doc['title'], description='',
               time_limit_seconds=60, attempt_limit=2, show_correct_answers=1, question_count=2,
               content_hash=digest(doc), published_by=1, published_at=0)
        for ident, question in enumerate(doc['questions'], 20):
            insert(db, 'test_version_questions', id=ident, version_id=20, position=ident-19,
                   title=question['title'], prompt_text=question['prompt_text'], code_text=question.get('code_text'),
                   question_type='free_text', free_input_mode=question['free_input_mode'], grading_mode=question['grading_mode'])
        insert(db, 'test_accepted_answers', question_id=20, position=1, value='9')
        db.execute('UPDATE test_versions SET sealed=1 WHERE id=20')
        db.execute("UPDATE tests SET publication_state='published',current_version_id=20 WHERE id=20")
        for ident, number in ((201, 1), (202, 2)):
            insert(db, 'test_attempts', id=ident, user_id=2, test_id=20, version_id=20, attempt_no=number,
                   started_at=1000, deadline_at=61000, time_limit_seconds_snapshot=60,
                   show_correct_answers_snapshot=1, start_request_key=str(ident))
            for question_id, answer in ((20, '9'), (21, 'Historical explanation')):
                insert(db, 'test_attempt_answers', attempt_id=ident, question_id=question_id, version_id=20,
                       answer_json=canonical_json(answer), revision=1, saved_at=1500, was_unanswered=0)
            if ident == 201:
                db.execute("UPDATE test_attempt_answers SET score=1,auto_score=CASE WHEN question_id=20 THEN 1 END,grading_source=CASE WHEN question_id=20 THEN 'automatic' ELSE 'manual' END,graded_by=CASE WHEN question_id=21 THEN 1 END,graded_at=2000,grade_revision=1 WHERE attempt_id=201")
                db.execute("UPDATE test_attempts SET state='graded',submitted_at=2000,finalized_at=2000,finish_reason='manual',result_revision=2 WHERE id=201")
        for question, source, actor in ((20, 'automatic', None), (21, 'manual', 1)):
            insert(db, 'test_grade_events', attempt_id=201, question_id=question, new_score=1, new_source=source,
                   actor_user_id=actor, actor_kind='system' if actor is None else 'admin', occurred_at=2000,
                   request_key='grade-'+str(question), result_revision=2)
        insert(db, 'test_attempt_grants', user_id=2, test_id=20, amount=1, granted_by=1, granted_at=3000, request_key='historical-grant')
        insert(db, 'test_operation_keys', actor_user_id=2, operation_scope='start', request_key='historical-test-start',
               request_hash='b'*64, resource_id=202, created_at=1000)
