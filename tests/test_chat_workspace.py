"""Multi-turn material correction, guarded dates and batch execution contracts."""
import json
import unittest
from unittest.mock import Mock, patch
from tests import test_chat_actions as fixtures
EXAM, DEADLINE, PNG = fixtures.EXAM, fixtures.DEADLINE, fixtures.PNG
from backend.mail.chat import MailChat
from backend.core.user_errors import UserFacingError
from backend import app


class ChatWorkspaceTests(unittest.TestCase):
    send = fixtures.ChatActionTests.send
    counts = fixtures.ChatActionTests.counts
    tearDown = fixtures.ChatActionTests.tearDown
    def setUp(self):
        fixtures.ChatActionTests.setUp(self)
        self.vault = {}
        def vault(action, ident, value=''):
            if action == 'save': self.vault[ident] = value
            if action == 'delete': self.vault.pop(ident, None)
            return self.vault.get(ident, '')
        self.chat.media_store = vault

    def test_multiturn_uses_stable_ids_and_one_list_with_source_and_images(self):
        first = self.send(images=[{'name':'安排.png','dataUrl':PNG}])
        old = first['events'][0]
        self.model.return_value = {'reply':'日期已更新。', 'events':[{**DEADLINE,'id':old['id'],'start':'2026-10-27T23:59'}]}
        second = self.send(message='提交日期改为27日', conversationId=first['conversationId'])
        self.assertEqual({p['id'] for p in second['events']}, {p['id'] for p in first['events']})
        self.assertEqual(next(p for p in second['events'] if p['id']==old['id'])['event']['start'],'2026-10-27T23:59')
        self.assertEqual(self.model.call_args.args[2]['_images'][0]['dataUrl'], PNG)
        self.assertEqual(self.model.call_args.args[2]['task_scope'],'external')
        self.assertEqual(self.model.call_args.args[2]['mail_context']['mails'],[])
        history=self.chat.history(first['conversationId'])['messages']
        self.assertEqual([len(m['events']) for m in history], [0,0,0,2])
        self.assertEqual(history[0]['images'][0]['name'],'安排.png')
        self.assertNotIn(PNG, self.path.read_bytes().decode('latin1'))
        self.chat.delete(first['conversationId'])
        self.assertFalse(self.vault)

    def test_expired_image_not_sent_again_and_new_batch_replaces_it(self):
        first=self.send(images=[{'name':'旧图.png','dataUrl':PNG}])
        with self.db() as c:
            data=json.loads(c.execute('SELECT data FROM chat_workspaces').fetchone()[0])
            data['image_saved_at']=1
            c.execute('UPDATE chat_workspaces SET data=?',(json.dumps(data),))
        self.send(conversationId=first['conversationId'],message='继续核对')
        self.assertNotIn('_images',self.model.call_args.args[2])
        self.assertFalse(self.vault)
        new=self.send(conversationId=first['conversationId'],images=[{'name':'新图.png','dataUrl':PNG}])
        self.assertNotEqual(first['batchId'],new['batchId'])
        self.assertEqual(len(new['events']),2)
        self.assertEqual(self.chat.history(first['conversationId'])['messages'][-2]['images'][0]['name'],'新图.png')

    def test_questions_for_blocking_gaps_and_date_only_permission(self):
        self.model.return_value={'reply':'整理好了。','events':[{**EXAM,'start':'','end':'','missing_fields':['year','date'],'timePrecision':'date'}]}
        result=self.send(approvalMode='auto')
        self.assertIn('年份',result['reply']);self.assertIn('？',result['reply'])
        self.assertEqual(result['events'][0]['status'],'needs_info')
        self.assertEqual(self.counts(),(0,0))
        self.model.return_value={'reply':'整理好了。','events':[{**EXAM,'start':'2026-10-26','end':'','missing_fields':['time','location'],'timePrecision':'date'}]}
        first=self.send(approvalMode='auto')
        self.assertIn('时间待定',first['reply']);self.assertEqual(self.counts(),(0,0))
        self.assertEqual(first['events'][0]['status'],'pending')
        self.model.return_value['events'][0]['id']=first['events'][0]['id']
        denied=self.send(conversationId=first['conversationId'],message='不要按日期添加',approvalMode='auto')
        self.assertFalse(self.model.call_args.args[2]['date_only_approved']);self.assertEqual(self.counts(),(0,0))
        agreed=self.send(conversationId=first['conversationId'],message='可以先按日期添加',approvalMode='auto')
        self.assertEqual(agreed['events'][0]['status'],'added');self.assertEqual(self.counts(),(0,1))
        with self.db() as c: item=json.loads(c.execute('SELECT detail FROM calendar_events').fetchone()[0])
        with patch.object(app,'DB',self.path): ics=app.export_calendar_event(item)
        self.assertIn('时间待定',ics);self.assertIn('DTSTART;VALUE=DATE:20261026',ics)

    def test_batch_partial_failure_idempotency_and_no_cross_owner_writes(self):
        self.model.return_value['events']=[DEADLINE,{**EXAM,'start':'','missing_fields':['date']}]
        first=self.send();valid,bad=[p['id'] for p in first['events']]
        with self.assertRaises(UserFacingError):self.chat.add_events({'ids':[valid,'other-user-id']})
        self.assertEqual(self.counts(),(0,0))
        result=self.chat.add_events({'ids':[valid,bad],'dateOnly':True})
        self.assertEqual(len(result['errors']),1);self.assertEqual(self.counts(),(1,0))
        self.chat.add_events({'ids':[valid],'dateOnly':True});self.assertEqual(self.counts(),(1,0))
        fixed=self.chat.edit_event({'id':bad,'fields':{'start':'2026-10-26','end':'','timePrecision':'date','location':'','allDay':True}})
        self.assertEqual(next(p for p in fixed['events'] if p['id']==bad)['status'],'pending')
        self.chat.add_events({'ids':[bad],'dateOnly':True});self.assertEqual(self.counts(),(1,1))
        with self.db() as c: data=json.loads(c.execute('SELECT data FROM chat_workspaces').fetchone()[0])
        self.assertIn('用户在编辑表单已核对',data['user_instructions'][-1])

    def test_same_title_sessions_not_collapsed_and_saved_items_not_rewritten(self):
        self.model.return_value['events']=[EXAM,{**EXAM,'start':'2026-10-27T09:00','end':'2026-10-27T11:00','evidence':'27日考试'}]
        first=self.send();self.assertEqual(len(first['events']),2)
        second=self.send(conversationId=first['conversationId']);self.assertEqual(len(second['events']),2)
        ident=first['events'][0]['id'];self.chat.add_event({'id':ident})
        self.model.return_value['events']=[{**EXAM,'id':ident,'title':'模型误改的主题'}]
        final=self.send(conversationId=first['conversationId'])
        saved=next(p for p in final['events'] if p['id']==ident)
        self.assertEqual(saved['event']['title'],EXAM['title']);self.assertEqual(saved['status'],'added')

    def test_normal_chat_does_not_move_list_and_timezone_survives_add(self):
        first=self.send(timeZone='America/New_York')
        self.model.return_value={'reply':'你好。','events':[]}
        follow=self.send(conversationId=first['conversationId'],message='你好')
        self.assertEqual(follow['events'],[])
        self.assertEqual(len(self.chat.history(first['conversationId'])['messages'][1]['events']),2)
        self.chat.add_event({'id':first['events'][1]['id']})
        with self.db() as c: item=json.loads(c.execute('SELECT detail FROM calendar_events').fetchone()[0])
        self.assertEqual(item['timeZone'],'America/New_York')
        with patch.object(app,'DB',self.path): ics=app.export_calendar_event(item)
        self.assertIn('DTSTART:20261026T130000Z',ics)

    def test_distinct_similar_items_in_same_batch_add_together(self):
        self.model.return_value['events']=[{**EXAM,'title':f'课程 {i} 考试','start':f'2026-11-{i:02d}','end':'','timePrecision':'date','missing_fields':['time']} for i in range(1,9)]
        first=self.send()
        result=self.chat.add_events({'ids':[p['id'] for p in first['events']],'dateOnly':True})
        self.assertFalse(result['errors']);self.assertEqual(self.counts(),(0,8))
        self.assertTrue(all(p['status']=='added' for p in result['events']))
