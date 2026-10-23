"""OAuth authorization-code + PKCE and revocable, account-scoped agent grants."""
import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit

SCOPES = {'mail:read', 'mail:write', 'items:read', 'items:write', 'changes:read'}
DEFAULT_SCOPE = 'mail:read mail:write items:read changes:read'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def scopes(value):
    if not isinstance(value, str) or not value.split() or set(value.split()) - SCOPES:
        raise ValueError('权限范围无效。')
    return ' '.join(sorted(set(value.split())))


def install_schema(store):
    with store.db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS agent_clients (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, redirects TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_grants (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_id TEXT NOT NULL,
          name TEXT NOT NULL, provider TEXT NOT NULL, scope TEXT NOT NULL,
          created REAL NOT NULL, expires REAL NOT NULL, last_used REAL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS agent_tokens (
          hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL, kind TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_codes (
          hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_id TEXT NOT NULL,
          redirect_uri TEXT NOT NULL, challenge TEXT NOT NULL, scope TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_subscriptions (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, grant_id TEXT NOT NULL, kind TEXT NOT NULL,
          name TEXT NOT NULL, url TEXT NOT NULL, secret BLOB NOT NULL, cursor INTEGER NOT NULL,
          expires REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, pending TEXT,
          attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
          last_delivery REAL, last_ack REAL, last_error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS agent_deliveries (
          event_id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, grant_id TEXT NOT NULL,
          user_id TEXT NOT NULL, created REAL NOT NULL, acknowledged REAL);
        CREATE INDEX IF NOT EXISTS agent_grants_owner ON agent_grants(user_id);
        CREATE INDEX IF NOT EXISTS agent_tokens_grant ON agent_tokens(grant_id);
        ''')
        columns={row[1] for row in c.execute('PRAGMA table_info(agent_subscriptions)')}
        if 'previous_secret' not in columns: c.execute('ALTER TABLE agent_subscriptions ADD COLUMN previous_secret BLOB')
        if 'previous_secret_until' not in columns: c.execute('ALTER TABLE agent_subscriptions ADD COLUMN previous_secret_until REAL')


def remove_user(c, uid):
    c.execute('DELETE FROM agent_tokens WHERE grant_id IN (SELECT id FROM agent_grants WHERE user_id=?)', (uid,))
    for table in ('agent_codes', 'agent_subscriptions', 'agent_deliveries', 'agent_grants'):
        c.execute(f'DELETE FROM {table} WHERE user_id=?', (uid,))


def create_grant(store, uid, name, provider, scope=DEFAULT_SCOPE, client_id='manual', connection=None):
    scope = scopes(scope)
    ident = secrets.token_hex(16)
    expires = time.time() + 90 * 86400
    def insert(c):
        if c.execute('SELECT COUNT(*) FROM agent_grants WHERE user_id=? AND revoked=0 AND expires>?', (uid,time.time())).fetchone()[0] >= 20:
            raise ValueError('最多连接 20 个 Agent，请先移除不用的连接。')
        c.execute('INSERT INTO agent_grants VALUES (?,?,?,?,?,?,?,?,NULL,0)', (ident, uid, client_id, name[:80], provider, scope, time.time(), expires))
    if connection is not None:
        insert(connection)
    else:
        with store.db() as c: insert(c)
    return ident, expires


def issue(c, grant_id, kind, ttl):
    raw = 'tm_' + secrets.token_urlsafe(32)
    c.execute('INSERT INTO agent_tokens VALUES (?,?,?,?)', (digest(raw), grant_id, kind, time.time()+ttl))
    return raw


def authenticate(store, raw):
    if not isinstance(raw, str) or len(raw)>200: return None
    with store.db() as c:
        row=c.execute('''SELECT g.* FROM agent_tokens t JOIN agent_grants g ON g.id=t.grant_id
          JOIN users u ON u.id=g.user_id WHERE t.hash=? AND t.kind IN ('access','personal')
          AND t.expires>? AND g.expires>? AND g.revoked=0''', (digest(raw),time.time(),time.time())).fetchone()
        if row:
            c.execute('UPDATE agent_grants SET last_used=? WHERE id=?', (time.time(),row['id']))
            return dict(row)
    return None


def revoke(c, uid, ident):
    if not c.execute('UPDATE agent_grants SET revoked=1 WHERE id=? AND user_id=?', (ident,uid)).rowcount:
        raise ValueError('找不到这个连接。')
    c.execute('DELETE FROM agent_tokens WHERE grant_id=?', (ident,))
    c.execute('DELETE FROM agent_subscriptions WHERE grant_id=?', (ident,))
    c.execute('DELETE FROM agent_deliveries WHERE grant_id=?', (ident,))


def redirect_valid(value):
    if not isinstance(value, str) or len(value)>2000 or any(ord(x)<33 for x in value): return False
    u=urlsplit(value)
    return bool(u.scheme=='https' and u.hostname and not u.username and not u.password and not u.fragment)


def register_client(store, data):
    redirects=data.get('redirect_uris')
    name=data.get('client_name','个人 Agent')
    if not isinstance(name,str) or not name.strip() or len(name)>80: raise ValueError('客户端名称无效。')
    if not isinstance(redirects,list) or not 1<=len(redirects)<=5 or not all(redirect_valid(u) for u in redirects):
        raise ValueError('需要完整的 HTTPS 回调地址。')
    if data.get('token_endpoint_auth_method','none')!='none': raise ValueError('只支持 PKCE 公共客户端。')
    if set(data.get('grant_types',['authorization_code','refresh_token']))-{'authorization_code','refresh_token'}:
        raise ValueError('授权类型不支持。')
    ident=secrets.token_urlsafe(24)
    with store.db() as c:
        c.execute('DELETE FROM agent_clients WHERE created<? AND id NOT IN (SELECT client_id FROM agent_grants WHERE revoked=0)', (time.time()-30*86400,))
        c.execute('INSERT INTO agent_clients VALUES (?,?,?,?)', (ident,name.strip(),json.dumps(redirects),time.time()))
    return {'client_id':ident,'client_name':name,'redirect_uris':redirects,'token_endpoint_auth_method':'none',
            'grant_types':['authorization_code','refresh_token'],'response_types':['code']}


def validate_authorize(store, data, origin):
    with store.db() as c: client=c.execute('SELECT * FROM agent_clients WHERE id=?',(str(data.get('client_id','')),)).fetchone()
    if not client or data.get('redirect_uri') not in json.loads(client['redirects']): raise ValueError('客户端或回调地址无效。')
    if data.get('response_type')!='code' or data.get('resource')!=origin+'/mcp': raise ValueError('授权资源无效。')
    if data.get('code_challenge_method')!='S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}',str(data.get('code_challenge',''))):
        raise ValueError('需要 PKCE S256 验证。')
    if len(str(data.get('state','')))>1000: raise ValueError('授权状态无效。')
    return dict(client), scopes(data.get('scope',DEFAULT_SCOPE))


def exchange(store, data, origin):
    if data.get('resource')!=origin+'/mcp': raise ValueError('invalid_target')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if data.get('grant_type')=='authorization_code':
            row=c.execute('SELECT * FROM agent_codes WHERE hash=? AND expires>?',(digest(str(data.get('code',''))),time.time())).fetchone()
            verifier=str(data.get('code_verifier',''))
            if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}',verifier): raise ValueError('invalid_grant')
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            if not row or row['client_id']!=data.get('client_id') or row['redirect_uri']!=data.get('redirect_uri') or not secrets.compare_digest(challenge,row['challenge']):
                raise ValueError('invalid_grant')
            client=c.execute('SELECT name FROM agent_clients WHERE id=?',(row['client_id'],)).fetchone()
            if not c.execute('SELECT 1 FROM users WHERE id=?',(row['user_id'],)).fetchone(): raise ValueError('invalid_grant')
            grant,_=create_grant(store,row['user_id'],client['name'],'oauth',row['scope'],row['client_id'],c)
            scope=row['scope']
            c.execute('DELETE FROM agent_codes WHERE hash=?',(row['hash'],))
        elif data.get('grant_type')=='refresh_token':
            row=c.execute('''SELECT t.hash,g.* FROM agent_tokens t JOIN agent_grants g ON g.id=t.grant_id
              JOIN users u ON u.id=g.user_id WHERE t.hash=? AND t.kind='refresh' AND t.expires>?
              AND g.expires>? AND g.revoked=0''',(digest(str(data.get('refresh_token',''))),time.time(),time.time())).fetchone()
            if not row or row['client_id']!=data.get('client_id'): raise ValueError('invalid_grant')
            grant,scope=row['id'],row['scope']
            c.execute('DELETE FROM agent_tokens WHERE hash=?',(row['hash'],))
        else: raise ValueError('unsupported_grant_type')
        return {'access_token':issue(c,grant,'access',3600),'token_type':'Bearer','expires_in':3600,
                'refresh_token':issue(c,grant,'refresh',90*86400),'scope':scope}
