"""Deleting an inbox source must preserve the user's saved work."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import app
from backend.core.database import MailDatabase
from backend.events import event_join


class SavedEventRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'mail.db'
        for name, value in [('DB', self.path), ('DATABASE', MailDatabase())]:
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.event = {
            'title': '项目提交截止', 'action': '提交小组报告',
            'start': '2026-10-20T23:59', 'end': '', 'location': '线上',
            'allDay': False, 'kind': '截止',
        }

    def mail(self, ident, event=None):
        event = event or self.event
        original = {'html': '<p>Original notice</p>', 'external': []}
        with app.db() as c:
            c.execute(
                'INSERT INTO mails(id,subject,body,source_body,result,original,source,created) VALUES (?,?,?,?,?,?,?,?)',
                (ident, 'Notice', 'Original notice', 'Original notice',
                 json.dumps({'events': [event]}), json.dumps(original), 'manual', 1),
            )
        return original

    def pin(self, ident):
        app.update_pin({'id': ident, 'index': 0, 'action': 'pin'})

    def test_deleted_deadline_source_can_still_be_edited_completed_and_restored(self):
        self.mail('first')
        self.pin('first')
        app.update_mail({'id': 'first', 'action': 'delete'})
        edited = {name: self.event[name] for name in event_join.FIELDS}
        edited.update(title='修改后的标题', start='2026-10-21T20:00')
        app.manage_event({'id': 'first', 'index': 0, 'action': 'edit', 'fields': edited})
        app.manage_event({'id': 'first', 'index': 0, 'action': 'complete'})
        with app.db() as c:
            pin = c.execute('SELECT title,due,state FROM pins').fetchone()
            self.assertEqual(tuple(pin), ('修改后的标题', '2026-10-21T20:00', 'completed'))
            self.assertEqual(c.execute("SELECT is_deleted FROM mails WHERE id='first'").fetchone()[0], 1)
        app.manage_event({'id': 'first', 'index': 0, 'action': 'restore'})
        app.update_mail({'id': 'first', 'action': 'restore'})
        with app.db() as c:
            self.assertEqual(c.execute('SELECT state FROM pins').fetchone()[0], 'active')
            self.assertEqual(event_join.effective(c, 'first', 0)['title'], '修改后的标题')

    def test_deleted_original_and_linked_sources_stay_linked_and_deduplicate_new_notice(self):
        self.mail('first')
        self.pin('first')
        self.mail('reminder')
        self.pin('reminder')
        app.update_mail_batch({'ids': ['first', 'reminder'], 'action': 'delete'})
        self.mail('latest')
        self.pin('latest')
        app.manage_event({'id': 'reminder', 'index': 0, 'action': 'complete'})
        with app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pins').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT state FROM pins').fetchone()[0], 'completed')
            self.assertEqual(event_join.resolve(c, 'reminder', 0), ('first', 0))
            self.assertEqual(event_join.resolve(c, 'latest', 0), ('first', 0))

    def test_calendar_remains_subscribed_and_editable_after_source_deletion(self):
        schedule = {**self.event, 'kind': '活动', 'title': '项目讨论',
                    'start': '2026-10-20T14:00', 'end': '2026-10-20T15:00'}
        self.mail('meeting', schedule)
        with app.db() as c:
            c.execute(
                'INSERT INTO calendar_events(mail_id,event_index,status,calendar_name,detail,created) VALUES (?,?,?,?,?,?)',
                ('meeting', 0, 'subscribed', 'TimeMate', json.dumps(schedule), 1),
            )
        app.update_mail({'id': 'meeting', 'action': 'delete'})
        fields = {name: schedule[name] for name in event_join.FIELDS}
        fields['location'] = '会议室 A'
        app.manage_event({'id': 'meeting', 'index': 0, 'action': 'edit', 'fields': fields})
        with app.db() as c:
            row = c.execute('SELECT status,detail FROM calendar_events').fetchone()
            self.assertEqual(row['status'], 'subscribed')
            self.assertEqual(json.loads(row['detail'])['location'], '会议室 A')
        app.manage_event({'id': 'meeting', 'index': 0, 'action': 'remove'})
        with app.db() as c:
            self.assertEqual(c.execute('SELECT status FROM calendar_events').fetchone()[0], 'removed')

    def test_deleted_source_still_opens_and_uses_cached_translation(self):
        original = self.mail('first')
        self.pin('first')
        markup = original['html']
        with app.db() as c:
            c.execute(
                'UPDATE mails SET translation=?,translation_subject=?,translation_format=? WHERE id=?',
                ('<p>原始通知</p>', '通知', app.mail_translation.fingerprint('Notice', markup), 'first'),
            )
        app.update_mail({'id': 'first', 'action': 'delete'})
        self.assertEqual(app.original_mail('first'), original)
        with patch.object(app.ai_services, 'complete', side_effect=AssertionError('cache must be reused')):
            translated = app.translate_source('first')
        self.assertTrue(translated['cached'])
        self.assertEqual(translated['html'], '<p>原始通知</p>')


if __name__ == '__main__':
    unittest.main()
