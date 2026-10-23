"""Pinned public HTTPS callback delivery. Never follow redirects or use proxies."""
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit


def checked_url(url):
    if not isinstance(url,str) or len(url)>2048 or any(ord(c)<33 for c in url): raise ValueError('通知地址无效。')
    u=urlsplit(url)
    try: port=u.port
    except ValueError: raise ValueError('通知地址无效。') from None
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or port not in (None,443):
        raise ValueError('通知地址必须使用 HTTPS 默认端口。')
    host=u.hostname.encode('idna').decode('ascii')
    if host.endswith('.') or '%' in host: raise ValueError('通知地址无效。')
    return u,host


def public_addresses(host):
    addresses=list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('通知地址必须指向公网。')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address):
        super().__init__(host,443,timeout=8,context=ssl.create_default_context())
        self.address=address

    def connect(self):
        sock=socket.create_connection((self.address,443),self.timeout)
        try: self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def post_json(url, body, headers):
    u,host=checked_url(url)
    addresses=public_addresses(host)
    conn=PinnedHTTPS(host,addresses[0])
    try:
        path=u.path or '/'
        if u.query: path+='?'+u.query
        conn.request('POST',path,body=body,headers={'Content-Type':'application/json',**headers})
        response=conn.getresponse()
        raw=response.read(65537)
        if len(raw)>65536: raise ValueError('通知响应过大。')
        if not 200<=response.status<300: raise ValueError('通知未被接收（HTTP '+str(response.status)+'）。')
        try: payload=json.loads(raw) if raw else {}
        except ValueError: payload={}
        return payload
    finally: conn.close()


def secret_bytes(secret):
    if not isinstance(secret,str) or not secret.startswith('whsec_'): raise ValueError('签名密钥格式无效。')
    try: value=base64.b64decode(secret[6:],validate=True)
    except Exception: raise ValueError('签名密钥格式无效。') from None
    if not 24<=len(value)<=64: raise ValueError('签名密钥长度无效。')
    return value


def signed_headers(secret,ident,body,subscription):
    stamp=str(int(time.time()))
    message=ident.encode()+b'.'+stamp.encode()+b'.'+body
    signature=base64.b64encode(hmac.new(secret_bytes(secret),message,hashlib.sha256).digest()).decode()
    return {'webhook-id':ident,'webhook-timestamp':stamp,'webhook-signature':'v1,'+signature,'X-MCP-Subscription-Id':subscription}
