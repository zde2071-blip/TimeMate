"""Delivery checkpoints survive retries, restarts and mailbox UID resets."""
from functools import partial
import imaplib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.core.database import MailDatabase
from backend.mail import ingest


class MailReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = partial(MailDatabase().connect, Path(self.temp.name) / 'mail.db')
        self.config = dict(account='example@qq.com', password='secret', school_sender='school@example.edu',
                           base='https://example.test', model='example', key='model-secret')
        self.status = {'auto': False}
        self.conn = Mock()
        self.connect = Mock(return_value=(self.conn, 'v1', [1, 2, 3]))
        self.importer = Mock(return_value=('mail-id', True))
        self.analyze = Mock(return_value=(0, 0))
        self.close = Mock()
        self.receiver = ingest.MailReceiver(self.database, self.config, self.status,
                                            self.connect, self.importer, self.close, self.analyze)

    def checkpoint(self, validity='v1', uid=1):
        with self.database() as c:
            c.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?)',
                      (ingest.cursor_key(self.config['account']), validity, uid))

    def position(self):
        with self.database() as c:
            return tuple(c.execute('SELECT validity,uid FROM cursors').fetchone())

    def imported_uids(self):
        return [call.args[3] for call in self.importer.call_args_list]

    def test_first_auto_opt_in_skips_old_mail_but_resume_keeps_checkpoint(self):
        self.receiver.start_auto()
        self.assertEqual(self.position(), ('v1', 3))
        self.status['auto'] = False
        self.connect.return_value = (self.conn, 'v1', [1, 2, 3, 4, 5])
        self.receiver.start_auto()
        self.assertEqual(self.position(), ('v1', 3))
        self.receiver.process_new()
        self.assertEqual(self.imported_uids(), [4, 5])

    def test_network_retry_keeps_auto_and_uses_capped_backoff(self):
        self.status['auto'] = True
        self.checkpoint()
        self.connect.side_effect = TimeoutError('private diagnostic')
        now = 1000
        for delay in (60, 120, 240, 480, 900, 900):
            with patch.object(ingest.time, 'time', return_value=now):
                message = self.receiver.process_new()
            self.assertTrue(self.status['auto'])
            self.assertEqual(self.status['sync_retry_at'], now + delay)
            self.assertEqual(self.status['sync_state'], 'retrying')
            self.assertNotIn('private diagnostic', message)
            with patch.object(ingest.time, 'time', return_value=now + delay - 1):
                calls = self.connect.call_count
                self.receiver.process_new()
                self.assertEqual(self.connect.call_count, calls)
            now += delay
        self.connect.side_effect = None
        with patch.object(ingest.time, 'time', return_value=now):
            self.receiver.process_new()
        self.assertEqual(self.imported_uids(), [2, 3])
        self.assertEqual(self.status['last_sync_at'], now)
        self.assertEqual(self.status['sync_retry_at'], 0)
        self.assertEqual(self.status['sync_attempts'], 0)

    def test_auth_rejection_pauses_without_discarding_checkpoint(self):
        self.status['auto'] = True
        self.checkpoint(uid=1)
        self.connect.side_effect = imaplib.IMAP4.error('AUTHENTICATIONFAILED secret')
        message = self.receiver.process_new()
        self.assertFalse(self.status['auto'])
        self.assertEqual(self.status['sync_state'], 'paused')
        self.assertEqual(self.status['sync_error_code'], 'mail_authentication_failed')
        self.assertNotIn('secret', message)
        self.assertEqual(self.position(), ('v1', 1))

    def test_server_abort_during_login_is_retried_not_treated_as_bad_password(self):
        self.status['auto'] = True
        self.checkpoint()
        self.connect.side_effect = imaplib.IMAP4.abort('LOGIN failed: connection closed')
        self.receiver.process_new()
        self.assertTrue(self.status['auto'])
        self.assertEqual(self.status['sync_state'], 'retrying')

    def test_initial_connection_failure_keeps_retrying(self):
        self.connect.side_effect = ConnectionResetError()
        self.receiver.start_auto()
        self.assertTrue(self.status['auto'])
        self.assertEqual(self.status['sync_state'], 'retrying')

    def test_interrupted_batch_retries_failed_uid_before_advancing(self):
        self.status['auto'] = True
        self.checkpoint(uid=0)
        self.importer.side_effect = [('first', True), TimeoutError()]
        self.receiver.process_new()
        self.assertEqual(self.position(), ('v1', 1))
        self.importer.reset_mock()
        self.importer.side_effect = None
        # Explicit checks may immediately retry even while auto is backing off.
        self.receiver.fetch()
        self.assertEqual(self.imported_uids(), [2, 3])
        self.assertEqual(self.position(), ('v1', 3))

    def test_uidvalidity_change_recovers_every_uid_and_does_not_pause(self):
        self.status['auto'] = True
        self.checkpoint(validity='old', uid=999)
        self.connect.return_value = (self.conn, 'new', [3, 1, 2])
        self.receiver.process_new()
        self.assertEqual(self.imported_uids(), [1, 2, 3])
        self.assertEqual(self.position(), ('new', 3))
        self.assertTrue(self.status['auto'])

    def test_uidvalidity_change_while_resuming_does_not_use_new_maximum(self):
        self.checkpoint(validity='old', uid=999)
        self.receiver.start_auto()
        self.assertEqual(self.position(), ('v1', 0))
        self.receiver.process_new()
        self.assertEqual(self.imported_uids(), [1, 2, 3])

    def test_missing_checkpoint_after_restart_recovers_existing_mail(self):
        self.status['auto'] = True
        self.receiver.process_new()
        self.assertEqual(self.imported_uids(), [1, 2, 3])

    def test_first_manual_check_preserves_recent_fifty_scope_and_reuses_checkpoint(self):
        self.connect.return_value = (self.conn, 'v1', list(range(1, 81)))
        self.receiver.fetch()
        self.assertEqual(self.imported_uids(), list(range(31, 81)))
        self.importer.reset_mock()
        self.connect.return_value = (self.conn, 'v1', list(range(1, 84)))
        self.receiver.fetch()
        self.assertEqual(self.imported_uids(), [81, 82, 83])

    def test_manual_resume_does_not_cap_the_gap_at_fifty(self):
        self.checkpoint(uid=1)
        self.connect.return_value = (self.conn, 'v1', list(range(1, 84)))
        self.receiver.fetch()
        self.assertEqual(self.imported_uids(), list(range(2, 84)))

    def test_analysis_status_excludes_deleted_and_already_analyzed_mail(self):
        with self.database() as c:
            for ident, result, deleted, error in [
                ('waiting', None, 0, None), ('failed', None, 0, 'safe error'),
                ('deleted', None, 1, 'safe error'), ('done', '{}', 0, None),
            ]:
                c.execute('INSERT INTO mails(id,result,is_deleted,analysis_error,source) VALUES (?,?,?,?,?)',
                          (ident, result, deleted, error, 'manual'))
        self.receiver.fetch()
        self.assertEqual(self.status['pending_analysis'], 1)
        self.assertEqual(self.status['failed_analysis'], 1)

    def mail_connection(self, subject='Notice', body='Original notice'):
        header = b'From: school@example.edu\r\n\r\n'
        raw = (f'From: school@example.edu\r\nSubject: {subject}\r\n'
               f'Date: Mon, 12 Oct 2026 10:00:00 +0800\r\n\r\n{body}').encode()
        conn = Mock()
        conn.uid.side_effect = [('OK', [(b'header', header)]), ('OK', [(b'body', raw)])]
        return conn

    def import_real(self, validity, uid, **mail):
        return ingest.import_uid(self.mail_connection(**mail), self.config, validity, uid,
                                 'auto', self.database, ingest.parse_mail)

    def test_same_message_after_uid_reset_preserves_read_deleted_and_analysis(self):
        original, added = self.import_real('old', 999)
        self.assertTrue(added)
        with self.database() as c:
            c.execute('UPDATE mails SET is_read=1,is_deleted=1,result=? WHERE id=?', ('{}', original))
        recovered, added = self.import_real('new', 1)
        self.assertEqual(recovered, original)
        self.assertFalse(added)
        with self.database() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mails').fetchone()[0], 1)
            self.assertEqual(tuple(c.execute('SELECT is_read,is_deleted,result FROM mails').fetchone()), (1, 1, '{}'))

    def test_legacy_exact_copy_adopts_fingerprint_without_replacing_state(self):
        original, _ = self.import_real('old', 999)
        with self.database() as c:
            c.execute('UPDATE mails SET source_fingerprint=NULL,receiving_account=NULL,is_read=1 WHERE id=?', (original,))
        recovered, added = self.import_real('new', 1)
        self.assertEqual(recovered, original)
        self.assertFalse(added)
        with self.database() as c:
            row = c.execute('SELECT source_fingerprint,is_read FROM mails').fetchone()
        self.assertTrue(row['source_fingerprint'])
        self.assertEqual(row['is_read'], 1)

    def test_different_message_content_is_not_deduplicated(self):
        original, _ = self.import_real('old', 999)
        with self.database() as c:
            c.execute('UPDATE mails SET source_fingerprint=NULL,receiving_account=NULL WHERE id=?', (original,))
        recovered, added = self.import_real('new', 1, body='Corrected notice')
        self.assertNotEqual(recovered, original)
        self.assertTrue(added)

    def test_empty_fetch_is_retried_instead_of_saved_as_a_blank_mail(self):
        conn = self.mail_connection()
        conn.uid.side_effect = [
            ('OK', [(b'header', b'From: school@example.edu\r\n\r\n')]), ('OK', [None]),
        ]
        with self.assertRaises(RuntimeError):
            ingest.import_uid(conn, self.config, 'v1', 1, 'auto', self.database, ingest.parse_mail)
        with self.database() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mails').fetchone()[0], 0)

    def test_failed_login_closes_connection_without_leaking_provider_details(self):
        conn = Mock()
        conn.login.side_effect = imaplib.IMAP4.error('AUTHENTICATIONFAILED private-server-text')
        # A transport failure during cleanup must not replace the useful error.
        conn.shutdown.side_effect = OSError('close error')
        with patch.object(ingest.imaplib, 'IMAP4_SSL', return_value=conn):
            with self.assertRaises(ingest.MailAuthenticationError) as error:
                ingest.connect_mail(self.config)
        self.assertNotIn('private-server-text', str(error.exception))
        conn.shutdown.assert_called_once()


if __name__ == '__main__':
    unittest.main()
