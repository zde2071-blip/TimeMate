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

    def test_single_delete_can_be_undone_without_changing_read_status(self):
        app.update_mail({'id': 'two', 'action': 'delete'})
        app.update_mail({'id': 'two', 'action': 'restore'})
        with self.database.connect(self.path) as c:
            row = c.execute('SELECT is_read,is_deleted FROM mails WHERE id=?', ('two',)).fetchone()
            self.assertEqual(tuple(row), (1, 0))
        with self.assertRaises(app.UserFacingError):
            app.update_mail({'id': 'two', 'action': 'restore'})

    def test_batch_undo_restores_exact_selection_and_rejects_partial_restore(self):
        app.update_mail_batch({'ids': ['one', 'two'], 'action': 'delete'})
        with self.assertRaises(app.UserFacingError):
            app.update_mail_batch({'ids': ['one', 'missing'], 'action': 'restore'})
        with self.database.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM mails WHERE is_deleted=1").fetchone()[0], 2)
        app.update_mail_batch({'ids': ['one', 'one', 'two'], 'action': 'restore'})
        with self.database.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM mails WHERE is_deleted=1").fetchone()[0], 0)
            self.assertEqual([tuple(r) for r in c.execute(
                "SELECT id,is_read FROM mails WHERE id IN ('one','two') ORDER BY id")], [('one', 0), ('two', 1)])

    def test_restore_never_accepts_live_mail_or_simulation_rows(self):
        app.update_mail({'id': 'one', 'action': 'delete'})
        with self.database.connect(self.path) as c:
            c.execute("UPDATE mails SET is_deleted=1 WHERE id='demo'")
        for invalid in ('two', 'demo'):
            with self.subTest(invalid=invalid), self.assertRaises(app.UserFacingError):
                app.update_mail_batch({'ids': ['one', invalid], 'action': 'restore'})
        with self.database.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT is_deleted FROM mails WHERE id='one'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
