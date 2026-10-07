"""Stored sidebar titles. Runtime rendering never infers a title from mail contents."""
import html
import re
import unicodedata

VERSION = 1
MAX_LENGTH = 120


def normalize(value):
    if not isinstance(value, str):
        return ''
    title = unicodedata.normalize('NFKC', html.unescape(value))
    return ' '.join(title.split()).strip()


def validated(value):
    """Reject malformed/truncated output rather than clipping a meaningful name."""
    if not isinstance(value, str) or re.search(r'\.{2,}|…|�', value):
        return ''
    title = normalize(value)
    return title if title and len(title) <= MAX_LENGTH else ''


def from_analysis(subject, result):
    return validated(result.get('short_title')) or str(subject or '').strip() or '无主题'


def migrate(connection):
    """Upgrade each old row once, without paid model calls or editing its analysis."""
    from backend.migrations.legacy_titles import display_title
    rows = connection.execute(
        'SELECT id,subject,result FROM mails WHERE title_version IS NULL'
    ).fetchall()
    for row in rows:
        connection.execute('UPDATE mails SET display_title=?,title_version=? WHERE id=?',
                           (display_title(row['subject'], row['result']), VERSION, row['id']))
