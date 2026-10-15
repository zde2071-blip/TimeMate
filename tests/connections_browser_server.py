import os,sys,tempfile,time,secrets
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
from flask import redirect
from werkzeug.serving import make_server
from backend.cloud import create_app,digest,password_hash
from backend.mail import oauth
os.environ['MAIL_GOOGLE_CLIENT_ID']='test-id'
os.environ['MAIL_GOOGLE_CLIENT_SECRET']='test-secret'
def fake_http(url,token=None,form=None,raw=False):
 if form:return {'access_token':'fixture-access','refresh_token':'fixture-refresh','expires_in':3600}
 if '/profile' in url:return {'emailAddress':'student@example.edu'}
 if 'messages' in url:return {'messages':[]}
 raise RuntimeError('Unexpected fixture request')
oauth.http=fake_http
with tempfile.TemporaryDirectory() as directory:
 app=create_app(directory,Fernet.generate_key())
 @app.get('/fixture-login')
 def login():
  uid=secrets.token_hex(16);session=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
  with app.store.db() as c:
   c.execute('INSERT INTO users VALUES (?,?,?)',(uid,uid+'@example.com',password_hash('fixture-password')))
   c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(session),uid,csrf,time.time()+3600))
  engine=app.store.engine(uid)
  engine.ai_services.complete=staticmethod(lambda *args,**kwargs:{'ok':True})
  r=redirect('/#settings');r.set_cookie('mail_session',session,httponly=True,samesite='Lax');return r
 server=make_server('127.0.0.1',0,app,threaded=True)
 origin='http://127.0.0.1:'+str(server.server_port);app.config['MAIL_ALLOWED_ORIGINS']={origin}
 # create_app's canonical redirect is irrelevant to the fixture; callbacks are
 # navigated to the local route explicitly, never to provider services.
 print(origin,flush=True);server.serve_forever()
