"""Actual Flask-WTF failures and renewal; synthetic accounts/databases only."""
import time
from unittest import mock

from itsdangerous import URLSafeTimedSerializer
from tests_support import AdminHTTPCase, document


class CSRFRefreshTests(AdminHTTPCase):
    def expired_token(self):
        with self.client.session_transaction() as session:
            raw = session['csrf_token']
        with mock.patch('itsdangerous.timed.TimestampSigner.get_timestamp',
                        return_value=int(time.time()) - 3601):
            return URLSafeTimedSerializer(self.app.secret_key, salt='wtf-csrf-token').dumps(raw)

    def refresh(self):
        return self.client.get('/api/admin/tests/csrf', headers={'X-CSRF-Refresh': '1'})

    def test_expired_create_save_repeat_and_publish_keep_same_keys(self):
        self.csrf = self.expired_token()
        with self.assertLogs('flask_wtf.csrf', level='INFO') as logs:
            response = self.call('/api/admin/tests', 'POST', {'request_key': 'create-once'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['error']['code'], 'CSRF_FAILED')
        self.assertEqual(response.json['csrf_reason'], 'expired')
        self.assertIn('The CSRF token has expired.', logs.output[0])
        self.assertEqual(self.open().execute('SELECT COUNT(*) FROM tests').fetchone()[0], 0)
        fresh = self.refresh()
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.json['user_id'], 1)
        self.csrf = fresh.json['csrf_token']
        draft = self.create('create-once')
        self.assertEqual(self.create('create-once')['test_id'], draft['test_id'])
        self.csrf = self.expired_token()
        rejected = self.save(draft, key='save-once')
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json['csrf_reason'], 'expired')
        self.assertEqual(self.call(f'/api/admin/tests/{draft["id"]}/draft').json['document']['questions'], [])
        self.csrf = self.refresh().json['csrf_token']
        saved = self.save(draft, key='save-once')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.save(draft, key='save-once').json, saved.json)
        repeated = self.save(saved.json, key='second-save')
        self.assertEqual(repeated.status_code, 200)
        body = {'expected_revision': repeated.json['revision'], 'request_key': 'publish-once'}
        path = f'/api/admin/tests/{draft["id"]}/publish'
        self.csrf = self.expired_token()
        self.assertEqual(self.call(path, 'POST', body).json['csrf_reason'], 'expired')
        self.assertEqual(self.open().execute('SELECT COUNT(*) FROM test_versions').fetchone()[0], 0)
        self.csrf = self.refresh().json['csrf_token']
        published = self.call(path, 'POST', body)
        self.assertEqual(published.status_code, 200)
        self.assertEqual(self.call(path, 'POST', body).json, published.json)
        self.assertEqual(self.open().execute('SELECT COUNT(*) FROM test_versions').fetchone()[0], 1)
        self.assertEqual(self.app.config['WTF_CSRF_TIME_LIMIT'], 3600)

    def test_refresh_is_private_admin_only_and_requires_custom_header(self):
        self.assertEqual(self.client.get('/api/admin/tests/csrf').status_code, 400)
        fresh = self.refresh()
        self.assertIn('no-store', fresh.headers['Cache-Control'])
        self.assertNotIn('Access-Control-Allow-Origin', fresh.headers)
        self.login(2)
        self.assertEqual(self.refresh().status_code, 403)
        self.login(None)
        self.assertEqual(self.refresh().status_code, 401)
        self.assertEqual(self.call('/api/admin/tests', 'POST', {}, csrf=False).status_code, 401)
        self.login(1)
        self.open().execute('UPDATE users SET is_admin=0 WHERE id=1')
        self.assertEqual(self.refresh().status_code, 403)

    def test_missing_invalid_and_foreign_session_tokens_still_rejected(self):
        other = self.app.test_client()
        foreign = other.get('/fixture-csrf').json['token']
        for token, reason in (('', 'missing'), ('not-a-token', 'invalid'), (foreign, 'mismatch')):
            with self.subTest(reason=reason):
                self.csrf = token
                response = self.call('/api/admin/tests', 'POST', {'request_key': self.key()})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['csrf_reason'], reason)
        self.assertEqual(self.open().execute('SELECT COUNT(*) FROM tests').fetchone()[0], 0)
