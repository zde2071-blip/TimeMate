"""Multiple sources remain independent, with encrypted shared recipients."""
import unittest
from unittest.mock import Mock
from tests import test_cloud as cloud_tests
from backend.mail.accounts import MultipleReceivers


class MailAccountTests(cloud_tests.CloudTests):
    # Reuse the authenticated two-user fixture without rerunning its test suite.
    def save_mail(self, source, recipient='reader@qq.com', secret='receiver-secret', ident=''):
        return self.post(self.a,'/api/settings/mail',dict(mailAccountId=ident,school_sender=source,account=recipient,mail_provider='qq',password=secret),self.ta)

    def test_independent_sources_shared_receiver_and_account_isolation(self):
        self.assertEqual(self.save_mail('school@example.edu').status_code,200)
        self.assertEqual(self.save_mail('personal@example.com',secret='').status_code,200)
        state=self.state(self.a,self.ta).json
        self.assertEqual(len(state['mailAccounts']),2)
        self.assertTrue(all(x['connected'] for x in state['mailAccounts']))
        self.assertNotIn('receiver-secret',str(state))
        self.assertEqual(self.state(self.b,self.tb).json['mailAccounts'],[])
        engine=self.app.store.engine(self.ua)
        self.assertEqual(len(engine.mail_accounts().receivers(engine.CFG)),1)
        self.assertEqual(len(engine.mail_accounts().receivers(engine.CFG)[0]['_mail_sources']),2)
        with self.app.store.db() as c:
            encrypted=c.execute('SELECT value FROM credentials WHERE user_id=?',(self.ua,)).fetchone()[0]
        self.assertNotIn(b'receiver-secret',bytes(encrypted))
        duplicate=self.save_mail('SCHOOL@example.edu')
        self.assertEqual(duplicate.status_code,400)
        first=state['mailAccounts'][0]
        response=self.save_mail('school@example.edu',ident=first['id'],secret='')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(self.state(self.a,self.ta).json['mailAccounts']),2)
        self.app.store.engines.pop(self.ua)
        self.assertEqual(len(self.state(self.a,self.ta).json['mailAccounts']),2)

    def test_multiple_receivers_and_cursor_replay_preserve_existing_mail(self):
        self.save_mail('school@example.edu')
        engine=self.app.store.engine(self.ua)
        from backend.mail.ingest import cursor_key
        with engine.db() as c:
            c.execute('INSERT INTO cursors VALUES (?,?,?)',(cursor_key('reader@qq.com'),'v1',50))
        self.save_mail('other@example.edu',secret='')
        with engine.db() as c:
            self.assertEqual(c.execute('SELECT uid FROM cursors').fetchone()[0],0)
        self.save_mail('third@example.edu','second@qq.com','other-secret')
        groups=engine.mail_accounts().receivers(engine.CFG)
        self.assertEqual(len(groups),2)
        self.assertEqual({c['account']:c['password'] for c in groups},{'reader@qq.com':'receiver-secret','second@qq.com':'other-secret'})
        foreign=self.state(self.a,self.ta).json['mailAccounts'][0]['id']
        response=self.post(self.b,'/api/settings/mail',dict(mailAccountId=foreign),self.tb)
        self.assertEqual(response.status_code,400)

    def test_existing_oauth_survives_adding_forwarded_mailbox_and_restart(self):
        import json
        from backend.mail import oauth
        engine=self.app.store.engine(self.ua)
        oauth.save(engine.RUNTIME,'google',{'access_token':'fixture-access','refresh_token':'fixture-refresh','reauthorize':False,'expires_at':9999999999})
        engine.CFG.update(mail_mode='oauth',mail_provider='google',account='connected@gmail.com')
        response=self.save_mail('school@example.edu')
        self.assertEqual(response.status_code,200,response.text)
        state=self.state(self.a,self.ta).json
        self.assertEqual(len(state['mailAccounts']),2)
        self.assertEqual(state['mailConnection']['account'],'connected@gmail.com')
        self.assertTrue(any(cfg.get('_direct') for cfg in engine.mail_receiver().configs))
        self.app.store.engines.pop(self.ua)
        self.assertEqual(len(self.state(self.a,self.ta).json['mailAccounts']),2)

    def test_adopts_legacy_account_without_changing_read_deleted_or_mail_identity(self):
        import json
        from backend.mail.ingest import cursor_key
        engine=self.app.store.engine(self.ua)
        engine.CFG.update(account='reader@qq.com',mail_provider='qq',school_sender='school@example.edu',password='legacy-secret')
        engine.credential_store('save','mail',engine.CFG,'legacy-secret')
        engine.PREFS.write_text(json.dumps({k:engine.CFG[k] for k in engine.DEFAULTS}))
        with engine.db() as c:
            c.execute('INSERT INTO mails(id,subject,sender,created,source,receiving_account,is_read,is_deleted) VALUES(?,?,?,?,?,?,?,?)',('legacy-mail','Legacy notice','school@example.edu',1,'manual',cursor_key('reader@qq.com'),1,1))
        self.app.store.engines.pop(self.ua)
        state=self.state(self.a,self.ta).json
        self.assertEqual(len(state['mailAccounts']),1)
        engine=self.app.store.engine(self.ua)
        with engine.db() as c: row=c.execute('SELECT id,is_read,is_deleted,mailbox_id FROM mails').fetchone()
        self.assertEqual(tuple(row[:3]),('legacy-mail',1,1))
        self.assertEqual(row['mailbox_id'],state['mailAccounts'][0]['id'])

    def test_both_sources_are_imported_and_attributed(self):
        from backend.mail import ingest
        self.save_mail('school@example.edu');self.save_mail('personal@example.com',secret='')
        engine=self.app.store.engine(self.ua);cfg=engine.mail_accounts().receivers(engine.CFG)[0]
        for uid,source in enumerate(['school@example.edu','personal@example.com'],1):
            header=('From: '+source+'\r\n\r\n').encode()
            raw=('From: '+source+'\r\nSubject: Notice '+str(uid)+'\r\n\r\nBody').encode()
            conn=Mock();conn.uid.side_effect=[('OK',[(b'header',header)]),('OK',[(b'body',raw)])]
            ident,added=engine.import_uid(conn,cfg,'v1',uid,'manual')
            self.assertTrue(added)
            with engine.db() as c:
                row=c.execute('SELECT mailbox_id FROM mails WHERE id=?',(ident,)).fetchone()
            expected=next(x['id'] for x in cfg['_mail_sources'] if x['address']==source)
            self.assertEqual(row['mailbox_id'],expected)
        self.assertEqual(len(self.state(self.a,self.ta).json['mails']),2)


# Prevent unittest from inheriting all the unrelated cloud fixture tests.
for name in list(cloud_tests.CloudTests.__dict__):
    if name.startswith('test_') and name not in MailAccountTests.__dict__:
        setattr(MailAccountTests,name,None)


class MultipleReceiverHealthTests(unittest.TestCase):
    def test_failed_receiver_does_not_block_another(self):
        configs=[{'account':'a@qq.com'},{'account':'b@qq.com'}];status={'auto':True};called=[]
        def factory(cfg,child):
            def run():
                called.append(cfg['account'])
                if cfg['account']=='a@qq.com':child.update(auto=False,sync_state='paused',sync_error_code='mail_authentication_failed')
                else:child.update(auto=True,sync_state='ready',added=2)
                return 'done'
            return Mock(process_new=run)
        receiver=MultipleReceivers(configs,status,factory)
        receiver.process_new();self.assertTrue(status['auto']);self.assertEqual(called,['a@qq.com','b@qq.com'])
        called.clear();receiver.process_new();self.assertEqual(called,['b@qq.com'])
        self.assertEqual(status['added'],2)
