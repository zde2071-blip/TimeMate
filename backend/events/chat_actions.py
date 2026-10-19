"""Persist proposals separately from mail; only explicit server-side decisions save items."""
import json
import secrets
import time
from datetime import datetime, timedelta
import re
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
    missing = item.get('missing_fields')
    structured = isinstance(missing, list) and all(isinstance(x, str) and x in ('year','date','time','end','location','timezone','evidence') for x in missing)
    uncertainty = str(item.get('uncertainty') or '').strip()[:400]
    reason = ''
    if structured:
        event['missing_fields'] = list(dict.fromkeys(missing))
        blocked = set(missing) & {'year','date','timezone','evidence'}
        if blocked:
            labels = {'year':'年份','date':'具体日期','timezone':'时区','evidence':'时间出处'}
            reason = '请确认' + '、'.join(labels[x] for x in ('year','date','timezone','evidence') if x in blocked) + '。'
    else:
        # Older clients/models use a single uncertainty string. Only narrowly
        # recognized optional gaps are non-blocking; ambiguous dates stay blocked.
        optional = bool(re.search(r'地点|场地|时刻|钟点|时段|截止时间|起止|结束时间', uncertainty))
        critical = bool(re.search(r'年份|日期.*(不明|不清|未定|冲突)|时区|推断|推定|考试周|周次', uncertainty))
        reason = uncertainty if uncertainty and (not optional or critical) else ''
    date_only = item.get('timePrecision') == 'date' or structured and bool(set(missing) & {'time','end'})
    event['timePrecision'] = 'date' if date_only else 'datetime'
    if isinstance(item.get('annotation'),str): event['annotation'] = item['annotation'][:400]
    event['timeZone'] = str(item.get('timeZone') or 'Asia/Shanghai')[:80]
    if uncertainty and not reason:
        event['annotation'] = uncertainty
    try:
        if not event['evidence']:
            raise ValueError('请确认事项的日期出处。')
        raw = event['start']
        if date_only and re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?', raw):
            start = datetime.fromisoformat(raw[:10])
            event['allDay'] = True
            event['start'] = start.isoformat(timespec='minutes')
            event['end'] = (start + timedelta(days=1)).isoformat(timespec='minutes') if event['kind'] == '活动' else ''
            if item.get('start') and 'T' in item['start'] and item['start'][11:16] != '00:00':
                event['annotation'] = '开始时间 ' + item['start'][11:16] + '，结束时间待定。'
        else:
            if not re_full_datetime(raw):
                raise ValueError('请确认具体日期。')
            start = datetime.fromisoformat(raw)
            event['start'] = start.isoformat(timespec='minutes')
            if event['kind'] == '截止':
                event['end'] = ''
            else:
                if not re_full_datetime(event['end']):
                    raise ValueError('请补充结束时间，或选择按日期记录。')
                end = datetime.fromisoformat(event['end'])
                if end.tzinfo or end <= start or (end-start).days > 31:
                    raise ValueError('日程起止时间无效，请核对后重新整理。')
                if event['allDay'] and end.time() != datetime.min.time():
                    raise ValueError('全天日程需要核对结束日期。')
                event['end'] = end.isoformat(timespec='minutes')
        if start.tzinfo or not 2000 <= start.year <= 2100:
            raise ValueError('请明确 2000—2100 年间的本地日期和时间。')
        if event['allDay'] and start.time() != datetime.min.time():
            raise ValueError('请核对按日期记录的事项。')
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try: ZoneInfo(event['timeZone'])
        except (ValueError, ZoneInfoNotFoundError): raise ValueError('请确认有效的时区。') from None
    except (TypeError, ValueError) as error:
        reason = reason or str(error) or '请确认日期。'
    return event, reason


def re_full_datetime(value):
    import re
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?', value))


def proposals(connection, message_id):
    output = []
    for row in connection.execute("SELECT * FROM chat_event_proposals WHERE message_id=? AND status!='superseded' ORDER BY rowid", (message_id,)):
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


