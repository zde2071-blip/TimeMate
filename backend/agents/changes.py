"""Transactional, metadata-only change journal in each user's mail database."""

def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS agent_changes (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, record_id TEXT NOT NULL,
      item_index INTEGER, operation TEXT NOT NULL, created REAL NOT NULL)''')
    # Triggers make UI, importer and agent changes equally durable with their writes.
    for table,entity,key,index,fields in (
        ('mails','mail','id','NULL',('is_read','is_deleted','result','manual_category')),
        ('pins','item','mail_id','event_index',('title','due','state')),
        ('calendar_events','item','mail_id','event_index',('status','detail')),
        ('event_overrides','item','mail_id','event_index',('fields','state')),
        ('event_links','item','mail_id','event_index',('target_mail_id','target_index')),
    ):
        for action in ('INSERT','UPDATE','DELETE'):
            ref='OLD' if action=='DELETE' else 'NEW'
            idx='NULL' if index=='NULL' else ref+'.'+index
            condition=' WHEN '+ ' OR '.join('OLD.'+f+' IS NOT NEW.'+f for f in fields) if action=='UPDATE' else ''
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS agent_{table}_{action.lower()}
              AFTER {action} ON {table}{condition} BEGIN
              INSERT INTO agent_changes(entity,record_id,item_index,operation,created)
              VALUES ('{entity}',{ref}.{key},{idx},'{action.lower()}',CAST(strftime('%s','now') AS REAL)); END''')


def latest(engine):
    with engine.db() as c:
        return c.execute('SELECT COALESCE(MAX(seq),0) FROM agent_changes').fetchone()[0]


def read(engine,cursor,limit=50):
    if type(cursor) is not int or cursor<0: raise ValueError('变更位置无效。')
    with engine.db() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM agent_changes WHERE seq>? ORDER BY seq LIMIT ?', (cursor,limit+1))]
    more=len(rows)>limit
    rows=rows[:limit]
    return {'changes':rows,'cursor':rows[-1]['seq'] if rows else cursor,'has_more':more}
