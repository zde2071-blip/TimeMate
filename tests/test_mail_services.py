"""Account dependencies stay local after extracting the analysis service."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
from pathlib import Path
import tempfile
import unittest
from mail_analysis import MailAnalyzer
from mail_database import MailDatabase


class MailServiceTests(unittest.TestCase):
    def test_parallel_accounts_keep_config_result_and_retry_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            services=[];connections=[];statuses=[]
            def model(cfg,prompt,data):
                if cfg['key']=='failure':raise TimeoutError()
                return {'category':'其他','summary':cfg['key']+' '+data['body'],
                        'time':'','location':'','action':'','uncertainties':'','events':[]}
            for key in ('account-a','account-b'):
                database=MailDatabase()
                connect=partial(database.connect,Path(directory)/(key+'.db'))
                with connect() as c:
                    c.execute('INSERT INTO mails (id,subject,body,created,source) VALUES (?,?,?,?,?)',
                              ('same-id','原题',key,1,'manual'))
                status={}
                services.append(MailAnalyzer(connect,{'key':key},status,model,lambda row,result:result['category']))
                connections.append(connect);statuses.append(status)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda service:service.pending(service.analyze),services))
            self.assertEqual(results,[(1,0),(1,0)])
            for key,connect in zip(('account-a','account-b'),connections):
                with connect() as c:
                    result=json.loads(c.execute('SELECT result FROM mails').fetchone()[0])
                self.assertEqual(result['summary'],key+' '+key)
            services[0].config['key']='failure'
            with connections[0]() as c:c.execute('INSERT INTO mails (id,subject,body,source) VALUES (?,?,?,?)',('failed','原题','正文','manual'))
            self.assertEqual(services[0].pending(services[0].analyze),(0,1))
            with connections[1]() as c:
                self.assertEqual(c.execute('SELECT SUM(analysis_attempts) FROM mails').fetchone()[0],0)
            self.assertEqual(statuses[1]['failed'],0)
