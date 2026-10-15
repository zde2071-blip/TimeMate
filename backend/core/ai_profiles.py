"""Account-scoped AI connections. Metadata lives in mail.db; secrets stay encrypted."""
import json
import secrets
from backend.core.user_errors import UserFacingError

FIELDS = ('provider', 'base', 'model')

class AIProfiles:
    def __init__(self, database, runtime, validate):
        self.database, self.runtime, self.validate = database, runtime, validate

    def list(self):
        with self.database() as c:
            rows = [dict(row) for row in c.execute('SELECT id,name,provider,base,model,is_default,models,model_names FROM ai_profiles ORDER BY rowid')]
        for row in rows:
            row['models'] = json.loads(row['models']) or [row['model']]
            row['model_names'] = json.loads(row['model_names'])
        return rows

    def get(self, ident):
        if not isinstance(ident, str) or not ident or len(ident) > 80:
            raise UserFacingError('AI 连接编号无效。')
        with self.database() as c:
            row = c.execute('SELECT * FROM ai_profiles WHERE id=?', (ident,)).fetchone()
        if not row:
            raise UserFacingError('找不到这条 AI 连接，请重新选择。')
        cfg = dict(row)
        cfg['models'] = json.loads(cfg['models']) or [cfg['model']]
        cfg['model_names'] = json.loads(cfg['model_names'])
        cfg['key'] = self.runtime.credential('load', 'ai-profile:' + ident)
        return cfg

    def save(self, data):
        ident = data.get('profileId')
        old = self.get(ident) if ident else None
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise UserFacingError('连接名称不能为空，且不能超过 60 个字符。')
        cfg = {field: str(data.get(field) or '').strip() for field in FIELDS}
        models = data.get('models', [cfg['model']])
        if not isinstance(models, list) or not models or len(models) > 100 or any(not isinstance(m, str) or not m.strip() or len(m) > 200 for m in models):
            raise UserFacingError('请启用 1 至 100 个有效模型。')
        models = list(dict.fromkeys(m.strip() for m in models))
        raw_names=data.get('modelNames',data.get('model_names',old['model_names'] if old else {}))
        if not isinstance(raw_names,dict) or len(raw_names)>5000:
            raise UserFacingError('模型名称格式无效。')
        names={model:raw_names[model].strip() for model in models if isinstance(raw_names.get(model),str) and raw_names[model].strip() and len(raw_names[model])<=200 and not any(ord(c)<32 for c in raw_names[model])}
        if old and old['is_default'] and data.get('makeDefault') is not True:
            if old['model'] not in models:
                raise UserFacingError('请先选择另一个邮件自动分析模型，再停用当前型号。')
            cfg['model'] = old['model']
        if cfg['model'] not in models:
            raise UserFacingError('所选型号未启用。')
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
            c.execute('INSERT INTO ai_profiles(id,name,provider,base,model,is_default,models,model_names) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,provider=excluded.provider,base=excluded.base,model=excluded.model,is_default=excluded.is_default,models=excluded.models,model_names=excluded.model_names',
                      (ident, name.strip(), cfg['provider'], cfg['base'], cfg['model'], int(default), json.dumps(models),json.dumps(names)))
        return ident

    def update_model_names(self, ident, names):
        profile=self.get(ident)
        merged={**profile['model_names'],**{model:names[model] for model in profile['models'] if model in names}}
        if merged!=profile['model_names']:
            with self.database() as c:
                c.execute('UPDATE ai_profiles SET model_names=? WHERE id=?',(json.dumps(merged),ident))

    def adopt(self, cfg):
        if not self.list() and cfg.get('key'):
            self.save({**cfg, 'name': cfg.get('model') or '原有连接', 'makeDefault': True})

    def delete(self, ident):
        profile = self.get(ident)
        if profile['is_default']:
            raise UserFacingError('请先选择另一个邮件自动分析模型，再移除此服务。')
        with self.database() as c:
            c.execute('DELETE FROM ai_profiles WHERE id=?', (ident,))
        self.runtime.credential('delete', 'ai-profile:' + ident)
