import json,re,tempfile,time,unittest
from pathlib import Path
from cryptography.fernet import Fernet
from cloud import create_app

class CloudTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.key=Fernet.generate_key();self.app=create_app(self.tmp.name,self.key);self.app.testing=True;self.app.config["SERVER_NAME"]="127.0.0.1:18744"
  self.a=self.app.test_client();self.b=self.app.test_client();self.anon=self.app.test_client()
  self.ta,self.ua=self.register(self.a,'a@example.com');self.tb,self.ub=self.register(self.b,'b@example.com')
 def tearDown(self):self.tmp.cleanup()
 def post(self,c,path,data,token=''):
  return c.post(path,json=data,headers={'Origin':'http://127.0.0.1:18744','X-Token':token})
 def register(self,c,address):
  code=self.app.store.invite(address)
  r=self.post(c,'/api/auth/register',{'email':address,'password':'test-password-123','invite':code});self.assertEqual(r.status_code,200)
  page=c.get('/').text; token=re.search("const token='([^']+)'",page)[1]
  with self.app.store.db() as db:uid=db.execute('SELECT id FROM users WHERE email=?',(address,)).fetchone()[0]
  return token,uid
 def state(self,c,t):return c.get('/api/state',headers={'X-Token':t})
 def test_auth_csrf_invite_logout(self):
  self.assertEqual(self.anon.get('/').status_code,302);self.assertEqual(self.state(self.anon,'').status_code,401)
  self.assertEqual(self.post(self.b,'/api/pin',{},self.ta).status_code,403)
  self.assertEqual(self.a.post('/api/auto',json={},headers={'X-Token':self.ta}).status_code,403)
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'x@example.com','password':'test-password-123','invite':'invalid'}).status_code,400)
  self.assertEqual(self.post(self.a,'/api/auth/logout',{},self.ta).status_code,200)
  self.assertEqual(self.state(self.a,self.ta).status_code,401)
 def test_mail_pins_and_secrets_isolated(self):
  a=self.app.store.engine(self.ua);b=self.app.store.engine(self.ub)
  self.assertNotEqual(a.DB,b.DB);self.assertIsNot(a.CFG,b.CFG);self.assertIsNot(a.LOCK,b.LOCK)
  with a.db() as c:
   c.execute('INSERT INTO mails(id,subject,sender,date,body,created,original) VALUES (?,?,?,?,?,?,?)',('private-a','secret subject','a@school.edu','2026-10-05','private body',time.time(),json.dumps({'html':'private html','external':[]})))
   c.execute('INSERT INTO pins VALUES (?,?,?,?,?)',('private-a',0,'private pin','2026-10-10','active'))
  state=self.state(self.b,self.tb);self.assertEqual(state.json['mails'],[]);self.assertEqual(state.json['pins'],[])
  self.assertNotIn('private',self.post(self.b,'/api/source',{'id':'private-a'},self.tb).text)
  self.assertEqual(self.post(self.b,'/api/calendar/export',{'id':'private-a','index':0},self.tb).status_code,400)
  self.post(self.b,'/api/pin',{'id':'private-a','index':0,'action':'remove'},self.tb)
  self.assertEqual(len(self.state(self.a,self.ta).json['pins']),1)
  cfg={'account':'123@qq.com','school_sender':'a@school.edu','password':'private-mail-secret'}
  self.assertEqual(self.post(self.a,'/api/settings/mail',cfg,self.ta).status_code,200)
  self.assertFalse(self.state(self.b,self.tb).json['ready']['mail'])
  self.assertNotIn('private-mail-secret',self.state(self.a,self.ta).text)
  with self.app.store.db() as c:
   blob=c.execute('SELECT value FROM credentials WHERE user_id=?',(self.ua,)).fetchone()[0]
   self.assertNotIn(b'private-mail-secret',blob)
   stored=c.execute('SELECT password FROM users WHERE id=?',(self.ua,)).fetchone()[0]
   self.assertNotEqual(stored,'test-password-123')
 def test_restart_restores_settings_and_cursor(self):
  self.post(self.a,'/api/settings/mail',{'account':'123@qq.com','school_sender':'a@school.edu','password':'secret-value'},self.ta)
  e=self.app.store.engine(self.ua)
  with e.db() as c:c.execute('INSERT INTO cursors VALUES (?,?,?)',('account-hash','validity',42))
  e.STATUS['auto']=True
  restarted=create_app(self.tmp.name,self.key);n=restarted.store.engine(self.ua)
  self.assertTrue(n.STATUS['auto']);self.assertEqual(n.CFG['password'],'secret-value')
  with n.db() as c:self.assertEqual(c.execute('SELECT uid FROM cursors').fetchone()[0],42)
  calls=[];n.process_new=lambda:calls.append('a') or 'done';n.job=lambda f:f()
  restarted.store.tick();self.assertEqual(calls,['a'])
 def test_reset_revokes_sessions_and_is_single_use(self):
  code=self.app.store.reset('a@example.com')
  self.assertEqual(self.post(self.anon,'/api/auth/reset',{'reset':code,'password':'new-password-123'}).status_code,200)
  self.assertEqual(self.state(self.a,self.ta).status_code,401)
  self.assertEqual(self.post(self.anon,'/api/auth/reset',{'reset':code,'password':'another-password'}).status_code,400)
  self.assertEqual(self.post(self.a,'/api/auth/login',{'email':'a@example.com','password':'new-password-123'}).status_code,200)
 def test_provider_cannot_target_internal_address(self):
  for base in ['https://127.0.0.1','https://api.deepseek.com.evil.example','https://api.deepseek.com@evil.example']:
   r=self.post(self.a,'/api/settings/ai',{'provider':'deepseek','base':base,'model':'test','key':'test-key'},self.ta)
   self.assertEqual(r.status_code,400)
 def test_password_change_and_invite_binding(self):
  invite=self.app.store.invite('invited@example.com')
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'wrong@example.com','password':'test-password-123','invite':invite}).status_code,400)
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'invited@example.com','password':'test-password-123','invite':invite}).status_code,200)
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'invited@example.com','password':'test-password-123','invite':invite}).status_code,400)
  self.assertEqual(self.post(self.a,'/api/auth/password',{'old':'test-password-123','password':'changed-password-123'},self.ta).status_code,200)
  self.assertEqual(self.state(self.a,self.ta).status_code,403)
  self.assertEqual(self.post(self.b,'/api/auth/login',{'email':'a@example.com','password':'test-password-123'}).status_code,400)
  self.assertEqual(self.post(self.b,'/api/auth/login',{'email':'a@example.com','password':'changed-password-123'}).status_code,200)
 def test_eight_character_password_applies_to_registration_and_reset(self):
  invite=self.app.store.invite('short@example.com')
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'short@example.com','password':'1234567','invite':invite}).status_code,400)
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'short@example.com','password':'12345678','invite':invite}).status_code,200)
  reset=self.app.store.reset('short@example.com')
  self.assertEqual(self.post(self.anon,'/api/auth/reset',{'reset':reset,'password':'1234567'}).status_code,400)
  self.assertEqual(self.post(self.anon,'/api/auth/reset',{'reset':reset,'password':'abcdefgh'}).status_code,200)
 def test_expired_session_and_secure_cookie(self):
  with self.app.store.db() as c:c.execute('UPDATE sessions SET expires=0 WHERE user_id=?',(self.ua,))
  self.assertEqual(self.state(self.a,self.ta).status_code,401)
  secure=create_app(self.tmp.name,self.key,'https://mail.example.com');secure.config['SERVER_NAME']='mail.example.com'
  c=secure.test_client();response=c.post('/api/auth/login',json={'email':'a@example.com','password':'test-password-123'},headers={'Origin':'https://mail.example.com'},base_url='https://mail.example.com')
  self.assertEqual(response.status_code,200);self.assertIn('Secure',response.headers['Set-Cookie'])
 def test_rate_limit(self):
  for _ in range(10):r=self.post(self.anon,'/api/auth/login',{'email':'absent@example.com','password':'wrong'})
  self.assertEqual(r.status_code,400)
  self.assertEqual(self.post(self.anon,'/api/auth/login',{'email':'absent@example.com','password':'wrong'}).status_code,429)
 def test_cookie_and_host(self):
  self.assertEqual(self.a.get('/',headers={'Host':'evil.example'}).status_code,400)
  response=self.post(self.anon,'/api/auth/login',{'email':'a@example.com','password':'test-password-123'})
  cookie=response.headers['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)

if __name__=='__main__':unittest.main()
