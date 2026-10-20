"""Regression: English echoes must not masquerade as cached Chinese translations."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import app
from backend.core.user_errors import UserFacingError
from backend.mail import translation

SUBJECT = 'Important exam registration notice'
BODY = 'Please register for your final examination before Friday. You must bring your student card to the examination room.'
CHINESE = {'items':[{'id':0,'text':'重要考试报名通知'},{'id':1,'text':'请在周五前报名期末考试。进入考场时必须携带学生证。'}]}
ECHO = {'items':[{'id':0,'text':SUBJECT},{'id':1,'text':BODY}]}


class TranslationLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db_patch=patch.object(app,'DB',Path(self.temp.name)/'mail.db')
        self.db_patch.start()
        self.cfg_patch=patch.dict(app.CFG,provider='deepseek',base='https://api.deepseek.com',model='test-model',key='test-key')
        self.cfg_patch.start()
        with app.db() as c:
            c.execute('INSERT INTO mails(id,subject,body,created,source) VALUES (?,?,?,?,?)',('english',SUBJECT,BODY,1,'manual'))

    def tearDown(self):
        self.cfg_patch.stop();self.db_patch.stop();self.temp.cleanup()

    def test_english_echo_is_retried_then_only_chinese_is_cached(self):
        with patch.object(app.ai_services,'complete',side_effect=[ECHO,CHINESE]) as model:
            result=app.translate_source('english')
            cached=app.translate_source('english')
        self.assertEqual(model.call_count,2)
        self.assertIn('请在周五前',result['html'])
        self.assertTrue(cached['cached'])
        self.assertEqual(model.call_args.args[2]['target_language'],'zh-CN')

    def test_english_body_is_rejected_even_when_subject_is_chinese(self):
        wrong={'items':[{'id':0,'text':'重要考试报名通知'},{'id':1,'text':BODY}]}
        with patch.object(app.ai_services,'complete',side_effect=[wrong,CHINESE]) as model:
            result=app.translate_source('english')
        self.assertEqual(model.call_count,2)
        self.assertNotIn(BODY,result['html'])

    def test_bad_cached_english_is_not_reused(self):
        stamp=translation.fingerprint(SUBJECT,'<pre>'+BODY+'</pre>')
        with app.db() as c:
            c.execute('UPDATE mails SET translation=?,translation_subject=?,translation_format=? WHERE id=?',('<pre>'+BODY+'</pre>',SUBJECT,stamp,'english'))
        with patch.object(app.ai_services,'complete',return_value=CHINESE) as model:
            result=app.translate_source('english')
        model.assert_called_once()
        self.assertFalse(result['cached']);self.assertIn('请在周五前',result['html'])

    def test_repeated_english_is_explicit_failure_and_not_cached(self):
        with patch.object(app.ai_services,'complete',return_value=ECHO) as model:
            with self.assertRaisesRegex(UserFacingError,'中文'):
                app.translate_source('english')
        self.assertEqual(model.call_count,2)
        with app.db() as c:
            row=c.execute('SELECT translation,translation_format FROM mails WHERE id=?',('english',)).fetchone()
        self.assertIsNone(row['translation']);self.assertIsNone(row['translation_format'])

    def test_adding_a_chinese_prefix_does_not_hide_an_english_body(self):
        wrong={'items':[{'id':0,'text':'重要考试报名通知'},{'id':1,'text':'译文：'+BODY}]}
        with patch.object(app.ai_services,'complete',side_effect=[wrong,CHINESE]) as model:
            result=app.translate_source('english')
        self.assertEqual(model.call_count,2);self.assertNotIn('Please register',result['html'])

    def test_chinese_translation_preserves_names_codes_links_and_layout(self):
        markup='<p>Please contact Dr. John Smith about your CSI101 examination.</p><p><a href="https://example.test/a">Register here</a></p><p>CSI101</p>'
        with app.db() as c:
            c.execute('UPDATE mails SET original=? WHERE id=?',(json.dumps({'html':markup,'external':[]}), 'english'))
        answer={'items':[{'id':0,'text':'重要考试报名通知'},{'id':1,'text':'请联系 Dr. John Smith 咨询 CSI101 考试。'},{'id':2,'text':'点击报名'},{'id':3,'text':'CSI101'}]}
        with patch.object(app.ai_services,'complete',return_value=answer) as model:
            result=app.translate_source('english')
            again=app.translate_source('english')
        model.assert_called_once();self.assertTrue(again['cached'])
        self.assertIn('href="https://example.test/a">点击报名</a>',result['html'])
        self.assertIn('<p>CSI101</p>',result['html'])

    def test_old_cache_version_is_regenerated(self):
        current=translation.fingerprint(SUBJECT,'<pre>'+BODY+'</pre>')
        old='original-layout-v1:'+current.split(':',1)[1]
        with app.db() as c:
            c.execute('UPDATE mails SET translation=?,translation_subject=?,translation_format=? WHERE id=?',('<pre>'+BODY+'</pre>',SUBJECT,old,'english'))
        with patch.object(app.ai_services,'complete',return_value=CHINESE) as model:
            result=app.translate_source('english')
        model.assert_called_once();self.assertFalse(result['cached'])

    def test_split_inline_english_sentence_is_still_retried(self):
        markup='<p><span>Please</span> <b>register</b> <span>before</span> <em>Friday</em>.</p>'
        with app.db() as c:
            c.execute('UPDATE mails SET original=? WHERE id=?',(json.dumps({'html':markup,'external':[]}), 'english'))
        def model(cfg,prompt,data,**kwargs):
            if 'untranslated_ids' not in data:
                return {'items':[{'id':item['id'],'text':item['text']} for item in data['items']]}
            phrases=['重要考试报名通知','请','报名','在此之前','周五','。']
            return {'items':[{'id':item['id'],'text':phrases[item['id']]} for item in data['items']]}
        with patch.object(app.ai_services,'complete',side_effect=model) as complete:
            result=app.translate_source('english')
        self.assertEqual(complete.call_count,2)
        self.assertIn('<b>报名</b>',result['html']);self.assertIn('<em>周五</em>',result['html'])

    def test_language_guard_keeps_names_ids_and_rejects_reverse_translation(self):
        for text in ['Dr. John Smith','XJTLU','CSI101','OpenAI API','student@example.com','https://example.com/notice']:
            self.assertFalse(translation.language_issue(text,text),text)
        self.assertTrue(translation.language_issue('请在周五前报名。','Please register before Friday.'))
        self.assertTrue(translation.language_issue('Please register before Friday.','译文：Please register before Friday.'))
