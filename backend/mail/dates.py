"""Read original send times from forwarded headers without an LLM call."""
import json, re
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

SCHOOL_ZONE = ZoneInfo('Asia/Shanghai')

def parse_date(text):
    text = text.strip().replace('\u00a0', ' ')
    try:
        # The RFC parser can accept Outlook text while silently ignoring PM.
        value = None if re.search(r'\b(?:AM|PM)\b', text, re.I) else parsedate_to_datetime(text)
    except (ValueError, TypeError, OverflowError):
        value = None
    if value is None:
        normalized = re.sub(r'星期[一二三四五六日天]|周[一二三四五六日天]', '', text)
        normalized = re.sub(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b,?', '', normalized, flags=re.I)
        normalized = re.sub(r'\s+', ' ', normalized).strip(' ,')
        chinese = re.fullmatch(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*(上午|下午)?\s*(\d{1,2}):(\d{2})(?::\d{2})?', normalized)
        if chinese:
            year, month, day, period, hour, minute = chinese.groups()
            hour = int(hour)
            if period: hour = hour % 12 + (12 if period == '下午' else 0)
            try: value = datetime(int(year), int(month), int(day), hour, int(minute))
            except ValueError: return None
        else:
            try: value = datetime.fromisoformat(normalized)
            except ValueError: pass
            if value is None:
                for fmt in ('%B %d, %Y %I:%M %p', '%B %d, %Y %H:%M',
                            '%d %B %Y %H:%M', '%d %B %Y %I:%M %p',
                            '%Y/%m/%d %H:%M', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M',
                            '%B %d, %Y at %I:%M %p'):
                    try:
                        value = datetime.strptime(normalized, fmt)
                        break
                    except ValueError: pass
    if value is None: return None
    if value.tzinfo is None: value = value.replace(tzinfo=SCHOOL_ZONE)
    return value.replace(second=0, microsecond=0)

def forwarded_date(text):
    # Only header fields beside a sender field qualify, never activity dates.
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'^\s*[>\s]*(?:发送时间|发送日期|寄件日期|日期|Sent|Date)\s*[:：]\s*(.+)$', line, re.I)
        if not match: continue
        nearby = '\n'.join(lines[max(0, index-6):index+7])
        if not re.search(r'(?:^|\n)\s*[>\s]*(?:发件人|寄件者|From)\s*[:：]', nearby, re.I): continue
        value = parse_date(match.group(1))
        if value is not None: return value
    return None

def effective_date(row):
    """Resolve once on import/upgrade, not by decoding image-rich HTML on polling."""
    value = parse_date(row.get('sent_date') or '')
    if value is not None: return value
    value = forwarded_date(row.get('source_body') or row.get('body') or '')
    if value is None and row.get('original'):
        from backend.mail.original import text_from_html
        try:
            original = json.loads(row['original'])
            value = forwarded_date(text_from_html(original.get('html', '')))
        except (ValueError, TypeError, AttributeError): pass
    return value or parse_date(row.get('date') or '')

def stored_date(row):
    value = effective_date(row)
    return value.isoformat(timespec='minutes') if value else ''
