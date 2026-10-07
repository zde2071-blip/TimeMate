"""Mail analysis, result validation and per-account retry queue."""
import json, re, time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from backend.core.ai_services import AIServiceError
from backend.core.user_errors import UserFacingError
from backend.mail import titles as mail_titles
from backend.core import operation_status
from backend.mail.prompts import ANALYSIS_PROMPT, EVENT_RULES, EXTRACTION_PROMPT

def is_course_week_window(item,source_text):
    if item.get('allDay') is not True or not source_text: return False
    try:
        start=datetime.fromisoformat(str(item.get('start','')).strip())
        end=datetime.fromisoformat(str(item.get('end','')).strip())
    except (TypeError,ValueError): return False
    span=(end-start).total_seconds()/86400
    text=' '.join((source_text,str(item.get('title','')),str(item.get('action','')),str(item.get('evidence','')))).lower()
    course=bool(re.search(r'\b(?:[a-z]{2,5}\s?\d{3,4}|lab|tutorial|course|class)\b|实验课|课程|课表',text))
    teaching_week=bool(re.search(r'\bweek\s*\d*\b|\bthis week\b|本周|第\s*\d+\s*周',text))
    check_timetable=bool(re.search(r'timetable|check your schedule|查看.{0,8}课表|按.{0,8}课表|个人课表',text))
    return 2<=span<=14 and course and teaching_week and check_timetable

def normalize_events(value,source_text=''):
    if not isinstance(value,list): return []
    events=[]
    for item in value:
        if not isinstance(item,dict): continue
        try:
            if is_course_week_window(item,source_text): continue
            title=str(item['title']).strip()[:120]
            start=datetime.fromisoformat(str(item['start']).strip())
            end=datetime.fromisoformat(str(item['end']).strip()) if item.get('end') and item.get('kind')!='截止' else None
            if start.tzinfo or (end and (end.tzinfo or end<=start)) or not (2000<=start.year<=2100) or not title: continue
            if end and (end-start).days>31: continue
            events.append({'title':title,'start':start.isoformat(timespec='seconds'),
                           'end':end.isoformat(timespec='seconds') if end else '','location':str(item.get('location','')).strip()[:200],
                           'action':str(item.get('action','')).strip()[:500],
                           'kind':str(item.get('kind','日程')).strip()[:40],
                           'evidence':str(item.get('evidence','')).strip()[:400],
                           'allDay':item.get('allDay') is True})
        except (KeyError,TypeError,ValueError): continue
    return events

