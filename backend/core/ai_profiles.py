"""Account-scoped AI connections. Metadata lives in mail.db; secrets stay encrypted."""
import secrets
from backend.core.user_errors import UserFacingError

FIELDS = ('provider', 'base', 'model')

class AIProfiles:
    def __init__(self, database, runtime, validate):
        self.database, self.runtime, self.validate = database, runtime, validate

    def list(self):
        with self.database() as c:
            return [dict(row) for row in c.execute('SELECT id,name,provider,base,model,is_default FROM ai_profiles ORDER BY is_default DESC,rowid')]

    def get(self, ident):
        if not isinstance(ident, str) or not ident or len(ident) > 80:
            raise UserFacingError('AI 连接编号无效。')
        with self.database() as c:
            row = c.execute('SELECT * FROM ai_profiles WHERE id=?', (ident,)).fetchone()
        if not row:
            raise UserFacingError('找不到这条 AI 连接，请重新选择。')
        cfg = dict(row)
        cfg['key'] = self.runtime.credential('load', 'ai-profile:' + ident)
        return cfg

    def save(self, data):
        ident = data.get('profileId')
        old = self.get(ident) if ident else None
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise UserFacingError('连接名称不能为空，且不能超过 60 个字符。')
        cfg = {field: str(data.get(field) or '').strip() for field in FIELDS}
        key = data.get('key')
        if key is not None and (not isinstance(key, str) or len(key) > 8192):
            raise UserFacingError('API Key 格式无效。')
        same = old and old['provider'] == cfg['provider'] and old['base'].rstrip('/') == cfg['base'].rstrip('/')
        cfg['key'] = key.strip() if isinstance(key, str) and key.strip() else old['key'] if same else ''
        self.validate(cfg)
        profiles = self.list()
        if not old and len(profiles) >= 20:
            raise UserFacingError('最多保存 20 条 AI 连接。')
        default = not profiles or data.get('makeDefault') is True or bool(old and old['is_default'])
        ident = ident or secrets.token_urlsafe(18)
        self.runtime.credential('save', 'ai-profile:' + ident, cfg['key'])
        with self.database() as c:
            c.execute('BEGIN IMMEDIATE')
            if default:
                c.execute('UPDATE ai_profiles SET is_default=0')
            c.execute('INSERT INTO ai_profiles(id,name,provider,base,model,is_default) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,provider=excluded.provider,base=excluded.base,model=excluded.model,is_default=excluded.is_default',
                      (ident, name.strip(), cfg['provider'], cfg['base'], cfg['model'], int(default)))
        return ident

    def adopt(self, cfg):
        if not self.list() and cfg.get('key'):
            self.save({**cfg, 'name': cfg.get('model') or '原有连接', 'makeDefault': True})

    def delete(self, ident):
        profile = self.get(ident)
        if profile['is_default']:
            raise UserFacingError('请先将另一条连接设为默认，再移除此连接。')
        with self.database() as c:
            c.execute('DELETE FROM ai_profiles WHERE id=?', (ident,))
        self.runtime.credential('delete', 'ai-profile:' + ident)
