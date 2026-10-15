import json
from unittest import mock
from flask import Flask
from flask_wtf.csrf import CSRFProtect, generate_csrf
from thematic_support import DatabaseCase, ROOT
from features.thematic import attempts, repository, service
from features.thematic.routes_student import register_student
from features.thematic.routes_admin import register_admin


class AttemptCase(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.apply()
        self.db = self.open()
        self.variant, self.version, self.items = self.seed_version(self.db)
        self.update_content(self.db, 'variants', self.variant, state='published', current_version_id=self.version)
        self.insert_content(self.db, 'drafts', variant_id=self.variant, document_json='{}', revision=1, updated_at=0)
        for ident in (2, 3):
            self.db.execute('INSERT INTO users(id,username,password_hash,is_admin) VALUES (?,?,?,0)', (ident, f'synthetic-{ident}', 'x'))
        self.clock = self.enterContext(mock.patch('features.thematic.service.now_ms', return_value=1000))

    def start(self, key='start-operation-0001', actor=2):
        return attempts.start(self.db, self.variant, {'request_key': key}, actor)

    def save(self, ident, answer='9', revision=0, key='save-operation-0001', item=None, actor=2):
        return attempts.mutate(self.db, ident, item or self.items[0], {'answer': answer, 'expected_revision': revision, 'mutation_id': key}, actor)

    def finish(self, ident, actor=2, **extra):
        return attempts.finish(self.db, ident, {'request_key': 'finish-operation-001', **extra}, actor)

    def delete(self):
        revision = repository.row(self.db, 'variants', self.variant)['revision']
        return attempts.delete_variant(self.db, self.variant, {'request_key': 'delete-operation-001', 'expected_revision': revision, 'confirmed': True}, 1)

    def state(self, state):
        revision = repository.row(self.db, 'variants', self.variant)['revision']
        return service.visibility(self.db, self.variant, {'state': state, 'expected_revision': revision}, 1)


class AttemptTests(AttemptCase):
    def test_start_resume_replay_after_finish_and_new_attempt(self):
        first = self.start()
        self.assertEqual(self.start('start-operation-0002')['id'], first['id'])
        self.save(first['id'])
        self.assertEqual(attempts.view(self.db, first['id'], 2)['questions'][0]['answer'], '9')
        self.finish(first['id'])
        self.assertEqual(self.start('start-operation-0002')['id'], first['id'])
        second = self.start('start-operation-0003')
        self.assertNotEqual(second['id'], first['id'])
        self.assertEqual(second['attempt_no'], 2)

    def test_save_check_change_replay_and_final_recheck(self):
        ident = self.start()['id']
        saved = self.save(ident)
        self.assertEqual(self.save(ident)['revision'], saved['revision'])
        payload = {'request_key': 'check-operation-0001', 'expected_revision': 1}
        checked = attempts.mutate(self.db, ident, self.items[0], payload, 2, check=True)
        self.assertTrue(checked['is_correct'])
        self.save(ident, 'wrong', 1, 'save-operation-0002')
        replay = attempts.mutate(self.db, ident, self.items[0], payload, 2, check=True)
        self.assertEqual(replay['revision'], 1)
        self.assertEqual(replay['current_revision'], 2)
        row = attempts.view(self.db, ident, 2)['questions'][0]
        self.assertIsNone(row['is_correct'])
        self.assertNotIn('grading', json.dumps(attempts.view(self.db, ident, 2)))
        with self.assertRaises(attempts.AttemptError) as error:
            self.save(ident, '9', 0, 'save-operation-0003')
        self.assertEqual(error.exception.details['revision'], 2)
        # A forged cached check cannot become the final score.
        self.db.execute('UPDATE thematic_answers SET is_correct=1,checked_revision=revision WHERE attempt_id=?', (ident,))
        final = self.finish(ident)
        self.assertEqual(final['correct_count'], 0)
        by_item = dict(self.db.execute('SELECT item_id,final_status FROM thematic_answers WHERE attempt_id=?', (ident,)))
        statuses = [by_item[item] for item in self.items]
        self.assertEqual(statuses, ['incorrect', 'skipped'])
        self.assertEqual(self.finish(ident, answers=[{'bad': 'ignored'}]), final)
        with self.assertRaises(attempts.AttemptError):
            self.save(ident, '9', 2)

    def test_finish_package_atomic_and_ownership(self):
        ident = self.start()['id']
        with self.assertRaises(attempts.AttemptError):
            self.finish(ident, answers=[{'item_id': self.items[0], 'answer': '9', 'expected_revision': 0},
                                       {'item_id': self.items[1], 'answer': '9', 'expected_revision': 99}])
        self.assertEqual(self.db.execute('SELECT SUM(revision) FROM thematic_answers WHERE attempt_id=?', (ident,)).fetchone()[0], 0)
        with self.assertRaises(attempts.AttemptError) as error:
            attempts.view(self.db, ident, 3)
        self.assertEqual(error.exception.status, 404)
        final = self.finish(ident, answers=[{'item_id': self.items[0], 'answer': '9', 'expected_revision': 0}])
        self.assertEqual(final['correct_count'], 1)

    def test_invalid_shapes_item_and_key_reuse(self):
        ident = self.start()['id']
        for answer in (True, 9, {}, ['9']):
            with self.assertRaises(attempts.AttemptError):
                self.save(ident, answer)
        with self.assertRaises(attempts.AttemptError):
            self.save(ident, item=9999)
        self.save(ident)
        with self.assertRaises(repository.Conflict):
            self.save(ident, 'different')
        self.save(ident, None, 1, 'save-operation-clear')
        self.assertIsNone(attempts.view(self.db, ident, 2)['questions'][0]['answer'])

    def test_old_version_retained_after_publication(self):
        first = self.start()
        _, second_version, _ = self.seed_version(self.db, count=3, variant_id=self.variant)
        self.update_content(self.db, 'variants', self.variant, current_version_id=second_version)
        self.assertEqual(self.start('start-operation-0002')['version_id'], self.version)
        self.assertEqual(len(attempts.view(self.db, first['id'], 2)['questions']), 2)
        self.finish(first['id'])
        self.assertEqual(self.start('start-operation-0003')['version_id'], second_version)

    def test_rate_limit_and_idempotent_retry(self):
        ident = self.start()['id']
        self.save(ident)
        self.db.executemany('INSERT INTO thematic_operation_keys VALUES (?,?,?,?,?,?)',
                           [(2, 'save:fixture', f'key-{n}', '0' * 64, 1, 1000) for n in range(239)])
        self.assertTrue(self.save(ident)['replayed'])
        with self.assertRaises(attempts.AttemptError) as error:
            self.save(ident, '9', 1, 'new-save-limited-001')
        self.assertEqual(error.exception.status, 429)
        self.clock.return_value = 62000
        self.assertEqual(self.save(ident, '9', 1, 'new-save-limited-001')['revision'], 2)

    def test_pair_and_grid_input_validation_and_binary_finalization(self):
        from features.thematic.validation import make_snapshot
        sources = [{'id': 1, 'description': ['pair'], 'answers': ['1', '2']},
                   {'id': 2, 'description': ['grid'], 'answer_grid': {'rows': 2, 'cols': 2, 'answers': [['1', '2'], ['3', '4']]}}]
        version = repository.store_version(self.db, self.variant, 'Shapes', '', [make_snapshot(27, s) for s in sources], actor_id=1, now=0)
        self.update_content(self.db, 'variants', self.variant, current_version_id=version)
        ident = self.start()['id']
        items = [r['id'] for r in repository.get_version(self.db, version)['items']]
        self.save(ident, ['1', 'wrong'], item=items[0])
        with self.assertRaises(attempts.AttemptError):
            self.save(ident, [['1']], item=items[1])
        self.save(ident, [['1', '2'], ['3', '4']], item=items[1])
        self.assertEqual(self.finish(ident)['correct_count'], 1)


class RouteTests(AttemptCase):
    def setUp(self):
        super().setUp()
        app = Flask(__name__, template_folder=str(ROOT / 'templates'))
        app.config.update(SECRET_KEY='synthetic-only', TESTING=True)
        CSRFProtect(app)
        register_admin(app, lambda: repository.connect(self.path), ROOT / 'tasks', self.root / 'media')
        register_student(app, lambda: repository.connect(self.path))
        app.add_url_rule('/fixture-csrf', view_func=lambda: {'csrf': generate_csrf()})
        self.client = app.test_client()
        self.csrf = self.client.get('/fixture-csrf').json['csrf']
        self.actor(2)

    def actor(self, ident):
        with self.client.session_transaction() as session:
            session['user_id'] = ident

    def call(self, path, method='GET', body=None):
        return self.client.open(path, method=method, json=body, headers={'X-CSRFToken': self.csrf})

    def test_http_auth_csrf_owner_and_no_reference(self):
        path = f'/api/thematic-variants/{self.variant}/attempts'
        self.assertEqual(self.client.post(path, json={'request_key': 'start-http-key-0001'}).status_code, 400)
        started = self.call(path, 'POST', {'request_key': 'start-http-key-0001'})
        self.assertEqual(started.status_code, 200)
        ident = started.json['id']
        response = self.call(f'/api/thematic-attempts/{ident}')
        self.assertEqual(response.status_code, 200)
        for secret in ['correct_answer', 'snapshot_json', 'grading', 'reference', 'storage_key']:
            self.assertNotIn(secret, response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        saved = self.call(f'/api/thematic-attempts/{ident}/answers/{self.items[0]}', 'PUT', {'mutation_id': 'save-http-key-0001', 'expected_revision': 0, 'answer': '9'})
        self.assertEqual(saved.status_code, 200)
        checked = self.call(f'/api/thematic-attempts/{ident}/check/{self.items[0]}', 'POST', {'request_key': 'check-http-key-0001', 'expected_revision': 1})
        self.assertTrue(checked.json['is_correct'])
        self.assertNotIn('score', checked.json)
        self.actor(3)
        for url, method, body in [(f'/api/thematic-attempts/{ident}', 'GET', None),
            (f'/api/thematic-attempts/{ident}/answers/{self.items[0]}', 'PUT', {'mutation_id': 'other-user-key-0001'}),
            (f'/api/thematic-attempts/{ident}/check/{self.items[0]}', 'POST', {'request_key': 'other-user-key-0001'}),
            (f'/api/thematic-attempts/{ident}/submit', 'POST', {'request_key': 'other-user-key-0001'}),
            (f'/thematic-attempts/{ident}/media/1', 'GET', None)]:
            self.assertEqual(self.call(url, method, body).status_code, 404, url)
        self.assertEqual(self.call(f'/api/admin/thematic-variants/{self.variant}', 'DELETE', {}).status_code, 403)
        self.actor(2)
        self.state('hidden')
        hidden = self.call(f'/api/thematic-attempts/{ident}')
        self.assertEqual(hidden.status_code, 423)
        self.assertNotIn('questions', hidden.json)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}').status_code, 401)

    def test_http_delete_confirmation_and_finished_access(self):
        ident = self.start()['id']
        self.actor(1)
        url = f'/api/admin/thematic-variants/{self.variant}'
        payload = {'expected_revision': 1, 'request_key': 'delete-http-key-0001'}
        self.assertEqual(self.call(url, 'DELETE', payload).status_code, 400)
        payload['confirmed'] = True
        self.assertEqual(self.call(url, 'DELETE', payload).status_code, 200)
        self.assertTrue(self.call(url, 'DELETE', payload).json['replayed'])
        self.actor(2)
        self.assertEqual(self.call(f'/api/thematic-attempts/{ident}').json['state'], 'finished')
        self.assertEqual(self.call(f'/api/thematic-variants/{self.variant}/attempts', 'POST', {'request_key': 'deleted-start-0001'}).status_code, 410)

    def test_media_bound_to_owner_version_role_and_visibility(self):
        import hashlib
        from features.thematic.validation import make_snapshot
        root = self.root / 'media'
        root.mkdir()
        snapshots = []
        ids = []
        for index, role in enumerate(['condition', 'reference'], 1):
            data = f'synthetic-bytes-{index}'.encode()
            key = hashlib.sha256(data).hexdigest()
            (root / key).write_bytes(data)
            media_id = self.insert_content(self.db, 'media', storage_key=key, sha256=key,
                mime_type='application/octet-stream', size_bytes=len(data), original_name='fixture.bin', created_at=0)
            ids.append(media_id)
            snapshot = make_snapshot(1, {'id': index, 'description': ['fixture'], 'correct_answer': '9'})
            snapshot['materials'] = [{'media_id': media_id, 'sha256': key, 'role': role, 'position': 1, 'alt_text': '', 'display_metadata': {}}]
            snapshots.append(snapshot)
        version = repository.store_version(self.db, self.variant, 'Media', '', snapshots, actor_id=1, now=0)
        self.update_content(self.db, 'variants', self.variant, current_version_id=version)
        ident = self.start()['id']
        path = f'/thematic-attempts/{ident}/media/'
        response = self.call(path + str(ids[0]))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.call(path + str(ids[1])).status_code, 404)
        self.assertEqual(self.call(path + '9999').status_code, 404)
        self.actor(3)
        self.assertEqual(self.call(path + str(ids[0])).status_code, 404)
        self.actor(2)
        self.state('hidden')
        self.assertEqual(self.call(path + str(ids[0])).status_code, 423)
        self.delete()
        for media_id in ids:
            response = self.call(path + str(media_id))
            self.assertEqual(response.status_code, 200)
            response.close()
