"""Read-only school mailbox OAuth. Credentials never enter browser responses."""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from backend.core.user_errors import UserFacingError
from backend.mail.ingest import MailAuthenticationError

PROVIDERS = {
    'google': {'authorize':'https://accounts.google.com/o/oauth2/v2/auth',
               'token':'https://oauth2.googleapis.com/token',
               'scope':'https://www.googleapis.com/auth/gmail.readonly',
               'api':'https://gmail.googleapis.com'},
    'microsoft': {'authorize':'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
                  'token':'https://login.microsoftonline.com/common/oauth2/v2.0/token',
                  'scope':'offline_access https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read',
                  'api':'https://graph.microsoft.com'},
}

class OAuthError(UserFacingError):
    def __init__(self, kind):
        self.kind = kind
        super().__init__({'unavailable':'此连接方式暂未启用，请使用其他连接方式。',
            'admin':'需要学校管理员批准此应用。','blocked':'学校限制了此应用的邮箱访问。',
            'cancel':'连接已取消。','network':'连接暂时失败，请重试。',
            'permission':'未取得读取邮箱的权限。','expired':'请重新授权邮箱。',
            'invalid':'授权已失效，请重新连接。','busy':'请等待当前操作完成后重试。'}.get(kind,'连接未完成，请重试。'))

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args): return None

def credentials(provider):
    if not isinstance(provider,str) or provider not in PROVIDERS: raise OAuthError('invalid')
    prefix='MAIL_'+provider.upper()+'_'
    return os.environ.get(prefix+'CLIENT_ID','').strip(), os.environ.get(prefix+'CLIENT_SECRET','').strip()

def available():
    return {p:all(credentials(p)) for p in PROVIDERS}

def remote_error(data, status=400):
    # Only explicit provider policy errors are classified as institutional blocks.
    error=data.get('error','') if isinstance(data,dict) else ''
    code=error if isinstance(error,str) else error.get('code','')
    description=str(data.get('error_description','')) if isinstance(data,dict) else ''
    codes=data.get('error_codes',[]) if isinstance(data,dict) else []
    if not isinstance(codes,list): codes=[]
    if code in ('invalid_client','unauthorized_client'): return 'unavailable'
    if code in ('admin_policy_enforced','access_denied_admin') or 90094 in codes or 'AADSTS90094' in description: return 'admin'
    if code in ('org_internal','domain_policy','access_denied_by_policy') or 'AADSTS53003' in description or 53003 in codes: return 'blocked'
    if code=='access_denied': return 'cancel'
    if code=='invalid_grant': return 'expired'
    if status==401: return 'expired'
    if status==403: return 'permission'
    return 'network'

