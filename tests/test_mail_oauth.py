import base64
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from backend.mail import oauth
from tests import test_cloud as fixture

class OAuthTests(unittest.TestCase):
    setUp=fixture.CloudTests.setUp
    tearDown=fixture.CloudTests.tearDown
    register=fixture.CloudTests.register
    post=fixture.CloudTests.post
    state=fixture.CloudTests.state

    def start(self, client=None, token=None, provider='google'):
        with patch.dict('os.environ',{'MAIL_'+provider.upper()+'_CLIENT_ID':'fixture-id','MAIL_'+provider.upper()+'_CLIENT_SECRET':'fixture-secret'}):
            response=self.post(client or self.a,'/api/mail/oauth/start',{'provider':provider},token or self.ta)
        self.assertEqual(response.status_code,200,response.json)
        params=parse_qs(urlsplit(response.json['url']).query)
        self.assertEqual(params['code_challenge_method'],['S256'])
        return params['state'][0]

    def callback(self, nonce, provider='google', client=None, **query):
        return (client or self.a).get('/oauth/mail/'+provider+'/callback',query_string={'state':nonce,**query})

    def finish(self, nonce, provider='google'):
        with patch.object(oauth,'credentials',return_value=('fixture-id','fixture-secret')), patch.object(oauth,'http',return_value={'access_token':'secret-access','refresh_token':'secret-refresh','expires_in':3600}), patch.object(oauth,'verify',return_value='school@example.edu') as verify:
            response=self.callback(nonce,provider,code='authorization-code')
        self.assertIn('mail_connection=success',response.location)
        verify.assert_called_once_with(provider,'secret-access')

    def test_unconfigured_is_not_institutional_block_and_requires_csrf(self):
        with patch.object(oauth,'credentials',return_value=('','')):
            r=self.post(self.a,'/api/mail/oauth/start',{'provider':'google'},self.ta)
        self.assertEqual(r.status_code,503);self.assertEqual(r.json['kind'],'unavailable')
        self.assertEqual(self.post(self.a,'/api/mail/oauth/start',{'provider':'google'},'wrong').status_code,403)

    def test_state_is_session_bound_single_use_and_expires(self):
        nonce=self.start()
        self.assertIn('mail_connection=invalid',self.callback(nonce,client=self.b,error='access_denied').location)
        self.assertIn('mail_connection=cancel',self.callback(nonce,error='access_denied').location)
        self.assertIn('mail_connection=invalid',self.callback(nonce,error='access_denied').location)
        nonce=self.start()
        with self.app.store.db() as c:c.execute('UPDATE mailbox_oauth_attempts SET expires=0')
        self.assertIn('mail_connection=invalid',self.callback(nonce,code='expired').location)

    def test_read_verified_before_ready_and_secrets_encrypted_isolated(self):
        nonce=self.start();self.finish(nonce)
        d=self.state(self.a,self.ta).json
        self.assertTrue(d['ready']['mail']);self.assertEqual(d['mailConnection']['account'],'school@example.edu')
        self.assertFalse(self.state(self.b,self.tb).json['ready']['mail'])
        self.assertNotIn('secret-access',json.dumps(d));self.assertNotIn('secret-refresh',json.dumps(d))
        engine=self.app.store.engine(self.ua)
        self.assertNotIn('secret-',engine.PREFS.read_text())
        with self.app.store.db() as c:
            blob=c.execute("SELECT value FROM credentials WHERE user_id=? AND identity='mail-oauth:google'",(self.ua,)).fetchone()[0]
        self.assertNotIn(b'secret-refresh',blob)
        self.assertIn('mail_connection=invalid',self.callback(nonce,code='replay').location)

    def test_read_denial_preserves_existing_connection(self):
        nonce=self.start();self.finish(nonce)
        nonce=self.start(provider='microsoft')
        with patch.object(oauth,'credentials',return_value=('id','secret')),patch.object(oauth,'http',return_value={'access_token':'x','refresh_token':'y'}),patch.object(oauth,'verify',side_effect=oauth.OAuthError('permission')):
            response=self.callback(nonce,'microsoft',code='code')
        self.assertIn('mail_connection=permission',response.location)
        self.assertEqual(self.state(self.a,self.ta).json['mailConnection']['provider'],'google')

    def test_network_cancel_and_admin_have_distinct_results(self):
        self.assertEqual(oauth.remote_error({'error':'access_denied'}),'cancel')
        self.assertEqual(oauth.remote_error({'error':'access_denied','error_description':'AADSTS65004 user declined'}),'cancel')
        self.assertEqual(oauth.remote_error({'error':'admin_policy_enforced'}),'admin')
        self.assertEqual(oauth.remote_error({'error':'access_denied','error_description':'AADSTS53003'}),'blocked')
        self.assertEqual(oauth.remote_error({'error':'temporarily_unavailable'}),'network')
        self.assertEqual(oauth.remote_error({'error':'invalid_client'}),'unavailable')

    def test_refresh_rotation_and_revocation_need_only_mail_reauthorization(self):
        self.finish(self.start());engine=self.app.store.engine(self.ua)
        data=oauth.load(engine.RUNTIME,'google');data['expires_at']=0;oauth.save(engine.RUNTIME,'google',data)
        with patch.object(oauth,'credentials',return_value=('id','secret')),patch.object(oauth,'http',return_value={'access_token':'new-access','refresh_token':'new-refresh','expires_in':3600}):
            self.assertEqual(oauth.access(engine),'new-access')
        self.assertEqual(oauth.load(engine.RUNTIME,'google')['refresh_token'],'new-refresh')
        data=oauth.load(engine.RUNTIME,'google');data['expires_at']=0;oauth.save(engine.RUNTIME,'google',data)
        with patch.object(oauth,'credentials',return_value=('id','secret')),patch.object(oauth,'http',side_effect=oauth.OAuthError('expired')):
            with self.assertRaises(oauth.MailAuthenticationError):oauth.access(engine)
        state=self.state(self.a,self.ta).json
        self.assertFalse(state['ready']['mail']);self.assertTrue(state['mailConnection']['reauthorize'])

    def test_pagination_never_sends_token_to_arbitrary_hosts(self):
        with patch.object(oauth,'http') as http:
            with self.assertRaises(oauth.OAuthError):oauth.api('microsoft','https://attacker.example/page','secret')
            http.assert_not_called()

    def test_microsoft_callback_and_malformed_start(self):
        self.finish(self.start(provider='microsoft'),provider='microsoft')
        state=self.state(self.a,self.ta).json
        self.assertTrue(state['ready']['mail'])
        self.assertEqual(state['mailConnection']['provider'],'microsoft')
        for data in [[],{'provider':{}},{'provider':'unknown'}]:
            response=self.post(self.a,'/api/mail/oauth/start',data,self.ta)
            self.assertEqual(response.status_code,400)

    def test_verify_checks_message_reading(self):
        with patch.object(oauth,'api',side_effect=[{'emailAddress':'school@example.edu'},{'messages':[{'id':'one'}]},{'raw':'eA=='}]) as api:
            self.assertEqual(oauth.verify('google','token'),'school@example.edu')
            self.assertIn('?format=raw',api.call_args.args[1])
        with patch.object(oauth,'api',side_effect=[{'mail':'school@example.edu'},{'value':[{'id':'one'}]},b'mime']) as api:
            self.assertEqual(oauth.verify('microsoft','token'),'school@example.edu')
            self.assertTrue(api.call_args.kwargs['raw'])

    def test_direct_import_keeps_checkpoint_on_failure_and_deduplicates(self):
        self.finish(self.start());engine=self.app.store.engine(self.ua)
        raw=b'From: Teacher <teacher@example.edu>\r\nSubject: Exam\r\nDate: Thu, 15 Oct 2026 09:00:00 +0800\r\n\r\nExam tomorrow'
        encoded=base64.urlsafe_b64encode(raw).decode()
        def responses(provider,path,token,**kwargs):
            if 'format=raw' in path:return {'raw':encoded}
            if 'pageToken=next' in path:return {'messages':[{'id':'old'}]}
            return {'messages':[{'id':'old'}]}
        with patch.object(oauth,'api',side_effect=responses),patch.object(engine,'analyze_pending',return_value=(0,0)):
            engine.fetch_mail();engine.fetch_mail()
        with engine.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM mails').fetchone()[0],1)
        def failed(provider,path,token,**kwargs):
            if 'format=raw' in path:raise oauth.OAuthError('network')
            return {'messages':[{'id':'new'}],'nextPageToken':'next'} if 'pageToken=next' not in path else {'messages':[{'id':'old'}]}
        with patch.object(oauth,'api',side_effect=failed),patch.object(engine,'analyze_pending',return_value=(0,0)):
            engine.fetch_mail()
        with engine.db() as c:self.assertEqual(c.execute('SELECT marker FROM oauth_checkpoints').fetchone()[0],'old')
        self.assertEqual(engine.STATUS['sync_error_code'],'mail_sync_failed')

if __name__=='__main__':unittest.main()
