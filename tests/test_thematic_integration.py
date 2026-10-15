"""Integrate into actual app without network/server or original DB connections."""
import importlib.util
import os
import sqlite3
from unittest import mock
from thematic_support import DatabaseCase, ROOT


class IntegrationTests(DatabaseCase):
    def test_real_app_routes_on_migrated_temporary_database(self):
        self.apply()
        real_connect = sqlite3.connect
        opened = []

        def guarded(database, *args, **kwargs):
            self.assertEqual(database, self.path.as_uri() + '?mode=rw')
            opened.append(database)
            return real_connect(database, *args, **kwargs)

        with mock.patch.dict(os.environ, {
            'SECRET_KEY': 'thematic-integration-test', 'SITE_PASSWORD': 'synthetic',
            'ADMIN_USERNAME': 'synthetic', 'ADMIN_PASSWORD': 'synthetic',
            'EGEVOLUTION_LOCAL_CHECK': '1', 'EGEVOLUTION_DB_PATH': str(self.path),
        }, clear=True), mock.patch('dotenv.load_dotenv', return_value=False), \
             mock.patch('sqlite3.connect', side_effect=guarded), \
             mock.patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            spec = importlib.util.spec_from_file_location('thematic_isolated_app', ROOT / 'app.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.app.config.update(TESTING=True, THEMATIC_MEDIA_ROOT=str(self.root / 'media'))
            client = module.app.test_client()
            self.assertEqual(client.get('/api/admin/thematic-bank/1').status_code, 401)
            self.assertEqual(client.get('/api/thematic-attempts/1').status_code, 401)
            with client.session_transaction() as session:
                session['user_id'] = 1
            for url in ['/admin', '/variants', '/constructor_gate', '/constructor_from_base', '/admin/thematic-variants', '/admin/thematic-variants/new']:
                response = client.get(url)
                self.assertEqual(response.status_code, 200, url)
            self.assertIn('/admin/thematic-variants', client.get('/admin').text)
            self.assertEqual(client.post('/api/admin/thematic-variants', json={}).status_code, 400)
            self.assertEqual(client.post('/api/thematic-variants/1/attempts', json={}).status_code, 400)
            self.assertGreater(len(opened), 1)
            self.assertFalse((self.root / 'media').exists())
