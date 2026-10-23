"""User isolation, OAuth/PKCE, durable feedback, and existing UI mutation coverage."""
import base64
import hashlib
import json
import secrets
import tempfile
import time
import unittest
from urllib.parse import urlencode,urlsplit,parse_qs
from unittest.mock import patch
from cryptography.fernet import Fernet
from backend.cloud import create_app,digest
from backend.agents import auth,transport,changes
from backend.agents.service import EVENT_NAME

ORIGIN='https://timemate.example'

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.key=Fernet.generate_key()
        self.app=create_app(self.tmp.name,self.key,ORIGIN);self.app.testing=True
        self.a,self.b,self.anon=(self.app.test_client() for _ in range(3))
        self.ua,self.ta=self.user(self.a,'a');self.ub,self.tb=self.user(self.b,'b')
        self.ga,self.ka=self.connect(self.a,self.ta)
        self.gb,self.kb=self.connect(self.b,self.tb)

    def tearDown(self): self.tmp.cleanup()

    def user(self,client,name):
        uid=secrets.token_hex(16);session=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        with self.app.store.db() as c:
            c.execute('INSERT INTO users VALUES (?,?,?)',(uid,name+'@example.com','fixture'))
            c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(session),uid,csrf,time.time()+3600))
        client.set_cookie('mail_session',session,domain='timemate.example')
        self.app.store.engine(uid)
        return uid,csrf

    def post(self,client,path,data,csrf):
        return client.post(path,json=data,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Token':csrf})

    def connect(self,client,csrf,edits=False):
        r=self.post(client,'/api/agents/connect',{'provider':'grok','allow_edits':edits},csrf)
        self.assertEqual(r.status_code,200,r.text)
        return r.json['id'],r.json['token']

    def rpc(self,method,params=None,key=None):
        return self.anon.post('/mcp',base_url=ORIGIN,json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}},headers={'Authorization':'Bearer '+(key or self.ka)})

    def call(self,name,args=None,key=None):
        response=self.rpc('tools/call',{'name':name,'arguments':args or {}},key)
        self.assertEqual(response.status_code,200,response.text)
        return response.json['result']

    def imported(self):
        result=self.call('submit_mail',{'external_id':'source@example/message-1','subject':'考试通知','body':'考试将在 11 月 3 日举行。','sent_at':'2026-10-23T12:00:00+08:00','summary':'考试通知'})
        self.assertFalse(result['isError'],result)
        return result['structuredContent']['id']

    def subscribe(self):
        self.secret='whsec_'+base64.b64encode(b'a'*32).decode()
        def verify(url,body,headers):return {'challenge':json.loads(body)['challenge']}
        with patch('backend.agents.transport.post_json',side_effect=verify):
            r=self.rpc('events/subscribe',{'name':EVENT_NAME,'arguments':{},'delivery':{'mode':'webhook','url':'https://callback.example/events','secret':self.secret}})
        self.assertNotIn('error',r.json,r.text)
        return r.json['result']['id']

    def test_requires_bearer_not_cookie_and_scopes_are_server_enforced(self):
        self.assertEqual(self.a.post('/mcp',base_url=ORIGIN,json={}).status_code,401)
        self.assertIn('resource_metadata',self.anon.post('/mcp',base_url=ORIGIN,json={}).headers['WWW-Authenticate'])
        self.assertEqual(self.a.get('/api/agents',base_url=ORIGIN).status_code,403)
        self.assertEqual(self.post(self.a,'/api/agents/connect',{'provider':'grok'},'bad').status_code,403)
        names={t['name'] for t in self.rpc('tools/list').json['result']['tools']}
        self.assertNotIn('update_item',names)
        self.assertTrue(self.call('update_item',{'mail_id':'x','index':0,'version':'x','action':'remove'})['isError'])
        self.assertNotIn('credentials',str(self.rpc('tools/list').json))
        blocked=self.anon.post('/mcp',base_url=ORIGIN,json={'jsonrpc':'2.0','id':1,'method':'ping'},headers={'Authorization':'Bearer '+self.ka,'Origin':'https://evil.example'})
        self.assertEqual(blocked.status_code,403)

    def test_mail_isolation_idempotency_and_durable_changes(self):
        ident=self.imported()
        first=changes.latest(self.app.store.engine(self.ua))
        self.assertEqual(ident,self.imported())
        self.assertEqual(first,changes.latest(self.app.store.engine(self.ua)))
        self.assertTrue(self.call('read_mail',{'id':ident},self.kb)['isError'])
        self.assertEqual(self.call('search_mail',{},self.kb)['structuredContent']['total'],0)
        self.assertEqual(self.call('search_mail')['structuredContent']['total'],1)
        r=self.call('read_mail',{'id':ident})['structuredContent']
        self.assertEqual(r['text'],'考试将在 11 月 3 日举行。')
        engine=self.app.store.engine(self.ua)
        self.assertEqual(self.post(self.a,'/api/mail',{'id':ident,'action':'read'},self.ta).status_code,200)
        log=self.call('read_changes',{'cursor':first})['structuredContent']
        self.assertEqual(log['changes'][0]['record_id'],ident)
        self.assertNotIn('body',str(log))
        restarted=create_app(self.tmp.name,self.key,ORIGIN)
        self.assertEqual(changes.latest(restarted.store.engine(self.ua)),log['cursor'])

    def test_transaction_rollback_does_not_emit_notification(self):
        ident=self.imported();engine=self.app.store.engine(self.ua);before=changes.latest(engine)
        try:
            with engine.db() as c:
                c.execute('UPDATE mails SET is_read=1 WHERE id=?',(ident,))
                raise RuntimeError('rollback')
        except RuntimeError:pass
        self.assertEqual(changes.latest(engine),before)

    def test_notice_verification_retry_and_ack_are_account_scoped(self):
        sid=self.subscribe();self.imported()
        with patch('backend.agents.transport.post_json',side_effect=OSError('secret server address')):
            self.app.agents.tick()
        with self.app.store.db() as c:
            row=c.execute('SELECT * FROM agent_subscriptions WHERE id=?',(sid,)).fetchone()
            pending=json.loads(row['pending']);self.assertEqual(row['attempts'],1)
            self.assertNotIn('secret',row['last_error'])
            c.execute('UPDATE agent_subscriptions SET retry_at=0 WHERE id=?',(sid,))
        restarted=create_app(self.tmp.name,self.key,ORIGIN)
        with patch('backend.agents.transport.post_json',return_value={}) as sender:
            restarted.agents.tick()
        event=json.loads(sender.call_args.args[1]);headers=sender.call_args.args[2]
        self.assertEqual(event['eventId'],pending['event']['eventId'])
        self.assertIn('webhook-signature',headers)
        self.assertTrue(self.call('acknowledge_feedback',{'event_id':event['eventId']},self.kb)['isError'])
        self.assertFalse(self.call('acknowledge_feedback',{'event_id':event['eventId']})['isError'])
        with self.app.store.db() as c:
            row=c.execute('SELECT * FROM agent_subscriptions WHERE id=?',(sid,)).fetchone()
            self.assertIsNone(row['pending']);self.assertIsNotNone(row['last_delivery']);self.assertIsNotNone(row['last_ack'])
        self.assertEqual(self.call('read_changes',{},self.kb)['structuredContent']['changes'],[])

    def test_failed_verification_never_subscribes(self):
        with patch('backend.agents.transport.post_json',return_value={'challenge':'wrong'}):
            r=self.rpc('events/subscribe',{'name':EVENT_NAME,'delivery':{'mode':'webhook','url':'https://callback.example/events','secret':'whsec_'+base64.b64encode(b'a'*32).decode()}})
        self.assertIn('error',r.json)
        with self.app.store.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM agent_subscriptions').fetchone()[0],0)

    def test_grok_registration_does_not_start_run_until_test(self):
        with patch('backend.agents.transport.public_addresses',return_value=['8.8.8.8']),patch('backend.agents.transport.post_json') as sender:
            r=self.post(self.a,'/api/agents/feedback',{'id':self.ga,'url':'https://api2.cursor.sh/automations/webhook/test','key':'secret-test-key'},self.ta)
            self.assertEqual(r.status_code,200,r.text);sid=r.json['id'];sender.assert_not_called()
            self.app.agents.tick();sender.assert_not_called()
            sender.return_value={}
            self.assertEqual(self.post(self.a,'/api/agents/test',{'id':sid},self.ta).status_code,200)
            self.assertTrue(json.loads(sender.call_args.args[1])['data']['test'])
            self.assertEqual(sender.call_args.args[2],{'Authorization':'Bearer secret-test-key'})
        self.assertEqual(self.post(self.b,'/api/agents/test',{'id':sid},self.tb).status_code,400)
        with self.app.store.db() as c:
            secret=c.execute('SELECT secret FROM agent_subscriptions WHERE id=?',(sid,)).fetchone()[0]
        self.assertNotIn(b'secret-test-key',secret)

    def test_replacing_grok_callback_pauses_old_delivery_and_requires_new_test(self):
        with patch('backend.agents.transport.public_addresses',return_value=['8.8.8.8']),patch('backend.agents.transport.post_json',return_value={}) as sender:
            def save(suffix):
                return self.post(self.a,'/api/agents/feedback',{'id':self.ga,'url':'https://api2.cursor.sh/automations/webhook/'+suffix,'key':'fixture-key'},self.ta).json['id']
            first=save('first')
            self.post(self.a,'/api/agents/test',{'id':first},self.ta)
            self.assertTrue(sender.called)
            sender.reset_mock()
            second=save('second');self.imported();self.app.agents.tick();sender.assert_not_called()
            status=self.app.agents.feedback_status(self.ga)
            self.assertEqual(len(status),1);self.assertEqual(status[0]['id'],second)
            self.assertFalse(status[0]['enabled']);self.assertIsNone(status[0]['last_delivery'])
            self.assertEqual(self.post(self.a,'/api/agents/test',{'id':first},self.ta).status_code,400)

    def test_revoke_stops_both_directions_and_hides_secrets(self):
        self.subscribe();self.imported()
        page=self.a.get('/api/agents',base_url=ORIGIN,headers={'X-Token':self.ta}).text
        self.assertNotIn(self.ka,page);self.assertNotIn(self.secret,page);self.assertNotIn('callback.example',page)
        self.assertEqual(self.post(self.b,'/api/agents/revoke',{'id':self.ga},self.tb).status_code,400)
        self.assertEqual(self.post(self.a,'/api/agents/revoke',{'id':self.ga},self.ta).status_code,200)
        self.assertEqual(self.rpc('ping').status_code,401)
        with patch('backend.agents.transport.post_json') as sender:self.app.agents.tick();sender.assert_not_called()
        self.assertEqual(self.rpc('ping',key=self.kb).status_code,200)

    def test_public_callback_transport_blocks_private_redirects_and_dns_rebinding(self):
        for url in ('http://example.com','https://user:pass@example.com','https://example.com:22','https://example.com/#x','https://example.com/\r\n'):
            with self.assertRaises(ValueError):transport.checked_url(url)
        for ip in ('127.0.0.1','10.1.1.1','169.254.169.254','::1','::ffff:127.0.0.1'):
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(ip,443))]):
                with self.assertRaises(ValueError):transport.public_addresses('callback.example')
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):transport.public_addresses('mixed.example')
        with patch('backend.agents.transport.public_addresses',return_value=['8.8.8.8']),patch('backend.agents.transport.PinnedHTTPS') as conn:
            conn.return_value.getresponse.return_value.status=302
            conn.return_value.getresponse.return_value.read.return_value=b''
            with self.assertRaises(ValueError):transport.post_json('https://callback.example/events',b'{}',{})
            conn.assert_called_once_with('callback.example','8.8.8.8')

    def oauth_client(self):
        r=self.anon.post('/agent/register',base_url=ORIGIN,json={'client_name':'Fixture Agent','redirect_uris':['https://agent.example/callback']})
        self.assertEqual(r.status_code,201,r.text)
        verifier='a'*43;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        args={'client_id':r.json['client_id'],'redirect_uri':'https://agent.example/callback','response_type':'code',
              'resource':ORIGIN+'/mcp','code_challenge':challenge,'code_challenge_method':'S256','state':'retained','scope':'mail:read changes:read'}
        return args,verifier

    def test_oauth_pkce_redirect_scope_refresh_replay_and_revocation(self):
        args,verifier=self.oauth_client()
        self.assertEqual(self.a.get('/agent/authorize?'+urlencode(args),base_url=ORIGIN).status_code,200)
        self.assertEqual(self.a.get('/agent/authorize?'+urlencode({**args,'redirect_uri':'https://evil.example'}),base_url=ORIGIN).status_code,400)
        r=self.post(self.a,'/api/agents/authorize',{**args,'approve':True},self.ta)
        query=parse_qs(urlsplit(r.json['redirect']).query);self.assertEqual(query['state'],['retained']);self.assertEqual(query['iss'],[ORIGIN])
        data={'grant_type':'authorization_code','code':query['code'][0],'client_id':args['client_id'],'redirect_uri':args['redirect_uri'],'resource':args['resource'],'code_verifier':verifier}
        self.assertEqual(self.anon.post('/agent/token',base_url=ORIGIN,data={**data,'code_verifier':'z'*43}).status_code,400)
        self.assertEqual(self.anon.post('/agent/token',base_url=ORIGIN,data={**data,'resource':'https://evil.example'}).status_code,400)
        r=self.anon.post('/agent/token',base_url=ORIGIN,data=data);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.anon.post('/agent/token',base_url=ORIGIN,data=data).status_code,400)
        access,refresh=r.json['access_token'],r.json['refresh_token']
        self.assertTrue(self.call('submit_mail',{},access)['isError'])
        payload={'grant_type':'refresh_token','client_id':args['client_id'],'resource':ORIGIN+'/mcp','refresh_token':refresh}
        r=self.anon.post('/agent/token',base_url=ORIGIN,data=payload);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.anon.post('/agent/token',base_url=ORIGIN,data=payload).status_code,400)
        self.assertEqual(self.anon.post('/agent/revoke',base_url=ORIGIN,data={'token':r.json['refresh_token'],'client_id':args['client_id']}).status_code,200)
        self.assertEqual(self.rpc('ping',key=access).status_code,401)

    def test_event_edit_uses_existing_validation_and_conflict_check(self):
        ga,key=self.connect(self.a,self.ta,True)
        ident=self.imported();engine=self.app.store.engine(self.ua)
        with engine.db() as c:
            c.execute('UPDATE mails SET result=? WHERE id=?',(json.dumps({'events':[{'kind':'截止','title':'提交报告','start':'2026-11-03T12:00','end':'','action':'提交','location':'','allDay':False}]}),ident))
            c.execute('INSERT INTO pins VALUES (?,?,?,?,?)',(ident,0,'提交报告','2026-11-03T12:00','active'))
        item=self.call('list_items',key=key)['structuredContent']['items'][0]
        result=self.call('update_item',{'mail_id':ident,'index':0,'action':'complete','version':item['version']},key)
        self.assertFalse(result['isError'],result);self.assertEqual(result['structuredContent']['state'],'completed')
        self.assertTrue(self.call('update_item',{'mail_id':ident,'index':0,'action':'restore','version':item['version']},key)['isError'])
        self.assertTrue(self.call('list_items',key=self.kb)['structuredContent']['items']==[])

    def test_account_deletion_cleans_grants_tokens_and_pending_notifications(self):
        self.subscribe();self.imported()
        self.assertTrue(self.app.store.delete_account(self.ua))
        self.assertEqual(self.rpc('ping').status_code,401)
        with self.app.store.db() as c:
            for table in ('agent_grants','agent_codes','agent_subscriptions','agent_deliveries'):
                self.assertFalse(c.execute(f'SELECT 1 FROM {table} WHERE user_id=?',(self.ua,)).fetchone())
        with patch('backend.agents.transport.post_json') as sender:self.app.agents.tick();sender.assert_not_called()

if __name__=='__main__':unittest.main()
