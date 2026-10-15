"""Email-verified public web gateway. Each authenticated user owns an isolated engine and DB.
Run exactly one application process; its scheduler services all user engines.
"""
import argparse, hashlib, hmac, importlib.util, json, os, re, secrets, sqlite3, threading, time, logging
from html import escape
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from cryptography.fernet import Fernet
from flask import Flask, request, jsonify, redirect, g, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from backend.core import ai_services
ROOT=Path(__file__).resolve().parents[1]
os.umask(0o077)

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

class PersistentStatus(dict):
    """Keep receiver health across restarts without persisting transient jobs."""
    PERSISTED = {'auto', 'last_sync_at', 'sync_state', 'sync_error_code',
                 'sync_message', 'sync_retry_at', 'sync_attempts'}

    def __init__(self, path):
        self.path = path
        self._save_lock = threading.Lock()
        try:
            stored = json.loads(path.read_text())
            if not isinstance(stored, dict): stored = {}
        except (OSError, ValueError):
            stored = {}
        enabled = stored.get('auto') is True
        super().__init__(busy=False, auto=enabled,
                         message='自动分析已恢复' if enabled else '尚未开启自动分析')
        for key in self.PERSISTED - {'auto'}:
            if key in stored: dict.__setitem__(self, key, stored[key])
        if self.get('sync_state') == 'checking':
            dict.__setitem__(self, 'sync_state', 'ready' if enabled else 'paused')

    def _save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({k:self[k] for k in self.PERSISTED if k in self}, ensure_ascii=False))
        temp.replace(self.path)

    def __setitem__(self, key, value):
        with self._save_lock:
            super().__setitem__(key, value)
            if key in self.PERSISTED: self._save()

    def update(self, *args, **kwargs):
        changes = dict(*args, **kwargs)
        with self._save_lock:
            super().update(changes)
            if self.PERSISTED.intersection(changes): self._save()



class Runtime:
    def __init__(self,store,uid):
        self.store=store; self.uid=uid
        self.directory=store.directory/'users'/uid
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.status=PersistentStatus(self.directory/'status.json')
        self.request_lock=threading.Lock()
    def credential(self,action,identity,secret=''):
        with self.store.db() as c:
            if action=='delete':
                c.execute('DELETE FROM credentials WHERE user_id=? AND identity=?',(self.uid,identity))
                return ''
            if action=='save':
                c.execute('INSERT OR REPLACE INTO credentials VALUES (?,?,?)',(self.uid,identity,self.store.cipher.encrypt(secret.encode())))
                return ''
            row=c.execute('SELECT value FROM credentials WHERE user_id=? AND identity=?',(self.uid,identity)).fetchone()
            return self.store.cipher.decrypt(row['value']).decode() if row else ''

