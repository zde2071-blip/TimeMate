"""QQ mailbox transport and import workflow, with explicit account dependencies."""
import email, hashlib, html, imaplib, json, re, ssl, time
from email import policy
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import urlparse
import certifi
import mail_original
import operation_status
from user_errors import UserFacingError

def mail_id(account,validity,uid):
    return hashlib.sha256((account.lower()+validity+str(uid)).encode()).hexdigest()

def connect_mail(cfg):
    conn=imaplib.IMAP4_SSL('imap.qq.com',993,ssl_context=ssl.create_default_context(cafile=certifi.where()),timeout=15)
    try:
        checked(conn.login(cfg['account'],cfg['password']))
        checked(conn.select('INBOX',readonly=True))
        validity=str(conn.response('UIDVALIDITY')[1])
        ids=[int(x) for x in (checked(conn.uid('SEARCH',None,'ALL'))[0] or b'').split()]
        return conn,validity,ids
    except Exception:
        conn.shutdown()
        raise

def close_mail(conn):
    try: conn.shutdown()
    except Exception: pass

def mail_sender(conn,uid):
    chunks=checked(conn.uid('FETCH',str(uid),'(BODY.PEEK[HEADER.FIELDS (FROM)])'))
    raw=b''.join(x[1] for x in chunks if isinstance(x,tuple))
    header=email.message_from_bytes(raw,policy=policy.default)
    return str(header.get('From',''))

def matches_school_sender(sender,school_sender):
    actual=parseaddr(sender)[1].strip().casefold()
    expected=parseaddr(school_sender)[1].strip().casefold()
    return bool(expected and actual==expected)

def import_uid(conn,cfg,validity,uid,source,database,parse):
    ident=mail_id(cfg['account'],validity,uid)
    if not matches_school_sender(mail_sender(conn,uid),cfg['school_sender']): return None,False
    with database() as c:
        if c.execute('SELECT 1 FROM mails WHERE id=?',(ident,)).fetchone(): return ident,False
    chunks=checked(conn.uid('FETCH',str(uid),'(BODY.PEEK[])'))
    raw=b''.join(x[1] for x in chunks if isinstance(x,tuple))
    m=parse(raw)
    with database() as c:
        cur=c.execute('INSERT OR IGNORE INTO mails (id,subject,sender,date,body,result,created,source,source_links,original,source_body) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (ident,m['subject'],m['sender'],m['date'],m['body'],None,time.time(),source,json.dumps(m['links'],ensure_ascii=False),json.dumps(m['original'],ensure_ascii=False),m['source_body']))
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
    return f' {failed} 封分析失败，后续检查会自动重试。' if failed else ''

def cursor_key(account):
    return hashlib.sha256(account.casefold().encode()).hexdigest()

class MailReceiver:
    def __init__(self, database, config, status, connect, importer, close, analyze_pending):
        self.database = database
        self.config = config
        self.status = status
        self.connect = connect
        self.importer = importer
        self.close = close
        self.analyze_pending = analyze_pending

    def fetch(self):
        cfg=self.config.copy()
        if not cfg['account'] or not cfg['password']: raise UserFacingError('请先填写并应用 QQ 邮箱与授权码。')
        conn=None; added=0; matched=0
        try:
            operation_status.begin(self.status,'checking','正在登录 QQ 邮箱…',kind='check')
            conn,validity,ids=self.connect(cfg)
            for uid in reversed(ids[-50:]):
                self.status['message']='正在检查 QQ 邮箱最近 50 封邮件的发件人地址…'
                ident,was_added=self.importer(conn,cfg,validity,uid,'manual')
                matched+=ident is not None
                added+=was_added
            checked_count=min(50,len(ids))
        finally:
            if conn: self.close(conn)
        analyzed,failed=self.analyze_pending()
        message=f'检查完成：最近 {checked_count} 封中，{matched} 封发件人匹配学校邮箱，新增 {added} 封，自动分析 {analyzed} 封；其余邮件的发件人不匹配。'+analysis_retry_message(failed)
        operation_status.finish(self.status,message,added=added,success=analyzed,failed=failed)
        return message

    def start_auto(self):
        cfg=self.config.copy()
        if not all(cfg[k] for k in ('account','password','school_sender','base','model','key')):
            raise UserFacingError('先填写 QQ 邮箱授权码、学校邮箱和模型 API Key。')
        conn=None
        try:
            operation_status.begin(self.status,'checking','正在记录当前邮件位置，旧邮件不会自动分析…')
            conn,validity,ids=self.connect(cfg)
            with self.database() as c:
                c.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?)',
                          (cursor_key(cfg['account']),validity,max(ids,default=0)))
            self.status['auto']=True
            message='自动分析已开启。每分钟检查新邮件，只处理发件人地址匹配设置中学校邮箱的邮件。'
            operation_status.begin(self.status,'idle',message)
            return message
        finally:
            if conn: self.close(conn)

    def process_new(self):
        cfg=self.config.copy()
        if not self.status['auto']: return '自动分析已停止。'
        conn=None; imported=0; matched=0
        try:
            operation_status.begin(self.status,'checking','自动检查新邮件…',kind='check')
            conn,validity,ids=self.connect(cfg)
            key=cursor_key(cfg['account'])
            with self.database() as c:
                cursor=c.execute('SELECT validity,uid FROM cursors WHERE account=?',(key,)).fetchone()
                if not cursor: raise RuntimeError('缺少起始位置，请重新开启自动分析。')
                if cursor['validity']!=validity:
                    self.status['auto']=False
                    raise RuntimeError('邮箱编号已重置，自动分析已暂停。重新开启可建立新起点。')
                last=cursor['uid']
            for uid in (x for x in ids if x>last):
                ident,added=self.importer(conn,cfg,validity,uid,'auto')
                matched+=ident is not None
                imported+=added
                with self.database() as c:
                    c.execute('UPDATE cursors SET uid=? WHERE account=?',(uid,key))
            analyzed,failed=self.analyze_pending()
            message=f'自动检查完成：发现 {matched} 封发件人匹配学校邮箱的新邮件，导入 {imported} 封，分析 {analyzed} 封；发件人不匹配的邮件已忽略。'+analysis_retry_message(failed)
            operation_status.finish(self.status,message,added=imported,success=analyzed,failed=failed)
            return message
        except Exception:
            self.status['auto']=False
            raise
        finally:
            if conn: self.close(conn)

