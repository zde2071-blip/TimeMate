"""Exercise retrieval through authenticated routes with two real account DBs."""
import unittest
from tests import test_mail_read_model as fixture


class RetrievalIsolationTests(unittest.TestCase):
    setUp=fixture.MailReadModelTests.setUp
    mail=fixture.MailReadModelTests.mail
    post=fixture.MailReadModelTests.post

    def test_tools_cannot_search_or_read_another_accounts_mail(self):
        self.mail('alice-note',body='Alice private deadline',pending=True)
        self.mail('bob-note',user='bob',body='Bob secret deadline',pending=True)
        engine=self.engine
        engine.CFG.update(key='fixture',model='fixture')
        traces=[]
        def model(cfg,prompt,data):
            results=data.get('tool_results',[])
            traces.append(results)
            if not results: return {'tool_calls':[{'name':'search_mail','arguments':{}}]}
            if len(results)==1: return {'tool_calls':[{'name':'read_mail','arguments':{'id':'bob-note'}}]}
            return {'reply':'只能查看当前账号的邮件。','source_ids':['alice-note','bob-note'],'events':[]}
        engine.model_reply=model
        response=self.post('/api/chat',{'message':'查邮箱里的所有邮件'})
        self.assertEqual(response.status_code,200)
        self.assertEqual([row['id'] for row in response.json['sources']],['alice-note'])
        self.assertEqual([row['id'] for row in traces[-1][0]['result']['mails']],['alice-note'])
        self.assertIn('error',traces[-1][1]['result'])
        self.assertNotIn('Bob secret',str(traces))
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.post('/api/chat',json={'message':'查邮件'},headers={'Origin':'http://127.0.0.1:18744'}).status_code,401)


if __name__=='__main__': unittest.main()