class Store:
    def __init__(self,directory,key):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.cipher=Fernet(key); self.engines={}; self.lock=threading.Lock()
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS credentials(user_id TEXT,identity TEXT,value BLOB,PRIMARY KEY(user_id,identity));
            CREATE TABLE IF NOT EXISTS resets(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS email_verifications(email TEXT PRIMARY KEY,code_hash TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS password_reset_codes(email TEXT PRIMARY KEY,code_hash TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS calendar_feeds(user_id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,token BLOB NOT NULL);
            ''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.directory/'accounts.db',timeout=15); c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    def reset(self,email):
        with self.db() as c:
            user=c.execute('SELECT id FROM users WHERE email=?',(valid_email(email),)).fetchone()
            if not user: raise ValueError('未找到账号')
            token=secrets.token_urlsafe(32)
            c.execute('DELETE FROM resets WHERE user_id=?',(user['id'],))
            c.execute('INSERT INTO resets VALUES (?,?,?)',(digest(token),user['id'],time.time()+1800))
        return token
    def limited(self,bucket,limit=10):
        now=time.time()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM attempts WHERE expires<?',(now,))
            c.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1',(digest(bucket),now+900))
            return c.execute('SELECT count FROM attempts WHERE bucket=?',(digest(bucket),)).fetchone()[0]>limit
    def calendar_feed(self,uid,origin):
        with self.db() as c:
            row=c.execute('SELECT token FROM calendar_feeds WHERE user_id=?',(uid,)).fetchone()
        return origin+'/calendar/'+self.cipher.decrypt(row['token']).decode()+'.ics' if row else None
    def create_calendar_feed(self,uid,origin):
        current=self.calendar_feed(uid,origin)
        if current: return current
        token=secrets.token_urlsafe(32)
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO calendar_feeds VALUES (?,?,?)',(uid,digest(token),self.cipher.encrypt(token.encode())))
        return self.calendar_feed(uid,origin)
    def engine(self,uid):
        with self.lock:
            if uid not in self.engines:
                with self.db() as c:
                    if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(): raise ValueError('账号不存在')
                runtime=Runtime(self,uid)
                spec=importlib.util.spec_from_file_location('backend.mail_user_'+uid,ROOT/'backend/app.py')
                engine=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(engine)
                engine.initialize(runtime)
                engine.db().close()
                # The shared AI adapter is wrapped per engine, never globally mutated.
                class CloudAI:
                    PROVIDERS={k:v for k,v in ai_services.PROVIDERS.items() if k!='custom'}
                    infer_provider=staticmethod(ai_services.infer_provider)
                    @staticmethod
                    def validate(cfg,model=True):
                        provider=CloudAI.PROVIDERS.get(cfg.get('provider'))
                        if not provider or cfg.get('base','').rstrip('/')!=provider['base'].rstrip('/'):
                            raise ai_services.AIServiceError('多人版请使用所选服务商的预设接口地址。')
                        ai_services.validate(cfg,model)
                    @staticmethod
                    def complete(cfg,*args,**kwargs):
                        CloudAI.validate(cfg); return ai_services.complete(cfg,*args,**kwargs)
                    @staticmethod
                    def list_models(cfg):
                        CloudAI.validate(cfg,False); return ai_services.list_models(cfg)
                engine.ai_services=CloudAI
                self.engines[uid]=engine
            return self.engines[uid]
    def tick(self):
        with self.db() as c: users=[r[0] for r in c.execute('SELECT id FROM users')]
        for uid in users:
            try:
                engine=self.engine(uid)
                if engine.STATUS['auto'] and not engine.STATUS['busy'] and engine.STATUS.get('sync_retry_at',0)<=time.time(): engine.job(engine.process_new)
            except Exception:
                # One damaged account must not stop other users. Never log secrets.
                continue

def valid_email(value):
    value=str(value).strip().casefold()
    if len(value)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value): raise ValueError('请输入有效邮箱地址。')
    return value

def password_hash(value):
    if not isinstance(value,str) or not 8<=len(value)<=128: raise ValueError('密码需为 8–128 个字符。')
    return generate_password_hash(value,method='scrypt')

class NoEmailRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def send_auth_email(address,code,subject,action):
    api_key=os.environ.get('RESEND_API_KEY','').strip()
    sender=os.environ.get('MAIL_FROM','').strip() or 'TimeMate <noreply@timemate.cc>'
    if not api_key:
        raise ValueError('邮箱验证服务尚未配置，请稍后再试或联系管理员。')
    payload={'from':sender,'to':[address],'subject':subject,
             'text':f'你的 TimeMate{action}验证码是：{code}\n\n验证码 10 分钟内有效。若非本人操作，请忽略此邮件。'}
    req=Request('https://api.resend.com/emails',data=json.dumps(payload).encode('utf-8'),
                headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json',
                         'User-Agent':'TimeMate/1.0'},method='POST')
    try:
        with build_opener(NoEmailRedirect()).open(req,timeout=15) as response:
            result=json.loads(response.read(65536))
        if not isinstance(result,dict) or not result.get('id'):
            raise ValueError('验证码邮件暂时发送失败，请稍后重试。')
    except HTTPError as error:
        try:
            details=json.loads(error.read(65536))
            name=str(details.get('name','unknown')) if isinstance(details,dict) else 'unknown'
        except (ValueError,OSError):
            name='unknown'
        if name not in {'validation_error','missing_api_key','invalid_api_key','restricted_api_key','rate_limit_exceeded','daily_quota_exceeded','monthly_quota_exceeded'}:
            name='unknown'
        error.close()
        logging.getLogger(__name__).warning('Email API rejected request (status=%s, reason=%s)',error.code,name)
        raise ValueError('验证码邮件暂时发送失败，请稍后重试。') from None
    except (URLError,TimeoutError,OSError,ValueError) as error:
        logging.getLogger(__name__).warning('Email API request failed (%s)',type(error).__name__)
        raise ValueError('验证码邮件暂时发送失败，请稍后重试。') from None

