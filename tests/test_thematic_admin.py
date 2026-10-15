"""Real HTTP handlers, CSRF and SQLite migrations; temporary synthetic data only."""
import json
import re
from pathlib import Path
from unittest import mock
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from thematic_support import DatabaseCase, ROOT
from features.thematic.routes_admin import register_admin
from features.thematic import repository


class AdminTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.bank = self.root / 'tasks'
        folder = self.bank / 'task_01'
        folder.mkdir(parents=True)
        self.source = folder / 'tasks.json'
        self.source.write_text(json.dumps({'tasks': [
            {'id': 1, 'description': ['<table><tr><td>A</td></tr></table>', '<pre>print(1)\nprint(2)</pre>'], 'correct_answer': '1'},
            {'id': 2, 'description': ['Second source of same number'], 'correct_answer': '2'}]}), encoding='utf-8')
        app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
        app.config.update(SECRET_KEY='synthetic-test-secret', TESTING=True)
        CSRFProtect(app)
        app.add_url_rule('/login', 'login', lambda: 'login')
        register_admin(app, lambda: repository.connect(self.path), self.bank, self.root / 'private-media')
        self.app = app
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        page = self.client.get('/admin/thematic-variants/new')
        self.assertEqual(page.status_code, 200)
        self.csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text)[1]
        self.document = {'title': 'Synthetic variant', 'description': 'Only fixture data', 'items': [
            {'source_task_num': 1, 'source_task_id': 1}, {'source_task_num': 1, 'source_task_id': 2}]}

    def call(self, path, method='GET', body=None):
        return self.client.open(path, method=method, json=body, headers={'X-CSRFToken': self.csrf})

    def create(self, key='create-request-0001'):
        response = self.call('/api/admin/thematic-variants', 'POST', {'document': self.document, 'request_key': key})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json

    def publish(self, data, key='publish-request-0001'):
        return self.call(f'/api/admin/thematic-variants/{data["id"]}/publish', 'POST', {
            'expected_revision': data['revision'], 'variant_revision': data['variant_revision'], 'request_key': key})

    def test_auth_and_csrf_every_surface(self):
        db = self.open()
        db.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (2,'fake-student','x',0)")
        surfaces = [('/admin/thematic-variants', 'GET'), ('/admin/thematic-variants/new', 'GET'),
            ('/admin/thematic-variants/1/edit', 'GET'), ('/api/admin/thematic-variants', 'GET'),
            ('/api/admin/thematic-variants', 'POST'), ('/api/admin/thematic-variants/1/draft', 'GET'),
            ('/api/admin/thematic-variants/1/draft', 'PUT'), ('/api/admin/thematic-variants/1/publish', 'POST'),
            ('/api/admin/thematic-variants/1/visibility', 'PATCH'), ('/api/admin/thematic-variants/order', 'PUT'),
            ('/api/admin/thematic-bank/1', 'GET'), ('/api/admin/thematic-bank/1/1/media/condition/1', 'GET'),
            ('/api/admin/thematic-variants/1/media/1', 'GET')]
        with self.client.session_transaction() as session:
            session['user_id'] = 2
            session['is_admin'] = True  # Never trust the cookie role.
        for url, method in surfaces:
            self.assertEqual(self.call(url, method, {} if method != 'GET' else None).status_code, 403, url)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        self.assertEqual(self.client.post('/api/admin/thematic-variants', json={}).status_code, 400)
        with self.client.session_transaction() as session:
            session.pop('user_id')
        self.assertEqual(self.client.get('/api/admin/thematic-variants').status_code, 401)
        self.assertEqual(self.client.get('/admin/thematic-variants').status_code, 302)

    def test_create_save_publish_immutable_and_cas(self):
        first = self.create()
        self.assertEqual(self.create()['id'], first['id'])
        published = self.publish(first)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(self.publish(first).json['version_id'], published.json['version_id'])
        current = published.json['draft']
        document = dict(current['document'], title='Changed draft')
        url = f'/api/admin/thematic-variants/{first["id"]}/draft'
        saved = self.call(url, 'PUT', {'document': document, 'expected_revision': current['revision']})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.call(url, 'PUT', {'document': document, 'expected_revision': current['revision']}).status_code, 409)
        db = self.open()
        old = repository.get_version(db, published.json['version_id'])
        self.assertEqual(old['title'], 'Synthetic variant')
        self.assertEqual(repository.rows(db, 'variants')[0]['current_version_id'], old['id'])
        again = self.publish(saved.json, 'publish-request-0002')
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json['draft']['version_no'], 2)
        self.assertEqual(repository.get_version(db, old['id']), old)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_input_validation_bank_change_and_missing_task(self):
        for bad in [dict(self.document, items=self.document['items'] * 2),
                    dict(self.document, items=[{'source_task_num': 28, 'source_task_id': 1}]),
                    dict(self.document, items=[{'source_task_num': 1, 'source_task_id': 99}])]:
            response = self.call('/api/admin/thematic-variants', 'POST', {'document': bad, 'request_key': 'bad-create-key-0001'})
            self.assertEqual(response.status_code, 400, response.text)
        first = self.create()
        source = json.loads(self.source.read_text())
        source['tasks'][0]['correct_answer'] = '999'
        self.source.write_text(json.dumps(source), encoding='utf-8')
        self.assertEqual(self.publish(first).status_code, 409)
        self.assertEqual(self.open().execute('SELECT COUNT(*) FROM thematic_versions').fetchone()[0], 0)
        self.document = {'title': '', 'items': []}
        empty = self.create('empty-create-key-0001')
        self.assertEqual(self.publish(empty).status_code, 400)

    def test_visibility_order_and_revision_guards(self):
        first = self.publish(self.create()).json['draft']
        second = self.create('create-request-0002')
        path = f'/api/admin/thematic-variants/{first["id"]}/visibility'
        hidden = self.call(path, 'PATCH', {'state': 'hidden', 'expected_revision': first['variant_revision']})
        self.assertEqual(hidden.status_code, 200)
        self.assertEqual(self.call(path, 'PATCH', {'state': 'published', 'expected_revision': first['variant_revision']}).status_code, 409)
        shown = self.call(path, 'PATCH', {'state': 'published', 'expected_revision': hidden.json['variant_revision']})
        self.assertEqual(shown.status_code, 200)
        db = self.open()
        self.assertEqual(db.execute('SELECT COUNT(*) FROM thematic_versions').fetchone()[0], 1)
        self.assertIsNotNone(db.execute('SELECT visible_at FROM thematic_visibility_intervals').fetchone()[0])
        catalog = self.call('/api/admin/thematic-variants').json
        order = {'ids': [second['id'], first['id']], 'expected_revision': catalog['revision']}
        moved = self.call('/api/admin/thematic-variants/order', 'PUT', order)
        self.assertEqual([v['id'] for v in moved.json['variants']], order['ids'])
        self.assertEqual(self.call('/api/admin/thematic-variants/order', 'PUT', order).status_code, 409)

    def test_schema_unavailable_no_initialization(self):
        db = self.open()
        db.execute('DELETE FROM schema_migrations')
        self.assertEqual(self.call('/api/admin/thematic-variants').status_code, 503)
        response = self.client.get('/admin/thematic-variants')
        self.assertEqual(response.status_code, 503)
        self.assertIn('автоматически не запускается', response.text)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 0)

    def test_bank_markup_and_no_grading_leak(self):
        response = self.call('/api/admin/thematic-bank/1')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('correct_answer', response.text)
        self.assertIn('<table>', response.json['tasks'][0]['description_html'][0])
        from features.thematic.bank import condition_html
        rendered = condition_html('<script>alert(1)</script><img src=x onerror=x><td onclick="x" colspan="2">A</td>[pre]x\ny[/pre]')
        self.assertNotIn('<script', rendered)
        self.assertNotIn('onclick', rendered)
        self.assertNotIn('<img', rendered)
        self.assertIn('<td colspan="2">A</td>', rendered)
        self.assertIn('<pre>x\ny</pre>', rendered)

    def test_transaction_failure_retains_publication(self):
        current = self.publish(self.create()).json['draft']
        db = self.open()
        prior = repository.rows(db, 'variants')[0]['current_version_id']
        # Fail after sealing, pointer update and interval/catalog updates, before
        # the operation receipt. Every preceding database write must roll back.
        with mock.patch('features.thematic.service.record', side_effect=ValueError('injected failure')):
            response = self.publish(current, 'failing-publish-0001')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(repository.rows(db, 'variants')[0]['current_version_id'], prior)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM thematic_versions').fetchone()[0], 1)

    def test_publish_from_hidden_closes_interval(self):
        current = self.publish(self.create()).json['draft']
        current = self.call(f'/api/admin/thematic-variants/{current["id"]}/visibility', 'PATCH', {
            'state': 'hidden', 'expected_revision': current['variant_revision']}).json
        result = self.publish(current, 'second-publish-key-001')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json['draft']['state'], 'published')
        self.assertEqual(result.json['draft']['version_no'], 2)
        self.assertIsNotNone(self.open().execute('SELECT visible_at FROM thematic_visibility_intervals').fetchone()[0])

    def test_concurrent_publish_same_receipt(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import closing
        from threading import Barrier
        from features.thematic.bank import Bank
        from features.thematic.service import publish
        current = self.create()
        barrier = Barrier(2)
        body = {'expected_revision': current['revision'], 'variant_revision': current['variant_revision'], 'request_key': 'parallel-publish-0001'}

        def worker():
            with closing(repository.connect(self.path)) as db:
                barrier.wait(timeout=5)
                return publish(db, Bank(self.bank), self.root / 'media', current['id'], body, 1)['version_id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            ids = [f.result() for f in futures]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.open().execute('SELECT COUNT(*) FROM thematic_versions').fetchone()[0], 1)

    def test_real_bank_readonly_all_numbers(self):
        from features.thematic.bank import Bank
        bank = Bank(ROOT / 'tasks')
        total = 0
        for number in range(1, 28):
            for task in bank.tasks(number):
                # Full condition serialization never opens the application DB.
                bank.dto(number, task)
                total += 1
        self.assertGreater(total, 27)
