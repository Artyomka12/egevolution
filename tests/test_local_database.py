"""No server, production database connection, .env loading or network access."""
import ast
from contextlib import closing
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LocalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.original_hash = hashlib.sha256((ROOT / 'users.db').read_bytes()).digest()
        self.addCleanup(self.verify_original)
        self.temp = tempfile.TemporaryDirectory(prefix='ege-local-db-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ('app.py', 'database_config.py', 'validator.py', 'tracer.py'):
            shutil.copy2(ROOT / name, self.root / name)
        self.default = self.root / 'users.db'
        self.alternative = self.root / 'dev-users.db'
        for path in (self.default, self.alternative):
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE sentinel (value TEXT)')
                db.commit()
        self.default_hash = hashlib.sha256(self.default.read_bytes()).digest()
        self.env = mock.patch.dict(os.environ, {
            'SECRET_KEY': 'isolated-test-secret', 'SITE_PASSWORD': 'test',
            'ADMIN_USERNAME': 'local_test_admin', 'ADMIN_PASSWORD': 'test-only',
            'EGEVOLUTION_LOCAL_CHECK': '1', 'EGEVOLUTION_DB_PATH': str(self.alternative),
            'TELEGRAM_BOT_TOKEN': 'fake-test-token', 'TELEGRAM_CHAT_ID': 'fake-test-chat',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.modules = mock.patch.dict(sys.modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.config = load_module('database_config', self.root / 'database_config.py')

    def verify_original(self):
        self.assertEqual(hashlib.sha256((ROOT / 'users.db').read_bytes()).digest(), self.original_hash)

    def test_paths_and_fail_closed(self):
        self.assertEqual(self.config.resolve_database_path(), self.alternative)
        os.environ['EGEVOLUTION_DB_PATH'] = 'dev-users.db'
        self.assertEqual(self.config.resolve_database_path(), self.alternative)
        for path in ('', str(self.default), str(self.root / 'missing.db')):
            os.environ['EGEVOLUTION_DB_PATH'] = path
            with self.assertRaises(RuntimeError):
                self.config.resolve_database_path()
        del os.environ['EGEVOLUTION_DB_PATH']
        with self.assertRaises(RuntimeError):
            self.config.resolve_database_path()
        del os.environ['EGEVOLUTION_LOCAL_CHECK']
        self.assertEqual(self.config.resolve_database_path(), self.default)

    def test_hardlink_cannot_alias_original(self):
        alias = self.root / 'alias.db'
        try:
            os.link(self.default, alias)
        except OSError:
            self.skipTest('Filesystem does not support hardlinks')
        os.environ['EGEVOLUTION_DB_PATH'] = str(alias)
        with self.assertRaises(RuntimeError):
            self.config.resolve_database_path()

    def test_connection_audit_before_import(self):
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        connections = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute)
                       and isinstance(n.func.value, ast.Name)
                       and n.func.value.id == 'sqlite3' and n.func.attr == 'connect']
        get_db = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_db')
        self.assertEqual(len(connections), 2)
        self.assertTrue(all(n in list(ast.walk(get_db)) for n in connections))

    def test_import_and_requests_use_only_temporary_database(self):
        self.test_connection_audit_before_import()
        load_module('validator', self.root / 'validator.py')
        load_module('tracer', self.root / 'tracer.py')
        real_connect = sqlite3.connect
        opened = []

        def guarded_connect(database, *args, **kwargs):
            self.assertEqual(database, self.alternative.as_uri() + '?mode=rw')
            self.assertTrue(kwargs.get('uri'))
            opened.append(database)
            return real_connect(database, *args, **kwargs)

        with mock.patch('dotenv.load_dotenv', return_value=False), \
             mock.patch('sqlite3.connect', side_effect=guarded_connect), \
             mock.patch('socket.socket.connect', side_effect=AssertionError('Network prohibited')), \
             mock.patch('urllib.request.urlopen', side_effect=AssertionError('Notification prohibited')) as send:
            module = load_module('isolated_local_app', self.root / 'app.py')
            self.assertFalse((self.root / 'static').exists())
            module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
            module.app.template_folder = str(ROOT / 'templates')
            module.notify_new_application('Demo', 'Demo', '0', 'telegram', 'demo')
            send.assert_not_called()
            with closing(module.get_db()) as db:
                db.execute("INSERT INTO sentinel VALUES ('test')")
                db.commit()
                admin_id = db.execute('SELECT id FROM users WHERE is_admin=1').fetchone()[0]
                self.assertEqual(Path(db.execute('PRAGMA database_list').fetchone()[2]), self.alternative)
            client = module.app.test_client()
            with client.session_transaction() as session:
                session['user_id'] = admin_id
                session['username'] = 'local_test_admin'
            response = client.get('/variants')
            self.assertEqual(response.status_code, 200)
            self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
            for url in ('/api/theory/save', '/api/uroki/save', '/api/variants/save',
                        '/profile/upload_avatar', '/admin/tasks/1/add',
                        '/admin/tasks/1/edit/1', '/admin/tasks/1/delete/1'):
                self.assertEqual(client.post(url).status_code, 403, url)
            os.environ['EGEVOLUTION_DB_PATH'] = str(self.default)
            with self.assertRaises(RuntimeError):
                module.get_db()
        self.assertGreater(len(opened), 1)
        self.assertEqual(hashlib.sha256(self.default.read_bytes()).digest(), self.default_hash)


if __name__ == '__main__':
    unittest.main()
