"""Real Flask pages, isolated DB/media, no server or external requests."""
import importlib.util
import json
import os
import re
import sqlite3
from unittest import mock
from thematic_support import DatabaseCase, ROOT
from features.thematic import attempts, repository, service
from features.thematic.validation import make_snapshot


class StudentPageCase(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.db = self.open()
        self.db.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (2,'synthetic-student','x',0)")
        self.db.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (3,'other-student','x',0)")
        self.variant = self.insert_content(self.db, 'variants', created_at=0, updated_at=0, created_by=1)
        self.version = self.version_with(2, 'Historical title')
        self.insert_content(self.db, 'drafts', variant_id=self.variant, document_json='{}', revision=1, updated_at=0)
        self.update_content(self.db, 'variants', self.variant, current_version_id=self.version, state='published')
        self.enterContext(mock.patch.dict(os.environ, {
            'SECRET_KEY': 'student-test-only', 'SITE_PASSWORD': 'synthetic', 'ADMIN_USERNAME': 'synthetic', 'ADMIN_PASSWORD': 'synthetic',
            'EGEVOLUTION_LOCAL_CHECK': '1', 'EGEVOLUTION_DB_PATH': str(self.path)
        }, clear=True))
        self.enterContext(mock.patch('dotenv.load_dotenv', return_value=False))
        self.enterContext(mock.patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))
        original_connect = sqlite3.connect
        def guarded(database, *args, **kwargs):
            self.assertEqual(database, self.path.as_uri() + '?mode=rw')
            return original_connect(database, *args, **kwargs)
        self.enterContext(mock.patch('sqlite3.connect', side_effect=guarded))
        spec = importlib.util.spec_from_file_location('thematic_student_test_app', ROOT / 'app.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.app = self.module.app
        self.app.config.update(TESTING=True, THEMATIC_MEDIA_ROOT=str(self.root / 'private-media'))
        self.client = self.app.test_client()
        self.actor(2)
        page = self.client.get(f'/thematic-variants/{self.variant}/solve')
        self.assertEqual(page.status_code, 200, page.text)
        self.csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text)[1]

    def actor(self, ident):
        with self.client.session_transaction() as session:
            session['user_id'] = ident

    def call(self, path, method='GET', body=None):
        return self.client.open(path, method=method, json=body, headers={'X-CSRFToken': self.csrf})

    def version_with(self, count, title):
        snapshots = [make_snapshot(1, {'id': n, 'description': ['<b>Original condition</b><table><tr><td>cell</td></tr></table>',
                '<pre>print(1)\nprint(2)</pre><img src=x onerror=alert(1)>'], 'correct_answer': 'PRIVATE_REFERENCE'}) for n in range(1, count + 1)]
        return repository.store_version(self.db, self.variant, title, 'Fixture description', snapshots, actor_id=1, now=0)

    def start(self, key='start-page-request-001'):
        return self.call(f'/api/thematic-variants/{self.variant}/attempts', 'POST', {'request_key': key}).json

    def complete(self, count=1, key='start-page-request-001'):
        attempt = self.start(key)
        questions = self.call(f'/api/thematic-attempts/{attempt["id"]}').json['questions']
        body = {'request_key': 'submit-page-request-001', 'answers': [
            {'item_id': q['item_id'], 'expected_revision': 0, 'answer': 'PRIVATE_REFERENCE'} for q in questions[:count]]}
        response = self.call(f'/api/thematic-attempts/{attempt["id"]}/submit', 'POST', body)
        self.assertEqual(response.status_code, 200, response.text)
        return attempt['id']


