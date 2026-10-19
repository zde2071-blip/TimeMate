"""Local browser fixture: real application/routes/storage, deterministic model, no external calls."""
import json
import secrets
import signal
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import redirect
from cryptography.fernet import Fernet
from werkzeug.serving import make_server
from backend.cloud import create_app, digest, password_hash
from backend.core.ai_services import AIServiceError, ModelCatalog
from tests.test_chat_actions import DEADLINE, EXAM


def main():
    with tempfile.TemporaryDirectory(prefix='timemate-chat-browser-') as directory:
        app = create_app(directory, Fernet.generate_key())
        def model(cfg, prompt, data, **kwargs):
            if data.get('test'): return {'ok':True}
            question=data.get('question', '')
            if '查询当前连接' in question: return {'reply':'当前模型：'+cfg['model'],'events':[]}
            if '不支持图片' in question:
                raise AIServiceError('请求或模型参数不受支持。（HTTP 400）')
            if '查询' in question:
                return {'reply':'这是查询回答，不添加事项。', 'events':[]}
            if '多项' in question:
                events=[{**EXAM,'title':f'课程 {i} 考试','start':f'2026-11-{i:02d}','end':'','location':'','timePrecision':'date','missing_fields':['time','location']} for i in range(1,9)]
                events[6].update(start='',missing_fields=['year'],evidence='11月7日考试')
                events[7].update(start='',missing_fields=['date'],evidence='考试日期待通知')
                return {'reply':'第7项是哪一年？第8项的日期是什么时候？','source_text':'课程安排：11月1日至8日，部分日期待核对','events':events}
            if '统一2026年' in question:
                events=[p.copy() for p in data.get('pending_events',[])]
                for event in events:
                    if event['title']=='课程 7 考试': event.update(start='2026-11-07',missing_fields=['time'])
                assert kwargs.get('images'), 'follow-up must retain the current source images'
                assert data['task_scope']=='external' and not data['mail_context']['mails']
                return {'reply':'年份已确认。第8项的具体日期是什么时候？','events':events}
            if '只知道日期' in question:
                return {'reply':'已整理。','events':[{**EXAM,'title':'日期待定钟点考试','start':'2026-12-01','end':'','timePrecision':'date','missing_fields':['time']}]}
            events=[DEADLINE, EXAM]
            if '不完整' in question:
                events=[{**EXAM, 'end':'', 'uncertainty':'缺少考试结束时间'}]
            return {'reply':'已整理出以下事项。', 'events':events, 'source_ids':[]}

        @app.get('/fixture-login')
        def fixture_login():
            uid, session, csrf = secrets.token_hex(16), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with app.store.db() as connection:
                connection.execute('INSERT INTO users VALUES (?,?,?)',(uid,uid+'@example.com',password_hash('fixture-password-only')))
                connection.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(session),uid,csrf,time.time()+3600))
            engine=app.store.engine(uid)
            engine.CFG.update(key='fixture-only',model='fixture-vision')
            engine.ai_services.complete=staticmethod(model)
            engine.ai_services.list_models=staticmethod(lambda *args,**kwargs:ModelCatalog(['first-model','second-model'],{'first-model':'DeepSeek-V4.1-Flash','second-model':'DeepSeek-V4-Pro'}))
            response=redirect('/#chat')
            response.set_cookie('mail_session',session,httponly=True,samesite='Lax')
            return response

        server=make_server('127.0.0.1',0,app,threaded=True)
        origin='http://127.0.0.1:'+str(server.server_port)
        app.config['MAIL_ALLOWED_ORIGINS']={origin}
        print(origin,flush=True)
        signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
        server.serve_forever()

if __name__=='__main__':main()
