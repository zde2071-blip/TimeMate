"""User controls must not leave a stopped receiver displayed as retrying."""
import tempfile
import time
import unittest

from cryptography.fernet import Fernet
from backend.cloud import create_app, digest, PersistentStatus


class ReceiverStatusControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, Fernet.generate_key())
        self.app.testing = True
        self.app.config['SERVER_NAME'] = '127.0.0.1:18744'
        with self.app.store.db() as c:
            c.execute('INSERT INTO users VALUES (?,?,?)', ('test', 'test@example.com', 'unused'))
            c.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                      (digest('session'), 'test', 'csrf', time.time() + 3600))
        self.client = self.app.test_client()
        self.client.set_cookie('mail_session', 'session', domain='127.0.0.1')
        self.engine = self.app.store.engine('test')

    def post(self, path, data):
        return self.client.post(path, json=data, headers={
            'X-Token': 'csrf', 'Origin': 'http://127.0.0.1:18744'})

    def failing(self, state='retrying'):
        self.engine.STATUS.update(auto=state == 'retrying', sync_state=state,
                                  sync_message='原邮箱连接异常', sync_error_code='mail_sync_failed',
                                  sync_retry_at=time.time() + 900, sync_attempts=5,
                                  last_sync_at=1234, phase='error', error_code='mail_sync_failed')

    def assert_cleared(self):
        status = self.engine.STATUS
        self.assertFalse(status['auto'])
        self.assertEqual(status['sync_state'], 'idle')
        self.assertEqual(status['sync_retry_at'], 0)
        self.assertEqual(status['sync_attempts'], 0)
        self.assertEqual(status['sync_message'], '')
        self.assertEqual(status['sync_error_code'], '')
        self.assertEqual(status['phase'], 'idle')
        self.assertEqual(status['error_code'], '')
        self.assertEqual(status['last_sync_at'], 1234)
        restored = PersistentStatus(self.engine.RUNTIME.directory / 'status.json')
        self.assertEqual(restored['sync_state'], 'idle')
        self.assertEqual(restored['sync_retry_at'], 0)
        self.assertFalse(restored['auto'])

    def test_turning_off_auto_clears_retry_message_and_persisted_timer(self):
        self.failing()
        response = self.post('/api/auto', {'enabled': False})
        self.assertEqual(response.status_code, 200)
        self.assert_cleared()

    def test_saving_mail_settings_clears_the_previous_connection_failure(self):
        for state in ('paused', 'retrying'):
            with self.subTest(state=state):
                self.failing(state)
                response = self.post('/api/settings/mail', {
                    'account': 'test@qq.com', 'mail_provider': 'qq',
                    'school_sender': 'student@example.edu', 'password': 'new-test-authorization'})
                self.assertEqual(response.status_code, 200, response.json)
                self.assert_cleared()

    def test_failed_settings_save_preserves_receiver_failure_and_retry(self):
        self.failing()
        response = self.post('/api/settings/mail', {'account': 'invalid'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.engine.STATUS['auto'])
        self.assertEqual(self.engine.STATUS['sync_state'], 'retrying')
        self.assertGreater(self.engine.STATUS['sync_retry_at'], time.time())

    def test_saving_ai_settings_does_not_clear_mail_authentication_failure(self):
        self.failing('paused')
        self.engine.STATUS['sync_error_code'] = 'mail_authentication_failed'
        response = self.post('/api/settings/ai', {
            'provider': 'deepseek', 'base': 'https://api.deepseek.com',
            'model': 'deepseek-flash', 'key': 'test-api-key'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.engine.STATUS['sync_state'], 'paused')
        self.assertEqual(self.engine.STATUS['sync_error_code'], 'mail_authentication_failed')
        self.assertEqual(self.engine.STATUS['sync_message'], '原邮箱连接异常')

    def test_saving_ai_settings_stops_the_retry_timer_and_retry_message(self):
        self.failing('retrying')
        response = self.post('/api/settings/ai', {
            'provider': 'deepseek', 'base': 'https://api.deepseek.com',
            'model': 'deepseek-flash', 'key': 'test-api-key'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assert_cleared()


if __name__ == '__main__':
    unittest.main()
