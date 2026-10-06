"""Invite-only web gateway. Each authenticated user owns an isolated engine and DB.
Run exactly one application process; its scheduler services all user engines.
"""
import argparse, hashlib, importlib.util, io, json, os, re, secrets, sqlite3, threading, time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from cryptography.fernet import Fernet
from flask import Flask, request, jsonify, redirect, g, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import ai_services

ROOT=Path(__file__).resolve().parent
os.umask(0o077)

def invitation_link(origin,email,token):
    return origin+'/login#'+urlencode({'email':valid_email(email),'invite':token})

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

class PersistentStatus(dict):
    def __init__(self,path):
        self.path=path
        try: enabled=json.loads(path.read_text()).get('auto',False) is True
        except (OSError,ValueError): enabled=False
        super().__init__(busy=False,auto=enabled,message='自动分析已恢复。' if enabled else '尚未开启自动分析。')
    def __setitem__(self,key,value):
        super().__setitem__(key,value)
        if key=='auto':
            temp=self.path.with_suffix('.tmp')
            temp.write_text(json.dumps({'auto':bool(value)})); temp.replace(self.path)

class Runtime:
    def __init__(self,store,uid):
        self.store=store; self.uid=uid
        self.directory=store.directory/'users'/uid
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.status=PersistentStatus(self.directory/'status.json')
        self.request_lock=threading.Lock()
    def credential(self,action,identity,secret=''):
        with self.store.db() as c:
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
            CREATE TABLE IF NOT EXISTS invites(token TEXT PRIMARY KEY,email TEXT NOT NULL,expires REAL NOT NULL,used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS credentials(user_id TEXT,identity TEXT,value BLOB,PRIMARY KEY(user_id,identity));
            CREATE TABLE IF NOT EXISTS resets(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS calendar_feeds(user_id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,token BLOB NOT NULL);
            ''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.directory/'accounts.db',timeout=15); c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    def invite(self,email):
        email=valid_email(email); token=secrets.token_urlsafe(24)
        with self.db() as c: c.execute('INSERT INTO invites(token,email,expires) VALUES (?,?,?)',(digest(token),email,time.time()+7*86400))
        return token
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
                spec=importlib.util.spec_from_file_location('mail_user_'+uid,ROOT/'app.py')
                engine=importlib.util.module_from_spec(spec); engine._runtime=runtime
                spec.loader.exec_module(engine)
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
                if engine.STATUS['auto'] and not engine.STATUS['busy']: engine.job(engine.process_new)
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

def create_app(directory,key,origin='http://127.0.0.1:18744'):
    url=urlsplit(origin)
    if url.scheme not in ('http','https') or not url.netloc or url.path or url.query or url.fragment: raise ValueError('请设置完整站点来源地址')
    if url.scheme!='https' and url.hostname not in ('localhost','127.0.0.1'): raise ValueError('公网必须使用 HTTPS')
    store=Store(directory,key)
    app=Flask(__name__); app.store=store
    app.config.update(MAX_CONTENT_LENGTH=20000,TRUSTED_HOSTS=[url.hostname])
    secure=url.scheme=='https'
    @app.before_request
    def guard():
        g.auth=None
        token=request.cookies.get('mail_session','')
        with store.db() as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            if token: g.auth=c.execute('SELECT * FROM sessions WHERE token=?',(digest(token),)).fetchone()
        if request.method=='POST':
            if request.headers.get('Origin')!=origin: return jsonify(error='页面来源不匹配，请重新打开。'),403
            if not request.is_json: return jsonify(error='请求格式不正确。'),415
        if request.path.startswith('/api/') and not (request.path.startswith('/api/auth/') and request.method=='POST'):
            if not g.auth: return jsonify(error='请先登录。'),401
            if not secrets.compare_digest(request.headers.get('X-Token',''),g.auth['csrf']): return jsonify(error='请刷新页面。'),403
        if request.path in ('/api/auth/logout','/api/auth/password'):
            if not g.auth or not secrets.compare_digest(request.headers.get('X-Token',''),g.auth['csrf']): return jsonify(error='请刷新后重试。'),403
    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data: https:; frame-src 'self' about:; frame-ancestors 'none'; form-action 'self'"})
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
    def login_page(): return (ROOT/'login.html').read_text()
    @app.get('/')
    def index():
        if not g.auth: return redirect('/login')
        return (ROOT/'index.html').read_text().replace('__TOKEN__',g.auth['csrf'])
    @app.get('/styles.css')
    def stylesheet():
        response=make_response((ROOT/'styles.css').read_text())
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
            if action in ('register','login'):
                address=valid_email(d.get('email',''))
                if store.limited('account:'+address): return jsonify(error='操作过于频繁，请 15 分钟后重试。'),429
                if action=='register':
                    hashed=password_hash(d.get('password')); uid=secrets.token_hex(16)
                    with store.db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        invite=c.execute('SELECT * FROM invites WHERE token=? AND email=? AND used=0 AND expires>?',(digest(str(d.get('invite',''))),address,time.time())).fetchone()
                        if not invite: raise ValueError('邀请链接无效、已过期、已使用或与邮箱不匹配，请联系管理员重新邀请。')
                        c.execute('INSERT INTO users VALUES (?,?,?)',(uid,address,hashed))
                        c.execute('UPDATE invites SET used=1 WHERE token=?',(invite['token'],))
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
                with store.db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    row=c.execute('SELECT * FROM resets WHERE token=? AND expires>?',(digest(str(d.get('reset',''))),time.time())).fetchone()
                    if not row: raise ValueError('重置码无效或已过期。')
                    c.execute('UPDATE users SET password=? WHERE id=?',(hashed,row['user_id']))
                    c.execute('DELETE FROM resets WHERE user_id=?',(row['user_id'],))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
                return jsonify(ok=True)
            return jsonify(error='接口不存在。'),404
        except sqlite3.IntegrityError: return jsonify(error='无法注册，请核对账号或登录。'),400
        except ValueError as e: return jsonify(error=str(e)),400
    @app.route('/api/<path:path>',methods=['GET','POST'])
    def api(path):
        engine=store.engine(g.auth['user_id'])
        raw=request.get_data() if request.method=='POST' else b''
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
        class Adapter(engine.Handler):
            def __init__(self):
                self.path='/api/'+path; self.headers={'X-Token':engine.TOKEN,'Content-Length':str(len(raw))}; self.rfile=io.BytesIO(raw)
            def valid_host(self): return True
            def reply(self,code,data,ctype='application/json; charset=utf-8'):
                # The core handler already serializes intentional errors by type.
                # Never decide visibility by matching translated message text.
                if code==200 and self.path=='/api/state':
                    data['calendarSubscriptionSupported']=True
                    data['calendarSubscriptionUrl']=store.calendar_feed(g.auth['user_id'],origin)
                self.result=make_response(jsonify(data),code)
        handler=Adapter()
        with engine.RUNTIME.request_lock:
            if request.method=='GET': handler.do_GET()
            else: handler.do_POST()
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

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['serve','invite','reset']);parser.add_argument('--email'); args=parser.parse_args()
    directory,key,origin=settings(); app=create_app(directory,key,origin)
    if args.command!='serve':
        if not args.email: parser.error('需要 --email')
        print(invitation_link(origin,args.email,app.store.invite(args.email)) if args.command=='invite' else app.store.reset(args.email))
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
