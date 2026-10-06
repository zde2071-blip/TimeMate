"""Copy stopped-server data and verify recovery in an isolated temporary directory."""
import argparse
import fcntl
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet


def verify(directory, key):
    source = Path(directory).resolve()
    if not (source / 'accounts.db').is_file():
        raise ValueError('备份缺少 accounts.db')
    # Exercise recovery without modifying the live data or the backup.
    with tempfile.TemporaryDirectory(prefix='mail-recovery-') as temp:
        recovered = Path(temp) / 'data'
        shutil.copytree(source, recovered)
        for path in recovered.rglob('*.db'):
            connection = sqlite3.connect(path)
            try:
                if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('数据库完整性检查失败')
            finally:
                connection.close()
        connection = sqlite3.connect(recovered / 'accounts.db')
        try:
            cipher = Fernet(key)
            for value, in connection.execute('SELECT value FROM credentials'):
                cipher.decrypt(value)
            for value, in connection.execute('SELECT token FROM calendar_feeds'):
                cipher.decrypt(value)
            for uid, in connection.execute('SELECT id FROM users'):
                if not (recovered / 'users' / uid / 'mail.db').is_file():
                    raise ValueError('备份缺少用户邮件数据库')
        finally:
            connection.close()


def backup(source, destination, key):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents:
        raise ValueError('备份位置不能位于原数据目录内')
    if destination.exists():
        raise ValueError('备份位置已存在，请使用新的目录')
    if not (source / 'accounts.db').is_file():
        raise ValueError('原数据目录缺少 accounts.db')
    # The application uses the same lock. Refuse inconsistent live copies.
    with (source / 'server.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('请先停止服务，再执行备份') from None
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('server.lock'))
        verify(destination, key)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'verify'])
    parser.add_argument('--data', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    key = os.environ.get('MAIL_MASTER_KEY')
    if not key:
        parser.error('需要环境变量 MAIL_MASTER_KEY；不要在命令参数中填写密钥')
    if args.action == 'backup':
        if not args.output:
            parser.error('备份需要 --output')
        backup(args.data, args.output, key)
    else:
        verify(args.data, key)
    print('验证通过：数据已在临时目录恢复，数据库完整且凭证可解密。')


if __name__ == '__main__':
    main()
