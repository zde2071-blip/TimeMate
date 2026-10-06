"""Frozen compatibility rules from the former UI, used ONLY for one-time migration.

Do not extend this list for new mail subjects. New titles come from mail_titles.
Keeping this migration separate preserves already-shipped titles without AI costs.
"""
import html
import json
import re
import unicodedata

CHINESE = re.compile(r'[\u3400-\u9fff]')


def topic(title):
    title = re.sub(r'\b\d{4}\s*[-–—~至]\s*\d{4}\s*(?:学年|年度|届)?|\b\d{4}\s*(?:学年|年度|年|届)|\d{4}-\d{2}-S\d', '', title, flags=re.I | re.ASCII)
    title = re.sub(r'(?:仅限|面向|针对)(?:本地|国际|全体|本科|研究生|太仓|园区)*(?:学生|同学|生)\s*[:：]?', '', title)
    title = re.sub(r'[<>《》]', '', title)
    parts = []
    for part in title.split('、'):
        part = re.sub(r'^(?:(?:关于|有关|开展|举行|举办|组织开展|组织|发布|启动|提醒|通知|公告|重要|最新|诚邀|邀请|诚邀参加|请参加|请|报名开启|报名开放)\s*[:：]?)+', '', part.strip())
        part = re.sub(r'(?:工作)?(?:的|的重要)?(?:通知|公告|提醒|安排|来袭|开启)[!！。:：\s]*$', '', part).replace('报名报名', '报名').strip()
        if part and not re.fullmatch(r'[\d\s:：\-—–]+', part):
            parts.append(part)
    return re.sub(r'\s+', ' ', re.sub(r'\.{2,}|…+|�+', '', '、'.join(parts))).strip(' :：、')


def compact(raw, legacy=True):
    if not isinstance(raw, str) or not raw.strip():
        return ''
    title = re.sub(r'^(?:(?:转发|轉發|fw|fwd)\s*[:：]\s*)+', '', unicodedata.normalize('NFKC', html.unescape(raw)), flags=re.I)
    tail = re.search(r'\b(?:Notice|Reminder|Announcement|Invitation)\s+(?:on|of|for|about|to)\b', title, re.I)
    if tail and CHINESE.search(title[:tail.start()]):
        title = title[:tail.start()]
    title = re.sub(r'\b\d{4}[-–—]\d{2,4}[- ]?S\d+\b|\bWEEK\s*\d+\b', '', title, flags=re.I | re.ASCII)
    title = re.sub(r'<[^>]*>|\[[^\]]*\]|【[^】]*】|\([^)]*\)|第[一二三四五六七八九十\d]+(?:次|期|批|届)', '', title)
    title = re.sub(r'(?:预报从速|报名从速|重要通知|温馨提醒|活动邀请)[!！:：|\s]*', '', title).strip()
    codes = []
    if legacy and CHINESE.search(title):
        def protect(match):
            codes.append(match[0])
            return chr(0xE000 + len(codes)-1)
        title = re.sub(r'\b[A-Z]{3}\d{3}\b', protect, title)
        title = re.sub(r'''[A-Za-z][A-Za-z0-9 .,'’:“”"!?\-]*''', '', title)
        title = re.sub(r'(?:\.{2,}|…+)[\s，,、]*', '、', title)
        title = re.sub(r'来袭|开启|开始报名|开放报名', '报名', title).replace('报名报名', '报名')
        title = re.sub(r'''[“”"']''', '', title)
        parts = [re.sub(r'^[\s,:：!！\d]+(?=[\u3400-\u9fff])|[\s,:：!！]+$', '', p.strip()) for p in re.split(r'[&|｜;；、]+', title)]
        parts = list(dict.fromkeys(filter(None, parts)))
        if len(parts)>3 and len(parts[-1])<=16 and re.search(r'报名|招募|通知|提醒|申请$', parts[-1]):
            parts = parts[-1:]
        title = '、'.join(parts)
        title = re.sub(r'[\uE000-\uEFFF]', lambda m: codes[ord(m[0])-0xE000], title)
    if not CHINESE.search(title):
        code = re.search(r'\b[A-Z]{3}\s*\d{3}\b', title, re.I)
        for pattern, name in [(r'\bIELTS\b','雅思'),(r'\bphysical (?:fitness|health)\b.*\btest\b','体质健康测试'),(r'\bgroup project\b.*\btopic\b','小组项目主题提交'),(r'\blab\b.*\bbegins?\b','实验课开始'),(r'\bpsychology groups?\b','心理团体报名')]:
            if re.search(pattern, title, re.I):
                title = (re.sub(r'\s+', '', code[0]).upper()+' ' if code else '')+name
                break
    return topic(title)


def display_title(subject, result):
    try:
        result = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        result = None
    result = result if isinstance(result, dict) else {}
    original = compact(subject)
    raw = result.get('short_title', '')
    generated = compact(raw, False)
    if generated and len(generated)<=32 and not re.search(r'\.{2,}|…|�', str(raw)):
        return generated
    events = list(dict.fromkeys(compact(e.get('title')) for e in result.get('events', []) if isinstance(e, dict)))
    if not CHINESE.search(original) and len(events)==1 and events[0] and len(events[0])<=32:
        return events[0]
    title = original or generated or str(subject or '').strip() or '无主题'
    if len(title)>32 and '、' in title:
        parts = []
        for part in title.split('、'):
            match = re.search(r'(?:特殊教育|特殊儿童|助残|环保|社区)?志愿者招募|(?:\d+米)?长跑', part)
            parts.append(match[0] if match else '瑜伽体验' if '瑜伽' in part and '体验' in part else '瑜伽' if '瑜伽' in part else part)
        title = '、'.join(dict.fromkeys(parts))
    return title
