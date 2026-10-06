"""Explicit, user-reviewed linking of mail candidates to saved items."""
import json
import re
import unicodedata
from difflib import SequenceMatcher

FIELDS=('title','action','start','end','location','allDay')
LABELS={'title':'事项主题','action':'待办','start':'开始／截止时间','end':'结束时间','location':'地点','allDay':'全天'}

def key(data):
    ident,index=data.get('id'),data.get('index')
    if not isinstance(ident,str) or not ident or not isinstance(index,int) or isinstance(index,bool):
        raise ValueError('事项编号无效。')
    return ident,index

def resolve(c,ident,index):
    row=c.execute('SELECT target_mail_id,target_index FROM event_links WHERE mail_id=? AND event_index=?',(ident,index)).fetchone()
    return (row['target_mail_id'],row['target_index']) if row else (ident,index)

def raw_event(c,ident,index):
    row=c.execute("SELECT result FROM mails WHERE id=? AND is_deleted=0 AND source NOT IN ('simulation','test_archive')",(ident,)).fetchone()
    events=json.loads(row['result']).get('events',[]) if row and row['result'] else []
    if index<0 or index>=len(events) or events[index].get('kind') not in ('活动','截止'):
        raise ValueError('找不到这条事项。')
    event=dict(events[index])
    if len(events)==1 and not event.get('action'):event['action']=json.loads(row['result']).get('action','')
    return event

def effective(c,ident,index):
    event=raw_event(c,ident,index)
    saved=c.execute("SELECT detail FROM calendar_events WHERE mail_id=? AND event_index=? AND status IN ('saved','subscribed')",(ident,index)).fetchone()
    if saved:
        detail=json.loads(saved['detail'] or '{}')
        event.update({name:detail[name] for name in FIELDS if name in detail})
    override=c.execute('SELECT fields FROM event_overrides WHERE mail_id=? AND event_index=?',(ident,index)).fetchone()
    if override:event.update(json.loads(override['fields'] or '{}'))
    return event

def normalized(value):
    text=unicodedata.normalize('NFKC',str(value or '')).casefold()
    return ''.join(char for char in text if char.isalnum())

def snapshot(event):
    values={name:(bool(event.get(name)) if name=='allDay' else str(event.get(name) or '')[:16] if name in ('start','end') else str(event.get(name) or '').strip()) for name in FIELDS}
    # Old all-day deadlines carry a calendar-style next-day end; deadlines have only one time.
    if event.get('kind')=='截止':values['end']=''
    return values

def same(a,b):
    a,b=snapshot(a),snapshot(b)
    return all(a[name]==b[name] if name in ('start','end','allDay') else normalized(a[name])==normalized(b[name]) for name in FIELDS)

def similarity(a,b):
    title_a,title_b=normalized(a.get('title')),normalized(b.get('title'))
    if not title_a or not title_b:return 0
    codes=lambda text:set(re.findall(r'[a-z]{3}\d{3}',text))
    if codes(title_a) and codes(title_b) and codes(title_a)!=codes(title_b):return 0
    if title_a==title_b:return 1
    return SequenceMatcher(None,title_a,title_b).ratio()

def saved_keys(c,kind):
    if kind=='截止':
        return [(r['mail_id'],r['event_index']) for r in c.execute("SELECT mail_id,event_index FROM pins WHERE state IN ('active','completed')")]
    return [(r['mail_id'],r['event_index']) for r in c.execute("SELECT mail_id,event_index FROM calendar_events WHERE status IN ('saved','subscribed')")]

def check(c,data):
    ident,index=key(data)
    incoming=effective(c,ident,index)
    # Calendar confirmation can supply user-reviewed time/location values.
    incoming.update({name:data[name] for name in FIELDS if name in data})
    candidates=[]
    for target,target_index in saved_keys(c,incoming['kind']):
        if (target,target_index)==(ident,index):continue
        try:
            original=raw_event(c,target,target_index)
            current=effective(c,target,target_index)
        except ValueError:continue
        score=max(similarity(incoming,current),similarity(incoming,original))
        if score<0.55:continue
        exact=same(incoming,current)
        before,after,base=snapshot(current),snapshot(incoming),snapshot(original)
        changes=[{'field':name,'label':LABELS[name],'before':before[name],'after':after[name],
                  'edited':before[name]!=base[name]}
                 for name in FIELDS if before[name]!=after[name] and
                 (name=='allDay' or after[name] not in ('','未说明','待确认','地点待确认','时间待确认'))]
        calendar=c.execute('SELECT status FROM calendar_events WHERE mail_id=? AND event_index=?',(target,target_index)).fetchone()
        candidates.append({'id':target,'index':target_index,'event':before,'exact':exact,
                           'confidence':'same' if score==1 else 'uncertain','changes':changes,'score':score,
                           'calendarStatus':calendar['status'] if calendar else ''})
    candidates.sort(key=lambda x:(x['exact'],x['score']),reverse=True)
    return {'incoming':snapshot(incoming),'kind':incoming['kind'],'candidates':candidates}

def link(c,data):
    ident,index=key(data)
    target,target_index=key({'id':data.get('targetId'),'index':data.get('targetIndex')})
    if (ident,index)==(target,target_index):raise ValueError('不能把事项关联到自身。')
    incoming=raw_event(c,ident,index)
    target_event=effective(c,target,target_index)
    if incoming['kind']!=target_event['kind'] or (target,target_index) not in saved_keys(c,incoming['kind']):
        raise ValueError('目标事项未加入或类型不同。')
    if (ident,index) in saved_keys(c,incoming['kind']):raise ValueError('这条事项已单独加入，请先移除后再关联。')
    if resolve(c,target,target_index)!=(target,target_index):raise ValueError('请关联到原始事项。')
    c.execute('INSERT INTO event_links VALUES (?,?,?,?) ON CONFLICT(mail_id,event_index) DO UPDATE SET target_mail_id=excluded.target_mail_id,target_index=excluded.target_index',
              (ident,index,target,target_index))

def unlink_removed(c,ident,index):
    c.execute('DELETE FROM event_links WHERE target_mail_id=? AND target_index=?',(ident,index))
