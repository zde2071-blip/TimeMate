"""QQ mailbox transport and import workflow, with explicit account dependencies."""
import email, hashlib, html, imaplib, json, re, ssl, time
from email import policy
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import urlparse
import certifi
from backend.mail import original as mail_original
from backend.mail import dates as mail_dates
from backend.core import operation_status
from backend.core.user_errors import UserFacingError


class MailAuthenticationError(UserFacingError):
    code = 'mail_authentication_failed'


def authentication_failed(error):
    """Only explicit authentication rejection pauses unattended receiving."""
    if isinstance(error, MailAuthenticationError):
        return True
    if isinstance(error, imaplib.IMAP4.abort):
        return False
    if not isinstance(error, imaplib.IMAP4.error):
        return False
    message = str(error).casefold()
    return any(reason in message for reason in (
        'authenticationfailed', 'authentication failed', 'authentication unsuccessful',
        'invalid credentials', 'invalid password', 'wrong password', 'login fail',
        'login denied', 'login rejected', 'authorization failed',
        'authentication error', 'authentication failure', 'invalid login',
        'login error', 'password error', 'login command error',
        '用户名或密码', '密码错误', '授权码错误', '授权码失效', '登录失败',
    ))

def mail_id(account,validity,uid):
    return hashlib.sha256((account.lower()+validity+str(uid)).encode()).hexdigest()

def mail_server(cfg):
    account=(cfg.get('account') or '').strip().casefold()
    if account.endswith('@163.com'): return 'imap.163.com'
    if account.endswith('@126.com'): return 'imap.126.com'
    return 'imap.qq.com'

def connect_mail(cfg):
    conn=imaplib.IMAP4_SSL(mail_server(cfg),993,ssl_context=ssl.create_default_context(cafile=certifi.where()),timeout=15)
    try:
        try:
            checked(conn.login(cfg['account'],cfg['password']))
        except imaplib.IMAP4.error as error:
            if authentication_failed(error):
                raise MailAuthenticationError('接收邮箱登录失败，请检查邮箱地址、客户端授权码及 IMAP 服务是否开启') from None
            raise
        checked(conn.select('INBOX',readonly=True))
        validity=str(conn.response('UIDVALIDITY')[1])
        ids=[int(x) for x in (checked(conn.uid('SEARCH',None,'ALL'))[0] or b'').split()]
        return conn,validity,ids
    except Exception:
        close_mail(conn)
        raise

def close_mail(conn):
    try: conn.shutdown()
    except Exception: pass

def mail_sender(conn,uid):
    chunks=checked(conn.uid('FETCH',str(uid),'(BODY.PEEK[HEADER.FIELDS (FROM)])'))
    raw=b''.join(x[1] for x in chunks if isinstance(x,tuple))
    if not raw: raise RuntimeError('未能读取邮件发件人，将在下次检查时重试')
    header=email.message_from_bytes(raw,policy=policy.default)
    return str(header.get('From',''))

def matches_school_sender(sender,school_sender):
    actual=parseaddr(sender)[1].strip().casefold()
    expected=parseaddr(school_sender)[1].strip().casefold()
    return bool(expected and actual==expected)

def import_uid(conn,cfg,validity,uid,source,database,parse):
    ident=mail_id(cfg['account'],validity,uid)
    with database() as c:
        if c.execute('SELECT 1 FROM mails WHERE id=?',(ident,)).fetchone(): return ident,False
    sender=mail_sender(conn,uid)
    sources=cfg.get('_mail_sources') or [{'id':None,'address':cfg['school_sender']}]
    matched=next((item for item in sources if matches_school_sender(sender,item['address'])),None)
    if not matched: return None,False
    chunks=checked(conn.uid('FETCH',str(uid),'(BODY.PEEK[])'))
    raw=b''.join(x[1] for x in chunks if isinstance(x,tuple))
    if not raw: raise RuntimeError('未能读取邮件正文，将在下次检查时重试')
    result=import_raw(raw,ident,cfg['account'],source,database,parse)
    if matched.get('id'):
        with database() as c: c.execute('UPDATE mails SET mailbox_id=? WHERE id=? AND mailbox_id IS NULL',(matched['id'],result[0]))
    return result

