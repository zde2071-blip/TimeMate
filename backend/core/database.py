"""Versioned account database initialization; ordinary connections do no upgrades."""
from pathlib import Path
import sqlite3
import threading
from backend.mail import titles as mail_titles
from backend.mail import dates as mail_dates
SCHEMA_VERSION = 7
MAIL_COLUMNS = {
    'original': 'TEXT', 'source_links': 'TEXT',
    'source': "TEXT NOT NULL DEFAULT 'manual'",
    'is_read': 'INTEGER NOT NULL DEFAULT 0', 'is_deleted': 'INTEGER NOT NULL DEFAULT 0',
    'translation': 'TEXT', 'translation_subject': 'TEXT', 'source_body': 'TEXT',
    'translation_format': 'TEXT', 'translation_body_length': 'INTEGER',
    'manual_category': 'TEXT', 'display_title': 'TEXT', 'title_version': 'INTEGER',
    'analysis_attempts': 'INTEGER NOT NULL DEFAULT 0',
    'analysis_retry_at': 'REAL NOT NULL DEFAULT 0', 'analysis_error': 'TEXT',
}
TABLES = (
    'CREATE TABLE IF NOT EXISTS courses (code TEXT PRIMARY KEY)',
    'CREATE TABLE IF NOT EXISTS cursors (account TEXT PRIMARY KEY, validity TEXT NOT NULL, uid INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS calendar_events (mail_id TEXT NOT NULL, event_index INTEGER NOT NULL, status TEXT NOT NULL, event_id TEXT, calendar_name TEXT, detail TEXT, created REAL NOT NULL, PRIMARY KEY(mail_id,event_index))',
    "CREATE TABLE IF NOT EXISTS pins (mail_id TEXT NOT NULL,event_index INTEGER NOT NULL,title TEXT NOT NULL,due TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(mail_id,event_index))",
    "CREATE TABLE IF NOT EXISTS event_overrides (mail_id TEXT NOT NULL,event_index INTEGER NOT NULL,fields TEXT NOT NULL DEFAULT '{}',state TEXT NOT NULL DEFAULT 'active',PRIMARY KEY(mail_id,event_index))",
    'CREATE TABLE IF NOT EXISTS event_links (mail_id TEXT NOT NULL,event_index INTEGER NOT NULL,target_mail_id TEXT NOT NULL,target_index INTEGER NOT NULL,PRIMARY KEY(mail_id,event_index))',
)


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def initialize(connection):
    """Adopt legacy databases and upgrade atomically, once per schema version."""
    connection.execute('BEGIN IMMEDIATE')
    try:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError('数据库版本高于当前程序版本，请使用新版程序。')
        if version < 1:
            connection.execute('CREATE TABLE IF NOT EXISTS mails (id TEXT PRIMARY KEY, subject TEXT, sender TEXT, date TEXT, body TEXT, result TEXT, created REAL)')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(mails)')}
            for name, kind in MAIL_COLUMNS.items():
                if name not in columns:
                    connection.execute(f'ALTER TABLE mails ADD COLUMN {name} {kind}')
            for statement in TABLES:
                connection.execute(statement)
        if version < 2:
            mail_titles.migrate(connection)
        if version < 3:
            connection.execute('ALTER TABLE mails ADD COLUMN sent_date TEXT')
            # Stream one original at a time; embedded images can be many MB.
            for row in connection.execute('SELECT id,date,body,source_body,original FROM mails'):
                connection.execute('UPDATE mails SET sent_date=? WHERE id=?',
                                   (mail_dates.stored_date(dict(row)), row['id']))
        if version < 4:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(mails)')}
            for name in ('source_fingerprint', 'receiving_account'):
                if name not in columns:
                    connection.execute(f'ALTER TABLE mails ADD COLUMN {name} TEXT')
            connection.execute('CREATE INDEX IF NOT EXISTS mail_source_fingerprint ON mails(receiving_account,source_fingerprint)')
            connection.execute('CREATE INDEX IF NOT EXISTS pending_mail_analysis ON mails(is_deleted,analysis_retry_at) WHERE result IS NULL')
            connection.execute('CREATE TABLE IF NOT EXISTS state_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)')
            connection.execute('INSERT OR IGNORE INTO state_revision VALUES (1,0)')
            for table in ('mails', 'pins', 'calendar_events', 'event_overrides', 'event_links', 'courses'):
                for action in ('INSERT', 'UPDATE', 'DELETE'):
                    connection.execute(f"CREATE TRIGGER IF NOT EXISTS revision_{table}_{action.lower()} AFTER {action} ON {table} BEGIN UPDATE state_revision SET revision=revision+1 WHERE id=1; END")
        if version < 5:
            connection.execute('CREATE TABLE IF NOT EXISTS chat_conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)')
            connection.execute("CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL)")
            connection.execute('CREATE INDEX IF NOT EXISTS chat_messages_conversation ON chat_messages(conversation_id,id)')
            connection.execute('CREATE INDEX IF NOT EXISTS chat_conversations_updated ON chat_conversations(updated DESC)')
        if version < 6:
            connection.execute("CREATE TABLE IF NOT EXISTS chat_event_proposals (id TEXT PRIMARY KEY,message_id INTEGER NOT NULL REFERENCES chat_messages(id),event TEXT NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',saved_id TEXT,saved_index INTEGER)")
            connection.execute('CREATE INDEX IF NOT EXISTS chat_event_message ON chat_event_proposals(message_id)')
            connection.execute('CREATE TABLE IF NOT EXISTS chat_requests (id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,response TEXT NOT NULL)')
        if version < 7:
            connection.execute('CREATE TABLE IF NOT EXISTS ai_profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL,provider TEXT NOT NULL,base TEXT NOT NULL,model TEXT NOT NULL,is_default INTEGER NOT NULL DEFAULT 0)')
            connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS ai_profile_default ON ai_profiles(is_default) WHERE is_default=1')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(chat_conversations)')}
            if 'ai_profile_id' not in columns:
                connection.execute("ALTER TABLE chat_conversations ADD COLUMN ai_profile_id TEXT NOT NULL DEFAULT ''")
            for action in ('INSERT', 'UPDATE', 'DELETE'):
                connection.execute(f"CREATE TRIGGER IF NOT EXISTS revision_ai_profiles_{action.lower()} AFTER {action} ON ai_profiles BEGIN UPDATE state_revision SET revision=revision+1 WHERE id=1; END")
        connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        connection.commit()
    except Exception:
        connection.rollback()
        raise


class MailDatabase:
    """Each account owns its initialization cache and opens independent connections."""
    def __init__(self):
        self._lock = threading.Lock()
        self._initialized = None

    def connect(self, path):
        path = Path(path).resolve()
        with self._lock:
            connection = sqlite3.connect(path, factory=Connection)
            connection.row_factory = sqlite3.Row
            try:
                stat = path.stat()
                identity = (path, stat.st_dev, stat.st_ino)
                if identity != self._initialized:
                    initialize(connection)
                    self._initialized = identity
                return connection
            except Exception:
                connection.close()
                raise