class MailAnalyzer:
    def __init__(self, database, config, status, model_reply, category):
        self.database = database
        self.config = config
        self.status = status
        self.model_reply = model_reply
        self.category = category

    def analyze(self,ident):
        try:
            return self.saved(ident)
        except Exception as error:
            if isinstance(error,AIServiceError):
                detail=str(error)
            elif isinstance(error,TimeoutError):
                detail='模型请求超时，请稍后重试。'
            else:
                detail='程序处理分析结果时发生异常，需要检查程序。'
            for key in ('password','key'):
                if self.config.get(key): detail=detail.replace(self.config[key],'[隐藏]')
            detail='分析失败：'+detail
            with self.database() as c:
                row=c.execute('SELECT analysis_attempts FROM mails WHERE id=?',(ident,)).fetchone()
                attempts=(row['analysis_attempts'] if row else 0)+1
                delay=min(60*(2**min(attempts-1,5)),1800)
                c.execute('UPDATE mails SET analysis_error=?,analysis_attempts=?,analysis_retry_at=? WHERE id=? AND result IS NULL',(detail,attempts,time.time()+delay,ident))
            raise AIServiceError(detail) from None

    def saved(self,ident):
        cfg=self.config.copy()
        with self.database() as c:
            row=c.execute('SELECT * FROM mails WHERE id=?',(ident,)).fetchone()
            if not row: raise UserFacingError('邮件不存在')
            if row['result']: return '这封邮件已有分析结果，未重复调用。'
            self.status['message']='正在分析这封邮件…'
            prompt=ANALYSIS_PROMPT
            result=self.model_reply(cfg,prompt,{**{k:row[k] for k in ('subject','sender','date','body')},
                                           'currentLocalTime':datetime.now().astimezone().isoformat(timespec='seconds')})
            keys=('category','summary','time','location','action','uncertainties')
            if not isinstance(result,dict) or not all(isinstance(result.get(k),str) for k in keys): raise AIServiceError('模型没有返回完整结构，未保存结果，可以重试。')
            clean={k:result[k] for k in keys}
            clean['category']=self.category(row,clean)
            title=mail_titles.validated(result.get('short_title'))
            if title: clean['short_title']=title
            source_text=row['subject']+'\n'+row['body']
            clean['events']=normalize_events(result.get('events'),source_text)
            # Mail IDs are stable across QQ re-imports. If the mail table was reset
            # while pins survived, an old pin could otherwise attach to a newly
            # analyzed event with the same index. A first analysis is an unreviewed
            # draft, so it must not inherit any saved pin state.
            c.execute('DELETE FROM pins WHERE mail_id=?',(ident,))
            c.execute('UPDATE mails SET result=?,display_title=?,title_version=?,analysis_error=NULL,analysis_attempts=0,analysis_retry_at=0 WHERE id=?',(json.dumps(clean,ensure_ascii=False),mail_titles.from_analysis(row['subject'],clean),mail_titles.VERSION,ident))
        return f'分析完成，提出 {len(clean["events"])} 条待审核日程；尚未写入 Apple 日历。'

    def extract_events(self,ident):
        cfg=self.config.copy()
        with self.database() as c:
            row=c.execute('SELECT * FROM mails WHERE id=?',(ident,)).fetchone()
            if not row or not row['result']: raise UserFacingError('请先分析这封邮件。')
            result=json.loads(row['result'])
            if 'events' in result: return '这封邮件已经提取过日程。'
            self.status['message']='正在从已有分析中提取日程草稿…'
            prompt=EXTRACTION_PROMPT
            answer=self.model_reply(cfg,prompt,{**{k:row[k] for k in ('subject','sender','date','body')},
                                           'analysis':result,
                                           'currentLocalTime':datetime.now().astimezone().isoformat(timespec='seconds')})
            source_text=row['subject']+'\n'+row['body']
            result['events']=normalize_events(answer.get('events') if isinstance(answer,dict) else None,source_text)
            c.execute('UPDATE mails SET result=? WHERE id=?',(json.dumps(result,ensure_ascii=False),ident))
        return f'已提出 {len(result["events"])} 条日程草稿。请核对后再加入 Apple 日历。'

    def pending(self, analyze):
        with self.database() as c:
            pending=[r['id'] for r in c.execute(
                "SELECT id FROM mails WHERE result IS NULL AND is_deleted=0 AND source IN ('manual','auto') AND analysis_retry_at<=? ORDER BY created",(time.time(),)
            )]
            deferred=c.execute("SELECT COUNT(*) FROM mails WHERE result IS NULL AND is_deleted=0 AND source IN ('manual','auto') AND analysis_retry_at>?",(time.time(),)).fetchone()[0]
        self.status['deferred']=deferred
        analyzed=0; failed=0
        if not pending: return analyzed,failed
        operation_status.begin(self.status,'analyzing',f'正在分析 {len(pending)} 封邮件…',total=len(pending),deferred=deferred)
        with ThreadPoolExecutor(max_workers=min(2,len(pending))) as pool:
            futures=[pool.submit(analyze,ident) for ident in pending]
            for future in as_completed(futures):
                try:
                    future.result()
                    analyzed+=1
                except Exception:
                    # 保留未分析状态，下次检查重试；其他请求独立完成。
                    failed+=1
                operation_status.progress(self.status,analyzed,failed)
                self.status['message']=f'并行分析进度：已完成 {analyzed+failed}/{len(pending)} 封，成功 {analyzed} 封，失败 {failed} 封。'
        return analyzed,failed

