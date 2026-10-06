import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import event_join


class EventJoinTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db_patch=patch.object(app,'DB',Path(self.temp.name)/'mail.db')
        self.db_patch.start()
        self.event={'title':'研究峰会项目报名截止','action':'提交研究项目申请',
                    'start':'2026-10-15T23:59','end':'','location':'线上报名系统','allDay':False,'kind':'截止'}

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def mail(self,ident,**changes):
        event={**self.event,**changes}
        result={'events':[event],'action':''}
        with app.db() as c:
            c.execute('INSERT INTO mails(id,subject,sender,date,body,result,created) VALUES (?,?,?,?,?,?,?)',
                      (ident,'通知','school@xjtlu.edu.cn','2026-10-06','body',json.dumps(result),1))
        return event

    def join(self,ident,**extra):
        app.update_pin({'id':ident,'index':0,'action':'pin',**extra})

    def decision(self,ident,**extra):
        candidate=app.check_event_join({'id':ident,'index':0})['candidates'][0]
        app.decide_event_join({'id':ident,'index':0,'targetId':candidate['id'],'targetIndex':candidate['index'],
                              'expected':candidate['event'],'mode':'link',**extra})

    def test_repeated_notice_links_without_second_card(self):
        self.mail('first');self.join('first');self.mail('reminder');self.join('reminder')
        with app.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pins WHERE state='active'").fetchone()[0],1)
            self.assertEqual(event_join.resolve(c,'reminder',0),('first',0))

    def test_checking_update_does_not_change_existing_card(self):
        self.mail('first');self.join('first');self.mail('update',start='2026-10-18T23:59')
        check=app.check_event_join({'id':'update','index':0})
        self.assertFalse(check['candidates'][0]['exact'])
        self.assertEqual(check['candidates'][0]['changes'][0]['field'],'start')
        with self.assertRaisesRegex(ValueError,'先选择'):self.join('update')
        with app.db() as c:
            self.assertEqual(c.execute("SELECT due FROM pins WHERE mail_id='first'").fetchone()[0],'2026-10-15T23:59')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],0)

    def test_update_only_selected_fields_and_preserve_manual_edits(self):
        self.mail('first');self.join('first')
        edited={**{name:self.event[name] for name in event_join.FIELDS},'action':'我已准备材料，补充导师签字'}
        app.manage_event({'id':'first','index':0,'action':'edit','fields':edited})
        self.mail('update',start='2026-10-18T23:59',action='提交更新后的材料')
        candidate=app.check_event_join({'id':'update','index':0})['candidates'][0]
        self.assertTrue(next(change for change in candidate['changes'] if change['field']=='action')['edited'])
        self.decision('update',mode='update',selectedFields=['start'])
        with app.db() as c:
            saved=event_join.effective(c,'first',0)
            self.assertEqual(saved['start'],'2026-10-18T23:59')
            self.assertEqual(saved['action'],edited['action'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pins').fetchone()[0],1)

    def test_legacy_all_day_deadline_end_does_not_block_partial_update(self):
        self.mail('first',start='2026-10-11T00:00',end='2026-10-12T00:00',allDay=True)
        self.join('first')
        self.mail('update',start='2026-10-11T23:59',end='',allDay=False,action='提交150词说明')
        check=app.check_event_join({'id':'update','index':0})
        self.assertEqual(check['candidates'][0]['event']['end'],'')
        self.assertNotIn('end',[change['field'] for change in check['candidates'][0]['changes']])
        self.decision('update',mode='update',selectedFields=['action'])
        with app.db() as c:
            saved=event_join.effective(c,'first',0)
            self.assertEqual(saved['end'],'')
            self.assertEqual(saved['start'],'2026-10-11T00:00')
            self.assertTrue(saved['allDay'])
            self.assertEqual(saved['action'],'提交150词说明')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],1)

    def test_deadline_normalization_drops_end_but_schedule_preserves_it(self):
        deadline={**self.event,'start':'2026-10-11T00:00','end':'2026-10-12T00:00','allDay':True}
        schedule={**deadline,'kind':'活动'}
        values=app.normalize_events([deadline,schedule])
        self.assertEqual(values[0]['end'],'')
        self.assertEqual(values[1]['end'],'2026-10-12T00:00:00')

    def test_new_missing_location_does_not_propose_erasing_current_location(self):
        self.mail('first');self.join('first');self.mail('update',start='2026-10-18T23:59',location='')
        changes=app.check_event_join({'id':'update','index':0})['candidates'][0]['changes']
        self.assertNotIn('location',[change['field'] for change in changes])

    def test_choose_separate_keeps_two_independent_cards(self):
        self.mail('first');self.join('first');self.mail('update',start='2026-10-18T23:59')
        self.join('update',joinDecision='new')
        with app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pins').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],0)

    def test_uncertain_title_requires_user_choice(self):
        self.mail('first');self.join('first');self.mail('reminder',title='研究峰会项目申请报名截止提醒')
        candidate=app.check_event_join({'id':'reminder','index':0})['candidates'][0]
        self.assertEqual(candidate['confidence'],'uncertain')
        with self.assertRaises(ValueError):self.join('reminder')
        self.decision('reminder')

    def test_remove_from_linked_mail_clears_all_links_and_allows_rejoining(self):
        self.mail('first');self.join('first');self.mail('second');self.join('second')
        app.update_pin({'id':'second','index':0,'action':'remove'})
        with app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT state FROM pins').fetchone()[0],'removed')
        self.join('second')
        with app.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pins WHERE state='active'").fetchone()[0],1)

    def test_stale_confirmation_is_rejected(self):
        self.mail('first');self.join('first');self.mail('update',start='2026-10-18T23:59')
        candidate=app.check_event_join({'id':'update','index':0})['candidates'][0]
        fields={name:self.event[name] for name in event_join.FIELDS};fields['location']='新地点'
        app.manage_event({'id':'first','index':0,'action':'edit','fields':fields})
        with self.assertRaisesRegex(ValueError,'发生变化'):
            app.decide_event_join({'id':'update','index':0,'targetId':'first','targetIndex':0,
                                  'expected':candidate['event'],'mode':'update','selectedFields':['start']})
        with app.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],0)

    def test_completion_preserves_links_and_menu_removal_clears_them(self):
        self.mail('first');self.join('first');self.mail('second');self.join('second')
        app.manage_event({'id':'second','index':0,'action':'complete'})
        with app.db() as c:
            self.assertEqual(c.execute('SELECT state FROM pins').fetchone()[0],'completed')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],1)
        app.manage_event({'id':'first','index':0,'action':'remove'})
        with app.db() as c:
            self.assertEqual(c.execute('SELECT state FROM pins').fetchone()[0],'removed')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],0)

    def test_invalid_update_rolls_back_link_and_preserves_saved_item(self):
        self.mail('first');self.join('first');self.mail('bad',start='invalid')
        with self.assertRaises(ValueError):self.decision('bad',mode='update',selectedFields=['start'])
        with app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM event_links').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT due FROM pins').fetchone()[0],self.event['start'])

    def test_course_codes_prevent_unrelated_coursework_merge(self):
        self.mail('first',title='SOE104 Coursework 1 提交截止');self.join('first')
        self.mail('other',title='CSI101 Coursework 1 提交截止')
        self.assertEqual(app.check_event_join({'id':'other','index':0})['candidates'],[])
