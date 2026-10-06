"""Provider metadata and small adapters; no credentials are persisted here."""
import json, re, ssl
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlencode
import certifi

PROVIDERS = {
 'openai': {'name':'OpenAI','base':'https://api.openai.com/v1'},
 'deepseek': {'name':'DeepSeek','base':'https://api.deepseek.com'},
 'qwen': {'name':'通义千问 · 阿里云百炼（北京）','base':'https://dashscope.aliyuncs.com/compatible-mode/v1','hint':'地区和业务空间必须与 Key 一致。专属域名或其他地区请在高级设置中修改。'},
 'zhipu': {'name':'智谱 GLM','base':'https://open.bigmodel.cn/api/paas/v4','hint':'使用按量计费 API Key。若无法获取列表，请手动填写已开通的模型 ID。'},
 'doubao': {'name':'豆包 · 火山方舟（北京）','base':'https://ark.cn-beijing.volces.com/api/v3','hint':'若无法获取列表，请手动填写已开通的模型 ID 或推理接入点 ID（ep-…）。'},
 'kimi': {'name':'Kimi · Moonshot（中国）','base':'https://api.moonshot.cn/v1'},
 'gemini': {'name':'Google Gemini','base':'https://generativelanguage.googleapis.com/v1beta/openai'},
 'claude': {'name':'Anthropic Claude','base':'https://api.anthropic.com/v1','protocol':'anthropic'},
 'custom': {'name':'其他兼容服务','base':'','hint':'填写支持 Chat Completions 的 HTTPS 基础地址和模型 ID。'},
}
class AIServiceError(ValueError):
 """Only fixed, safe diagnostics; never provider response bodies or credentials."""

class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): raise AIServiceError('接口发生跳转，请核对高级设置中的地址。')

def infer_provider(base):
 return next((k for k,v in PROVIDERS.items() if v['base'] and v['base'].rstrip('/')==base.rstrip('/')),'custom')

def validate(cfg,model=True):
 if cfg.get('provider') not in PROVIDERS: raise AIServiceError('请选择模型服务商。')
 p=urlparse(cfg.get('base',''))
 if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:
  raise AIServiceError('请填写不含查询参数的 HTTPS 接口基础地址。')
 if not cfg.get('key'): raise AIServiceError('请填写当前服务商的 API Key。')
 if model and not cfg.get('model'): raise AIServiceError('请先选择模型，或手动填写模型 ID。')

def request_json(cfg,path,payload=None):
 validate(cfg,model=False)
 headers={'Content-Type':'application/json'}
 if cfg['provider']=='claude':headers.update({'x-api-key':cfg['key'],'anthropic-version':'2023-06-01'})
 else:headers['Authorization']='Bearer '+cfg['key']
 req=Request(cfg['base'].rstrip('/')+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
 try:
  opener=build_opener(NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
  with opener.open(req,timeout=60) as response:return json.loads(response.read(2_000_000))
 except HTTPError as e:
  # Never reflect a provider error body: it can contain credentials or request content.
  messages={400:'请求或模型参数不受支持，请核对模型和接口。',401:'API Key 无效，或与当前服务商、地区不匹配。',402:'账户余额不足或未开通付费服务。',403:'没有调用权限，请检查地区、模型开通状态和 Key 权限。',404:'接口或模型不存在；可尝试手动填写已开通的模型 ID。',429:'服务商限流或额度不足，请检查余额与限额后再试。'}
  raise AIServiceError(messages.get(e.code,'服务商暂时无法完成请求，请稍后再试。')+f'（HTTP {e.code}）') from None
 except (URLError,TimeoutError): raise AIServiceError('连接超时或网络不可达，请检查网络和接口地址。') from None
 except (json.JSONDecodeError,UnicodeDecodeError): raise AIServiceError('服务商返回了无法识别的数据，请核对接口地址。') from None

def list_models(cfg):
 data=request_json(cfg,'/models')
 items=list(data.get('data',[]))
 if cfg['provider']=='claude':
  for _ in range(9):
   if not data.get('has_more') or not data.get('last_id'):break
   data=request_json(cfg,'/models?'+urlencode({'after_id':data['last_id']}));items.extend(data.get('data',[]))
 models=sorted({x['id'] for x in items if isinstance(x,dict) and isinstance(x.get('id'),str)})
 # Model listing is discovery, not a guarantee of chat permissions/capabilities.
 if not models:raise AIServiceError('没有获取到模型，请手动填写服务商控制台中的模型 ID。')
 return models

def complete(cfg,prompt,data,max_tokens=4096):
 validate(cfg)
 user=json.dumps(data,ensure_ascii=False)
 if cfg['provider']=='claude':
  result=request_json(cfg,'/messages',{'model':cfg['model'],'max_tokens':max_tokens,'system':prompt,'messages':[{'role':'user','content':user}]})
  if result.get('stop_reason')=='max_tokens':raise AIServiceError('模型回答达到输出额度上限，结果不完整。')
  content=''.join(x.get('text','') for x in result.get('content',[]) if x.get('type')=='text')
 else:
  payload={'model':cfg['model'],'messages':[{'role':'system','content':prompt},{'role':'user','content':user}],'max_tokens':max_tokens,'stream':False}
  # Email extraction/translation needs a final answer, not a reasoning trace.
  # DeepSeek enables thinking by default, which shares the output token limit.
  if cfg['provider']=='deepseek':payload['thinking']={'type':'disabled'}
  result=request_json(cfg,'/chat/completions',payload)
  try:
   choice=result['choices'][0];message=choice['message'];content=message.get('content')
  except (KeyError,IndexError,TypeError,AttributeError):raise AIServiceError('模型接口返回结构异常，没有收到回答。') from None
  reason=choice.get('finish_reason')
  if reason=='length':
   if message.get('reasoning_content') and not content:
    raise AIServiceError('模型在思考阶段耗尽输出额度，尚未生成最终回答。')
   raise AIServiceError('模型回答达到输出额度上限，结果不完整。')
  if reason=='content_filter':raise AIServiceError('模型服务商拦截了本次回答，未生成可用结果。')
  if reason=='insufficient_system_resource':raise AIServiceError('模型服务商计算资源不足，请稍后重试。')
  if not content and message.get('reasoning_content'):
   raise AIServiceError('模型只返回了思考内容，没有最终回答；请检查思考模式兼容性。')
 if not isinstance(content,str) or not content.strip():raise AIServiceError('模型接口返回了空回答，请稍后重试。')
 try:return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',content.strip()))
 except ValueError:raise AIServiceError('模型没有返回所需格式，请重试或更换模型。') from None
