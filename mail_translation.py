"""Translate text nodes while preserving the inert original email markup."""
import hashlib
import html
import re
from html.parser import HTMLParser

VERSION='original-layout-v1'

class Template(HTMLParser):
    def __init__(self,source):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.texts=[]
        self.feed(source)
        self.close()
    def handle_starttag(self,tag,attrs):self.parts.append(self.get_starttag_text())
    def handle_startendtag(self,tag,attrs):self.parts.append(self.get_starttag_text())
    def handle_endtag(self,tag):self.parts.append('</'+tag+'>')
    def handle_data(self,data):
        # Keep whitespace and URL text outside model output, including plain-text fallback links.
        for piece in re.split(r'(https?://[^\s<>]+|\n)',data):
            if not piece:continue
            if not piece.strip() or re.match(r'^https?://',piece):
                self.parts.append(html.escape(piece));continue
            leading=piece[:len(piece)-len(piece.lstrip())];trailing=piece[len(piece.rstrip()):]
            self.parts.append(html.escape(leading))
            self.parts.append(len(self.texts));self.texts.append(piece.strip())
            self.parts.append(html.escape(trailing))
    def render(self,values):
        if len(values)!=len(self.texts) or any(not isinstance(v,str) or not v.strip() for v in values):
            raise ValueError('AI 返回的译文段落不完整，请重试。')
        return ''.join(html.escape(values[p]) if isinstance(p,int) else p for p in self.parts)

def source(row):
    import json
    if row['original']:
        original=json.loads(row['original'])
        if original.get('html'):return original['html'],original.get('external',[])
    body=row['source_body'] if row['source_body'] is not None else row['body'] or ''
    # Turn text/plain's label<URL> representation back into a clickable label.
    pieces=[];last=0
    for match in re.finditer(r'([^\n<>]+)<(https?://[^\s<>]+)>',body):
        pieces.append(html.escape(body[last:match.start()]))
        pieces.append('<a target="_blank" rel="noreferrer noopener" href="'+html.escape(match[2],quote=True)+'">'+html.escape(match[1])+'</a>')
        last=match.end()
    pieces.append(html.escape(body[last:]))
    return '<pre>'+''.join(pieces)+'</pre>',[]

def fingerprint(subject,markup):
    return VERSION+':'+hashlib.sha256((subject+'\0'+markup).encode()).hexdigest()

def batches(texts,limit=6000):
    batch=[];size=0
    for i,text in enumerate(texts):
        if batch and size+len(text)>limit:
            yield batch;batch=[];size=0
        batch.append({'id':i,'text':text});size+=len(text)
    if batch:yield batch
