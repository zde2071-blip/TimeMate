"""Per-user forwarding sources, sharing encrypted receiving-account credentials."""
import hashlib
import secrets
from email.utils import parseaddr
from backend.core.user_errors import UserFacingError


def direct_id(cfg):
    return 'oauth:' + cfg['mail_provider'] + ':' + hashlib.sha256(cfg['account'].lower().encode()).hexdigest()[:16]


def receiver_key(account):
    return 'mail:' + hashlib.sha256(account.strip().lower().encode()).hexdigest()


class MailAccounts:
    def __init__(self, database, runtime):
        self.database, self.runtime = database, runtime

    def list(self):
        with self.database() as c:
            rows = [dict(r) for r in c.execute('SELECT * FROM mail_accounts ORDER BY rowid')]
        names = self.names()
        for row in rows:
            row['name'] = names.get(row['id'], '')
            row['connected'] = bool(self.runtime.credential('load', receiver_key(row['account'])))
            row['mode'] = 'forward'
        return rows

    def names(self):
        with self.database() as c:
            return {row['id']: row['name'] for row in c.execute('SELECT id,name FROM mail_account_names')}

    def rename(self, ident, name, direct=None):
        # A label is independent of credentials, cursors and the sync switch.
        if not direct or ident != direct_id(direct):
            self.get(ident)
        if not isinstance(name, str) or len(name.strip()) > 60 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise UserFacingError('邮箱名称最多 60 个字符，请勿包含换行。')
        with self.database() as c:
            if name.strip():
                c.execute('INSERT INTO mail_account_names(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name', (ident,name.strip()))
            else:
                c.execute('DELETE FROM mail_account_names WHERE id=?', (ident,))

    def get(self, ident):
        if not isinstance(ident, str) or not ident or len(ident) > 80:
            raise UserFacingError('邮箱编号无效。')
        with self.database() as c:
            row = c.execute('SELECT * FROM mail_accounts WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise UserFacingError('找不到这个邮箱，请返回列表重新选择。')
        return {**dict(row), 'password': self.runtime.credential('load', receiver_key(row['account']))}

    def adopt(self, cfg):
        if cfg.get('mail_mode') == 'oauth' or not all(cfg.get(k) for k in ('account','school_sender','password')):
            return
        with self.database() as c:
            if c.execute('SELECT 1 FROM mail_accounts LIMIT 1').fetchone(): return
        self.save(cfg)

    def save(self, cfg, ident=None):
        old = self.get(ident) if ident else None
        source = parseaddr(cfg['school_sender'])[1].strip().lower()
        account = cfg['account'].strip().lower()
        with self.database() as c:
            duplicate = c.execute('SELECT id FROM mail_accounts WHERE school_sender=? COLLATE NOCASE', (source,)).fetchone()
            if duplicate and duplicate['id'] != ident:
                raise UserFacingError('这个邮箱已经添加过了，请在列表中点击它进行设置。')
        # Do not store authorization codes in preferences or mailbox metadata.
        self.runtime.credential('save', receiver_key(account), cfg['password'])
        ident = ident or secrets.token_urlsafe(18)
        with self.database() as c:
            c.execute('INSERT INTO mail_accounts(id,school_sender,account,mail_provider) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET school_sender=excluded.school_sender,account=excluded.account,mail_provider=excluded.mail_provider',
                      (ident,source,account,cfg['mail_provider']))
            # Attribute legacy mail without changing its read, deleted or event state.
            for row in c.execute("SELECT id,sender FROM mails WHERE mailbox_id IS NULL AND (receiving_account=? OR receiving_account IS NULL)",
                                 (hashlib.sha256(account.encode()).hexdigest(),)):
                if parseaddr(row['sender'])[1].strip().lower() == source:
                    c.execute('UPDATE mails SET mailbox_id=? WHERE id=?', (ident,row['id']))
            # A newly added source may have been skipped by an existing shared
            # receiver cursor. Replay safely; UID/fingerprint checks avoid duplicates.
            if not old or old['account'].lower() != account or old['school_sender'].lower() != source:
                c.execute('UPDATE cursors SET uid=0 WHERE account=?', (hashlib.sha256(account.encode()).hexdigest(),))
        return ident

    def receivers(self, config):
        groups = {}
        for row in self.list():
            key = row['account'].lower()
            if key not in groups:
                groups[key] = {**config, **self.get(row['id']), '_mail_sources': []}
            groups[key]['_mail_sources'].append({'id':row['id'],'address':row['school_sender']})
        return list(groups.values())


class MultipleReceivers:
    """One failing recipient does not stop the user's other recipients."""
    def __init__(self, configs, status, factory):
        self.configs, self.status, self.factory = configs, status, factory

    def fetch(self): return self._run('fetch')
    def start_auto(self):
        if any(not all(cfg.get(k) for k in ('base','model','key')) for cfg in self.configs):
            raise UserFacingError('请先配置 AI 服务。')
        self.status['auto'] = True
        return self._run('start_auto')
    def process_new(self):
        if not self.status.get('auto'): return '自动检查已停止'
        return self._run('process_new')

    def _run(self, action):
        health = self.status.setdefault('mailboxHealth', {})
        messages, added, active, failures = [], 0, 0, []
        for cfg in self.configs:
            key = cfg['account'].lower()
            child = dict(health.get(key, {}))
            if action == 'process_new' and child.get('sync_error_code') == 'mail_authentication_failed':
                failures.append(key); continue
            child['added'] = 0
            child['auto'] = action != 'fetch' or self.status.get('auto', False)
            try:
                message = getattr(self.factory(cfg, child), action)()
            except UserFacingError:
                child.update(auto=False,sync_state='paused',sync_error_code='mail_config_missing')
                message='请补全接收邮箱设置'
            health[key] = child
            added += child.get('added', 0)
            active += bool(child.get('auto'))
            messages.append(message)
            if child.get('sync_state') in ('paused','retrying','error'): failures.append(key)
        self.status['added'] = added
        if action != 'fetch': self.status['auto'] = bool(active)
        if len(self.configs) == 1 and messages:
            self.status.update({k:v for k,v in health[self.configs[0]['account'].lower()].items() if k != 'mailboxHealth'})
            return messages[0]
        from backend.core import operation_status
        message = f'已检查 {len(messages)} 个接收邮箱，新增 {added} 封邮件'
        if failures: message += '；部分邮箱连接异常，请在邮箱设置中检查'
        operation_status.finish(self.status, message, added=added)
        self.status.update(sync_state='retrying' if failures else 'ready',sync_message=message,
                           sync_error_code='mail_sync_partial' if failures else '')
        return message
