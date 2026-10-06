import json
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend.core import database as mail_database
class DatabaseUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'mail.db'
        self.database = mail_database.MailDatabase()

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_mail_and_user_decisions_survive_upgrade(self):
        result = json.dumps({'short_title':'心理团体报名','summary':'原摘要','events':[]},ensure_ascii=False)
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('CREATE TABLE mails(id TEXT PRIMARY KEY,subject TEXT,sender TEXT,date TEXT,body TEXT,result TEXT,created REAL,manual_category TEXT)')
            c.execute('INSERT INTO mails VALUES (?,?,?,?,?,?,?,?)',('old','原题','school','2026-10-06','原文',result,1,'其他'))
            c.execute("CREATE TABLE pins(mail_id TEXT,event_index INTEGER,title TEXT,due TEXT,state TEXT,PRIMARY KEY(mail_id,event_index))")
            c.execute('INSERT INTO pins VALUES (?,?,?,?,?)',('old',0,'用户保存的标题','2026-10-10','completed'))
        with self.database.connect(self.path) as c:
            row=c.execute('SELECT * FROM mails').fetchone()
            self.assertEqual(row['result'],result)
            self.assertEqual(row['body'],'原文')
            self.assertEqual(row['manual_category'],'其他')
            self.assertEqual(row['display_title'],'心理团体报名')
            self.assertEqual(c.execute('SELECT state FROM pins').fetchone()[0],'completed')
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],mail_database.SCHEMA_VERSION)

    def test_ordinary_connections_do_not_check_or_migrate_schema(self):
        self.database.connect(self.path).close()
        with patch.object(mail_database,'initialize',side_effect=AssertionError('Repeated initialization')):
            for _ in range(5):
                with self.database.connect(self.path) as c:
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM mails').fetchone()[0],0)

    def test_restart_does_not_rewrite_titles(self):
        with self.database.connect(self.path) as c:
            c.execute('INSERT INTO mails(id,subject,display_title,title_version) VALUES (?,?,?,?)',('one','原题','已保存的标题',1))
        with patch.object(mail_database.mail_titles,'migrate',side_effect=AssertionError('Already migrated')):
            with mail_database.MailDatabase().connect(self.path) as c:
                self.assertEqual(c.execute('SELECT display_title FROM mails').fetchone()[0],'已保存的标题')

    def test_simultaneous_first_connections_initialize_once(self):
        def read(_):
            with self.database.connect(self.path) as c:
                return c.execute('PRAGMA user_version').fetchone()[0]
        with patch.object(mail_database,'initialize',wraps=mail_database.initialize) as initialize:
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(list(pool.map(read,range(8))),[mail_database.SCHEMA_VERSION]*8)
            self.assertEqual(initialize.call_count,1)

    def test_failed_upgrade_rolls_back_and_can_retry(self):
        with patch.object(mail_database.mail_titles,'migrate',side_effect=RuntimeError('Upgrade interrupted')):
            with self.assertRaises(RuntimeError):self.database.connect(self.path)
        with closing(sqlite3.connect(self.path)) as c, c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='mails'").fetchone())
        with self.database.connect(self.path) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],mail_database.SCHEMA_VERSION)

    def test_replaced_database_and_other_accounts_initialize_independently(self):
        self.database.connect(self.path).close()
        replacement=Path(self.temp.name)/'replacement.db'
        replacement.touch()
        replacement.replace(self.path)
        with self.database.connect(self.path) as c:
            c.execute("INSERT INTO courses VALUES ('CSI101')")
        other=Path(self.temp.name)/'other.db'
        with mail_database.MailDatabase().connect(other) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM courses').fetchone()[0],0)
