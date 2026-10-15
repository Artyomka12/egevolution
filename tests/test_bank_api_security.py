"""Bank API regression tests against actual Flask, temporary DB only."""
from unittest import mock
from test_thematic_student_routes import StudentPageCase


class BankApiSecurityTests(StudentPageCase):
    def test_guest_student_forged_role_and_missing_user(self):
        with mock.patch.object(self.module, 'get_available_tasks', side_effect=AssertionError('Bank must not be read')):
            with self.client.session_transaction() as session:
                session.clear()
            response = self.client.get('/api/tasks/1')
            self.assertEqual(response.status_code, 401)
            self.assertTrue(response.is_json)
            self.actor(2)
            with self.client.session_transaction() as session:
                session['is_admin'] = True
            self.assertEqual(self.client.get('/api/tasks/1').status_code, 403)
            self.actor(999999)
            self.assertEqual(self.client.get('/api/tasks/1').status_code, 401)

    def test_current_database_role_and_unchanged_admin_payload(self):
        self.actor(1)
        tasks = self.module.get_available_tasks(1)
        response = self.client.get('/api/tasks/1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'tasks': tasks, 'count': len(tasks)})
        expected = [t for t in tasks if t.get('difficulty') == 'easy']
        self.assertEqual(self.client.get('/api/tasks/1?difficulty=easy').json,
                         {'tasks': expected, 'count': len(expected)})
        self.db.execute('UPDATE users SET is_admin=0 WHERE id=1')
        self.assertEqual(self.client.get('/api/tasks/1').status_code, 403)
        self.db.execute('UPDATE users SET is_admin=1 WHERE id=1')
        self.assertEqual(self.client.get('/api/tasks/1').status_code, 200)

    def test_constructor_pages_bank_and_preview(self):
        self.actor(1)
        for path in ('/constructor_gate', '/constructor_from_base', '/constructor_editor'):
            self.assertEqual(self.client.get(path).status_code, 200)
        refs = {}
        for number in range(1, 28):
            response = self.client.get(f'/api/tasks/{number}')
            self.assertEqual(response.status_code, 200)
            refs[str(number)] = {'task_id': response.json['tasks'][0]['id']}
        self.assertEqual(self.call('/api/variant/preview', 'POST', {'tasks': refs}).status_code, 200)
        self.assertEqual(self.client.post('/api/variant/preview', json={'tasks': refs}).status_code, 400)

    def test_all_existing_variant_modes_and_completion(self):
        self.assertEqual(len(self.module.get_available_variants()), 20)
        for number in range(1, 21):
            self.assertEqual(len(self.module.load_tasks(number)), 27)
            for route in ('choose-mode', 'solve', 'exam', 'results'):
                self.assertEqual(self.client.get(f'/{route}/{number}').status_code, 200)
            for route in ('save_results', 'finish_exam'):
                self.assertEqual(self.call(f'/{route}/{number}', 'POST',
                    {'answers': {}, 'time_spent': '00:00:01'}).status_code, 200)

    def test_active_thematic_reference_is_not_disclosed(self):
        ident = self.start()['id']
        for path in (f'/thematic-variants/{self.variant}/solve',
                     f'/api/thematic-attempts/{ident}', '/api/thematic-variants'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('PRIVATE_REFERENCE', response.text)
            self.assertNotIn('"grading"', response.text)
        self.assertEqual(self.client.get(f'/api/thematic-attempts/{ident}/result').status_code, 409)
        for path in ('/api/tasks/1', '/api/admin/thematic-bank/1',
                     f'/api/admin/thematic-variants/{self.variant}/draft'):
            self.assertEqual(self.client.get(path).status_code, 403)