class StudentRouteTests(StudentPageCase):
    def test_best_across_versions_counts_then_percentage(self):
        first = self.complete(1)
        version = self.version_with(3, 'Three tasks')
        self.update_content(self.db, 'variants', self.variant, current_version_id=version)
        second = self.complete(1, 'start-best-version-002')
        self.assertNotEqual(first, second)
        self.assertEqual(self.call('/api/thematic-variants').json['variants'][0]['best']['id'], first)
        third = self.complete(2, 'start-best-version-003')
        version = self.version_with(1, 'One task')
        self.update_content(self.db, 'variants', self.variant, current_version_id=version)
        self.complete(1, 'start-best-version-004')
        self.assertEqual(self.call('/api/thematic-variants').json['variants'][0]['best']['id'], third)

    def test_final_package_conflict_and_last_input(self):
        ident = self.start()['id']
        question = self.call(f'/api/thematic-attempts/{ident}').json['questions'][0]
        item = question['item_id']
        self.call(f'/api/thematic-attempts/{ident}/answers/{item}', 'PUT',
                  {'answer': 'other tab', 'expected_revision': 0, 'mutation_id': 'other-tab-save-001'})
        body = {'request_key': 'submit-last-input-001', 'answers': [
            {'item_id': item, 'expected_revision': 0, 'answer': 'PRIVATE_REFERENCE'}]}
        conflict = self.call(f'/api/thematic-attempts/{ident}/submit', 'POST', body)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json['item_id'], item)
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}').json['state'], 'active')
        body['answers'][0]['expected_revision'] = 1
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}/submit', 'POST', body).status_code, 200)
        result = self.call(f'/api/thematic-attempts/{ident}/result').json
        self.assertEqual(result['correct_count'], 1)
        self.assertEqual(result['questions'][0]['answer'], 'PRIVATE_REFERENCE')
        self.assertEqual(result['questions'][1]['status'], 'skipped')

    def test_get_does_not_start_and_active_contains_no_references(self):
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM thematic_attempts').fetchone()[0], 0)
        page = self.client.get(f'/thematic-variants/{self.variant}/solve')
        self.assertNotIn('PRIVATE_REFERENCE', page.text)
        self.assertNotIn('mc.yandex', page.text)
        ident = self.start()['id']
        response = self.call(f'/api/thematic-attempts/{ident}')
        self.assertNotIn('PRIVATE_REFERENCE', response.text)
        self.assertNotIn('grading', response.text)
        self.assertNotIn('onerror', response.text)
        self.assertIn('<table>', response.json['questions'][0]['description_html'][0])
        self.assertIn('<pre>', response.json['questions'][0]['description_html'][1])
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}/result').status_code, 409)
        self.assertEqual(self.client.get(f'/thematic-attempts/{ident}/result').status_code, 409)
        self.assertEqual(self.client.post(f'/api/thematic-variants/{self.variant}/attempts', json={}).status_code, 400)

    def test_result_old_version_hide_delete_and_repeat(self):
        ident = self.complete()
        page = self.client.get(f'/thematic-attempts/{ident}/result')
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('PRIVATE_REFERENCE', page.text)
        self.assertIn('1 из 2', page.text)
        self.assertIn('50,0%', page.text)
        self.assertIn('Начать новое прохождение', page.text)
        self.assertNotIn('onerror', page.text)
        new_version = self.version_with(3, 'Edited title')
        self.update_content(self.db, 'variants', self.variant, current_version_id=new_version)
        next_attempt = self.start('start-page-request-002')
        self.assertNotEqual(ident, next_attempt['id'])
        self.assertEqual(next_attempt['version_id'], new_version)
        service.visibility(self.db, self.variant, {'state': 'hidden', 'expected_revision': 1}, 1)
        self.assertEqual(self.client.get(f'/thematic-variants/{self.variant}/solve').status_code, 423)
        hidden = self.call(f'/api/thematic-attempts/{ident}/result')
        self.assertEqual(hidden.json['title'], 'Historical title')
        self.assertFalse(hidden.json['can_restart'])
        attempts.delete_variant(self.db, self.variant, {'confirmed': True, 'expected_revision': 2, 'request_key': 'delete-page-key-001'}, 1)
        historical = self.client.get(f'/thematic-attempts/{ident}/result')
        self.assertEqual(historical.status_code, 200)
        self.assertIn('Historical title', historical.text)
        self.assertNotIn('Начать новое прохождение', historical.text)

    def test_owner_admin_and_target_user_permissions(self):
        ident = self.complete()
        self.actor(3)
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}/result').status_code, 404)
        self.assertEqual(self.client.get(f'/thematic-attempts/{ident}/result').status_code, 404)
        self.assertEqual(self.client.get(f'/admin/user/2/thematic-attempt/{ident}').status_code, 403)
        self.actor(1)
        self.assertEqual(self.client.get(f'/admin/user/2/thematic-attempt/{ident}').status_code, 200)
        self.assertEqual(self.client.get(f'/admin/user/3/thematic-attempt/{ident}').status_code, 404)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get(f'/thematic-attempts/{ident}/result').status_code, 302)
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}/result').status_code, 401)

    def test_catalog_best_and_active_old_version_manual_order(self):
        best_id = self.complete()
        active = self.start('start-page-request-002')
        questions = self.call(f'/api/thematic-attempts/{active["id"]}').json['questions']
        self.call(f'/api/thematic-attempts/{active["id"]}/answers/{questions[0]["item_id"]}', 'PUT', {'answer': 'input', 'expected_revision': 0, 'mutation_id': 'save-page-key-0001'})
        new_version = self.version_with(3, 'Current title')
        self.update_content(self.db, 'variants', self.variant, current_version_id=new_version)
        catalog = self.call('/api/thematic-variants').json['variants']
        self.assertEqual(catalog[0]['best']['id'], best_id)
        self.assertEqual(catalog[0]['active']['answered'], 1)
        self.assertEqual(catalog[0]['active']['total'], 2)
        self.assertEqual(catalog[0]['question_count'], 3)
        page = self.client.get('/variants?kind=thematic')
        self.assertIn('Лучший результат', page.text)
        self.assertIn('Текущий прогресс', page.text)
        for number in range(1, 21):
            self.assertIn(f'href="/choose-mode/{number}"', page.text)
        other, _, _ = self.seed_version(self.db, count=1)
        version = next(v['id'] for v in repository.rows(self.db, 'versions') if v['variant_id'] == other)
        self.update_content(self.db, 'variants', other, state='published', current_version_id=version, sort_order=-1)
        self.assertEqual(self.call('/api/thematic-variants').json['variants'][0]['id'], other)
        service.visibility(self.db, self.variant, {'state': 'hidden', 'expected_revision': 1}, 1)
        self.assertNotIn(self.variant, [v['id'] for v in self.call('/api/thematic-variants').json['variants']])
