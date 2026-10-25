"""Durable event subscriptions and bounded retry delivery for personal agents."""
import json
import secrets
import threading
import time
from datetime import datetime,timezone
from backend.agents import auth,changes,transport

EVENT_NAME='timemate.changed'


def encoded(value): return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()


def utc(value=None): return datetime.fromtimestamp(value or time.time(),timezone.utc).isoformat()


class AgentService:
    def __init__(self,store,origin):
        self.store,self.origin=store,origin
        self.worker_lock=threading.Lock()
        auth.install_schema(store)

    def feedback_status(self,grant_id):
        with self.store.db() as c:
            rows=c.execute('''SELECT id,kind,enabled,expires,last_delivery,last_ack,last_error,attempts
              FROM agent_subscriptions WHERE grant_id=?''',(grant_id,)).fetchall()
        return [dict(r) for r in rows]

    def connections(self,uid):
        with self.store.db() as c:
            rows=c.execute('''SELECT id,name,provider,scope,created,expires,last_used,
              CASE WHEN client_id='manual' THEN 'personal' ELSE 'oauth' END AS auth_method FROM agent_grants
              WHERE user_id=? AND revoked=0 ORDER BY created DESC''',(uid,)).fetchall()
        connections=[]
        for row in rows:
            item=dict(row)
            item['name'],item['provider']=auth.connection_identity(item['name'],item['provider'])
            connections.append({**item,'feedback':self.feedback_status(row['id'])})
        return connections

    def subscribe(self,grant,delivery,kind='mcp',ttl_ms=None):
        if ttl_ms is not None and (type(ttl_ms) is not int or ttl_ms<=0): raise ValueError('订阅期限无效。')
        if 'changes:read' not in grant['scope'].split(): raise PermissionError('未授予反馈权限。')
        if not isinstance(delivery,dict) or delivery.get('mode')!='webhook': raise ValueError('仅支持 webhook 通知。')
        url,secret=delivery.get('url'),delivery.get('secret')
        parsed,host=transport.checked_url(url)
        ident=auth.digest(grant['id']+'|'+kind+'|'+url)[:32]
        # Verify ownership/reachability before persisting anything. No user data in probe.
        if kind=='mcp':
            transport.secret_bytes(secret)
            challenge=secrets.token_urlsafe(32)
            body=encoded({'type':'verification','challenge':challenge})
            response=transport.post_json(url,body,transport.signed_headers(secret,'verify_'+secrets.token_hex(16),body,ident))
            if not isinstance(response,dict) or not secrets.compare_digest(str(response.get('challenge','')),challenge):
                raise ValueError('通知地址验证失败。')
        else:
            if host!='api2.cursor.sh' or not parsed.path.startswith('/automations/webhook/') or parsed.query:
                raise ValueError('请使用 Grok Bot Routine 提供的 api2.cursor.sh 通知地址。')
            if not isinstance(secret,str) or not 8<=len(secret)<=1000 or any(ord(c)<33 or ord(c)>126 for c in secret):
                raise ValueError('请填写 Routine 的 key。')
            # No background execution until the user explicitly clicks Test.
            transport.public_addresses(host)
        now=time.time()
        lifetime=min(7*86400,ttl_ms/1000) if ttl_ms is not None else 7*86400
        expiry=min(now+lifetime if kind=='mcp' else grant['expires'],grant['expires'])
        cursor=changes.latest(self.store.engine(grant['user_id']))
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM agent_grants WHERE id=? AND user_id=? AND revoked=0 AND expires>?',(grant['id'],grant['user_id'],now)).fetchone():
                raise ValueError('连接已失效。')
            if c.execute('SELECT COUNT(*) FROM agent_subscriptions WHERE grant_id=?',(grant['id'],)).fetchone()[0]>=5 and not c.execute('SELECT 1 FROM agent_subscriptions WHERE id=?',(ident,)).fetchone():
                raise ValueError('通知订阅已达上限。')
            previous=c.execute('SELECT secret FROM agent_subscriptions WHERE id=?',(ident,)).fetchone()
            if previous and self.store.cipher.decrypt(previous['secret']).decode()!=secret:
                c.execute('UPDATE agent_subscriptions SET previous_secret=secret,previous_secret_until=? WHERE id=?',(now+300,ident))
            if kind=='grok':
                # Saving a replacement pauses delivery until the new endpoint is tested.
                c.execute('DELETE FROM agent_deliveries WHERE subscription_id IN (SELECT id FROM agent_subscriptions WHERE grant_id=? AND kind=?)',(grant['id'],kind))
                c.execute('DELETE FROM agent_subscriptions WHERE grant_id=? AND kind=?',(grant['id'],kind))
            c.execute('''INSERT INTO agent_subscriptions(id,user_id,grant_id,kind,name,url,secret,cursor,expires,enabled)
              VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
              secret=excluded.secret,expires=excluded.expires,enabled=excluded.enabled,last_error=''
              ''',(ident,grant['user_id'],grant['id'],kind,EVENT_NAME,url,self.store.cipher.encrypt(secret.encode()),cursor,expiry,int(kind=='mcp')))
        return {'id':ident,'refreshBefore':utc(expiry),'cursor':None,'truncated':False}

    def unsubscribe(self,grant,delivery):
        if not isinstance(delivery,dict) or not isinstance(delivery.get('url'),str): raise ValueError('订阅地址无效。')
        with self.store.db() as c:
            c.execute('DELETE FROM agent_subscriptions WHERE grant_id=? AND user_id=? AND kind=? AND url=?',(grant['id'],grant['user_id'],'mcp',delivery['url']))
        return {}

    def test_feedback(self,uid,subscription_id):
        # A test really starts the Bot. Never schedule duplicate tests on repeated clicks.
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('''SELECT s.* FROM agent_subscriptions s JOIN agent_grants g ON g.id=s.grant_id
              WHERE s.id=? AND s.user_id=? AND g.revoked=0 AND g.expires>? AND s.expires>?''', (subscription_id,uid,time.time(),time.time())).fetchone()
            if not row: raise ValueError('通知连接已失效。')
            if row['pending']: raise ValueError('已有通知等待发送，请稍后检查。')
            event={'eventId':'evt_'+secrets.token_hex(16),'name':EVENT_NAME,'timestamp':utc(),
                   'data':{'test':True,'changes':[],'cursor':row['cursor'],'url':self.origin},'cursor':None}
            c.execute('UPDATE agent_subscriptions SET pending=?,attempts=0,retry_at=0,enabled=1,last_error=? WHERE id=?',
                      (json.dumps({'event':event,'cursor':row['cursor']}),'',subscription_id))
        self.tick(subscription_id)

    def tick(self,only=None):
        if not self.worker_lock.acquire(False): return
        try:
            with self.store.db() as c:
                rows=c.execute('''SELECT s.id FROM agent_subscriptions s JOIN agent_grants g ON g.id=s.grant_id
                  JOIN users u ON u.id=s.user_id WHERE s.enabled=1 AND s.expires>? AND g.revoked=0 AND g.expires>?
                  AND s.retry_at<=? AND (? IS NULL OR s.id=?) ORDER BY s.retry_at LIMIT 25''',
                  (time.time(),time.time(),time.time(),only,only)).fetchall()
                c.execute('DELETE FROM agent_deliveries WHERE created<?',(time.time()-30*86400,))
                c.execute('DELETE FROM agent_codes WHERE expires<?',(time.time(),))
                c.execute('DELETE FROM agent_tokens WHERE expires<?',(time.time(),))
            for row in rows:
                try: self.deliver(row['id'])
                except Exception:
                    # No URLs, bodies or credentials in logs/error strings.
                    with self.store.db() as c:
                        c.execute("UPDATE agent_subscriptions SET retry_at=?,last_error='通知暂未送达，稍后重试' WHERE id=?",(time.time()+60,row['id']))
        finally: self.worker_lock.release()

    def deliver(self,ident):
        with self.store.db() as c:
            row=c.execute('''SELECT s.* FROM agent_subscriptions s JOIN agent_grants g ON g.id=s.grant_id
              JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.enabled=1 AND s.expires>? AND g.revoked=0 AND g.expires>?''',
              (ident,time.time(),time.time())).fetchone()
        if not row: return
        row=dict(row)
        pending=json.loads(row['pending']) if row['pending'] else None
        if not pending:
            batch=changes.read(self.store.engine(row['user_id']),row['cursor'])
            if not batch['changes']:
                with self.store.db() as c:
                    c.execute('UPDATE agent_subscriptions SET retry_at=? WHERE id=?',(time.time()+10,ident))
                return
            pending={'event':{'eventId':'evt_'+secrets.token_hex(16),'name':EVENT_NAME,'timestamp':utc(),
                             'data':{**batch,'url':self.origin},'cursor':None},'cursor':batch['cursor']}
            with self.store.db() as c:
                if not c.execute('UPDATE agent_subscriptions SET pending=? WHERE id=? AND enabled=1 AND pending IS NULL',(json.dumps(pending),ident)).rowcount: return
        event=pending['event']
        with self.store.db() as c:
            # A synchronous Agent may acknowledge before the HTTP response returns.
            if not c.execute('SELECT 1 FROM agent_subscriptions WHERE id=? AND enabled=1',(ident,)).fetchone(): return
            c.execute('INSERT OR IGNORE INTO agent_deliveries VALUES (?,?,?,?,?,NULL)',(event['eventId'],ident,row['grant_id'],row['user_id'],time.time()))
        secret=self.store.cipher.decrypt(row['secret']).decode()
        body=encoded(event)
        headers=transport.signed_headers(secret,event['eventId'],body,ident) if row['kind']=='mcp' else {'Authorization':'Bearer '+secret}
        if row['kind']=='mcp' and row['previous_secret'] and (row['previous_secret_until'] or 0)>time.time():
            old=self.store.cipher.decrypt(row['previous_secret']).decode()
            headers['webhook-signature']+=' '+transport.signed_headers(old,event['eventId'],body,ident,stamp=headers['webhook-timestamp'])['webhook-signature']
        try:
            transport.post_json(row['url'],body,headers)
        except Exception as error:
            terminal=isinstance(error,transport.DeliveryError) and error.status in (410,413)
            attempt=8 if terminal else row['attempts']+1
            # Pause after bounded retries; the user may retry the same stable event ID.
            with self.store.db() as c:
                c.execute('''UPDATE agent_subscriptions SET attempts=?,retry_at=?,enabled=?,last_error=? WHERE id=?''',
                          (attempt,time.time()+min(3600,30*2**min(attempt,7)),int(attempt<8),'通知未送达；请检查 Agent 后重试' if attempt>=8 else '通知暂未送达，稍后重试',ident))
            return
        with self.store.db() as c:
            c.execute('''UPDATE agent_subscriptions SET cursor=?,pending=NULL,attempts=0,retry_at=?,last_delivery=?,last_error=''
              WHERE id=? AND enabled=1''',(pending['cursor'],time.time()+10,time.time(),ident))
