import json
import unittest
from unittest.mock import patch
from tests import test_cloud as cloud_fixture
from backend.cloud import create_app
from cryptography.fernet import Fernet
import tempfile

class AIProfileTests(unittest.TestCase):
    setUp=cloud_fixture.CloudTests.setUp
    tearDown=cloud_fixture.CloudTests.tearDown
    post=cloud_fixture.CloudTests.post
    register=cloud_fixture.CloudTests.register
    state=cloud_fixture.CloudTests.state

    def save(self, name, key='test-profile-key', **extra):
        data={'profileId':'','name':name,'provider':'deepseek','base':'https://api.deepseek.com','model':'model-'+name,'key':key,**extra}
        response=self.post(self.a,'/api/settings/ai',data,self.ta)
        self.assertEqual(response.status_code,200,response.json)
        return response.json['profileId']

    def test_first_added_model_is_default_and_editor_can_switch_without_chat_effect(self):
        first=self.save('DeepSeek',model='flash',models=['flash','reasoner'])
        second=self.save('Another',model='other',models=['other','vision'])
        engine=self.app.store.engine(self.ua)
        self.assertEqual(engine.CFG['model'],'flash')
        with patch.object(engine.ai_services,'complete',return_value={'reply':'ok','events':[]}):
            sent=self.post(self.a,'/api/chat',{'message':'hello','profileId':first,'model':'reasoner'},self.ta)
        conversation=sent.json['conversationId']
        self.save('Another',key='',profileId=second,model='vision',models=['other','vision'],makeDefault=True)
        self.assertEqual(engine.CFG['model'],'vision')
        self.assertEqual(engine.chat_config({'conversationId':conversation})['model'],'reasoner')
        selected=[p for p in engine.ai_profiles().list() if p['is_default']]
        self.assertEqual([p['id'] for p in selected],[second])

    def test_same_provider_profiles_have_independent_encrypted_keys(self):
        first=self.save('first',key='private-key-A',makeDefault=True)
        second=self.save('second',key='private-key-B')
        engine=self.app.store.engine(self.ua)
        self.assertEqual(engine.ai_profiles().get(first)['key'],'private-key-A')
        self.assertEqual(engine.ai_profiles().get(second)['key'],'private-key-B')
        state=self.state(self.a,self.ta).json
        self.assertEqual(len(state['aiProfiles']),2)
        self.assertEqual(state['config']['model'],'model-first')
        self.assertNotIn('private-key-',json.dumps(state))
        self.assertEqual(self.state(self.b,self.tb).json['aiProfiles'],[])
        with self.app.store.db() as c:
            blobs=[bytes(row[0]) for row in c.execute("SELECT value FROM credentials WHERE user_id=? AND identity LIKE 'ai-profile:%'",(self.ua,))]
        self.assertEqual(len(blobs),2)
        self.assertTrue(all(b'private-key-' not in blob for blob in blobs))
        with engine.db() as c:
            self.assertNotIn('private-key-',str([dict(row) for row in c.execute('SELECT * FROM ai_profiles')]))

    def test_chat_switches_profile_without_changing_mail_analysis_default(self):
        first=self.save('first',key='private-key-A')
        second=self.save('second',key='private-key-B')
        engine=self.app.store.engine(self.ua)
        with patch.object(engine.ai_services,'complete',return_value={'reply':'已回答','events':[]}) as model:
            response=self.post(self.a,'/api/chat',{'message':'你好','profileId':second},self.ta)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(model.call_args.args[0]['key'],'private-key-B')
            self.assertEqual(model.call_args.args[0]['model'],'model-second')
            ident=response.json['conversationId']
            self.post(self.a,'/api/chat',{'message':'继续','conversationId':ident},self.ta)
            self.assertEqual(model.call_args.args[0]['key'],'private-key-B')
        self.assertEqual(engine.CFG['key'],'private-key-A')
        history=self.a.get('/api/chat/conversation?id='+ident,headers={'X-Token':self.ta}).json
        self.assertEqual(history['conversation']['profileId'],second)
        blocked=self.post(self.b,'/api/chat',{'message':'你好','profileId':second},self.tb)
        self.assertEqual(blocked.status_code,400)
        self.assertEqual(self.post(self.b,'/api/ai/profiles/delete',{'id':second},self.tb).status_code,400)

    def test_edit_blank_key_uses_only_that_profiles_key_and_new_requires_key(self):
        first=self.save('first',key='private-key-A')
        second=self.save('second',key='private-key-B')
        self.save('edited',key='',profileId=second)
        engine=self.app.store.engine(self.ua)
        self.assertEqual(engine.ai_profiles().get(second)['key'],'private-key-B')
        response=self.post(self.a,'/api/settings/ai',{'profileId':'','name':'third','provider':'deepseek','base':'https://api.deepseek.com','model':'model','key':''},self.ta)
        self.assertEqual(response.status_code,400)
        changed=self.post(self.a,'/api/settings/ai',{'profileId':second,'name':'changed','provider':'openai','base':'https://api.openai.com/v1','model':'model','key':''},self.ta)
        self.assertEqual(changed.status_code,400)
        self.assertEqual(engine.CFG['model'],'model-first')
        self.assertEqual(len(engine.ai_profiles().list()),2)

    def test_default_change_survives_restart_and_delete_erases_secret(self):
        first=self.save('first',key='private-key-A')
        second=self.save('second',key='private-key-B')
        self.save('second',key='',profileId=second,makeDefault=True)
        self.assertEqual(self.app.store.engine(self.ua).CFG['key'],'private-key-B')
        restarted=create_app(self.tmp.name,self.key).store.engine(self.ua)
        self.assertEqual(restarted.CFG['key'],'private-key-B')
        self.assertEqual(self.post(self.a,'/api/ai/profiles/delete',{'id':second},self.ta).status_code,400)
        self.assertEqual(self.post(self.a,'/api/ai/profiles/delete',{'id':first},self.ta).status_code,200)
        with self.app.store.db() as c:
            self.assertIsNone(c.execute('SELECT value FROM credentials WHERE user_id=? AND identity=?',(self.ua,'ai-profile:'+first)).fetchone())

    def test_legacy_config_is_adopted_once(self):
        engine=self.app.store.engine(self.ua)
        cfg={**engine.CFG,'key':'legacy-test-key','model':'old-model'}
        engine.ai_profiles().adopt(cfg)
        engine.ai_profiles().adopt(cfg)
        self.assertEqual(len(engine.ai_profiles().list()),1)
        default=engine.ai_profiles().list()[0]
        self.assertEqual(default['model'],'old-model')
        self.assertEqual(engine.ai_profiles().get(default['id'])['key'],'legacy-test-key')

    def test_models_share_connection_and_chat_choice_survives_mail_change_and_restart(self):
        ident=self.save('DeepSeek',model='flash',models=['flash','reasoner'])
        engine=self.app.store.engine(self.ua)
        with patch.object(engine.ai_services,'complete',return_value={'reply':'已回答','events':[]}) as complete:
            response=self.post(self.a,'/api/chat',{'message':'你好','profileId':ident,'model':'reasoner'},self.ta)
            self.assertEqual(response.status_code,200,response.json)
            conversation=response.json['conversationId']
            self.assertEqual(complete.call_args.args[0]['model'],'reasoner')
            self.assertEqual(engine.CFG['model'],'flash')
            changed=self.post(self.a,'/api/ai/mail-model',{'profileId':ident,'model':'reasoner'},self.ta)
            self.assertEqual(changed.status_code,200,changed.json)
            # The next message can explicitly use flash without changing mail analysis.
            sent=self.post(self.a,'/api/chat',{'message':'继续','conversationId':conversation,'profileId':ident,'model':'flash'},self.ta)
            self.assertEqual(sent.status_code,200,sent.json)
            self.assertEqual(engine.CFG['model'],'reasoner')
            self.post(self.a,'/api/chat',{'message':'再继续','conversationId':conversation},self.ta)
            self.assertEqual(complete.call_args.args[0]['model'],'flash')
        history=self.a.get('/api/chat/conversation?id='+conversation,headers={'X-Token':self.ta}).json
        self.assertEqual(history['conversation']['model'],'flash')
        restarted=create_app(self.tmp.name,self.key).store.engine(self.ua)
        self.assertEqual(restarted.CFG['model'],'reasoner')
        self.assertEqual(restarted.chat_config({'conversationId':conversation})['model'],'flash')
        self.assertEqual(restarted.ai_profiles().list()[0]['models'],['flash','reasoner'])
        self.assertNotIn('test-profile-key',json.dumps(self.state(self.a,self.ta).json))

    def test_mail_choice_checks_enabled_models_and_account_ownership(self):
        ident=self.save('DeepSeek',model='flash',models=['flash','reasoner'])
        self.assertEqual(self.post(self.a,'/api/ai/mail-model',{'profileId':ident,'model':'unknown'},self.ta).status_code,400)
        self.assertEqual(self.post(self.b,'/api/ai/mail-model',{'profileId':ident,'model':'reasoner'},self.tb).status_code,400)
        self.assertEqual(self.post(self.a,'/api/chat',{'message':'你好','profileId':ident,'model':'unknown'},self.ta).status_code,400)
        engine=self.app.store.engine(self.ua)
        self.assertEqual(engine.CFG['model'],'flash')

    def test_editing_models_preserves_mail_selection_and_cannot_disable_it(self):
        ident=self.save('DeepSeek',model='flash',models=['flash','reasoner'])
        self.save('DeepSeek',key='',profileId=ident,model='reasoner',models=['reasoner','flash'])
        engine=self.app.store.engine(self.ua)
        self.assertEqual(engine.CFG['model'],'flash')
        invalid=self.post(self.a,'/api/settings/ai',{'profileId':ident,'name':'DeepSeek','provider':'deepseek','base':'https://api.deepseek.com','model':'reasoner','models':['reasoner'],'key':''},self.ta)
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(engine.ai_profiles().get(ident)['models'],['reasoner','flash'])

if __name__=='__main__':unittest.main()
