import re
import tempfile
import unittest
from pathlib import Path
from backend.cloud import create_app
from backend.local import load_key

ORIGIN='http://127.0.0.1:18744'

class LocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.key=load_key(Path(self.tmp.name))
        self.app=create_app(self.tmp.name,self.key,local=True)
        self.app.config['SERVER_NAME']='127.0.0.1:18744'
        self.client=self.app.test_client()
        self.page=self.client.get('/').text
        self.token=re.search(r'name="csrf-token" content="([^"]+)"',self.page)[1]
    def tearDown(self): self.tmp.cleanup()
    def test_no_cloud_login_and_only_local_features(self):
        self.assertIn('timemate-local',self.page)
        self.assertNotIn('src="/chat.js"',self.page)
        self.assertNotIn('src="/agents.js"',self.page)
        self.assertNotIn('src="/intake.js"',self.page)
        self.assertEqual(self.client.get('/login').status_code,302)
        result=self.client.get('/api/state',headers={'X-Token':self.token})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json['mails'],[])
        for path in ['/api/chat','/api/chat/conversations','/api/agents','/mcp','/api/auth/register','/api/mail/oauth/start']:
            self.assertEqual(self.client.post(path,json={}).status_code,404,path)
    def test_local_api_still_requires_csrf_and_origin(self):
        self.assertEqual(self.client.get('/api/state').status_code,403)
        self.assertEqual(self.client.post('/api/settings/mail',json={},headers={'X-Token':self.token,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'Host':'evil.example'}).status_code,400)
        with self.assertRaises(ValueError): create_app(self.tmp.name,self.key,'https://example.com',local=True)
    def test_encrypted_settings_survive_restart(self):
        secret='fictional-imap-code'
        result=self.client.post('/api/settings/mail',json={'mailAccountId':'','school_sender':'source@example.edu','account':'receiver@qq.com','mail_provider':'qq','password':secret},headers={'X-Token':self.token,'Origin':ORIGIN})
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn(secret,Path(self.tmp.name,'accounts.db').read_bytes().decode('latin1'))
        self.assertEqual(load_key(Path(self.tmp.name)),self.key)
        restarted=create_app(self.tmp.name,self.key,local=True)
        engine=restarted.store.engine('0'*32)
        self.assertEqual(engine.CFG['school_sender'],'source@example.edu')

if __name__=='__main__': unittest.main()
