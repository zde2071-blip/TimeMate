"""Calendar subscriptions share one feed, but keep independent confirmation state."""
import json
from backend.core.user_errors import UserFacingError

PROVIDERS = ('apple', 'outlook')


def subscriptions(config):
    try:
        stored = json.loads(config.get('calendar_subscriptions', '[]'))
    except (ValueError, TypeError):
        stored = []
    rows = []
    if isinstance(stored, list):
        for row in stored:
            if isinstance(row, dict) and row.get('provider') in PROVIDERS and not any(x['provider'] == row['provider'] for x in rows):
                rows.append({'provider': row['provider'], 'confirmed': row.get('confirmed') == 'yes' and 'yes' or 'no'})
    # Existing single-calendar settings remain available without re-subscription.
    if not rows and config.get('calendar_method') == 'subscribe' and config.get('calendar_provider') in PROVIDERS:
        rows.append({'provider': config['calendar_provider'], 'confirmed': config.get('calendar_subscription_confirmed') == 'yes' and 'yes' or 'no'})
    return rows


def update(config, data):
    method = data.get('calendar_method')
    if method not in ('unset', 'ics', 'subscribe'):
        raise UserFacingError('请选择有效的日历添加方式。')
    provider = data.get('calendar_provider', config['calendar_provider'])
    if provider not in ('', *PROVIDERS):
        raise UserFacingError('请选择 Apple 或 Outlook 日历。')
    confirmed = data.get('calendar_subscription_confirmed')
    if confirmed not in (None, 'yes', 'no'):
        raise UserFacingError('订阅状态无效。')
    if confirmed == 'yes' and (method != 'subscribe' or not provider):
        raise UserFacingError('请先选择日历并完成订阅。')
    rows = subscriptions(config)
    existing = next((row for row in rows if row['provider'] == provider), None)
    if 'calendarProfileId' in data:
        ident = data['calendarProfileId']
        if method != 'subscribe' or provider not in PROVIDERS or ident not in ('', provider):
            raise UserFacingError('日历设置无效。')
        if ident and not existing:
            raise UserFacingError('此日历不存在，请返回列表重新选择。')
        if not ident and existing:
            raise UserFacingError('此日历已添加，请从列表进入设置。')
    previous = config.get('calendar_subscription_confirmed', 'no')
    if method != config['calendar_method'] or provider != config['calendar_provider']:
        previous = 'no'
    if method == 'subscribe' and provider:
        if existing is None:
            existing = {'provider': provider, 'confirmed': 'no'}
            rows.append(existing)
        if confirmed is not None:
            existing['confirmed'] = confirmed
        previous = existing['confirmed']
    elif method != 'subscribe':
        rows = []
    return {'calendar_method': method, 'calendar_provider': provider,
            'calendar_subscription_confirmed': confirmed if confirmed is not None else previous,
            'calendar_subscriptions': json.dumps(rows, ensure_ascii=False)}


def remove(config, data):
    provider = data.get('calendarProfileId')
    if provider not in PROVIDERS:
        raise UserFacingError('请选择要移除的日历。')
    rows = subscriptions(config)
    if not any(row['provider'] == provider for row in rows):
        raise UserFacingError('此日历不存在，请返回列表重新选择。')
    remaining = [row for row in rows if row['provider'] != provider]
    selected = next((row for row in remaining if row['provider'] == config.get('calendar_provider')), None)
    selected = selected or (remaining[0] if remaining else None)
    # Never revoke the shared feed or remove approved events for a single app.
    return {'calendar_method': 'subscribe' if remaining else 'unset',
            'calendar_provider': selected['provider'] if selected else '',
            'calendar_subscription_confirmed': selected['confirmed'] if selected else 'no',
            'calendar_subscriptions': json.dumps(remaining, ensure_ascii=False)}
