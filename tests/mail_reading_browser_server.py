"""Real mail routes and storage with local fixture messages; no external services."""
import json
import secrets
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
from flask import redirect
from werkzeug.serving import make_server
from backend.cloud import create_app, digest, password_hash


with tempfile.TemporaryDirectory(prefix='timemate-mail-reading-') as directory:
    app = create_app(directory, Fernet.generate_key())

    @app.get('/fixture-login')
    def login():
        uid, session, csrf = secrets.token_hex(16), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with app.store.db() as c:
            c.execute('INSERT INTO users VALUES (?,?,?)', (uid, uid + '@example.com', password_hash('fixture-password')))
            c.execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(session), uid, csrf, time.time() + 3600))
        engine = app.store.engine(uid)
        engine.CFG.update(key='fixture-only', model='fixture-model', calendar_method='subscribe')
        app.store.create_calendar_feed(uid, origin)
        engine.ai_services.complete = staticmethod(lambda cfg, prompt, data, **kwargs: {'items': [{'id': item['id'], 'text': '课程通知与考试安排'} for item in data['items']]})
        events = [
            {'title': 'ADS102 课堂测试', 'kind': '活动', 'action': '', 'start': '2026-10-23T14:00', 'end': '2026-10-23T15:00', 'location': 'MB204', 'allDay': False},
            {'title': 'ADS102 报告提交截止', 'kind': '截止', 'action': '', 'start': '2026-10-30T23:59', 'end': '', 'location': 'Learning Mall', 'allDay': False},
        ]
        result = {'category': '课程与教学', 'summary': '课堂测试在 MB204 举行，课程报告须于月底前提交。', 'events': events}
        with engine.db() as c:
            for i, subject in enumerate(['ADS102 课堂测试与报告提交安排', '图书馆开放时间通知']):
                c.execute('INSERT INTO mails(id,subject,sender,date,sent_date,body,source_body,original,result,created,source,is_read) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                          ('reading-' + str(i), subject, 'Academic Affairs <office@example.edu>', '2026-10-20', '2026-10-20T10:24:00+08:00', 'Please attend the examination on Friday.', 'Please attend the examination on Friday.', json.dumps({'html': '<p>Please attend the examination on Friday.</p>', 'external': []}), json.dumps(result if i == 0 else {'category': '校园服务', 'summary': '周末照常开放。', 'events': []}, ensure_ascii=False), time.time() - i, 'manual', 1))
        response = redirect('/#mail')
        response.set_cookie('mail_session', session, httponly=True, samesite='Lax')
        return response

    server = make_server('127.0.0.1', 0, app, threaded=True)
    origin = 'http://127.0.0.1:' + str(server.server_port)
    app.config['MAIL_ALLOWED_ORIGINS'] = {origin}
    print(origin, flush=True)
    server.serve_forever()
