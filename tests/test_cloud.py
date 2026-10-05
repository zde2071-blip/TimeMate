import json,os,re,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from cloud import create_app,settings,invitation_link
from urllib.parse import urlsplit,parse_qs

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
 def test_invitation_link_registration_and_expiry(self):
  email='friend+class@example.com';token=self.app.store.invite(email)
  link=invitation_link('http://127.0.0.1:18744',email,token)
  parts=urlsplit(link);params=parse_qs(parts.fragment)
  self.assertEqual(parts.query,'');self.assertEqual(params['email'],[email])
  self.assertEqual(self.anon.get(parts.path).status_code,200)
  payload={'email':params['email'][0],'invite':params['invite'][0],'password':'12345678'}
  self.assertEqual(self.post(self.anon,'/api/auth/register',payload).status_code,200)
  self.assertEqual(self.post(self.anon,'/api/auth/register',payload).status_code,400)
  expired=self.app.store.invite('expired@example.com')
  with self.app.store.db() as c:c.execute("UPDATE invites SET expires=0 WHERE email=?",('expired@example.com',))
  self.assertEqual(self.post(self.anon,'/api/auth/register',{'email':'expired@example.com','invite':expired,'password':'12345678'}).status_code,400)
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
 def test_cloud_translation_forwards_max_tokens_keyword(self):
  engine=self.app.store.engine(self.ua)
  engine.CFG.update(provider='deepseek',base='https://api.deepseek.com',model='deepseek-flash',key='test-key')
  with engine.db() as c:
   c.execute('INSERT INTO mails (id,subject,sender,date,body,created,source) VALUES (?,?,?,?,?,?,?)',
             ('translate-cloud','School notice','school@xjtlu.edu.cn','2026-10-05','Please register by Friday.',time.time(),'manual'))
  expected={'subject':'学校通知','translation':'请在周五前注册。'}
  with patch('cloud.ai_services.complete',return_value=expected) as complete:
   result=engine.translate_source('translate-cloud')
  self.assertEqual(result['translation'],expected['translation'])
  self.assertIn('max_tokens',complete.call_args.kwargs)
 def test_mail_read_and_delete_are_persistent_and_account_scoped(self):
  e=self.app.store.engine(self.ua)
  with e.db() as c:
   c.execute('INSERT INTO mails(id,subject,sender,date,body,result,created) VALUES (?,?,?,?,?,?,?)',('mail-1','测试邮件','school@example.com','2026-10-05','body',json.dumps({'events':[]}),time.time()))
   c.execute('INSERT INTO pins VALUES (?,?,?,?,?)',('mail-1',0,'截止项','2026-10-10','active'))
   c.execute('INSERT INTO calendar_events (mail_id,event_index,status,event_id,calendar_name,detail,created) VALUES (?,?,?,?,?,?,?)',('mail-1',0,'subscribed',None,'邮件助手','{}',time.time()))
  state=self.state(self.a,self.ta).json
  self.assertEqual(state['mails'][0]['is_read'],0)
  self.assertEqual(self.post(self.a,'/api/mail',{'id':'mail-1','action':'read'},self.ta).status_code,200)
  self.assertEqual(self.state(self.a,self.ta).json['mails'][0]['is_read'],1)
  self.assertEqual(self.post(self.a,'/api/mail',{'id':'mail-1','action':'unread'},self.ta).status_code,200)
  self.assertEqual(self.state(self.a,self.ta).json['mails'][0]['is_read'],0)
  self.assertEqual(self.post(self.b,'/api/mail',{'id':'mail-1','action':'delete'},self.tb).status_code,400)
  self.assertEqual(self.post(self.a,'/api/mail',{'id':'mail-1','action':'delete'},self.ta).status_code,200)
  deleted=self.state(self.a,self.ta).json
  self.assertEqual(deleted['mails'],[])
  self.assertEqual(deleted['pins'],[])
  self.assertEqual(len(deleted['calendarEvents']),1)
  self.assertEqual(self.state(self.b,self.tb).json['mails'],[])
  with e.db() as c:self.assertEqual(c.execute('SELECT is_deleted FROM mails WHERE id=?',('mail-1',)).fetchone()[0],1)

 def test_deadline_pin_can_be_removed_and_added_again(self):
  e=self.app.store.engine(self.ua)
  result={'events':[{'title':'提交材料','start':'2026-10-10T00:00:00','kind':'截止'}]}
  with e.db() as c:
   c.execute('INSERT INTO mails(id,subject,sender,date,body,result,created) VALUES (?,?,?,?,?,?,?)',('deadline-mail','截止通知','school@example.com','2026-10-05','body',json.dumps(result),time.time()))
   c.execute('INSERT INTO pins VALUES (?,?,?,?,?)',('deadline-mail',0,'提交材料','2026-10-10','active'))
  self.assertEqual(self.post(self.a,'/api/pin',{'id':'deadline-mail','index':0,'action':'remove'},self.ta).status_code,200)
  with e.db() as c:self.assertEqual(c.execute('SELECT state FROM pins WHERE mail_id=? AND event_index=0',('deadline-mail',)).fetchone()[0],'removed')
  self.assertEqual(self.post(self.a,'/api/pin',{'id':'deadline-mail','index':0,'action':'pin'},self.ta).status_code,200)
  with e.db() as c:self.assertEqual(c.execute('SELECT state FROM pins WHERE mail_id=? AND event_index=0',('deadline-mail',)).fetchone()[0],'active')

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
 def test_personal_calendar_subscription_only_contains_approved_events(self):
  a=self.app.store.engine(self.ua)
  with a.db() as c:
   c.execute('INSERT INTO mails(id,subject,sender,date,body,result,created) VALUES (?,?,?,?,?,?,?)',
             ('one','课程会议','school@example.com','2026-10-05','邮件正文',json.dumps({'events':[{'title':'课程会议','start':'2026-10-10T10:00:00','end':'2026-10-10T11:00:00','location':'教室','kind':'活动'}]}),time.time()))
  self.assertEqual(self.post(self.a,'/api/calendar/settings',{'calendar_method':'subscribe'},self.ta).status_code,200)
  response=self.post(self.a,'/api/calendar/subscription',{},self.ta)
  self.assertEqual(response.status_code,200);url=response.json['url'];path=url.removeprefix('http://127.0.0.1:18744')
  self.assertNotIn('课程会议',self.anon.get(path).text)
  reviewed={'id':'one','index':0,'title':'课程会议','start':'2026-10-10T10:00:00','end':'2026-10-10T11:00:00','location':'教室','allDay':False,'timeZone':'Asia/Shanghai'}
  self.assertEqual(self.post(self.a,'/api/calendar/approve',reviewed,self.ta).status_code,200)
  feed=self.anon.get(path)
  self.assertEqual(feed.status_code,200);self.assertIn('课程会议',feed.text);self.assertIn('DTSTART:20261010T020000Z',feed.text)
  self.assertNotIn('邮件正文',feed.text)
  self.assertEqual(self.post(self.b,'/api/calendar/cancel',{'id':'one','index':0},self.tb).status_code,400)
  self.assertEqual(self.post(self.a,'/api/calendar/cancel',{'id':'one','index':0},self.ta).status_code,200)
  self.assertNotIn('课程会议',self.anon.get(path).text)
  self.assertEqual(self.post(self.a,'/api/calendar/approve',reviewed,self.ta).status_code,200)
  self.assertIn('课程会议',self.anon.get(path).text)
  self.assertEqual(self.post(self.b,'/api/calendar/approve',reviewed,self.tb).status_code,400)
  self.assertIsNone(self.state(self.b,self.tb).json['calendarSubscriptionUrl'])
  b=self.app.store.engine(self.ub)
  with b.db() as c:
   c.execute('INSERT INTO mails(id,subject,sender,date,body,result,created) VALUES (?,?,?,?,?,?,?)',
             ('two','另一位同学的日程','school@example.com','2026-10-05','私人正文',json.dumps({'events':[{'title':'另一位同学的日程','start':'2026-10-12T10:00:00','end':'2026-10-12T11:00:00','location':'教室','kind':'活动'}]}),time.time()))
  self.assertEqual(self.post(self.b,'/api/calendar/settings',{'calendar_method':'subscribe'},self.tb).status_code,200)
  b_url=self.post(self.b,'/api/calendar/subscription',{},self.tb).json['url']
  self.assertNotEqual(url,b_url)
  self.assertEqual(self.post(self.b,'/api/calendar/approve',{**reviewed,'id':'two','title':'另一位同学的日程'},self.tb).status_code,200)
  self.assertIn('另一位同学的日程',self.anon.get(b_url.removeprefix('http://127.0.0.1:18744')).text)
  self.assertNotIn('另一位同学的日程',self.anon.get(path).text)
  self.assertNotIn('课程会议',self.anon.get(b_url.removeprefix('http://127.0.0.1:18744')).text)
  self.assertEqual(self.anon.get('/calendar/invalid.ics').status_code,404)
  restarted=create_app(self.tmp.name,self.key)
  restarted.config['SERVER_NAME']='127.0.0.1:18744'
  self.assertIn('课程会议',restarted.test_client().get(path).text)
 def test_calendar_provider_and_user_confirmation_persist(self):
  self.assertEqual(self.post(self.a,'/api/calendar/settings',{'calendar_method':'subscribe','calendar_provider':'apple'},self.ta).status_code,200)
  self.assertEqual(self.state(self.a,self.ta).json['config']['calendar_subscription_confirmed'],'no')
  self.post(self.a,'/api/calendar/subscription',{},self.ta)
  self.assertEqual(self.post(self.a,'/api/calendar/settings',{'calendar_method':'subscribe','calendar_provider':'apple','calendar_subscription_confirmed':'yes'},self.ta).status_code,200)
  restarted=create_app(self.tmp.name,self.key)
  self.assertEqual(restarted.store.engine(self.ua).CFG['calendar_subscription_confirmed'],'yes')
  self.assertEqual(self.post(self.a,'/api/calendar/settings',{'calendar_method':'subscribe','calendar_provider':'outlook'},self.ta).status_code,200)
  cfg=self.state(self.a,self.ta).json['config']
  self.assertEqual(cfg['calendar_provider'],'outlook');self.assertEqual(cfg['calendar_subscription_confirmed'],'no')
  self.assertEqual(self.post(self.a,'/api/calendar/settings',{'calendar_method':'subscribe','calendar_provider':'unknown'},self.ta).status_code,400)
  self.assertEqual(self.state(self.a,self.ta).json['config']['calendar_provider'],'outlook')
  self.assertEqual(self.state(self.b,self.tb).json['config']['calendar_provider'],'')
 def test_rate_limit(self):
  for _ in range(10):r=self.post(self.anon,'/api/auth/login',{'email':'absent@example.com','password':'wrong'})
  self.assertEqual(r.status_code,400)
  self.assertEqual(self.post(self.anon,'/api/auth/login',{'email':'absent@example.com','password':'wrong'}).status_code,429)
 def test_cookie_and_host(self):
  self.assertEqual(self.a.get('/',headers={'Host':'evil.example'}).status_code,400)
  response=self.post(self.anon,'/api/auth/login',{'email':'a@example.com','password':'test-password-123'})
  cookie=response.headers['Set-Cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)

class RailwaySettingsTests(unittest.TestCase):
 def test_requires_persistent_volume_and_https_domain(self):
  env={'RAILWAY_ENVIRONMENT_ID':'test','MAIL_MASTER_KEY':Fernet.generate_key().decode()}
  with patch.dict(os.environ,env,clear=True):
   with self.assertRaisesRegex(ValueError,'Volume'):settings()
   os.environ['RAILWAY_VOLUME_MOUNT_PATH']='/data'
   with self.assertRaisesRegex(ValueError,'公网域名'):settings()
   os.environ['RAILWAY_PUBLIC_DOMAIN']='mail.example.up.railway.app'
   directory,key,origin=settings()
   self.assertEqual(directory,Path('/data'))
   self.assertEqual(origin,'https://mail.example.up.railway.app')
   os.environ['MAIL_DATA_DIR']='/temporary'
   with self.assertRaisesRegex(ValueError,'Volume'):settings()
   os.environ['MAIL_DATA_DIR']='/data'
   os.environ['MAIL_ORIGIN']='http://mail.example.up.railway.app'
   with self.assertRaisesRegex(ValueError,'HTTPS'):settings()

if __name__=='__main__':unittest.main()
