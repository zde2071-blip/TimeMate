"""Mailbox labels are account-scoped metadata, independent of receiving credentials."""
import unittest
from unittest.mock import patch
from tests import test_cloud as cloud_tests
from backend.mail.accounts import receiver_key

class MailboxNameTests(cloud_tests.CloudTests):
    def add_source(self, address='school@example.edu'):
        response=self.post(self.a,'/api/settings/mail',dict(mailAccountId='',school_sender=address,account='reader@qq.com',mail_provider='qq',password='fixture-secret'),self.ta)
        self.assertEqual(response.status_code,200,response.text)
        return next(row for row in self.state(self.a,self.ta).json['mailAccounts'] if row['school_sender']==address)['id']

    def rename(self, ident, name):
        return self.post(self.a,'/api/mail/accounts/name',dict(id=ident,name=name),self.ta)

    def test_label_persists_and_changes_revision_without_touching_sync_or_credentials(self):
        ident=self.add_source();engine=self.app.store.engine(self.ua)
        with engine.db() as c:c.execute('INSERT INTO cursors VALUES (?,?,?)',('fixture-cursor','v1',23))
        engine.STATUS['auto']=True
        before=self.state(self.a,self.ta).json
        with patch.object(engine.imaplib,'IMAP4_SSL',side_effect=AssertionError('Rename must not test IMAP')):
            self.assertEqual(self.rename(ident,' 学校邮箱 ').status_code,200)
        after=self.state(self.a,self.ta).json
        self.assertEqual(after['mailAccounts'][0]['name'],'学校邮箱')
        self.assertEqual(after['mailAccounts'][0]['id'],ident)
        self.assertNotEqual(before['revision'],after['revision'])
        self.assertTrue(engine.STATUS['auto'])
        self.assertEqual(engine.RUNTIME.credential('load',receiver_key('reader@qq.com')),'fixture-secret')
        with engine.db() as c:self.assertEqual(c.execute('SELECT uid FROM cursors').fetchone()[0],23)
        self.app.store.engines.pop(self.ua)
        self.assertEqual(self.state(self.a,self.ta).json['mailAccounts'][0]['name'],'学校邮箱')

    def test_foreign_ids_invalid_names_and_duplicate_labels(self):
        first=self.add_source();second=self.add_source('work@example.com')
        self.assertEqual(self.post(self.b,'/api/mail/accounts/name',dict(id=first,name='foreign'),self.tb).status_code,400)
        self.assertEqual(self.rename('missing','Name').status_code,400)
        for name in [None,{},'x'*61,'first\nsecond']:
            self.assertEqual(self.rename(first,name).status_code,400)
        for ident in [first,second]:self.assertEqual(self.rename(ident,'收件箱').status_code,200)
        self.assertEqual(len(self.state(self.a,self.ta).json['mailAccounts']),2)
        self.assertEqual(self.rename(first,'').status_code,200)
        self.assertEqual(self.state(self.a,self.ta).json['mailAccounts'][0]['name'],'')
        self.assertEqual(self.state(self.b,self.tb).json['mailAccounts'],[])

    def test_direct_mailbox_label_uses_its_stable_id_and_preserves_tokens(self):
        from backend.mail import oauth
        engine=self.app.store.engine(self.ua)
        oauth.save(engine.RUNTIME,'google',dict(access_token='fixture-access',refresh_token='fixture-refresh',reauthorize=False,expires_at=9999999999))
        engine.CFG.update(mail_mode='oauth',mail_provider='google',account='connected@gmail.com')
        entry=self.state(self.a,self.ta).json['mailAccounts'][0]
        self.assertEqual(self.rename(entry['id'],'个人 Gmail').status_code,200)
        self.assertEqual(self.state(self.a,self.ta).json['mailAccounts'][0]['name'],'个人 Gmail')
        self.assertTrue(self.state(self.a,self.ta).json['mailConnection']['connected'])
        other=self.add_source()
        self.assertEqual(len(self.state(self.a,self.ta).json['mailAccounts']),2)
        self.assertEqual(next(x for x in self.state(self.a,self.ta).json['mailAccounts'] if x['id']==entry['id'])['name'],'个人 Gmail')

# Inherit the fixture helpers, not the unrelated full cloud test suite.
for _name in tuple(name for name in dir(cloud_tests.CloudTests) if name.startswith('test_')):
    setattr(MailboxNameTests,_name,None)

if __name__=='__main__':unittest.main()
