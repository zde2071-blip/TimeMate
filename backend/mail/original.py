"""Convert email HTML to inert markup; no original scripts, CSS or active embeds."""
import base64,html
from html.parser import HTMLParser
from urllib.parse import urlparse
try:
    from charset_normalizer import from_bytes
except ImportError:
    from_bytes=None

def decode_text(payload,declared_charset=None):
    if not payload:return ''
    try:return payload.decode('utf-8-sig')
    except UnicodeDecodeError:pass
    if declared_charset:
        try:
            decoded=payload.decode(declared_charset)
            if '\ufffd' not in decoded:return decoded
        except (LookupError,UnicodeDecodeError):pass
    if from_bytes:
        try:
            best=from_bytes(payload).best()
            if best is not None:return str(best)
        except Exception:pass
    for charset in ('gb18030','big5'):
        try:
            decoded=payload.decode(charset)
            if '\ufffd' not in decoded:return decoded
        except UnicodeDecodeError:pass
    try:return payload.decode(declared_charset or 'utf-8',errors='replace')
    except LookupError:return payload.decode('utf-8',errors='replace')

class Original(HTMLParser):
    tags=set('p div span br hr b strong i em u ul ol li blockquote table thead tbody tfoot tr td th h1 h2 h3 h4 pre'.split())
    safe_attrs={'width','height','colspan','rowspan','align','valign','border','cellpadding','cellspacing','start','type','dir','lang'}
    def __init__(self,images):
        super().__init__();self.images=images;self.out=[];self.external=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('script','style','iframe','object'):self.skip+=1;return
        if self.skip:return
        if tag in self.tags:
            attrs=''.join(' '+key+'="'+html.escape(str(a[key]),quote=True)+'"' for key in self.safe_attrs if a.get(key) is not None and len(str(a[key]))<80)
            style=a.get('style','')
            safe_style=[]
            for declaration in style.split(';'):
                key,sep,value=declaration.partition(':');key=key.strip().lower();value=value.strip()
                if sep and key in {'color','background-color','text-align','vertical-align','font-weight','font-style','text-decoration','font-size','font-family','width','max-width','border','border-collapse','padding','margin'} and not any(x in value.lower() for x in ('url','expression','javascript','@import')):
                    safe_style.append(key+':'+value)
            if safe_style:attrs+=' style="'+html.escape(';'.join(safe_style),quote=True)+'"'
            self.out.append('<'+tag+attrs+'>')
        elif tag=='a':
            url=a.get('href','')
            if urlparse(url).scheme in ('https','http'):self.out.append('<a target="_blank" rel="noreferrer noopener" href="'+html.escape(url,quote=True)+'">')
        elif tag=='img':
            src=a.get('src','');alt=a.get('alt','图片')
            if src.startswith('cid:'):src=self.images.get(src[4:].strip('<>').casefold(),'')
            dims=''.join(' '+name+'="'+html.escape(a[name],quote=True)+'"' for name in ('width','height') if a.get(name,'').isdigit() and int(a[name])<=4000)
            if src.startswith('data:image/') and src in self.images.values():self.out.append('<img alt="'+html.escape(alt,quote=True)+'"'+dims+' src="'+src+'">')
            elif urlparse(src).scheme=='https':
                index=len(self.external);self.external.append(src);self.out.append('<img alt="'+html.escape(alt,quote=True)+'（外部图片）" data-external="'+str(index)+'">')
            else:self.out.append('<p>[图片未包含在此邮件中]</p>')
    def handle_endtag(self,tag):
        if tag in ('script','style','iframe','object'):self.skip=max(0,self.skip-1);return
        if not self.skip and tag in self.tags|{'a'}:self.out.append('</'+tag+'>')
    def handle_data(self,data):
        if not self.skip:self.out.append(html.escape(data))

class PlainText(HTMLParser):
    blocks={'p','div','br','hr','li','tr','table','h1','h2','h3','h4','pre','blockquote'}
    def __init__(self):super().__init__();self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in self.blocks:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in self.blocks:self.parts.append('\n')
    def handle_data(self,data):self.parts.append(data)

def text_from_html(source):
    parser=PlainText();parser.feed(source or '')
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())

def extract(message,body):
    images={};rich=[]
    for part in message.walk():
        kind=part.get_content_type();payload=part.get_payload(decode=True) or b''
        cid=str(part.get('Content-ID','')).strip('<>')
        if cid and kind in ('image/png','image/jpeg','image/gif','image/webp'):
            images[cid.casefold()]='data:'+kind+';base64,'+base64.b64encode(payload).decode()
        if kind=='text/html' and part.get_content_disposition()!='attachment':
            rich.append(decode_text(payload,part.get_content_charset()))
    parser=Original(images);parser.feed('\n'.join(rich))
    return {'html':''.join(parser.out) if rich else '<pre>'+html.escape(body)+'</pre>','external':parser.external}
