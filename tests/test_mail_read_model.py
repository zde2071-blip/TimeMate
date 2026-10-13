"""Exercise read endpoints through the authenticated, per-account gateway."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from cryptography.fernet import Fernet

from backend.cloud import create_app, digest, PersistentStatus


class MailReadModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, Fernet.generate_key())
        self.app.testing = True
        self.app.config['SERVER_NAME'] = '127.0.0.1:18744'
        self.clients = {}
        for user in ('alice', 'bob'):
            with self.app.store.db() as c:
                c.execute('INSERT INTO users VALUES (?,?,?)', (user, user + '@example.com', 'unused-test-password'))
                c.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                          (digest(user + '-session'), user, user + '-csrf', time.time() + 3600))
            client = self.app.test_client()
            client.set_cookie('mail_session', user + '-session', domain='127.0.0.1')
            self.clients[user] = client
        self.engine = self.app.store.engine('alice')
        self.event = {'kind': '截止', 'title': '项目提交截止', 'action': '提交报告',
                      'start': '2026-10-20T23:59', 'end': '', 'allDay': False, 'location': '线上'}

    def get(self, path, user='alice', **query):
        return self.clients[user].get(path, query_string=query, headers={'X-Token': user + '-csrf'})

    def post(self, path, data, user='alice'):
        return self.clients[user].post(path, json=data, headers={
            'X-Token': user + '-csrf', 'Origin': 'http://127.0.0.1:18744'})

    def mail(self, ident, *, user='alice', body='Original notice', event=None, pending=False):
        engine = self.app.store.engine(user)
        event = event or self.event
        with engine.db() as c:
            c.execute('''INSERT INTO mails(id,subject,sender,date,sent_date,body,source_body,
                         result,original,source,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                      (ident, user + ' notice', user + '@example.com', '2026-10-10',
                       '2026-10-10T12:00+08:00', body, body,
                       None if pending else json.dumps({'events': [event]}),
                       json.dumps({'html': '<p>' + body + '</p>', 'external': []}), 'manual', 1))

    def revision(self):
        response = self.get('/api/updates')
        self.assertEqual(response.status_code, 200)
        return response.json['revision']

    def test_update_poll_does_not_read_bodies_images_or_translations(self):
        self.mail('large', body='Large body ' * 200_000, pending=True)
        with self.engine.db() as c:
            c.execute("UPDATE mails SET analysis_error='retry',translation=? WHERE id='large'", ('译文' * 100_000,))
        connect = self.engine.db

        @contextmanager
        def guarded_database():
            with connect() as c:
                def authorize(action, table, column, *_):
                    if action == sqlite3.SQLITE_READ and table == 'mails' and column in {
                        'body', 'source_body', 'original', 'translation', 'translation_subject', 'translation_format',
                    }:
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                c.set_authorizer(authorize)
                yield c

        with patch.object(self.engine, 'db', guarded_database):
            response = self.get('/api/updates')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['pendingCount'], 1)
        self.assertEqual(response.json['failedCount'], 1)
        self.assertLess(len(response.data), 3_000)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_revision_tracks_mail_and_saved_item_actions_and_settings(self):
        self.mail('first')
        actions = [
            ('/api/mail', {'id': 'first', 'action': 'read'}),
            ('/api/pin', {'id': 'first', 'index': 0, 'action': 'pin'}),
            ('/api/event/manage', {'id': 'first', 'index': 0, 'action': 'complete'}),
            ('/api/mail', {'id': 'first', 'action': 'delete'}),
            ('/api/mail', {'id': 'first', 'action': 'restore'}),
            ('/api/calendar/settings', {'calendar_method': 'subscribe', 'calendar_provider': 'apple'}),
        ]
        previous = self.revision()
        for endpoint, payload in actions:
            with self.subTest(endpoint=endpoint, action=payload):
                response = self.post(endpoint, payload)
                self.assertEqual(response.status_code, 200, response.json)
                current = self.revision()
                self.assertNotEqual(previous, current)
                self.assertEqual(self.get('/api/state').json['revision'], current)
                previous = current

    def test_state_omits_bodies_for_inbox_and_deleted_saved_sources(self):
        body = 'PRIVATE-BODY-ONLY ' * 50_000
        self.mail('visible', body=body)
        self.mail('saved-source', body=body)
        self.post('/api/pin', {'id': 'saved-source', 'index': 0, 'action': 'pin'})
        self.post('/api/mail', {'id': 'saved-source', 'action': 'delete'})
        response = self.get('/api/state')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('PRIVATE-BODY-ONLY', response.text)
        self.assertLess(len(response.data), 20_000)
        self.assertEqual([r['id'] for r in response.json['mails']], ['visible'])
        self.assertEqual([r['id'] for r in response.json['eventSourceMails']], ['saved-source'])
        for row in response.json['mails'] + response.json['eventSourceMails']:
            self.assertFalse({'body', 'source_body', 'original', 'translation'} & row.keys())
        self.assertTrue(response.json['eventSourceMails'][0]['is_deleted'])

    def test_detail_and_search_remain_isolated_and_require_authentication(self):
        self.mail('shared', body='ALICE-PRIVATE-TEXT')
        self.mail('shared', user='bob', body='BOB-PRIVATE-TEXT')
        self.mail('bob-only', user='bob', body='BOB-ONLY')
        response = self.get('/api/mail/detail', id='shared')
        self.assertEqual(response.json['mail']['body'], 'ALICE-PRIVATE-TEXT')
        self.assertNotIn('BOB-PRIVATE-TEXT', response.text)
        self.assertEqual(self.get('/api/mail/detail', id='bob-only').status_code, 400)
        self.assertEqual(self.get('/api/mail/search', q='BOB-PRIVATE-TEXT').json['ids'], [])
        self.assertEqual(self.get('/api/mail/search', user='bob', q='BOB-PRIVATE-TEXT').json['ids'], ['shared'])
        for endpoint in ('/api/updates', '/api/mail/detail?id=shared', '/api/mail/search?q=PRIVATE'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.app.test_client().get(endpoint).status_code, 401)
                self.assertEqual(self.clients['bob'].get(endpoint, headers={'X-Token': 'alice-csrf'}).status_code, 403)

    def test_deleted_sources_remain_available_for_saved_events_and_undo(self):
        self.mail('first')
        self.mail('reminder')
        for ident in ('first', 'reminder'):
            self.assertEqual(self.post('/api/pin', {'id': ident, 'index': 0, 'action': 'pin'}).status_code, 200)
        self.assertEqual(self.post('/api/mail/batch', {'ids': ['first', 'reminder'], 'action': 'delete'}).status_code, 200)
        state = self.get('/api/state').json
        self.assertEqual(state['mails'], [])
        self.assertEqual({row['id'] for row in state['eventSourceMails']}, {'first', 'reminder'})
        self.assertEqual(len(state['pins']), 1)
        self.assertEqual(len(state['eventLinks']), 1)
        self.assertEqual(len(state['eventOverrides']), 1)
        self.assertEqual(self.get('/api/mail/search', q='notice').json['ids'], [])
        self.assertEqual(self.get('/api/mail/detail', id='first').status_code, 200)
        self.assertEqual(self.post('/api/source', {'id': 'reminder'}).status_code, 200)
        self.assertEqual(self.post('/api/event/manage', {'id': 'reminder', 'index': 0, 'action': 'complete'}).status_code, 200)
        self.assertEqual(self.get('/api/state').json['pins'][0]['state'], 'completed')
        self.assertEqual(self.post('/api/mail/batch', {'ids': ['first', 'reminder'], 'action': 'restore'}).status_code, 200)
        restored = self.get('/api/state').json
        self.assertEqual(len(restored['mails']), 2)
        self.assertEqual(restored['eventSourceMails'], [])
        self.assertEqual(restored['pins'][0]['state'], 'completed')
        self.assertEqual(len(restored['eventLinks']), 1)

    def test_calendar_feed_survives_source_deletion(self):
        schedule = {**self.event, 'kind': '活动', 'title': 'Project meeting',
                    'start': '2026-10-20T14:00', 'end': '2026-10-20T15:00'}
        self.mail('meeting', event=schedule)
        self.post('/api/calendar/settings', {'calendar_method': 'subscribe', 'calendar_provider': 'apple'})
        subscription = self.post('/api/calendar/subscription', {}).json['url']
        response = self.post('/api/calendar/approve', {'id': 'meeting', 'index': 0, **schedule})
        self.assertEqual(response.status_code, 200, response.json)
        before = self.clients['alice'].get(urlsplit(subscription).path).text
        self.post('/api/mail', {'id': 'meeting', 'action': 'delete'})
        after = self.clients['alice'].get(urlsplit(subscription).path).text
        self.assertIn('SUMMARY:Project meeting', after)
        self.assertEqual(before, after)
        state = self.get('/api/state').json
        self.assertEqual(state['calendarEvents'][0]['status'], 'subscribed')
        self.assertEqual(state['eventSourceMails'][0]['id'], 'meeting')


class PersistentReceiverHealthTests(unittest.TestCase):
    def test_health_update_survives_restart_without_transient_busy_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            status = PersistentStatus(path)
            status['auto'] = True
            status.update(last_sync_at=1234, sync_state='retrying', sync_attempts=2,
                          sync_retry_at=5678, sync_error_code='mail_sync_failed',
                          sync_message='邮箱连接中断，正在重试', busy=True)
            restored = PersistentStatus(path)
            self.assertEqual(restored['last_sync_at'], 1234)
            self.assertEqual(restored['sync_state'], 'retrying')
            self.assertEqual(restored['sync_attempts'], 2)
            self.assertEqual(restored['sync_retry_at'], 5678)
            self.assertEqual(restored['sync_error_code'], 'mail_sync_failed')
            self.assertTrue(restored['auto'])
            self.assertFalse(restored['busy'])


if __name__ == '__main__':
    unittest.main()
