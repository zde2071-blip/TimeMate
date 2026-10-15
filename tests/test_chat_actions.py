import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from backend.core.database import MailDatabase
from backend.core.user_errors import UserFacingError
from backend.core import ai_services
from backend.mail.chat import MailChat
from backend.mail.chat_images import validate_images
from backend import app

PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'\0'*16).decode()
DEADLINE = dict(title='ISA104 课程项目提交', kind='截止', start='2026-10-25T23:59', end='',
                action='提交项目', location='', allDay=False, evidence='2026年10月25日23:59截止', uncertainty='')
EXAM = dict(title='SOE104 期中考试', kind='活动', start='2026-10-26T09:00', end='2026-10-26T11:00',
            action='参加考试', location='FB308', allDay=False, evidence='2026年10月26日 09:00—11:00', uncertainty='')

class ChatActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'mail.db'
        self.database = MailDatabase()
        self.db = lambda: self.database.connect(self.path)
        self.model = Mock(return_value={'reply':'已整理出以下事项。', 'source_ids':[], 'events':[DEADLINE, EXAM]})
        self.chat = MailChat(self.db, {'base':'https://api.test', 'key':'test-secret', 'model':'vision'}, self.model)

    def tearDown(self):
        self.temp.cleanup()

    def send(self, **extra):
        return self.chat.send({'message':'帮我整理并加入这些考试和截止事项。', **extra})

    def counts(self):
        with self.db() as c:
            return (c.execute("SELECT COUNT(*) FROM pins WHERE state='active'").fetchone()[0],
                    c.execute("SELECT COUNT(*) FROM calendar_events WHERE status='subscribed'").fetchone()[0])

    def test_confirm_mode_defers_writes_and_adds_one_at_a_time(self):
        result=self.send()
        self.assertEqual(self.counts(), (0,0))
        self.assertEqual([event['status'] for event in result['events']], ['pending','pending'])
        first=result['events'][0]['id']
        self.chat.add_event({'id':first})
        self.assertEqual(self.counts(), (1,0))
        self.chat.add_event({'id':first})
        self.assertEqual(self.counts(), (1,0), 'double-click cannot add twice')
        history=self.chat.history(result['conversationId'])
        self.assertEqual([event['status'] for event in history['messages'][-1]['events']], ['added','pending'])
        self.chat.add_event({'id':result['events'][1]['id']})
        self.assertEqual(self.counts(), (1,1))

    def test_auto_mode_writes_reuses_existing_calendar_and_is_idempotent(self):
        request={'approvalMode':'auto', 'requestId':'unique-request-123'}
        first=self.send(**request)
        self.assertEqual(self.counts(), (1,1))
        self.assertEqual([event['status'] for event in first['events']], ['added','added'])
        replay=self.send(**request)
        self.assertEqual(replay,first)
        self.assertEqual(self.model.call_count,1)
        second=self.send(approvalMode='auto')
        self.assertEqual(self.counts(), (1,1))
        self.assertEqual([event['status'] for event in second['events']], ['duplicate','duplicate'])
        with self.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM mails WHERE is_deleted=0").fetchone()[0],0)
            item=json.loads(c.execute('SELECT detail FROM calendar_events').fetchone()[0])
        with patch.object(app,'DB',self.path):
            ics=app.export_calendar_event(item)
            self.assertIn('SUMMARY:SOE104',ics)
            self.assertIn('DTSTART:20261026T010000Z',ics)
            app.manage_event({'id':first['events'][0]['savedId'],'index':0,'action':'complete'})
        self.assertEqual(self.chat.history(first['conversationId'])['messages'][-1]['events'][0]['status'],'completed')

    def test_uncertain_missing_or_invalid_dates_never_auto_add(self):
        self.model.return_value['events']=[{**DEADLINE,'start':''}, {**EXAM,'end':''},
                                           {**DEADLINE,'uncertainty':'年份不清晰'}, {**DEADLINE,'start':'2026-02-30T10:00'},
                                           {**DEADLINE,'evidence':''}, {**DEADLINE,'start':'2026-10-25'},
                                           {**DEADLINE,'start':'2026-10-25T10:00+08:00'}]
        result=self.send(approvalMode='auto')
        self.assertEqual(self.counts(),(0,0))
        self.assertTrue(all(event['status']=='needs_info' for event in result['events']))
        for event in result['events']:
            with self.assertRaises(UserFacingError):self.chat.add_event({'id':event['id']})

    def test_similar_updated_event_requires_explicit_separate_decision(self):
        self.send(approvalMode='auto')
        self.model.return_value['events']=[{**DEADLINE,'start':'2026-10-28T23:59'}]
        result=self.send(approvalMode='auto')
        self.assertEqual(result['events'][0]['status'],'conflict')
        self.assertEqual(self.counts(),(1,1))
        self.chat.add_event({'id':result['events'][0]['id']})
        self.assertEqual(self.counts(),(1,1))
        self.chat.add_event({'id':result['events'][0]['id'],'separate':True})
        self.assertEqual(self.counts(),(2,1))

    def test_image_only_request_does_not_persist_image_bytes(self):
        result=self.chat.send({'images':[{'name':'考试.png','dataUrl':PNG}]})
        self.assertEqual(self.model.call_args.args[2]['_images'][0]['dataUrl'],PNG)
        self.assertEqual(self.model.call_args.args[2]['mail_context']['mails'],[])
        history=json.dumps(self.chat.history(result['conversationId']),ensure_ascii=False)
        self.assertIn('考试.png',history)
        self.assertNotIn('base64',history)
        self.assertNotIn(PNG,self.path.read_bytes().decode('latin1'))
        self.send(conversationId=result['conversationId'])
        self.assertNotIn('_images',self.model.call_args.args[2])
        self.assertEqual(len(self.model.call_args.args[2]['pending_events']),2)

    def test_delete_chat_preserves_saved_events_but_removes_proposals_and_replay(self):
        result=self.send(approvalMode='auto')
        self.chat.delete(result['conversationId'])
        self.assertEqual(self.counts(),(1,1))
        with self.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM chat_event_proposals').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM chat_requests').fetchone()[0],0)

    def test_invalid_inputs_and_unknown_ids_fail_before_model(self):
        for data in [{'message':'add','approvalMode':'no'}, {'images':[{'dataUrl':'https://example.com/private'}]},
                     {'images':[{'dataUrl':PNG}]*4}, {'images':[{'dataUrl':'data:image/png;base64,AAAA'}]}]:
            with self.assertRaises(UserFacingError):self.chat.send(data)
        self.model.assert_not_called()
        with self.assertRaises(UserFacingError):self.chat.add_event({'id':'other-user'})

    def test_multimodal_adapters_keep_image_separate_from_json(self):
        for provider in ('openai','claude'):
            result=({'content':[{'type':'text','text':'{"reply":"ok"}'}]} if provider=='claude' else
                    {'choices':[{'message':{'content':'{"reply":"ok"}'},'finish_reason':'stop'}]})
            cfg={'provider':provider,'base':ai_services.PROVIDERS[provider]['base'],'key':'dummy','model':'vision'}
            with patch.object(ai_services,'request_json',return_value=result) as request:
                ai_services.complete(cfg,'JSON',{'question':'考试'},images=validate_images([{'dataUrl':PNG}]))
            content=request.call_args.args[2]['messages'][-1]['content']
            self.assertEqual(content[0]['type'],'text')
            self.assertNotIn('base64',content[0]['text'])
            self.assertEqual(content[1]['type'],'image' if provider=='claude' else 'image_url')

if __name__=='__main__':unittest.main()