def create(connection, message_id, items, automatic, conversation_id=None, batch_id='', allow_date_only=False):
    if not isinstance(items, list) or not items:
        return
    existing = []
    if conversation_id:
        existing = connection.execute("SELECT p.* FROM chat_event_proposals p JOIN chat_messages m ON m.id=p.message_id WHERE m.conversation_id=? AND p.batch_id=? AND p.status!='superseded' ORDER BY p.rowid DESC", (conversation_id,batch_id)).fetchall()
    used, seen_items = set(), set()
    for item in items[:MAX_EVENTS]:
        cleaned = clean_proposal(item)
        if not cleaned:
            continue
        event, reason = cleaned
        fingerprint = json.dumps(event, sort_keys=True, ensure_ascii=False)
        if fingerprint in seen_items:
            continue
        seen_items.add(fingerprint)
        match = next((row for row in existing if row['id'] == item.get('id')), None)
        if match is None:
            candidates = [row for row in existing if json.loads(row['event']).get('kind') == event['kind'] and event_join.normalized(json.loads(row['event']).get('title')) == event_join.normalized(event['title'])]
            match = next((row for row in candidates if json.loads(row['event']).get('start') == event['start']), None)
            # A single renamed-date proposal may update by title. Repeated
            # sessions with the same title require their stable ID or date.
            same_title = sum(isinstance(x,dict) and x.get('kind') == event['kind'] and event_join.normalized(x.get('title','')) == event_join.normalized(event['title']) for x in items)
            if match is None and len(candidates) == 1 and same_title == 1:
                match = candidates[0]
        if match and match['id'] in used:
            continue
        if match:
            ident = match['id']
            used.add(ident)
            if match['status'] in ('added','duplicate','removed','completed'):
                continue
            connection.execute('UPDATE chat_event_proposals SET message_id=?,event=?,status=?,note=? WHERE id=?',
                (message_id,json.dumps(event,ensure_ascii=False),'needs_info' if reason else 'pending',reason,ident))
        else:
            ident = secrets.token_urlsafe(18)
            connection.execute('INSERT INTO chat_event_proposals(id,message_id,event,status,note,batch_id) VALUES (?,?,?,?,?,?)',
                (ident,message_id,json.dumps(event,ensure_ascii=False),'needs_info' if reason else 'pending',reason,batch_id))
        if automatic and not reason and (event.get('timePrecision') != 'date' or event['kind']=='截止' or allow_date_only):
            add(connection,ident,automatic=True,allow_date_only=allow_date_only)
    if conversation_id:
        # One current list per source batch; follow-ups update these same IDs.
        connection.execute("UPDATE chat_event_proposals SET message_id=? WHERE message_id IN (SELECT id FROM chat_messages WHERE conversation_id=?) AND batch_id=? AND status!='superseded'", (message_id,conversation_id,batch_id))


def add(connection, ident, automatic=False, separate=False, allow_date_only=False):
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
    if event.get('timePrecision') == 'date' and event['kind'] == '活动' and not allow_date_only:
        raise UserFacingError('此事项尚无具体钟点，请确认按日期添加。')
    # A private source record reuses existing editing, calendar-feed and completion
    # logic without creating a fake inbox email or retaining image bytes.
    source = 'chat-event:' + ident
    message = connection.execute('SELECT conversation_id FROM chat_messages WHERE id=?', (row['message_id'],)).fetchone()
    connection.execute('INSERT OR IGNORE INTO mails(id,subject,display_title,date,body,result,created,source,is_deleted) VALUES (?,?,?,?,?,?,?,?,1)',
                       (source, event['title'], event['title'], event['start'][:10], '',
                        json.dumps({'events': [event], 'category': 'AI 对话', 'conversationId': message['conversation_id']}, ensure_ascii=False),
                        time.time(), 'chat'))
    check = event_join.check(connection, {'id': source, 'index': 0})
    # Distinct entries selected from one material list are allowed together.
    # Keep exact deduplication and all conflicts against older material batches.
    siblings = {p['saved_id'] for p in connection.execute(
        'SELECT p.saved_id FROM chat_event_proposals p JOIN chat_messages m ON m.id=p.message_id WHERE m.conversation_id=? AND p.batch_id=? AND p.id!=? AND p.saved_id IS NOT NULL',
        (message['conversation_id'], row['batch_id'], ident))}
    check['candidates'] = [p for p in check['candidates'] if p['exact'] or p['id'] not in siblings]
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
                               (source, json.dumps({**event, 'id': source, 'index': 0, 'timeZone': event.get('timeZone','Asia/Shanghai')}, ensure_ascii=False), time.time()))
        connection.execute("INSERT INTO event_overrides VALUES (?,0,'{}','active')", (source,))
        connection.execute("UPDATE chat_event_proposals SET status='added',note=?,saved_id=?,saved_index=0 WHERE id=?",
                           ('已自动添加。' if automatic else '已添加。', source, ident))
    return proposals(connection, row['message_id'])


def edit(connection, data):
    ident = data.get('id')
    row = connection.execute('SELECT * FROM chat_event_proposals WHERE id=?',(ident,)).fetchone() if isinstance(ident,str) else None
    if row is None: raise UserFacingError('找不到这条对话事项。')
    if row['status'] not in ('pending','needs_info','conflict'):
        raise UserFacingError('已添加的事项请到重要事项中编辑。')
    fields = data.get('fields')
    if not isinstance(fields,dict): raise UserFacingError('事项修改内容无效。')
    event = json.loads(row['event'])
    for key in ('title','start','end','location','action','timePrecision','timeZone','allDay'):
        if key in fields: event[key] = fields[key]
    event['missing_fields'] = []
    event['uncertainty'] = ''
    event['evidence'] = '用户核对：' + str(event.get('start',''))
    cleaned = clean_proposal(event)
    if not cleaned or cleaned[1]: raise UserFacingError(cleaned[1] if cleaned else '请填写事项主题。')
    connection.execute("UPDATE chat_event_proposals SET event=?,status='pending',note='' WHERE id=?",(json.dumps(cleaned[0],ensure_ascii=False),ident))
    return proposals(connection,row['message_id'])
