import fcntl
import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from backend.cloud import Store
from tools.backup import backup, verify


class BackupTests(unittest.TestCase):
    def test_recovery_credentials_and_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = Fernet.generate_key()
            store = Store(root / 'data', key)
            with store.db() as connection:
                connection.execute('INSERT INTO users VALUES (?,?,?)',
                                   ('test-user', 'test@example.com', 'test-hash'))
                connection.execute('INSERT INTO credentials VALUES (?,?,?)',
                                   ('test-user', 'mail', store.cipher.encrypt(b'test-secret')))
            engine = store.engine('test-user')
            with engine.db() as connection:
                connection.execute('INSERT INTO mails(id,subject,sender,date,body,created) VALUES (?,?,?,?,?,?)',
                                   ('test-mail', '测试邮件', 'school@example.com', '2026-10-06', '恢复验证', 0))
            with (store.directory / 'server.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, '停止服务'):
                    backup(store.directory, root / 'blocked', key)
            backup(store.directory, root / 'copy', key)
            verify(root / 'copy', key)
            import sqlite3
            with sqlite3.connect(root / 'copy' / 'users' / 'test-user' / 'mail.db') as connection:
                self.assertEqual(connection.execute('SELECT body FROM mails').fetchone()[0], '恢复验证')
            with self.assertRaises(InvalidToken):
                verify(root / 'copy', Fernet.generate_key())
            with self.assertRaisesRegex(ValueError, '已存在'):
                backup(store.directory, root / 'copy', key)
            with self.assertRaisesRegex(ValueError, '原数据目录内'):
                backup(store.directory, store.directory / 'copy', key)
