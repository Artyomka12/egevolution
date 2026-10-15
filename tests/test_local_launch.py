"""Real python app.py on Windows, synthetic persistent DB and isolated content."""
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows direct-launch contract')
class LocalLaunchTests(unittest.TestCase):
    def test_direct_launch_actions_restart_override_and_single_worker(self):
        from scripts.run_tests_local import make_fixture
        # Refuse to touch any existing local server.
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 5000))
        root = Path(tempfile.mkdtemp(prefix='ege-local-launch-check-')).resolve()
        print('Local launch evidence: ' + str(root), flush=True)
        for name in ('app.py', 'database_config.py', 'validator.py', 'tracer.py'):
            shutil.copy2(ROOT / name, root / name)
        for name in ('core', 'features', 'templates', 'static', 'migrations', 'theory', 'uroki', 'variants', 'tasks'):
            shutil.copytree(ROOT / name, root / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'uploads'))
        (root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/migrate.py', root / 'scripts/migrate.py')
        shutil.copy2(ROOT / 'scripts/json_content_migration.py', root / 'scripts/json_content_migration.py')
        local = root / 'test-fixtures'
        local.mkdir()
        fixture = make_fixture(local)
        for name in ('thematic_variants','tests_content'):
            shutil.copytree(fixture.parent/name, root/name)
        # Only this synthetic fixture is moved; originals are never opened.
        database = root / 'users.db'
        fixture.rename(database)
        task = root / 'tasks/task_01'
        task.mkdir(parents=True, exist_ok=True)
        bank = json.loads((task / 'tasks.json').read_text(encoding='utf-8'))
        bank['tasks'].append({'id': 99999, 'description': ['Compute 3 * 3'], 'correct_answer': '9'})
        (task / 'tasks.json').write_text(json.dumps(bank), encoding='utf-8')
        (root / '.env').write_text('SECRET_KEY=synthetic-local-launch\nSITE_PASSWORD=local-tests-only\n'
                                  'ADMIN_USERNAME=tests-admin\nADMIN_PASSWORD=local-tests-only\n', encoding='utf-8')
        env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT',
               'TEMP', 'TMP', 'SystemDrive', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA') if k in os.environ}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['EGEVOLUTION_CONTENT_ROOT'] = str(root)
        process = None
        opened = []
        base = 'http://127.0.0.1:5000'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        token = ''
        sequence = 0

        def key():
            nonlocal sequence
            sequence += 1
            return 'local-launch-request-' + str(sequence)

        def request(path, method='GET', body=None, form=None, writer=None):
            headers = {'X-CSRFToken': token}
            if writer:
                headers['X-Test-Writer-Token'] = writer
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers['Content-Type'] = 'application/json'
            if form is not None:
                data = urllib.parse.urlencode(form).encode()
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
            req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
            try:
                with opener.open(req, timeout=10) as response:
                    text = response.read().decode('utf-8')
                    self.assertNotIn('SCHEMA_REQUIRED', text, path)
                    return json.loads(text) if 'application/json' in response.headers.get('Content-Type', '') else text
            except urllib.error.HTTPError as error:
                self.fail(f'{path}: HTTP {error.code}: {error.read().decode()[:800]}')

        def login(username):
            nonlocal opener, token
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            html = request('/login')
            token = re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
            request('/login', 'POST', form={'username': username, 'password': 'local-tests-only', 'csrf_token': token})
            token = re.search(r'name="csrf_token" value="([^"]+)"', request('/profile'))[1]

        def start():
            nonlocal process
            log = (root / ('server-' + key() + '.log')).open('wb')
            opened.append(log)
            process = subprocess.Popen([sys.executable, 'app.py'], cwd=root, env=env,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail('Server exited: ' + Path(log.name).read_text(encoding='utf-8', errors='replace'))
                try:
                    request('/')
                    return
                except (OSError, urllib.error.URLError):
                    time.sleep(.1)
            self.fail('Server did not start')

        def stop():
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

        def publish_test(seconds=60):
            created = request('/api/admin/tests', 'POST', {'request_key': key()})
            ident = created['id']
            doc = {'title': 'Synthetic launch test', 'description': '', 'time_limit_seconds': seconds,
                   'attempt_limit': 5, 'show_correct_answers': True, 'questions': [
                       {'title': 'Multiply', 'prompt_text': '3 * 3', 'question_type': 'free_text',
                        'free_input_mode': 'singleline', 'accepted_answers': ['9']}]}
            saved = request(f'/api/admin/tests/{ident}/draft', 'PUT', {
                'document': doc, 'expected_revision': created['revision'], 'request_key': key()})
            request(f'/api/admin/tests/{ident}/publish', 'POST', {
                'expected_revision': saved['revision'], 'request_key': key()})
            return ident

        try:
            start()
            login('tests-admin')
            pages = ['/', '/preparation', '/theory', '/tasks', '/variants', '/tests', '/stats', '/profile',
                     '/admin', '/admin/tasks', '/constructor_gate', '/constructor_editor', '/constructor_from_base',
                     '/constructor_theory', '/constructor_uroki', '/admin/tests', '/admin/tests/new',
                     '/admin/thematic-variants', '/admin/thematic-variants/new', '/visualizer']
            for page in pages:
                request(page)
            for number in (2, 5, 7, 8, 9, 10):
                request('/theory/' + str(number))
            test_id = publish_test()
            timer_test = publish_test(2)
            thematic = request('/api/admin/thematic-variants', 'POST', {'request_key': key(), 'document': {
                'title': 'Synthetic launch thematic', 'description': '',
                'items': [{'source_task_num': 1, 'source_task_id': 99999}]}})
            request(f'/api/admin/thematic-variants/{thematic["id"]}/publish', 'POST', {
                'expected_revision': thematic['revision'], 'variant_revision': thematic['variant_revision'],
                'request_key': key()})
            login('tests-student')
            for page in ['/', '/preparation', '/theory', '/tasks', '/variants', '/tests', '/stats', '/profile', '/visualizer']:
                request(page)
            for n in range(1, 21):
                request('/choose-mode/' + str(n))
            trace = request('/api/visualizer/trace', 'POST', form={'code': 'x = 3 * 3\nprint(x)', 'csrf_token': token})
            self.assertFalse(trace.get('error'), trace)
            request('/api/variant_progress/1', 'POST', {'answers': {'1': '9'}, 'time_remaining': 100})
            self.assertIsInstance(request('/api/variant_progress/1'), dict)
            request('/save_results/1', 'POST', {'score': 1, 'total': 27, 'answers': {'1': '9'}})
            attempt = request(f'/api/tests/{test_id}/attempts', 'POST', {'request_key': key()})
            ident = attempt['attempt_id']
            writer = request(f'/api/tests/attempts/{ident}/claim', 'POST', {
                'expected_generation': attempt['generation'], 'writer_client_id': 'synthetic-launch-tab'})
            question = request(f'/api/tests/attempts/{ident}')['questions'][0]
            request(f'/api/tests/attempts/{ident}/answers/{question["id"]}', 'PUT', {
                'answer': '9', 'expected_revision': 0, 'generation': writer['generation'], 'mutation_id': key()},
                writer=writer['writer_token'])
            request(f'/api/tests/attempts/{ident}/submit', 'POST', {
                'generation': writer['generation'], 'request_key': key()}, writer=writer['writer_token'])
            result = request(f'/api/tests/attempts/{ident}/result')
            self.assertEqual(result['summary']['earned'], 1)
            request(f'/tests/attempts/{ident}/result')
            ta = request(f'/api/thematic-variants/{thematic["id"]}/attempts', 'POST', {'request_key': key()})
            tq = request(f'/api/thematic-attempts/{ta["id"]}')['questions'][0]
            request(f'/api/thematic-attempts/{ta["id"]}/submit', 'POST', {'request_key': key(), 'answers': [
                {'item_id': tq['item_id'], 'expected_revision': 0, 'answer': '9'}]})
            request(f'/thematic-attempts/{ta["id"]}/result')
            self.assertIn('Synthetic launch thematic', request('/stats'))
            timed = request(f'/api/tests/{timer_test}/attempts', 'POST', {'request_key': key()})
            # No requests to the attempt: only the automatic worker can complete it.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                    state = db.execute('select state from test_attempts where id=?', (timed['attempt_id'],)).fetchone()[0]
                if state == 'graded':
                    break
                time.sleep(.2)
            self.assertEqual(state, 'graded')
            duplicate = subprocess.run([sys.executable, 'app.py'], cwd=root, env=env,
                                       capture_output=True, timeout=15)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn(b'already owns', duplicate.stderr)
            stop()
            start()
            login('tests-student')
            self.assertEqual(request(f'/api/tests/attempts/{ident}/result')['summary']['earned'], 1)
            self.assertIn('Synthetic launch thematic', request('/stats'))
            login('tests-admin')
            request('/admin/user/2')
            request('/api/admin/users/2/tests')
            stop()
            before = hashlib.sha256((local / 'before.db').read_bytes()).hexdigest()
            override = dict(env, EGEVOLUTION_DB_PATH=str(local / 'before.db'))
            failed = subprocess.run([sys.executable, 'app.py'], cwd=root, env=override,
                                    capture_output=True, timeout=15)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn(b'No migrations were run', failed.stderr)
            self.assertEqual(hashlib.sha256((local / 'before.db').read_bytes()).hexdigest(), before)
            # Explicit prepared override takes precedence; default may be absent.
            override_db = local / 'override.db'
            with sqlite3.connect(database) as src, sqlite3.connect(override_db) as dst:
                src.backup(dst)
            env['EGEVOLUTION_DB_PATH'] = str(override_db)
            start()
            login('tests-student')
            self.assertEqual(request(f'/api/tests/attempts/{ident}/result')['summary']['earned'], 1)
            stop()
            with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
                self.assertEqual(db.execute('pragma integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('pragma foreign_key_check').fetchall(), [])
            (root / 'result.json').write_text(json.dumps({'passed': True, 'pages': pages,
                'test_completion': True, 'thematic_completion': True, 'automatic_timeout': True,
                'restart_persistence': True, 'duplicate_worker_rejected': True,
                'unprepared_override_unchanged': True, 'prepared_override_supported': True}), encoding='utf-8')
        finally:
            stop()
            for stream in opened:
                stream.close()


if __name__ == '__main__':
    unittest.main()
