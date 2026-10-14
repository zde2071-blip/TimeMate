import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.core.database import MailDatabase
from backend.core.user_errors import UserFacingError
from backend.mail.chat import MailChat


class MailChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'mail.db'
        self.database = MailDatabase()

        def db():
            return self.database.connect(self.path)

        self.db = db
        self.reply = Mock(return_value={'reply': '本周有一项课程通知。', 'source_ids': ['real']})
        self.chat = MailChat(self.db, {'base': 'https://api.example', 'model': 'test', 'key': 'secret'}, self.reply)
        with self.db() as connection:
            connection.execute(
                'INSERT INTO mails(id,subject,display_title,sender,date,sent_date,result,source) VALUES (?,?,?,?,?,?,?,?)',
                ('real', '课程通知', '课程通知', '老师', '2026-10-14', '2026-10-14T10:00+08:00',
                 json.dumps({'category': '课程与教学', 'summary': '课程本周发布。', 'events': []}, ensure_ascii=False), 'mail'))
            connection.execute('INSERT INTO mails(id,subject,date,body,source) VALUES (?,?,?,?,?)',
                               ('old', '旧邮件', '2026-09-01', '不应进入上下文', 'mail'))
            connection.execute('INSERT INTO mails(id,subject,date,source) VALUES (?,?,?,?)',
                               ('sim', '模拟邮件', '2026-10-14', 'simulation'))

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **overrides):
        data = {'message': '总结本周课程通知', 'scope': 'week', 'fromDate': '2026-10-12', 'toDate': '2026-10-18'}
        data.update(overrides)
        return data

    def test_context_is_date_scoped_and_never_includes_original_body(self):
        context = self.chat._mail_context('2026-10-12', '2026-10-18')
        self.assertEqual(context['total'], 1)
        self.assertEqual(context['mails'][0]['id'], 'real')
        self.assertNotIn('body', context['mails'][0])
        self.assertNotIn('不应进入上下文', json.dumps(context, ensure_ascii=False))

    def test_send_persists_turns_and_validated_source_ids(self):
        result = self.chat.send(self.payload())
        self.assertEqual(result['sources'][0]['id'], 'real')
        self.reply.return_value = {'reply': '已整理。', 'source_ids': ['real', 'not-in-context']}
        second = self.chat.send(self.payload(conversationId=result['conversationId']))
        self.assertEqual([source['id'] for source in second['sources']], ['real'])
        history = self.chat.history(result['conversationId'])
        self.assertEqual([item['role'] for item in history['messages']], ['user', 'assistant', 'user', 'assistant'])

    def test_invalid_range_message_and_unknown_conversation_are_rejected(self):
        for data in (self.payload(fromDate='2026-02-31'), self.payload(fromDate='2026-10-01', toDate='2026-11-10'),
                     self.payload(message=' '), self.payload(conversationId='missing')):
            with self.subTest(data=data), self.assertRaises(UserFacingError):
                self.chat.send(data)

    def test_delete_removes_conversation_and_messages(self):
        result = self.chat.send(self.payload())
        self.chat.delete(result['conversationId'])
        self.assertEqual(self.chat.conversations(), [])
        with self.assertRaises(UserFacingError):
            self.chat.history(result['conversationId'])


if __name__ == '__main__':
    unittest.main()