def http(url, token=None, form=None, raw=False):
    headers={'Accept':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    data=None
    if form is not None:
        data=urlencode(form).encode();headers['Content-Type']='application/x-www-form-urlencoded'
    try:
        with build_opener(NoRedirect()).open(Request(url,data=data,headers=headers),timeout=20) as response:
            payload=response.read(30*1024*1024+1)
            if len(payload)>30*1024*1024: raise OAuthError('network')
            return payload if raw else json.loads(payload)
    except HTTPError as error:
        try: detail=json.loads(error.read(65536))
        except (ValueError,OSError): detail={}
        raise OAuthError(remote_error(detail,error.code)) from None
    except (URLError,OSError,ValueError): raise OAuthError('network') from None

def api(provider, path, token, raw=False):
    base=PROVIDERS[provider]['api']
    url=path if path.startswith('https://') else base+path
    # Provider-controlled pagination is still validated before forwarding a token.
    if urlsplit(url).scheme!='https' or urlsplit(url).netloc!=urlsplit(base).netloc: raise OAuthError('invalid')
    return http(url,token=token,raw=raw)

def verify(provider, token):
    if provider=='google':
        profile=api(provider,'/gmail/v1/users/me/profile',token)
        listing=api(provider,'/gmail/v1/users/me/messages?maxResults=1',token)
        if listing.get('messages'):
            api(provider,'/gmail/v1/users/me/messages/'+quote(listing['messages'][0]['id'],safe='')+'?format=raw',token)
        address=profile.get('emailAddress','')
    else:
        profile=api(provider,'/v1.0/me?$select=mail,userPrincipalName',token)
        listing=api(provider,'/v1.0/me/mailFolders/inbox/messages?$top=1&$select=id',token)
        if listing.get('value'):
            api(provider,'/v1.0/me/messages/'+quote(listing['value'][0]['id'],safe='')+'/$value',token,raw=True)
        address=profile.get('mail') or profile.get('userPrincipalName','')
    if not isinstance(address,str) or '@' not in address: raise OAuthError('permission')
    return address.casefold()

def load(runtime, provider):
    value=runtime.credential('load','mail-oauth:'+provider)
    try: return json.loads(value) if value else {}
    except ValueError: return {}

def save(runtime, provider, data):
    runtime.credential('save','mail-oauth:'+provider,json.dumps(data))

def access(engine):
    provider=engine.CFG['mail_provider'];data=load(engine.RUNTIME,provider)
    if not data.get('refresh_token'): raise MailAuthenticationError('邮箱授权已失效，请重新连接邮箱。')
    if data.get('expires_at',0)>time.time()+60: return data['access_token']
    ident,secret=credentials(provider)
    if not ident or not secret: raise UserFacingError('邮箱连接服务暂未启用，请联系网站管理员。')
    try:
        result=http(PROVIDERS[provider]['token'],form={'grant_type':'refresh_token','refresh_token':data['refresh_token'],'client_id':ident,'client_secret':secret})
    except OAuthError as error:
        if error.kind=='expired':
            data['reauthorize']=True;save(engine.RUNTIME,provider,data)
            raise MailAuthenticationError('邮箱授权已失效，请重新连接邮箱。') from None
        raise
    if not result.get('access_token'): raise OAuthError('network')
    data.update(access_token=result['access_token'],refresh_token=result.get('refresh_token') or data['refresh_token'],expires_at=time.time()+int(result.get('expires_in',3600)),reauthorize=False)
    save(engine.RUNTIME,provider,data)
    return data['access_token']

def connection_state(engine):
    direct=engine.CFG.get('mail_mode')=='oauth';data=load(engine.RUNTIME,engine.CFG['mail_provider']) if direct else {}
    return {'mode':'oauth' if direct else 'forward','provider':engine.CFG['mail_provider'],
            'account':engine.CFG['account'], 'connected':bool(direct and data.get('refresh_token') and not data.get('reauthorize')),
            'reauthorize':bool(direct and data.get('reauthorize')), 'available':available()}

def install(app, store, origin):
    from flask import request, g, jsonify, redirect
    with store.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS mailbox_oauth_attempts(state TEXT PRIMARY KEY,user_id TEXT,session TEXT,provider TEXT,verifier BLOB,expires REAL)')
    @app.post('/api/mail/oauth/start')
    def start():
        data=request.get_json(silent=True)
        if not isinstance(data,dict): return jsonify(error='请求格式不正确。',kind='invalid'),400
        provider=data.get('provider')
        try:
            ident,secret=credentials(provider)
            if not ident or not secret: raise OAuthError('unavailable')
            nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            with store.db() as c:
                c.execute('DELETE FROM mailbox_oauth_attempts WHERE expires<? OR (user_id=? AND session=?)',(time.time(),g.auth['user_id'],g.auth['token']))
                c.execute('INSERT INTO mailbox_oauth_attempts VALUES (?,?,?,?,?,?)',(hashlib.sha256(nonce.encode()).hexdigest(),g.auth['user_id'],g.auth['token'],provider,store.cipher.encrypt(verifier.encode()),time.time()+600))
            params={'client_id':ident,'redirect_uri':origin+'/oauth/mail/'+provider+'/callback','response_type':'code','scope':PROVIDERS[provider]['scope'],'state':nonce,'code_challenge':challenge,'code_challenge_method':'S256','prompt':'consent' if provider=='google' else 'select_account'}
            if provider=='google': params.update(access_type='offline',include_granted_scopes='true')
            return jsonify(url=PROVIDERS[provider]['authorize']+'?'+urlencode(params))
        except OAuthError as error: return jsonify(error=str(error),kind=error.kind),503 if error.kind=='unavailable' else 400
    @app.get('/oauth/mail/<provider>/callback')
    def callback(provider):
        def back(kind): return redirect('/?mail_connection='+quote(kind)+'#settings')
        if not g.auth: return redirect('/login')
        nonce=request.args.get('state','')
        if len(nonce)>200: return back('invalid')
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            attempt=c.execute('SELECT * FROM mailbox_oauth_attempts WHERE state=? AND user_id=? AND session=? AND provider=? AND expires>?',(hashlib.sha256(nonce.encode()).hexdigest(),g.auth['user_id'],g.auth['token'],provider,time.time())).fetchone()
            if not attempt: return back('invalid')
            c.execute('DELETE FROM mailbox_oauth_attempts WHERE state=?',(attempt['state'],))
        if request.args.get('error'): return back(remote_error(request.args))
        engine=store.engine(g.auth['user_id'])
        if not engine.LOCK.acquire(False): return back('busy')
        try:
            ident,secret=credentials(provider)
            if not ident or not secret: raise OAuthError('unavailable')
            code=request.args.get('code','')
            if not code or len(code)>10000: raise OAuthError('invalid')
            data=http(PROVIDERS[provider]['token'],form={'grant_type':'authorization_code','code':code,'client_id':ident,'client_secret':secret,'redirect_uri':origin+'/oauth/mail/'+provider+'/callback','code_verifier':store.cipher.decrypt(attempt['verifier']).decode()})
            if not data.get('access_token') or not data.get('refresh_token'): raise OAuthError('permission')
            address=verify(provider,data['access_token'])
            expires_at=time.time()+int(data.get('expires_in',3600))
            data={key:data[key] for key in ('access_token','refresh_token')};data.update(expires_at=expires_at,reauthorize=False)
            # Verify actual mailbox access before storing or replacing a connection.
            save(engine.RUNTIME,provider,data)
            updated={**engine.CFG,'mail_mode':'oauth','mail_provider':provider,'account':address,'school_sender':'','password':''}
            engine.PREFS.write_text(json.dumps({k:updated[k] for k in engine.DEFAULTS},ensure_ascii=False))
            engine.CFG.update(updated);engine.STATUS['auto']=False;engine.clear_receiver_health('邮箱已连接。')
            return back('success')
        except OAuthError as error: return back(error.kind)
        finally: engine.LOCK.release()

class OAuthReceiver:
    def __init__(self, engine): self.engine=engine
    def fetch(self): return self._check('manual')
    def start_auto(self):
        engine=self.engine
        if not engine.CFG.get('key') or not engine.CFG.get('model'): raise UserFacingError('请先配置 AI 服务。')
        try:
            verify(engine.CFG['mail_provider'],access(engine))
            engine.STATUS.update(auto=True,sync_state='ready',sync_error_code='',sync_retry_at=0,sync_attempts=0)
            return '自动检查已开启。'
        except (OAuthError,MailAuthenticationError) as error: return self._failure(error)
    def process_new(self):
        if not self.engine.STATUS.get('auto'): return '自动检查已停止。'
        if self.engine.STATUS.get('sync_retry_at',0)>time.time(): return '等待重试。'
        return self._check('auto')
    def _failure(self, error):
        from backend.mail.ingest import MailReceiver
        if isinstance(error,OAuthError) and error.kind in ('expired','permission','admin','blocked'):
            provider=self.engine.CFG['mail_provider'];data=load(self.engine.RUNTIME,provider)
            data['reauthorize']=True;save(self.engine.RUNTIME,provider,data)
            error=MailAuthenticationError('邮箱需要重新授权，请到连接设置中重新连接。')
        health=MailReceiver(self.engine.db,self.engine.CFG,self.engine.STATUS,None,None,None,None)
        return health._sync_failed(error)
    def _check(self, source):
        from backend.mail import ingest
        from backend.core import operation_status
        engine=self.engine;provider=engine.CFG['mail_provider'];account=engine.CFG['account'];added=0
        key=hashlib.sha256((provider+':'+account).encode()).hexdigest()
        try:
            token=access(engine)
            engine.STATUS.update(sync_state='checking',sync_message='正在检查邮箱…')
            with engine.db() as c:
                c.execute('CREATE TABLE IF NOT EXISTS oauth_checkpoints(account TEXT PRIMARY KEY, marker TEXT)')
                row=c.execute('SELECT marker FROM oauth_checkpoints WHERE account=?',(key,)).fetchone()
            marker=row['marker'] if row else None
            path='/gmail/v1/users/me/messages?labelIds=INBOX&maxResults=50' if provider=='google' else '/v1.0/me/mailFolders/inbox/messages?$top=50&$select=id&$orderby=receivedDateTime%20desc'
            pending=[];new_marker=None;seen_pages=set()
            while path:
                if path in seen_pages or len(seen_pages)>200: raise UserFacingError('邮件数量较多，暂时无法完成同步，请稍后重试。')
                seen_pages.add(path);page=api(provider,path,token)
                rows=page.get('messages' if provider=='google' else 'value',[])
                stop=False
                for item in rows:
                    remote_id=item.get('id')
                    if not isinstance(remote_id,str): raise OAuthError('network')
                    if new_marker is None: new_marker=remote_id
                    if remote_id==marker: stop=True;break
                    pending.append(remote_id)
                # First connection imports the most recent 50; later checks recover
                # every page back to the last successful checkpoint, with no date filter.
                if stop or marker is None: break
                path=('/gmail/v1/users/me/messages?labelIds=INBOX&maxResults=50&pageToken='+quote(page['nextPageToken'],safe='')) if provider=='google' and page.get('nextPageToken') else page.get('@odata.nextLink') if provider=='microsoft' else None
            for remote_id in reversed(pending):
                ident=hashlib.sha256((key+':'+remote_id).encode()).hexdigest()
                with engine.db() as c:
                    if c.execute('SELECT 1 FROM mails WHERE id=?',(ident,)).fetchone(): continue
                if provider=='google':
                    body=api(provider,'/gmail/v1/users/me/messages/'+quote(remote_id,safe='')+'?format=raw',token)
                    encoded=body.get('raw','');raw=base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
                else: raw=api(provider,'/v1.0/me/messages/'+quote(remote_id,safe='')+'/$value',token,raw=True)
                if not raw: raise OAuthError('network')
                _,created=ingest.import_raw(raw,ident,account,source,engine.db,engine.parse_mail)
                added+=created
            if new_marker:
                with engine.db() as c: c.execute('INSERT OR REPLACE INTO oauth_checkpoints VALUES (?,?)',(key,new_marker))
            engine.STATUS.update(last_sync_at=time.time(),sync_state='ready',sync_error_code='',sync_message='',sync_attempts=0,sync_retry_at=0)
        except (OAuthError,MailAuthenticationError,OSError,ValueError,UserFacingError) as error:
            engine.STATUS['added']=added
            return self._failure(error)
        analyzed,failed=engine.analyze_pending()
        engine.STATUS.update(ingest.analysis_queue_counts(engine.db))
        message=f'检查完成：新增 {added} 封，自动分析 {analyzed} 封'+ingest.analysis_retry_message(failed)
        operation_status.finish(engine.STATUS,message,added=added,success=analyzed,failed=failed)
        return message
