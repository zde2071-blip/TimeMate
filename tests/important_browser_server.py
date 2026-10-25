"""Isolated account and real event routes for the important-items browser regression."""
import json, secrets, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
from flask import redirect
from werkzeug.serving import make_server
from backend.cloud import create_app, digest, password_hash
with tempfile.TemporaryDirectory(prefix='timemate-important-') as directory:
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
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        stamp = lambda offset, hour=0: (today + timedelta(days=offset, hours=hour)).isoformat(timespec='minutes')
        data = [
            ('history', '上周课程讨论', '活动', stamp(-4, 10), stamp(-4, 11), '整理课堂笔记', False),
            ('overdue', '课程报告截止', '截止', stamp(-2, 23), '', '提交报告与实验数据', False),
            ('ongoing', '期末复习周', '活动', stamp(-1), stamp(4), '按复习计划完成每日练习', True),
            ('unknown', '今天的课程通知', '活动', stamp(0), '', '确认课堂安排', False),
            ('completed', '已提交课程作业', '截止', stamp(-3, 23), '', '提交最终作业', False),
        ]
        for i in range(28):
            data.append(('item-' + str(i), ['ADS102 课程练习与课堂讨论', 'Lab Exercise #6.1 Clock Constructor 测验', '课程报告材料提交'][i % 3] + ' ' + str(i + 1), '截止' if i % 2 else '活动', stamp(i // 4, 23 if i % 2 else 14), '' if i % 2 else stamp(i // 4, 16), ['完成本周练习并上传 Learning Mall', '携带电脑参加实验，提前检查开发环境', '整理实验记录并核对提交格式'][i % 3], False))
        with engine.db() as c:
            for ident, title, kind, start, end, action, all_day in data:
                event = dict(title=title, kind=kind, start=start, end=end, action=action, allDay=all_day, location='MB204' if kind == '活动' else 'Learning Mall')
                result = json.dumps(dict(category='课程与教学', summary='请核对课程安排。', events=[event]), ensure_ascii=False)
                c.execute('INSERT INTO mails(id,subject,sender,date,sent_date,body,source_body,result,created,source,is_read) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (ident,title,'office@example.edu',stamp(-5),stamp(-5),'课程安排原文','课程安排原文',result,time.time(),'manual',1))
                if kind == '活动':
                    c.execute('INSERT INTO calendar_events(mail_id,event_index,status,calendar_name,detail,created) VALUES (?,0,\'subscribed\',\'TimeMate\',?,?)', (ident, json.dumps(event), time.time()))
                else:
                    c.execute('INSERT INTO pins VALUES (?,0,?,?,?)', (ident, title, start, 'completed' if ident == 'completed' else 'active'))
        response = redirect('/')
        response.set_cookie('mail_session', session, httponly=True, samesite='Lax')
        return response
    server = make_server('127.0.0.1', 0, app, threaded=True)
    origin = 'http://127.0.0.1:' + str(server.server_port)
    app.config['MAIL_ALLOWED_ORIGINS'] = {origin}
    print(origin, flush=True)
    server.serve_forever()
