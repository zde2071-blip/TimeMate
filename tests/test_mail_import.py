import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app


class MailImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(app, 'DB', Path(self.temp.name) / 'mail.db')
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def fake_mail(self, sender, subject, body=b'Notice body\r\n'):
        raw = (f'From: {sender}\r\nSubject: {subject}\r\n'.encode()
               + b'Date: Mon, 05 Oct 2026 10:00:00 +0800\r\n'
               + b'Content-Type: text/plain; charset=utf-8\r\n\r\n' + body)
        header = f'From: {sender}\r\n\r\n'.encode()
        conn = Mock()
        conn.uid.side_effect = [
            ('OK', [(b'1 FETCH (BODY[HEADER.FIELDS (FROM)]', header), b')']),
            ('OK', [(b'1 FETCH (BODY[]', raw), b')']),
        ]
        return conn

    def test_mail_sort_uses_sent_time_instead_of_import_time(self):
        older_but_imported_later = {
            'date': 'Mon, 05 Oct 2026 09:00:00 +0800',
            'created': 200,
        }
        newer_but_imported_earlier = {
            'date': 'Mon, 05 Oct 2026 10:00:00 +0800',
            'created': 100,
        }

        self.assertGreater(
            app.mail_sort_timestamp(newer_but_imported_earlier),
            app.mail_sort_timestamp(older_but_imported_later),
        )

    def test_imports_matching_sender_without_forward_prefix(self):
        conn = self.fake_mail('School Office <school@xjtlu.edu.cn>', 'Weekly notice')
        cfg = {'account': 'user@qq.com', 'school_sender': 'school@xjtlu.edu.cn'}

        ident, added = app.import_uid(conn, cfg, '1', 42, 'manual')

        self.assertTrue(ident)
        self.assertTrue(added)
        self.assertEqual(conn.uid.call_count, 2)
        with app.db() as c:
            row = c.execute('SELECT subject,sender,body FROM mails WHERE id=?', (ident,)).fetchone()
        self.assertEqual(row['subject'], 'Weekly notice')
        self.assertIn('School Office', row['sender'])
        self.assertIn('Notice body', row['body'])

    def test_imports_matching_sender_when_message_is_larger_than_two_mb(self):
        conn = self.fake_mail('school@xjtlu.edu.cn', 'Large notice', b'x' * 2_000_100)
        cfg = {'account': 'user@qq.com', 'school_sender': 'school@xjtlu.edu.cn'}

        ident, added = app.import_uid(conn, cfg, '1', 43, 'manual')

        self.assertTrue(ident)
        self.assertTrue(added)
        with app.db() as c:
            row = c.execute('SELECT length(body) AS body_length FROM mails WHERE id=?', (ident,)).fetchone()
        self.assertEqual(row['body_length'], 20000)

    def test_rejects_different_sender_without_fetching_message_body(self):
        conn = Mock()
        header = b'From: other@example.edu\r\n\r\n'
        conn.uid.return_value = ('OK', [(b'1 FETCH (BODY[HEADER.FIELDS (FROM)]', header), b')'])
        cfg = {'account': 'user@qq.com', 'school_sender': 'school@xjtlu.edu.cn'}

        ident, added = app.import_uid(conn, cfg, '1', 44, 'manual')

        self.assertIsNone(ident)
        self.assertFalse(added)
        conn.uid.assert_called_once_with('FETCH', '44', '(BODY.PEEK[HEADER.FIELDS (FROM)])')
        with app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mails').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