def import_raw(raw,ident,receiving_account,source,database,parse):
    fingerprint=hashlib.sha256(raw).hexdigest()
    account=cursor_key(receiving_account)
    with database() as c:
        duplicate=c.execute('SELECT id FROM mails WHERE receiving_account=? AND source_fingerprint=?',
                            (account,fingerprint)).fetchone()
        if duplicate: return duplicate['id'],False
    m=parse(raw)
    with database() as c:
        original=json.dumps(m['original'],ensure_ascii=False)
        # Upgrade exact legacy copies in place, including read/deleted state and
        # saved events. UIDVALIDITY can change without the messages changing.
        legacy=c.execute("""SELECT id,original FROM mails WHERE source_fingerprint IS NULL
                            AND (receiving_account IS NULL OR receiving_account=?)
                            AND source IN ('manual','auto') AND subject=? AND sender=?
                            AND date=? AND body=? AND source_body=?""",
                         (account,m['subject'],m['sender'],m['date'],m['body'],m['source_body']))
        for row in legacy:
            try: same_original=json.loads(row['original'] or '{}')==m['original']
            except (ValueError,TypeError): same_original=False
            if same_original:
                c.execute('UPDATE mails SET receiving_account=?,source_fingerprint=? WHERE id=?',
                          (account,fingerprint,row['id']))
                return row['id'],False
        sent_date=mail_dates.stored_date({**m,'original':original})
        cur=c.execute('INSERT OR IGNORE INTO mails (id,subject,sender,date,body,result,created,source,source_links,original,source_body,sent_date,receiving_account,source_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (ident,m['subject'],m['sender'],m['date'],m['body'],None,time.time(),source,json.dumps(m['links'],ensure_ascii=False),original,m['source_body'],sent_date,account,fingerprint))
        return ident,bool(cur.rowcount)

def checked(result):
    code,data=result
    if code!='OK': raise RuntimeError('邮箱服务器没有完成请求')
    return data

def parse_mail(raw):
    m=email.message_from_bytes(raw,policy=policy.default)
    plain=[]; rich=[]
    for p in m.walk():
        if p.get_content_disposition()=='attachment': continue
        if p.get_content_type() not in ('text/plain','text/html'): continue
        payload=p.get_payload(decode=True) or b''
        s=mail_original.decode_text(payload,p.get_content_charset())
        (plain if p.get_content_type()=='text/plain' else rich).append(s)
    body='\n'.join(plain)
    if not body:
        body=html.unescape(re.sub('<[^>]+>',' ',re.sub(r'(?is)<(script|style).*?</\1>','','\n'.join(rich))))
    return {'subject':str(m.get('Subject','')),'sender':str(m.get('From','')),'date':str(m.get('Date','')),'body':body[:20000],'source_body':body,'links':extract_source_links(body,'\n'.join(rich)),'original':mail_original.extract(m,body)}

def source_links(body):
    links=[]
    for value in re.findall(r'https?://[^\s<>"\u3000]+',body):
        value=value.rstrip('。，；、）).,;')
        if value not in links: links.append(value)
    return links[:20]

class MailLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.url=None; self.label=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style'): self.hidden+=1
        if tag=='a' and not self.hidden:
            self.url=attrs.get('href','').strip(); self.label=[]
    def handle_data(self,data):
        if self.url and not self.hidden: self.label.append(data)
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
        if tag=='a' and self.url:
            self.links.append({'url':self.url,'label':' '.join(''.join(self.label).split())});self.url=None;self.label=[]

def extract_source_links(body,rich=''):
    parser=MailLinks();parser.feed(rich);output=[];seen=set()
    for item in parser.links+[{'url':url,'label':''} for url in source_links(body)]:
        url=item['url'];parts=urlparse(url)
        if parts.scheme not in ('http','https') or not parts.netloc or url in seen: continue
        seen.add(url);output.append({'url':url,'label':item['label'] or url})
    return output

def analysis_retry_message(failed):
    return f'；{failed} 封分析失败，后续检查会自动重试' if failed else ''

def cursor_key(account):
    return hashlib.sha256(account.casefold().encode()).hexdigest()


def analysis_queue_counts(database):
    with database() as c:
        row=c.execute("""SELECT COUNT(*) AS pending,
                         COALESCE(SUM(CASE WHEN analysis_error IS NOT NULL THEN 1 ELSE 0 END),0) AS failed
                         FROM mails WHERE result IS NULL AND is_deleted=0
                         AND source IN ('manual','auto')""").fetchone()
    return {'pending_analysis':row['pending']-row['failed'], 'failed_analysis':row['failed']}

class MailReceiver:
    def __init__(self, database, config, status, connect, importer, close, analyze_pending):
        self.database = database
        self.config = config
        self.status = status
        self.connect = connect
        self.importer = importer
        self.close = close
        self.analyze_pending = analyze_pending

    def _begin_check(self, message):
        operation_status.begin(self.status, 'checking', message, kind='check')
        self.status.update(sync_state='checking', sync_message=message)

    def _sync_succeeded(self):
        self.status.update(last_sync_at=time.time(), sync_state='ready',
                           sync_error_code='', sync_message='', sync_attempts=0, sync_retry_at=0)

    def _sync_failed(self, error):
        if authentication_failed(error):
            self.status['auto'] = False
            message = '自动检查已暂停，请检查接收邮箱地址、客户端授权码及 IMAP 服务是否开启'
            self.status.update(sync_state='paused', sync_error_code='mail_authentication_failed',
                               sync_message=message, sync_retry_at=0)
            operation_status.fail(self.status, message, 'mail_authentication_failed')
        else:
            attempts = int(self.status.get('sync_attempts', 0)) + 1
            delay = min(60 * 2 ** min(attempts - 1, 4), 900)
            automatic = self.status.get('auto', False)
            message = ('邮箱连接中断，正在重试' if automatic else '暂时无法完成收信，请稍后重试')
            self.status.update(sync_state='retrying' if automatic else 'error',
                               sync_error_code='mail_sync_failed', sync_message=message,
                               sync_attempts=attempts, sync_retry_at=time.time() + delay if automatic else 0)
            operation_status.fail(self.status, message, 'mail_sync_failed')
        return message

    def _cursor(self, cfg, validity, ids, initial_latest=False, initial_recent=False):
        key = cursor_key(cfg['account'])
        with self.database() as c:
            cursor = c.execute('SELECT validity,uid FROM cursors WHERE account=?', (key,)).fetchone()
            if cursor and cursor['validity'] == validity:
                return key, cursor['uid']
            # Only a brand-new opt-in starts at the latest message. A resumed
            # receiver, missing cursor or UIDVALIDITY reset must recover backlog.
            last = max(ids, default=0) if initial_latest and not cursor else 0
            if initial_recent and not cursor:
                ordered = sorted(set(ids))
                last = ordered[-51] if len(ordered) > 50 else 0
            c.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?)', (key, validity, last))
            return key, last

    def fetch(self):
        cfg = self.config.copy()
        if not all(cfg.get(key) for key in ('account', 'password', 'school_sender')):
            raise UserFacingError('请先填写并应用接收邮箱、客户端授权码与学校邮箱')
        # The first manual import keeps its existing recent-50 scope. Once a
        # checkpoint exists, recover the whole gap, even after a long interruption.
        return self._check(cfg, 'manual')

    def start_auto(self):
        cfg = self.config.copy()
        if not all(cfg.get(key) for key in ('account', 'password', 'school_sender', 'base', 'model', 'key')):
            raise UserFacingError('先填写接收邮箱授权码、学校邮箱和模型 API Key')
        conn = None
        self.status['auto'] = True
        try:
            self._begin_check('正在连接接收邮箱…')
            conn, validity, ids = self.connect(cfg)
            key = cursor_key(cfg['account'])
            with self.database() as c:
                existing = c.execute('SELECT 1 FROM cursors WHERE account=?', (key,)).fetchone()
            self._cursor(cfg, validity, ids, initial_latest=True)
            self.status.update(sync_state='ready', sync_error_code='', sync_message='',
                               sync_attempts=0, sync_retry_at=0)
            message = ('自动检查已恢复，将从上次位置继续收信' if existing else
                       '自动检查已开启，每分钟检查新邮件')
            operation_status.begin(self.status, 'idle', message, kind='check')
            return message
        except Exception as error:
            return self._sync_failed(error)
        finally:
            if conn is not None:
                self.close(conn)

    def process_new(self):
        if not self.status.get('auto'):
            return '自动检查已停止'
        if self.status.get('sync_retry_at', 0) > time.time():
            return self.status.get('sync_message', '邮箱连接中断，正在重试')
        cfg = self.config.copy()
        if not all(cfg.get(key) for key in ('account', 'password', 'school_sender')):
            self.status['auto'] = False
            message = '自动检查已暂停，请补全接收邮箱设置'
            self.status.update(sync_state='paused', sync_error_code='mail_config_missing',
                               sync_message=message, sync_retry_at=0)
            operation_status.fail(self.status, message, 'mail_config_missing')
            return message
        return self._check(cfg, 'auto')

    def _check(self, cfg, source):
        conn = None
        added = matched = checked_count = 0
        try:
            self._begin_check('正在检查接收邮箱…')
            conn, validity, ids = self.connect(cfg)
            key, last = self._cursor(cfg, validity, ids, initial_recent=source == 'manual')
            pending = sorted(uid for uid in set(ids) if uid > last)
            for uid in pending:
                self.status['message'] = f'正在检查邮件 {checked_count + 1}/{len(pending)}'
                ident, was_added = self.importer(conn, cfg, validity, uid, source)
                matched += ident is not None
                added += was_added
                checked_count += 1
                # Advance only after this message was durably imported or
                # positively identified as unrelated; interrupted batches resume.
                with self.database() as c:
                    c.execute('UPDATE cursors SET uid=? WHERE account=?', (uid, key))
            self._sync_succeeded()
        except Exception as error:
            self.status.update(added=added)
            return self._sync_failed(error)
        finally:
            if conn is not None:
                self.close(conn)
        analyzed, failed = self.analyze_pending()
        self.status.update(analysis_queue_counts(self.database))
        message = (f'检查完成：检查 {checked_count} 封邮件，{matched} 封匹配相应邮箱，'
                   f'新增 {added} 封，自动分析 {analyzed} 封' + analysis_retry_message(failed))
        operation_status.finish(self.status, message, added=added, success=analyzed, failed=failed)
        return message
