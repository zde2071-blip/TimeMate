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
from backend.core.ai_services import AIServiceError
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
