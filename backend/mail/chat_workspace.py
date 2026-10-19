"""Bounded task context; optional image cache uses the account's encrypted vault."""
import json
import re
import time
from backend.mail.chat_images import validate_images
from backend.core.user_errors import UserFacingError

IMAGE_TTL = 7 * 24 * 3600


def load(connection, conversation_id, vault=None):
    row = connection.execute('SELECT data FROM chat_workspaces WHERE conversation_id=?',(conversation_id,)).fetchone()
    try: data = json.loads(row['data']) if row else {}
    except (ValueError,TypeError): data = {}
    if not isinstance(data,dict): data = {}
    images = []
    if data.get('image_saved_at'):
        if vault and time.time() - data['image_saved_at'] < IMAGE_TTL:
            try: images = validate_images(json.loads(vault('load','chat-images:'+conversation_id) or '[]'))
            except (ValueError,TypeError,UserFacingError): images = []
        elif vault:
            vault('delete','chat-images:'+conversation_id)
            data.pop('image_saved_at',None)
    return data, images


def scope(question, images, previous):
    exclude = re.search(r'不要.*邮件|不用.*邮件|只.*(?:图片|课表)|不是.*邮件',question,re.I)
    mail = not exclude and re.search(r'邮件|邮箱|e-?mail|查找.*通知|收件',question,re.I)
    if mail: return 'mail'
    if images or exclude: return 'external'
    return previous.get('scope','external')


def save(connection, conversation_id, data, images=None, vault=None):
    if images is not None and vault:
        vault('save','chat-images:'+conversation_id,json.dumps(images,ensure_ascii=False))
        data['image_saved_at'] = time.time()
    connection.execute('INSERT INTO chat_workspaces VALUES (?,?) ON CONFLICT(conversation_id) DO UPDATE SET data=excluded.data',
                       (conversation_id,json.dumps(data,ensure_ascii=False)))
