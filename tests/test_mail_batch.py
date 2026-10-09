from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import app
from backend.core.database import MailDatabase


class MailBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'mail.db'
        self.database = MailDatabase()
        with self.database.connect(self.path) as c:
            c.executemany(
                'INSERT INTO mails(id,subject,source,is_read,is_deleted) VALUES (?,?,?,?,?)',
                [('one', 'One', 'imap', 0, 0), ('two', 'Two', 'imap', 1, 0),
                 ('demo', 'Demo', 'simulation', 0, 0)],
            )
        self.db_patch = patch.object(app, 'DB', self.path)
        self.database_patch = patch.object(app, 'DATABASE', self.database)
        self.db_patch.start()
        self.database_patch.start()

    def tearDown(self):
        self.database_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def test_read_unread_and_delete_only_update_selected_real_mail(self):
        app.update_mail_batch({'ids': ['one', 'two'], 'action': 'read'})
        with self.database.connect(self.path) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT is_read FROM mails WHERE id IN (?,?) ORDER BY id', ('one', 'two'))], [1, 1])
        app.update_mail_batch({'ids': ['two'], 'action': 'unread'})
        app.update_mail_batch({'ids': ['one'], 'action': 'delete'})
        with self.database.connect(self.path) as c:
            self.assertEqual(tuple(c.execute('SELECT is_read,is_deleted FROM mails WHERE id=?', ('two',)).fetchone()), (0, 0))
            self.assertEqual(c.execute('SELECT is_deleted FROM mails WHERE id=?', ('one',)).fetchone()[0], 1)
            self.assertEqual(tuple(c.execute('SELECT is_read,is_deleted FROM mails WHERE id=?', ('demo',)).fetchone()), (0, 0))

    def test_invalid_selection_does_not_partially_update(self):
        with self.assertRaises(app.UserFacingError):
            app.update_mail_batch({'ids': ['one', 'missing'], 'action': 'read'})
        with self.database.connect(self.path) as c:
            self.assertEqual(c.execute('SELECT is_read FROM mails WHERE id=?', ('one',)).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
