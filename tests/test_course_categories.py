import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import app
class CourseCategoriesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=patch.object(app,'DB',Path(self.tmp.name)/'mail.db');self.db.start()
 def tearDown(self):self.db.stop();self.tmp.cleanup()
 def test_only_original_mail_has_trusted_codes(self):
  row={'subject':'IELTS for students','body':'报名语言培训','result':json.dumps({'summary':'CSI101'})}
  self.assertEqual(app.mail_course_codes(row),[])
  self.assertEqual(app.category_for(row,{'category':'课程与教学'}),'课程与教学')
  self.assertEqual(app.category_for({'subject':'通知','body':'无代码'}, {'category':'课程与教学'}),'课程与教学')
  row.update(subject='csi 101: notice',source_body='SOE104 assignment',body='ISA104 group')
  self.assertEqual(app.mail_course_codes(row),['CSI101','ISA104','SOE104'])
  self.assertEqual(app.category_for(row,{'category':'活动与机会'}),'活动与机会')
 def test_manual_category_survives_analysis_result_change_and_reopen(self):
  with app.db() as c:c.execute('INSERT INTO mails(id,subject,body,result,created) VALUES (?,?,?,?,?)',('m','IELTS','报名','{}',1))
  app.change_mail_category({'id':'m','category':'课程与教学'})
  with app.db() as c:
   c.execute('UPDATE mails SET result=? WHERE id=?',(json.dumps({'category':'活动与机会'}),'m'))
  with app.db() as c:row=c.execute('SELECT * FROM mails WHERE id=?',('m',)).fetchone()
  self.assertEqual(app.category_for(row,json.loads(row['result'])),'课程与教学')
  app.change_mail_category({'id':'m','category':'校园服务'})
  with app.db() as c:row=c.execute('SELECT * FROM mails WHERE id=?',('m',)).fetchone()
  self.assertEqual(app.category_for(row,{'category':'课程与教学'}),'校园服务')
 def test_analysis_preserves_model_category_without_overwriting_manual_choice(self):
  with app.db() as c:
   c.execute('INSERT INTO mails(id,subject,body,created,manual_category) VALUES (?,?,?,?,?)',('m','IELTS','报名',1,'校园服务'))
  result={k:'' for k in ('summary','time','location','action','uncertainties')};result.update(category='课程与教学',events=[])
  with patch.object(app,'model_reply',return_value=result):app.analyze_saved_mail('m')
  with app.db() as c:row=c.execute('SELECT * FROM mails WHERE id=?',('m',)).fetchone()
  self.assertEqual(json.loads(row['result'])['category'],'课程与教学')
  self.assertEqual(app.category_for(row,json.loads(row['result'])),'校园服务')
 def test_codes_normalized_deduplicated_persisted_and_isolated(self):
  app.add_course({'code':'csi 101'});app.add_course({'code':'CSI101'})
  with app.db() as c:self.assertEqual([r['code'] for r in c.execute('SELECT code FROM courses')],['CSI101'])
  with patch.object(app,'DB',Path(self.tmp.name)/'other.db'):
   with app.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM courses').fetchone()[0],0)
  for code in ('IELTS','CSI101; DROP TABLE mails',''):
   with self.assertRaises(ValueError):app.add_course({'code':code})