def create_app(directory,key,origin='http://127.0.0.1:18744'):
    # Environment variables are strings; HMAC requires bytes.
    key=key.encode('ascii') if isinstance(key,str) else key
    url=urlsplit(origin)
    if url.scheme not in ('http','https') or not url.netloc or url.path or url.query or url.fragment: raise ValueError('请设置完整站点来源地址')
    if url.scheme!='https' and url.hostname not in ('localhost','127.0.0.1'): raise ValueError('公网必须使用 HTTPS')
    store=Store(directory,key)
    app=Flask(__name__,static_folder=str(ROOT/'web/assets'),static_url_path='/assets'); app.store=store
    # MAIL_ORIGIN is the canonical address used in generated links. Also accept
    # Railway's generated domain as an alias so both public URLs keep working.
    railway_domain=os.environ.get('RAILWAY_PUBLIC_DOMAIN','').strip().rstrip('.')
    trusted_hosts={url.hostname}
    allowed_origins={origin}
    if railway_domain:
        trusted_hosts.add(railway_domain)
        allowed_origins.add('https://'+railway_domain)
    app.config.update(MAX_CONTENT_LENGTH=20000,TRUSTED_HOSTS=sorted(trusted_hosts),MAIL_ALLOWED_ORIGINS=allowed_origins)
    secure=url.scheme=='https'
    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='上传内容过大；每次最多 3 张图片，合计不超过 6 MB。'),413
    @app.before_request
    def guard():
        # Keep ordinary routes small; only authenticated chat accepts image JSON.
        if request.path == '/api/chat' and request.method == 'POST':
            from backend.mail.chat_images import CHAT_REQUEST_BYTES
            request.max_content_length = CHAT_REQUEST_BYTES
        g.auth=None
        token=request.cookies.get('mail_session','')
        with store.db() as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            if token: g.auth=c.execute('SELECT * FROM sessions WHERE token=?',(digest(token),)).fetchone()
        if request.method=='POST':
            if request.headers.get('Origin') not in app.config['MAIL_ALLOWED_ORIGINS']: return jsonify(error='页面来源不匹配，请重新打开。'),403
            if not request.is_json: return jsonify(error='请求格式不正确。'),415
        if request.path.startswith('/api/') and not (request.path.startswith('/api/auth/') and request.method=='POST'):
            if not g.auth: return jsonify(error='请先登录。'),401
            if not secrets.compare_digest(request.headers.get('X-Token',''),g.auth['csrf']): return jsonify(error='请刷新页面。'),403
        if request.path in ('/api/auth/logout','/api/auth/password'):
            if not g.auth or not secrets.compare_digest(request.headers.get('X-Token',''),g.auth['csrf']): return jsonify(error='请刷新后重试。'),403
    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: https:; frame-src 'self' about:; frame-ancestors 'none'; form-action 'self'"})
        if response.status_code==200 and request.endpoint=='static' and re.fullmatch(r'/assets/(outlook-forwarding|qq-mail)/[0-9]{2}\.[0-9a-f]{12}\.webp',request.path):
            response.headers['Cache-Control']='public, max-age=31536000, immutable'
        if secure: response.headers['Strict-Transport-Security']='max-age=31536000'
        return response
    def new_session(uid):
        token=secrets.token_urlsafe(32)
        with store.db() as c:
            if g.auth: c.execute('DELETE FROM sessions WHERE token=?',(g.auth['token'],))
            c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(token),uid,secrets.token_urlsafe(32),time.time()+30*86400))
        response=jsonify(ok=True)
        response.set_cookie('mail_session',token,max_age=30*86400,httponly=True,secure=secure,samesite='Lax',path='/')
        return response
    @app.get('/login')
    def login_page(): return (ROOT/'web/login.html').read_text()
    @app.get('/privacy')
    def privacy_page(): return (ROOT/'web/privacy.html').read_text()
    @app.get('/')
    def index():
        if not g.auth: return redirect('/login')
        with store.db() as c: user=c.execute('SELECT email FROM users WHERE id=?',(g.auth['user_id'],)).fetchone()
        if not user: return redirect('/login')
        return (ROOT/'web/index.html').read_text().replace('__TOKEN__',g.auth['csrf']).replace('__EMAIL__',escape(user['email'],quote=True))
    @app.get('/<filename>.js')
    def javascript(filename):
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', filename): return '',404
        path = ROOT/'web'/(filename+'.js')
        if not path.is_file(): return '',404
        response=make_response(path.read_text())
        response.headers['Content-Type']='text/javascript; charset=utf-8'
        return response
    @app.get('/styles.css')
    def stylesheet():
        response=make_response((ROOT/'web/styles.css').read_text())
        response.headers['Content-Type']='text/css; charset=utf-8'
        return response
    @app.get('/account')
    def account():
        if not g.auth: return redirect('/login')
        return redirect('/#settings')
    @app.get('/calendar/<token>.ics')
    def calendar_feed(token):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token): return '',404
        with store.db() as c:
            owner=c.execute('SELECT user_id FROM calendar_feeds WHERE token_hash=?',(digest(token),)).fetchone()
        if not owner: return '',404
        engine=store.engine(owner['user_id'])
        with engine.db() as c:
            items=[json.loads(r['detail']) for r in c.execute("SELECT detail FROM calendar_events WHERE status='subscribed' ORDER BY created")]
        lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Campus Mail Assistant//ZH','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:邮件助手']
        for item in items:
            try:
                event=engine.export_calendar_event(item)
                lines.append(event[event.index('BEGIN:VEVENT'):event.index('END:VEVENT')+len('END:VEVENT')].strip())
            except (KeyError,ValueError,TypeError): continue
        response=make_response('\r\n'.join(lines+['END:VCALENDAR','']))
        response.headers['Content-Type']='text/calendar; charset=utf-8'
        response.headers['Content-Disposition']='inline; filename="mail-assistant.ics"'
        response.headers['X-Robots-Tag']='noindex, nofollow'
        return response
    @app.post('/api/auth/<action>')
    def auth(action):
        d=request.get_json(silent=True)
        if not isinstance(d,dict): return jsonify(error='请求格式不正确。'),400
        if store.limited('ip:'+str(request.remote_addr),60): return jsonify(error='操作过于频繁，请 15 分钟后重试。'),429
        try:
            if action=='send-reset-code':
                address=valid_email(d.get('email',''))
                if store.limited('password-reset:'+address,3): return jsonify(error='验证码发送过于频繁，请 15 分钟后重试。'),429
                with store.db() as c: user=c.execute('SELECT 1 FROM users WHERE email=?',(address,)).fetchone()
                if user:
                    code=f'{secrets.randbelow(1000000):06d}'
                    code_hash=hmac.new(key,('timemate-reset:'+address+':'+code).encode(),hashlib.sha256).hexdigest()
                    try: send_auth_email(address,code,'TimeMate 密码重置验证码','密码重置')
                    except (OSError,ValueError) as error:
                        app.logger.warning('Password reset email could not be sent (%s)',type(error).__name__)
                        raise ValueError('验证码邮件暂时发送失败，请稍后重试。')
                    with store.db() as c:
                        c.execute('INSERT OR REPLACE INTO password_reset_codes(email,code_hash,expires,attempts) VALUES (?,?,?,0)',(address,code_hash,time.time()+600))
                return jsonify(ok=True,message='如果该邮箱已注册，验证码邮件已发送。')
            if action=='send-code':
                address=valid_email(d.get('email',''))
                if store.limited('email-code:'+address,3): return jsonify(error='验证码发送过于频繁，请 15 分钟后重试。'),429
                code=f'{secrets.randbelow(1000000):06d}'
                code_hash=hmac.new(key,('timemate-email:'+address+':'+code).encode(),hashlib.sha256).hexdigest()
                try: send_auth_email(address,code,'TimeMate 注册验证码','注册')
                except (OSError,ValueError) as error:
                    app.logger.warning('Verification email could not be sent (%s)',type(error).__name__)
                    raise ValueError(str(error) if isinstance(error,ValueError) else '验证码邮件暂时发送失败，请稍后重试。')
                with store.db() as c:
                    c.execute('INSERT OR REPLACE INTO email_verifications(email,code_hash,expires,attempts) VALUES (?,?,?,0)',(address,code_hash,time.time()+600))
                return jsonify(ok=True)
            if action in ('register','login'):
                address=valid_email(d.get('email',''))
                if store.limited('account:'+address): return jsonify(error='操作过于频繁，请 15 分钟后重试。'),429
                if action=='register':
                    hashed=password_hash(d.get('password')); uid=secrets.token_hex(16)
                    registration_error=None
                    with store.db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        verification=c.execute('SELECT * FROM email_verifications WHERE email=? AND expires>?',(address,time.time())).fetchone()
                        if not verification: raise ValueError('请先获取有效的邮箱验证码。')
                        code=str(d.get('code','')).strip()
                        supplied=hmac.new(key,('timemate-email:'+address+':'+code).encode(),hashlib.sha256).hexdigest()
                        if verification['attempts']>=5 or not hmac.compare_digest(verification['code_hash'],supplied):
                            c.execute('UPDATE email_verifications SET attempts=attempts+1 WHERE email=?',(address,))
                            registration_error='验证码错误或已失效，请检查后重试。'
                        if not registration_error:
                            c.execute('INSERT INTO users VALUES (?,?,?)',(uid,address,hashed))
                            c.execute('DELETE FROM email_verifications WHERE email=?',(address,))
                    if registration_error: raise ValueError(registration_error)
                else:
                    with store.db() as c: user=c.execute('SELECT * FROM users WHERE email=?',(address,)).fetchone()
                    supplied=d.get('password','')
                    if not isinstance(supplied,str) or len(supplied)>128: raise ValueError('邮箱或密码不正确。')
                    # Always perform a password hash check, including unknown accounts.
                    if not check_password_hash(user['password'] if user else app.dummy_hash,supplied) or not user: raise ValueError('邮箱或密码不正确。')
                    uid=user['id']
                return new_session(uid)
            if action=='logout':
                with store.db() as c: c.execute('DELETE FROM sessions WHERE token=?',(g.auth['token'],))
                response=jsonify(ok=True); response.delete_cookie('mail_session'); return response
            if action=='password':
                with store.db() as c:
                    user=c.execute('SELECT * FROM users WHERE id=?',(g.auth['user_id'],)).fetchone()
                    old=d.get('old','')
                    if not isinstance(old,str) or len(old)>128 or not check_password_hash(user['password'],old): raise ValueError('当前密码不正确。')
                    hashed=password_hash(d.get('password'))
                    c.execute('UPDATE users SET password=? WHERE id=?',(hashed,user['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                    c.execute('DELETE FROM resets WHERE user_id=?',(user['id'],))
                return new_session(user['id'])
            if action=='reset':
                hashed=password_hash(d.get('password'))
                reset_error=None
                with store.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    address=valid_email(d.get('email','')) if not d.get('reset') else ''
                    verification=c.execute('SELECT * FROM password_reset_codes WHERE email=? AND expires>?',(address,time.time())).fetchone()
                    if verification:
                        code=str(d.get('code','')).strip()
                        supplied=hmac.new(key,('timemate-reset:'+address+':'+code).encode(),hashlib.sha256).hexdigest()
                        if verification['attempts']>=5 or not hmac.compare_digest(verification['code_hash'],supplied):
                            c.execute('UPDATE password_reset_codes SET attempts=attempts+1 WHERE email=?',(address,))
                            reset_error='验证码错误或已失效，请检查后重试。'
                        else:
                            user=c.execute('SELECT id FROM users WHERE email=?',(address,)).fetchone()
                            if not user: reset_error='验证码错误或已失效，请检查后重试。'
                            else:
                                uid=user['id']
                                c.execute('DELETE FROM password_reset_codes WHERE email=?',(address,))
                    else:
                        # Keep the administrator-issued one-time reset token as an emergency fallback.
                        row=c.execute('SELECT * FROM resets WHERE token=? AND expires>?',(digest(str(d.get('reset',''))),time.time())).fetchone()
                        if not row: reset_error='验证码错误或已失效，请检查后重试。'
                        else:
                            uid=row['user_id']
                            c.execute('DELETE FROM resets WHERE user_id=?',(uid,))
                    if not reset_error:
                        c.execute('UPDATE users SET password=? WHERE id=?',(hashed,uid))
                        c.execute('DELETE FROM resets WHERE user_id=?',(uid,))
                        c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
                if reset_error: raise ValueError(reset_error)
                return jsonify(ok=True)
            return jsonify(error='接口不存在。'),404
        except sqlite3.IntegrityError: return jsonify(error='无法注册，请核对账号或登录。'),400
        except ValueError as e: return jsonify(error=str(e)),400
    @app.route('/api/<path:path>',methods=['GET','POST'])
    def api(path):
        if path == 'chat' and request.method == 'POST' and store.limited('chat:'+g.auth['user_id'],20):
            return jsonify(error='对话请求过于频繁，请 15 分钟后再试。'),429
        engine=store.engine(g.auth['user_id'])
        if request.method=='POST' and not isinstance(request.get_json(silent=True),dict): return jsonify(error='请求格式不正确。'),400
        if path=='calendar/subscription' and request.method=='POST':
            if engine.CFG['calendar_method']!='subscribe': return jsonify(error='请先选择 Apple 或 Outlook 日历并点击连接。'),400
            return jsonify(url=store.create_calendar_feed(g.auth['user_id'],origin))
        if path=='calendar/approve' and request.method=='POST':
            if engine.CFG['calendar_method']!='subscribe': return jsonify(error='请先连接日历。'),400
            d=request.get_json()
            with engine.RUNTIME.request_lock:
                if not store.calendar_feed(g.auth['user_id'],origin): return jsonify(error='请先建立日历订阅链接。'),400
                try:
                    if engine.join_guard(d):return jsonify(ok=True)
                    engine.export_calendar_event(d)
                    with engine.db() as c:
                        result=json.loads(c.execute('SELECT result FROM mails WHERE id=?',(d['id'],)).fetchone()['result'])
                    event=result['events'][d['index']]
                    engine.manage_event({'id':d['id'],'index':d['index'],'action':'edit','fields':{'title':d['title'],'action':event.get('action',''),'start':d['start'],'end':d['end'],'location':d.get('location',''),'allDay':d.get('allDay') is True}})
                    with engine.db() as c:
                        c.execute('INSERT OR REPLACE INTO calendar_events (mail_id,event_index,status,event_id,calendar_name,detail,created) VALUES (?,?,?,?,?,?,?)',
                                  (d['id'],d['index'],'subscribed',None,'邮件助手',json.dumps(d,ensure_ascii=False),time.time()))
                    with engine.db() as c:c.execute("UPDATE event_overrides SET state='active' WHERE mail_id=? AND event_index=?",(d['id'],d['index']))
                except (KeyError,ValueError,TypeError): return jsonify(error='请核对日程标题和起止时间。'),400
            return jsonify(ok=True)
        if path=='calendar/cancel' and request.method=='POST':
            d=request.get_json(); ident=d.get('id'); index=d.get('index')
            if not isinstance(ident,str) or not ident or not isinstance(index,int) or isinstance(index,bool):
                return jsonify(error='日程编号无效。'),400
            with engine.RUNTIME.request_lock:
                with engine.db() as c:
                    ident,index=engine.event_join.resolve(c,ident,index)
                    cursor=c.execute("UPDATE calendar_events SET status='removed' WHERE mail_id=? AND event_index=? AND status='subscribed'",(ident,index))
                    if cursor.rowcount!=1: return jsonify(error='没有找到已同步的这条日程。'),400
                    engine.event_join.unlink_removed(c,ident,index)
            return jsonify(ok=True)
        class Adapter(engine.APIHandler):
            def __init__(self):
                self.path='/api/'+path; self.data=request.get_json(silent=True); self.query=request.args
            def reply(self,code,data,ctype='application/json; charset=utf-8'):
                # The core handler already serializes intentional errors by type.
                # Never decide visibility by matching translated message text.
                if code==200 and self.path=='/api/state':
                    data['calendarSubscriptionSupported']=True
                    data['calendarSubscriptionUrl']=store.calendar_feed(g.auth['user_id'],origin)
                self.result=make_response(jsonify(data),code)
        handler=Adapter()
        with engine.RUNTIME.request_lock:
            if request.method=='GET': handler.get()
            else: handler.post()
        return handler.result
    app.dummy_hash=generate_password_hash(secrets.token_urlsafe(32),method='scrypt')
    return app

def settings():
    railway=bool(os.environ.get('RAILWAY_ENVIRONMENT_ID'))
    mount=os.environ.get('RAILWAY_VOLUME_MOUNT_PATH','')
    directory=Path(os.environ.get('MAIL_DATA_DIR') or mount or ROOT/'cloud-data')
    key=os.environ.get('MAIL_MASTER_KEY','')
    domain=os.environ.get('RAILWAY_PUBLIC_DOMAIN','')
    origin=os.environ.get('MAIL_ORIGIN') or ('https://'+domain if railway and domain else 'http://127.0.0.1:18744')
    if not key: raise ValueError('缺少 MAIL_MASTER_KEY。请按多人版说明配置独立加密密钥。')
    if railway:
        if not mount or directory.resolve()!=Path(mount).resolve():
            raise ValueError('Railway 必须挂载持久化 Volume；数据目录须使用其挂载路径。')
        if not os.environ.get('MAIL_ORIGIN') and not domain:
            raise ValueError('请先在 Railway 生成公网域名，或设置 MAIL_ORIGIN。')
        if urlsplit(origin).scheme!='https':
            raise ValueError('Railway 必须设置 HTTPS 公网地址。')
    return directory,key,origin

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['serve','reset']);parser.add_argument('--email'); args=parser.parse_args()
    directory,key,origin=settings(); app=create_app(directory,key,origin)
    if args.command!='serve':
        if not args.email: parser.error('需要 --email')
        print(app.store.reset(args.email))
    else:
        # An OS lock rejects a second process sharing this data directory.
        import fcntl
        lock=(directory/'server.lock').open('w'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def scheduler():
            while True:
                app.store.tick(); time.sleep(60)
        threading.Thread(target=scheduler,daemon=True).start()
        from waitress import serve
        print('多人版已启动：'+origin,flush=True)
        serve(app,host=os.environ.get('MAIL_BIND','0.0.0.0' if os.environ.get('RAILWAY_ENVIRONMENT_ID') else '127.0.0.1'),port=int(os.environ.get('PORT','18744')),threads=12)


if __name__ == '__main__':
    main()
