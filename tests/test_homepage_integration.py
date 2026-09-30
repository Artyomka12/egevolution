"""Homepage integration checks against real routes with an isolated temporary DB.
Run: python -m unittest discover -s tests -v
No production database writes, .env loading, or Telegram notifications.
"""
from contextlib import ExitStack
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs
from unittest import TestCase, mock
import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links, self.assets, self.ids, self.fields, self.forms = [], [], set(), {}, []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a: self.ids.add(a['id'])
        if tag == 'a' and 'href' in a: self.links.append(a['href'])
        if tag in ('script', 'img') and a.get('src'): self.assets.append(a['src'])
        if tag == 'link' and a.get('rel') in ('stylesheet', 'icon'): self.assets.append(a['href'])
        if tag == 'input' and a.get('name'): self.fields[a['name']] = a.get('value', '')
        if tag == 'form': self.forms.append(a)

class HomepageIntegration(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.sandbox = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='ege-home-tests-'))
        cls.production_db = ROOT / 'users.db'
        cls.original_hash = hashlib.sha256(cls.production_db.read_bytes()).hexdigest() if cls.production_db.exists() else None
        cls.database = Path(cls.sandbox) / 'users.db'
        cls.connections = []
        connect = sqlite3.connect
        def isolated_connect(database, *args, **kwargs):
            if Path(database).resolve() == cls.production_db.resolve():
                database = cls.database
            connection = connect(database, *args, **kwargs)
            cls.connections.append(connection)
            return connection
        cls.stack.enter_context(mock.patch('sqlite3.connect', side_effect=isolated_connect))
        cls.stack.enter_context(mock.patch.dict(os.environ, {
            'SECRET_KEY': 'homepage-local-test-secret', 'SITE_PASSWORD': 'test',
            'ADMIN_USERNAME': 'test_admin', 'ADMIN_PASSWORD': 'local-test-password',
            'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_ID': '', 'WTF_CSRF_SECRET_KEY': 'test-csrf',
        }))
        cls.stack.enter_context(mock.patch('dotenv.load_dotenv', return_value=False))
        spec = importlib.util.spec_from_file_location('homepage_test_app', ROOT / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with mock.patch('builtins.print'):
            spec.loader.exec_module(cls.module)
        cls.app = cls.module.app
        cls.module.EGE_RENUMBER_ARCHIVE = str(Path(cls.sandbox) / 'ege-renumber-2026.json')
        cls.app.config.update(TESTING=True)
        cls.stack.enter_context(mock.patch.object(cls.module, 'notify_new_application'))
        db = cls.module.get_db()
        db.execute('INSERT INTO users (username,password_hash,name) VALUES (?,?,?)', ('student', cls.module.generate_password_hash('student-password'), 'Тестовый ученик'))
        cls.student_id = db.execute('SELECT id FROM users WHERE username=?', ('student',)).fetchone()[0]
        db.execute('INSERT INTO user_lesson_access (user_id,lesson_id,is_unlocked) VALUES (?,2,1)', (cls.student_id,))
        db.execute('INSERT INTO user_theory_access (user_id,task_num,is_unlocked) VALUES (?,2,1)', (cls.student_id,))
        db.execute('INSERT INTO user_theory_progress (user_id,task_num,practice_task_id,attempts,is_correct) VALUES (?,1,1,1,1)', (cls.student_id,))
        db.execute('INSERT INTO user_results (user_id,variant_num,score,secondary_score,total_tasks,date) VALUES (?,1,20,75,27,?)', (cls.student_id,'2026-09-24'))
        db.commit(); db.close()
    @classmethod
    def tearDownClass(cls):
        for connection in cls.connections:
            connection.close()
        cls.stack.close()
        if cls.original_hash:
            assert hashlib.sha256(cls.production_db.read_bytes()).hexdigest() == cls.original_hash, 'Production database changed'
    def setUp(self): self.client = self.app.test_client()
    def member(self):
        with self.client.session_transaction() as session:
            session['user_id'] = self.student_id
            session['username'] = 'student'
    def csrf(self, url='/login'):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return Document(response.get_data(as_text=True)).fields['csrf_token']
    def test_homepage_and_legacy_url(self):
        response = self.client.get('/')
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="heroScene"', text)
        self.assertNotIn('noindex', text)
        self.assertNotIn('Черновик', text)
        for value in ['favicon.png','canonical','og:image','metrika/tag.js','id="tryTaskSection"','href="/#quiz"']:
            self.assertIn(value,text)
        legacy = self.client.get('/new-home')
        self.assertEqual((legacy.status_code,legacy.location),(301,'/'))
        self.member()
        self.assertIn('href="/preparation" class="evo-start"',self.client.get('/').get_data(as_text=True))
    def test_all_home_links_assets_and_anchors_guest_and_member(self):
        for member in [False, True]:
            if member: self.member()
            doc = Document(self.client.get('/').get_data(as_text=True))
            for href in sorted(set(doc.links + doc.assets)):
                parts = urlsplit(href)
                if parts.scheme or parts.netloc: continue
                with self.subTest(member=member,href=href):
                    response = self.client.get(parts.path or '/', query_string=parts.query, follow_redirects=True)
                    self.assertEqual(response.status_code,200)
                    if parts.fragment:
                        self.assertIn(parts.fragment,Document(response.get_data(as_text=True)).ids)
                    response.close()
    def test_access_and_login_return(self):
        for target in ['/variants','/stats','/visualizer','/profile','/preparation/2','/theory/2']:
            with self.subTest(target=target):
                client = self.app.test_client()
                response = client.get(target)
                self.assertEqual(response.status_code,302)
                self.assertEqual(parse_qs(urlsplit(response.location).query)['next'],[target])
                login = client.get(response.location)
                fields = Document(login.get_data(as_text=True)).fields
                failed = client.post('/login',data={'username':'student','password':'wrong','next':fields['next'],'csrf_token':fields['csrf_token']})
                self.assertEqual(Document(failed.get_data(as_text=True)).fields['next'],target)
                response = client.post('/login',data={'username':'student','password':'student-password','next':fields['next'],'csrf_token':fields['csrf_token']})
                self.assertEqual(response.location,target)
                self.assertEqual(client.get(response.location).status_code,200)
    def test_safe_default_and_external_redirect_rejection(self):
        with self.app.test_request_context():
            for value in [None,'','https://example.com','//example.com','/%2fexample.com','/\\example.com','/%5cexample.com','/%0d%0aLocation:test','/login','/logout','stats','%2Fstats']:
                with self.subTest(value=value): self.assertEqual(self.module.safe_login_destination(value),'/profile')
            self.assertEqual(self.module.safe_login_destination('/stats?filter=1#chart'),'/stats?filter=1#chart')
        token = self.csrf()
        response = self.client.post('/login',data={'username':'student','password':'student-password','csrf_token':token})
        self.assertEqual(response.location,'/profile')
    def test_profile_preserves_progress_and_shared_navigation(self):
        self.member()
        text = self.client.get('/profile').get_data(as_text=True)
        for value in ['Решено задач','Изучено тем','1 / 27','75','href="/#intro"','href="/tasks"','href="/visualizer"','navbar.css','navbar.js']:
            self.assertIn(value,text)
        self.assertIn('id="platformMenu"',text)
        visualizer = self.client.get('/visualizer').get_data(as_text=True)
        for value in ['navbar.css', 'navbar.js', 'id="platformMenu"']:
            self.assertIn(value, visualizer)
    def test_application_valid_invalid_csrf_and_success_links(self):
        data = {'last_name':'Тест','first_name':'Ученик','phone':'+79000000000','contact_type':'telegram','contact_value':'@local_test'}
        self.assertEqual(self.client.post('/register',data=data).status_code,400)
        data['csrf_token'] = self.csrf('/register')
        invalid = dict(data,contact_value='')
        response = self.client.post('/register',data=invalid)
        self.assertIn('value="Тест"',response.get_data(as_text=True))
        db = self.module.get_db(); before = db.execute('SELECT COUNT(*) FROM site_applications').fetchone()[0]; db.close()
        response = self.client.post('/register',data=data)
        self.assertEqual(response.location,'/application-sent')
        text = self.client.get(response.location).get_data(as_text=True)
        self.assertIn('Заявка отправлена',text)
        self.assertNotIn('<form',text)
        for href in Document(text).links:
            if href.startswith('/'): self.assertEqual(self.client.get(href).status_code,200)
        db = self.module.get_db(); self.assertEqual(db.execute('SELECT COUNT(*) FROM site_applications').fetchone()[0],before+1); db.close()
    def test_logout_csrf_and_lesson_quiz_link(self):
        self.member()
        self.assertEqual(self.client.post('/logout').status_code,400)
        token = self.csrf('/')
        self.assertEqual(self.client.post('/logout',data={'csrf_token':token}).location,'/login')
        with self.client.session_transaction() as session: self.assertNotIn('user_id',session)
        self.assertIn('href="/#quiz"',self.client.get('/preparation/1').get_data(as_text=True))
        self.assertIn('href="/"',self.client.get('/login').get_data(as_text=True))
        self.assertIn('href="/"',self.client.get('/register').get_data(as_text=True))

if __name__ == '__main__': unittest.main()
