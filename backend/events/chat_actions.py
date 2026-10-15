"""Persist proposals separately from mail; only explicit server-side decisions save items."""
import json
import secrets
import time
from datetime import datetime
from backend.core.user_errors import UserFacingError
from backend.events import event_join

MAX_EVENTS = 30


def clean_proposal(item):
    if not isinstance(item, dict):
        return None
    event = {name: str(item.get(name) or '').strip()[:limit] for name, limit in
             [('title', 160), ('start', 40), ('end', 40), ('location', 300), ('action', 1000), ('evidence', 400)]}
    if not event['title'] or item.get('kind') not in ('活动', '截止'):
        return None
    event.update(kind=item['kind'], allDay=item.get('allDay') is True)
    reason = str(item.get('uncertainty') or '').strip()[:400]
    try:
        if not event['evidence']:
            raise ValueError('缺少时间出处，请补充信息后重新整理。')
        if not re_full_datetime(event['start']):
            raise ValueError('日期或时间不完整，请补充后重新整理。')
        start = datetime.fromisoformat(event['start'])
        if start.tzinfo or not 2000 <= start.year <= 2100:
            raise ValueError('请明确 2000—2100 年间的本地日期和时间。')
        if event['allDay'] and start.time() != datetime.min.time():
            raise ValueError('全天事项需要核对日期。')
        event['start'] = start.isoformat(timespec='minutes')
        if event['kind'] == '截止':
            event['end'] = ''
        else:
            if not re_full_datetime(event['end']):
                raise ValueError('日程缺少结束时间，请补充后重新整理。')
            end = datetime.fromisoformat(event['end'])
            if end.tzinfo or end <= start or (end-start).days > 31:
                raise ValueError('日程起止时间无效，请核对后重新整理。')
            if event['allDay'] and end.time() != datetime.min.time():
                raise ValueError('全天日程需要核对结束日期。')
            event['end'] = end.isoformat(timespec='minutes')
    except (TypeError, ValueError) as error:
        reason = reason or str(error) or '日期无效，请补充后重新整理。'
    return event, reason


def re_full_datetime(value):
    import re
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?', value))


def proposals(connection, message_id):
    output = []
    for row in connection.execute('SELECT * FROM chat_event_proposals WHERE message_id=? ORDER BY rowid', (message_id,)):
        event = json.loads(row['event'])
        status = row['status']
        if status in ('added', 'duplicate') and row['saved_id']:
            saved = connection.execute('SELECT state FROM event_overrides WHERE mail_id=? AND event_index=?',
                                       (row['saved_id'], row['saved_index'])).fetchone()
            if saved and saved['state'] == 'removed':
                status = 'removed'
            elif saved and saved['state'] == 'completed':
                status = 'completed'
        output.append({'id': row['id'], 'event': event, 'status': status, 'note': row['note'],
                       'savedId': row['saved_id'], 'savedIndex': row['saved_index']})
    return output


def create(connection, message_id, items, automatic):
    if not isinstance(items, list):
        return
    for item in items[:MAX_EVENTS]:
        cleaned = clean_proposal(item)
        if not cleaned:
            continue
        event, reason = cleaned
        ident = secrets.token_urlsafe(18)
        connection.execute('INSERT INTO chat_event_proposals(id,message_id,event,status,note) VALUES (?,?,?,?,?)',
                           (ident, message_id, json.dumps(event, ensure_ascii=False), 'needs_info' if reason else 'pending', reason))
        if automatic and not reason:
            add(connection, ident, automatic=True)


def add(connection, ident, automatic=False, separate=False):
    if not isinstance(ident, str) or not ident or len(ident) > 80:
        raise UserFacingError('事项编号无效。')
    row = connection.execute('SELECT * FROM chat_event_proposals WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise UserFacingError('找不到这条对话事项。')
    if row['status'] in ('added', 'duplicate'):
        return proposals(connection, row['message_id'])
    event, reason = clean_proposal(json.loads(row['event']))
    if row['status'] == 'needs_info' or reason:
        raise UserFacingError(row['note'] or reason)
    # A private source record reuses existing editing, calendar-feed and completion
    # logic without creating a fake inbox email or retaining image bytes.
    source = 'chat-event:' + ident
    message = connection.execute('SELECT conversation_id FROM chat_messages WHERE id=?', (row['message_id'],)).fetchone()
    connection.execute('INSERT OR IGNORE INTO mails(id,subject,display_title,date,body,result,created,source,is_deleted) VALUES (?,?,?,?,?,?,?,?,1)',
                       (source, event['title'], event['title'], event['start'][:10], '',
                        json.dumps({'events': [event], 'category': 'AI 对话', 'conversationId': message['conversation_id']}, ensure_ascii=False),
                        time.time(), 'chat'))
    check = event_join.check(connection, {'id': source, 'index': 0})
    exact = next((candidate for candidate in check['candidates'] if candidate['exact']), None)
    if exact:
        target, index = exact['id'], exact['index']
        connection.execute("UPDATE chat_event_proposals SET status='duplicate',note='已有相同事项，未重复添加。',saved_id=?,saved_index=? WHERE id=?", (target, index, ident))
        connection.execute('DELETE FROM mails WHERE id=?', (source,))
    elif check['candidates'] and not separate:
        connection.execute("UPDATE chat_event_proposals SET status='conflict',note='发现相似事项，请核对后选择另行添加。' WHERE id=?", (ident,))
        connection.execute('DELETE FROM mails WHERE id=?', (source,))
    else:
        if event['kind'] == '截止':
            connection.execute("INSERT INTO pins VALUES (?,?,?,?,'active')", (source, 0, event['title'], event['start']))
        else:
            connection.execute("INSERT INTO calendar_events(mail_id,event_index,status,calendar_name,detail,created) VALUES (?,0,'subscribed','TimeMate',?,?)",
                               (source, json.dumps({**event, 'id': source, 'index': 0, 'timeZone': 'Asia/Shanghai'}, ensure_ascii=False), time.time()))
        connection.execute("INSERT INTO event_overrides VALUES (?,0,'{}','active')", (source,))
        connection.execute("UPDATE chat_event_proposals SET status='added',note=?,saved_id=?,saved_index=0 WHERE id=?",
                           ('已自动添加。' if automatic else '已添加。', source, ident))
    return proposals(connection, row['message_id'])
