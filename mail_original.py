"""Convert email HTML to inert markup; no original scripts, CSS or active embeds."""
import base64,html
from html.parser import HTMLParser
from urllib.parse import urlparse
class Original(HTMLParser):
    tags=set('p div span br hr b strong i em u ul ol li blockquote table tbody tr td th h1 h2 h3 h4 pre'.split())
    def __init__(self,images):
        super().__init__();self.images=images;self.out=[];self.external=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('script','style','iframe','object'):self.skip+=1;return
        if self.skip:return
        if tag in self.tags:self.out.append('<'+tag+'>')
        elif tag=='a':
            url=a.get('href','')
            if urlparse(url).scheme in ('https','http'):self.out.append('<a target="_blank" rel="noreferrer noopener" href="'+html.escape(url,quote=True)+'">')
        elif tag=='img':
            src=a.get('src','');alt=a.get('alt','图片')
            if src.startswith('cid:'):src=self.images.get(src[4:].strip('<>'),'')
            if src.startswith('data:image/') and src in self.images.values():self.out.append('<img alt="'+html.escape(alt,quote=True)+'" src="'+src+'">')
            elif urlparse(src).scheme=='https':
                index=len(self.external);self.external.append(src);self.out.append('<img alt="'+html.escape(alt,quote=True)+'（外部图片）" data-external="'+str(index)+'">')
            else:self.out.append('<p>[图片未包含在此邮件中]</p>')
    def handle_endtag(self,tag):
        if tag in ('script','style','iframe','object'):self.skip=max(0,self.skip-1);return
        if not self.skip and tag in self.tags|{'a'}:self.out.append('</'+tag+'>')
    def handle_data(self,data):
        if not self.skip:self.out.append(html.escape(data))
def extract(message,body):
    images={};rich=[]
    for part in message.walk():
        kind=part.get_content_type();payload=part.get_payload(decode=True) or b''
        cid=str(part.get('Content-ID','')).strip('<>')
        if cid and kind in ('image/png','image/jpeg','image/gif','image/webp'):
            images[cid]='data:'+kind+';base64,'+base64.b64encode(payload).decode()
        if kind=='text/html' and part.get_content_disposition()!='attachment':
            try:rich.append(payload.decode(part.get_content_charset() or 'utf-8',errors='replace'))
            except LookupError:rich.append(payload.decode('utf-8',errors='replace'))
    parser=Original(images);parser.feed('\n'.join(rich))
    return {'html':''.join(parser.out) if rich else '<pre>'+html.escape(body)+'</pre>','external':parser.external}
