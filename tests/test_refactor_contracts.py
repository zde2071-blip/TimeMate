import json
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import ai_services
import mail_titles
import operation_status
from user_errors import UserFacingError, payload


class RefactorContracts(unittest.TestCase):
    def test_title_validation_preserves_topic_and_rejects_truncation(self):
        self.assertEqual(mail_titles.validated('关于开展体质健康测试的通知'), '体质健康测试')
        self.assertEqual(mail_titles.validated('ISA104 小组项目提交'), 'ISA104 小组项目提交')
        for title in ['...体育活动', '标题…', '坏�标题', '长' * 33, None]:
            self.assertEqual(mail_titles.validated(title), '')
        self.assertEqual(mail_titles.from_analysis('完整原题', {'short_title': '坏…'}), '完整原题')

    def test_legacy_migration_runs_once_and_preserves_analysis(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE mails(id TEXT, subject TEXT, result TEXT, display_title TEXT, title_version INTEGER)')
        result = json.dumps({'short_title': '心理团体报名', 'summary': '原摘要', 'events': []}, ensure_ascii=False)
        c.execute('INSERT INTO mails VALUES (?,?,?,?,?)', ('old', '长的中英双语原题', result, None, None))
        mail_titles.migrate(c)
        row = c.execute('SELECT * FROM mails').fetchone()
        self.assertEqual(row['display_title'], '心理团体报名')
        self.assertEqual(row['result'], result)
        c.execute("UPDATE mails SET display_title='已经保存的标题'")
        mail_titles.migrate(c)
        self.assertEqual(c.execute('SELECT display_title FROM mails').fetchone()[0], '已经保存的标题')

    def test_legacy_subject_regressions(self):
        from legacy_title_migration import display_title, compact
        physical='<Local Students Only> 关于开展2026-2027学年《国家学生体质健康标准》测试工作的通知 Notice on the 2026�C2027 Academic Year National Student Physical Health Standard Test'
        career='2026-27S1 WEEK4｜生涯护航一周活动速递（10.5-10.11） Career Support and Upcoming Events'
        cases=[(physical,None,'国家学生体质健康标准测试'),
               (physical,{'short_title':'国家学生体质健康标准测…'},'国家学生体质健康标准测试'),
               (career,{'short_title':'4、生涯护航一周活动速递'},'生涯护航一周活动速递'),
               ('【Notice】关于学生证注册的重要提醒',None,'学生证注册'),
               ('Love, Subjectivity, Attachment, Collage... A New Batch of Psychology Groups Is Here! 预报从速！爱情、主体性、依恋、拼贴画......SCC第三批心理团体报名来袭......',None,'心理团体报名')]
        for subject,result,expected in cases:
            with self.subTest(subject=subject):self.assertEqual(display_title(subject,result),expected)
        self.assertEqual(compact('5000米长跑、4、瑜伽体验',False),'5000米长跑、瑜伽体验')
        sports='【Volunteer Recruitment & Student Activity】Special Care Education义工学院特殊教育志愿者招募& 5000 Competition “迎新杯”5000米长跑 &Yoga Experience Event “迎新杯” 瑜伽体验活动'
        title=display_title(sports,None)
        self.assertLessEqual(len(title),32)
        for topic in ['志愿者招募','5000米长跑','瑜伽']:self.assertIn(topic,title)


    def test_public_errors_do_not_depend_on_chinese_prefix(self):
        self.assertEqual(payload(UserFacingError('全新文案'))['error_code'], 'invalid_input')
        self.assertEqual(payload(RuntimeError('先填写 secret'))['error_code'], 'operation_failed')
        self.assertNotIn('secret', payload(RuntimeError('先填写 secret'))['error'])

    def test_state_counts_are_independent_of_message(self):
        state = {}
        operation_status.begin(state, 'analyzing', '任意文案', kind='check', total=5)
        operation_status.progress(state, 2, 1)
        operation_status.finish(state, '换一段文案')
        self.assertEqual((state['phase'], state['completed'], state['success'], state['failed']), ('complete', 3, 2, 1))
        operation_status.begin(state, 'checking', '再次检查')
        self.assertEqual(state['failed'], 0)

    def test_users_model_requests_are_not_globally_serialized(self):
        started = threading.Barrier(6)
        def request(*args, **kwargs):
            started.wait(timeout=3)
            return {'choices': [{'message': {'content': '{"ok":true}'}}]}
        cfg={'provider':'custom','base':'https://example.com','model':'test','key':'test'}
        with patch.object(ai_services, 'request_json', side_effect=request), ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: ai_services.complete(cfg, '', {}), range(6)))
        self.assertEqual(results, [{'ok': True}] * 6)
