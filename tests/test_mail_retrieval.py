import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.core.database import MailDatabase
from backend.core.user_errors import UserFacingError
from backend.mail.chat import MailChat
from backend.mail.retrieval import MailRetrieval


def tool(name, **arguments):
    return {'tool_calls':[{'name':name,'arguments':arguments}]}


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'mail.db'
        store=MailDatabase()
        self.db=lambda:store.connect(self.path)
        with self.db() as c:
            c.execute("INSERT INTO mail_accounts VALUES ('school','student@school.edu','receiver@qq.com','qq')")
            c.execute("INSERT INTO mail_accounts VALUES ('personal','me@example.com','receiver@qq.com','qq')")
        self.r=MailRetrieval(self.db,'Asia/Shanghai')
        self.cfg={'base':'https://example.test','model':'test','key':'fixture'}

    def tearDown(self): self.temp.cleanup()

    def mail(self, ident, **fields):
        data={'id':ident,'subject':'课程通知 '+ident,'sender':'Teacher <teacher@school.edu>',
              'sent_date':'2026-10-22T23:30:00+08:00','date':'2026-10-22',
              'body':'报告提交截止：2026年11月6日23:59。','source':'mail','mailbox_id':'school'}
        data.update(fields)
        with self.db() as c:
            c.execute('INSERT INTO mails ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values()))

    def test_more_than_forty_and_unanalyzed_mail_paginate(self):
        for n in range(65): self.mail(f'm{n:03}')
        self.mail('deleted',is_deleted=1)
        self.mail('simulation',source='simulation')
        ids=[]
        for page in range(4):
            result=self.r.search({'page':page})
            self.assertEqual(result['total'],65)
            ids.extend(x['id'] for x in result['mails'])
        self.assertEqual(len(set(ids)),65)
        self.assertIsNone(result['next_page'])
        self.assertFalse(self.r.context()['truncated'])
        self.assertFalse(result['mails'][0]['analyzed'])

    def test_full_text_filters_timezone_and_literal_wildcards(self):
        self.mail('match',body='课程项目 隐藏细节 100%_完成')
        self.mail('wrong-mailbox',mailbox_id='personal')
        self.mail('next-day',sent_date='2026-10-22T16:30:00Z')
        self.mail('naive',sent_date='2026-10-22T23:50:00')
        query={'mailbox':'student@school.edu','sender':'teacher@school.edu','date_from':'2026-10-22','date_to':'2026-10-22'}
        self.assertEqual({m['id'] for m in self.r.search(query)['mails']},{'match','naive'})
        self.assertEqual([m['id'] for m in self.r.search({'query':'隐藏细节 100%_'})['mails']],['match'])
        for bad in ({'date_from':'yesterday'},{'date_from':'2026-10-23','date_to':'2026-10-22'},{'page':True}):
            with self.assertRaises(UserFacingError): self.r.search(bad)

    def test_search_decodes_json_values_without_matching_keys_or_escapes(self):
        self.mail('json',body='',sender='',subject='Project Z',result=json.dumps({'summary':'正常信息'}))
        self.assertEqual(self.r.search({'query':'正常'})['total'],1)
        self.assertEqual(self.r.search({'query':'summary'})['total'],0)
        self.assertEqual(self.r.search({'query':'Project B'})['total'],0)

    def test_forwarded_sender_is_searchable_without_treating_body_mentions_as_headers(self):
        self.mail('forward',sender='student@school.edu',body='From: Professor <prof@example.edu>\nDate: 2026-10-22\nSubject: 报告\n截止11月6日。')
        self.mail('mention',sender='student@school.edu',body='咨询可联系 prof@example.edu。')
        result=self.r.search({'sender':'prof@example.edu'})
        self.assertEqual([m['id'] for m in result['mails']],['forward'])
        self.assertIn('prof@example.edu',result['mails'][0]['sender_hints'])

    def test_body_pagination_and_ownership(self):
        self.mail('long',source_body='A'*6100+'最终截止说明')
        with self.assertRaises(UserFacingError): self.r.read({'id':'long'})
        self.r.search({})
        first=self.r.read({'id':'long'})
        self.assertEqual(first['next_offset'],6000)
        self.assertTrue(self.r.context()['truncated'])
        second=self.r.read({'id':'long','offset':6000})
        self.assertIn('最终截止说明',second['text'])
        self.assertFalse(self.r.context()['truncated'])
        with self.assertRaises(UserFacingError): self.r.read({'id':'another-account-mail'})
        with self.db() as c: c.execute("UPDATE mails SET is_deleted=1 WHERE id='long'")
        with self.assertRaises(UserFacingError): self.r.read({'id':'long'})

    def test_search_read_answer_sources_and_evidence(self):
        self.mail('notice')
        event={'title':'报告提交','kind':'截止','start':'2026-11-06T23:59','end':'','evidence':'2026年11月6日23:59',
               'source_ids':['notice'],'missing_fields':[]}
        model=Mock(side_effect=[tool('search_mail',query='报告'),tool('read_mail',id='notice'),
                               {'reply':'报告须在11月6日提交。','source_ids':['notice','invented'],'events':[event]}])
        chat=MailChat(self.db,self.cfg,model)
        result=chat.send({'message':'查邮件中的报告截止','requestId':'retrieval-check-1'})
        self.assertEqual([s['id'] for s in result['sources']],['notice'])
        self.assertEqual(result['events'][0]['status'],'pending')
        self.assertEqual(result['retrieval']['readCount'],1)
        self.assertEqual(model.call_args.args[2]['task_scope'],'mail')
        self.assertIn('报告提交截止',model.call_args.args[2]['tool_results'][1]['result']['text'])
        self.assertEqual(chat.send({'message':'查邮件中的报告截止','requestId':'retrieval-check-1'}),result)
        self.assertEqual(model.call_count,3)

    def test_unverified_evidence_never_auto_adds(self):
        self.mail('notice')
        event={'title':'报告提交','kind':'截止','start':'2026-11-06T23:59','end':'','evidence':'虚构的时间',
               'source_ids':['notice'],'missing_fields':[]}
        model=Mock(side_effect=[tool('search_mail'),{'reply':'整理好了。','source_ids':['notice'],'events':[event]}])
        result=MailChat(self.db,self.cfg,model).send({'message':'查邮件并添加截止','approvalMode':'auto'})
        self.assertEqual(result['events'][0]['status'],'needs_info')
        with self.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM pins').fetchone()[0],0)

    def test_partial_results_visible_persisted_and_no_auto_add(self):
        for n in range(25): self.mail(f'm{n:03}')
        model=Mock(side_effect=[tool('search_mail'),{'reply':'找到以下邮件。','events':[]}])
        chat=MailChat(self.db,self.cfg,model)
        result=chat.send({'message':'查所有邮件','approvalMode':'auto'})
        self.assertTrue(result['truncated'])
        self.assertIn('部分检索',result['reply'])
        self.assertIn('部分检索',chat.history(result['conversationId'])['messages'][-1]['content'])

    def test_unsearched_answer_is_not_claimed_as_verified(self):
        model=Mock(return_value={'reply':'没有截止。','events':[]})
        result=MailChat(self.db,self.cfg,model).send({'message':'查询邮箱'})
        self.assertIn('未完成邮件检索',result['retrievalNotice'])

    def test_bounded_loop_and_tool_allowlist(self):
        model=Mock(return_value=tool('send_email',recipient='attacker@example.com'))
        payload={'question':'查看邮件','task_scope':'mail'}
        with patch('backend.mail.retrieval.MAX_ROUNDS',2):
            result=self.r.run(model,self.cfg,'',payload)
        self.assertEqual(model.call_count,3)
        self.assertIn('上限',result['reply'])
        self.assertIn('只支持',self.r.results[0]['result']['error'])
        self.assertTrue(self.r.context()['truncated'])

    def test_content_budget_forces_final_call(self):
        self.mail('notice')
        model=Mock(return_value=tool('search_mail'))
        with patch('backend.mail.retrieval.MAX_CHARS',100):
            result=self.r.run(model,self.cfg,'',{'task_scope':'mail'})
        self.assertEqual(model.call_count,2)
        self.assertFalse(self.r.seen)
        self.assertTrue(self.r.context()['truncated'])

    def test_followup_requeries_and_keeps_scope(self):
        self.mail('notice')
        model=Mock(side_effect=[tool('search_mail'),{'reply':'找到课程通知。','source_ids':['notice']},
                               tool('search_mail',query='报告'),tool('read_mail',id='notice'),
                               {'reply':'原文截止11月6日。','source_ids':['notice']}])
        chat=MailChat(self.db,self.cfg,model)
        first=chat.send({'message':'本周邮箱有什么通知'})
        second=chat.send({'message':'那个报告什么时候截止','conversationId':first['conversationId']})
        self.assertEqual(second['sources'][0]['id'],'notice')
        self.assertEqual(second['retrieval']['toolCalls'],2)

    def test_empty_search_can_broaden_and_conflict_bodies_are_both_available(self):
        self.mail('old',body='原截止2026年11月6日23:59。')
        self.mail('new',body='更正：报告截止从11月6日改为2026年11月8日23:59。')
        model=Mock(side_effect=[tool('search_mail',query='不存在的关键词'),tool('search_mail',query='截止'),
                               {'tool_calls':[{'name':'read_mail','arguments':{'id':'old'}},{'name':'read_mail','arguments':{'id':'new'}}]},
                               {'reply':'通知明确更正为11月8日。','source_ids':['old','new']}])
        result=MailChat(self.db,self.cfg,model).send({'message':'检查邮件中的报告截止'})
        self.assertEqual(len(result['sources']),2)
        self.assertIn('更正',model.call_args.args[2]['tool_results'][-1]['result']['text'])


if __name__=='__main__': unittest.main()
