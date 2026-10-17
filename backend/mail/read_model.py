"""Small update checks, mailbox summaries, and on-demand mail bodies."""
import hashlib
import json
import unicodedata

from backend.core.user_errors import UserFacingError

REAL_MAIL = "source NOT IN ('simulation','test_archive')"
# Original HTML/images and cached translations have dedicated endpoints.
MAIL_COLUMNS = ('id,subject,sender,date,sent_date,body,result,created,source,'
                'source_links,source_body,is_read,is_deleted,manual_category,'
                'display_title,title_version,analysis_attempts,analysis_retry_at,analysis_error,mailbox_id,receiving_account')
VISIBLE_CONFIG = ('account','mail_provider','base','model','school_sender','calendar_method',
                  'calendar_provider','calendar_subscription_confirmed','provider')


def json_object(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


class MailReadModel:
    def __init__(self, database, config, status, providers, decorate):
        self.database = database
        self.config = config
        self.status = status
        self.providers = providers
        self.decorate = decorate

    def revision(self, connection):
        revision = connection.execute('SELECT revision FROM state_revision WHERE id=1').fetchone()[0]
        visible = {key:self.config[key] for key in VISIBLE_CONFIG}
        # Credential presence affects ready state; values never enter the response.
        identity = json.dumps([revision,visible,bool(self.config['password']),bool(self.config['key'])],sort_keys=True)
        return hashlib.sha256(identity.encode()).hexdigest()

    def updates(self, connection=None):
        if connection is None:
            with self.database() as connection:
                connection.execute('BEGIN')
                return self.updates(connection)
        row = connection.execute(f"SELECT COUNT(*) AS pending, COALESCE(SUM(analysis_error IS NOT NULL AND analysis_error!=''),0) AS failed FROM mails WHERE result IS NULL AND is_deleted=0 AND {REAL_MAIL}").fetchone()
        return {'revision':self.revision(connection), 'status':dict(self.status),
                'pendingCount':row['pending'], 'failedCount':row['failed']}

    def summarize(self, row):
        result = self.decorate(dict(row))
        result.pop('body', None)
        result.pop('source_body', None)
        return result

    def state(self):
        with self.database() as connection:
            # Read the revision and its data from the same snapshot. A concurrent
            # importer then advances the next update check instead of being lost.
            connection.execute('BEGIN')
            data = self.updates(connection)
            mails = [self.summarize(row) for row in connection.execute(f'SELECT {MAIL_COLUMNS} FROM mails WHERE is_deleted=0 AND {REAL_MAIL} ORDER BY created DESC')]
            # Soft deletion changes the inbox, not the saved event or its sources.
            sources = [self.summarize(row) for row in connection.execute(f'''SELECT {MAIL_COLUMNS} FROM mails WHERE is_deleted=1 AND {REAL_MAIL} AND (
                id IN (SELECT mail_id FROM pins WHERE state IN ('active','completed')) OR
                id IN (SELECT mail_id FROM calendar_events WHERE status='subscribed') OR
                id IN (SELECT mail_id FROM event_links) OR id IN (SELECT target_mail_id FROM event_links))''')]
            written = [dict(row) for row in connection.execute('SELECT mail_id,event_index,status,calendar_name,detail FROM calendar_events')]
            pins = [dict(row) for row in connection.execute(f"SELECT pins.* FROM pins JOIN mails ON mails.id=pins.mail_id WHERE pins.state IN ('active','completed') AND {REAL_MAIL} ORDER BY pins.due")]
            overrides = [dict(row) for row in connection.execute(f'SELECT event_overrides.* FROM event_overrides JOIN mails ON mails.id=event_overrides.mail_id WHERE {REAL_MAIL}')]
            links = [dict(row) for row in connection.execute('SELECT * FROM event_links')]
            courses = [row['code'] for row in connection.execute('SELECT code FROM courses ORDER BY code')]
        mails.sort(key=lambda row:row.pop('_sort_timestamp'), reverse=True)
        for row in sources: row.pop('_sort_timestamp', None)
        data.update(mails=mails, eventSourceMails=sources, pins=pins, calendarEvents=written,
                    eventOverrides=overrides,eventLinks=links,courseCodes=courses,
                    config={key:self.config[key] for key in VISIBLE_CONFIG},providers=self.providers,
                    ready={'mail':bool(self.config['account'] and self.config['password'] and self.config['school_sender']),
                           'ai':bool(self.config['base'] and self.config['model'] and self.config['key'])})
        return data

    def detail(self, ident):
        if not isinstance(ident,str) or not ident: raise UserFacingError('邮件编号无效')
        with self.database() as connection:
            row = connection.execute(f'SELECT {MAIL_COLUMNS} FROM mails WHERE id=? AND {REAL_MAIL}', (ident,)).fetchone()
        if row is None: raise UserFacingError('邮件不存在')
        mail = self.decorate(dict(row))
        mail.pop('_sort_timestamp', None)
        return {'mail':mail}

    def search(self, query):
        if not isinstance(query,str) or len(query)>500: raise UserFacingError('搜索内容过长')
        words = unicodedata.normalize('NFKC',query).casefold().split()
        ids = []
        with self.database() as connection:
            connection.execute('BEGIN')
            revision = self.revision(connection)
            for row in connection.execute(f'SELECT id,display_title,subject,sender,body,source_body,result FROM mails WHERE is_deleted=0 AND {REAL_MAIL}'):
                values = [row[key] or '' for key in ('display_title','subject','sender','body','source_body')]
                def collect(value):
                    if isinstance(value,str): values.append(value)
                    elif isinstance(value,list):
                        for item in value: collect(item)
                    elif isinstance(value,dict):
                        for item in value.values(): collect(item)
                collect(json_object(row['result']))
                text = unicodedata.normalize('NFKC','\n'.join(values)).casefold()
                if all(word in text for word in words): ids.append(row['id'])
        return {'ids':ids, 'revision':revision}
