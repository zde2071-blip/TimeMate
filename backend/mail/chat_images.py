"""Bounded inline image inputs; image bytes are never persisted."""
import base64
import binascii
import re
from backend.core.user_errors import UserFacingError

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 6 * 1024 * 1024
CHAT_REQUEST_BYTES = 9 * 1024 * 1024


def validate_images(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_IMAGES:
        raise UserFacingError('每次最多上传 3 张图片。')
    images, total = [], 0
    for item in value:
        if not isinstance(item, dict):
            raise UserFacingError('图片格式无效。')
        url = item.get('dataUrl')
        if not isinstance(url, str) or len(url) > MAX_IMAGE_BYTES * 4 // 3 + 100:
            raise UserFacingError('单张图片不能超过 3 MB。')
        match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)', url)
        if not match:
            raise UserFacingError('请上传 PNG、JPEG 或 WebP 图片。')
        try:
            raw = base64.b64decode(match[2], validate=True)
        except (ValueError, binascii.Error):
            raise UserFacingError('图片数据损坏，请重新上传。') from None
        mime = match[1]
        valid = (mime == 'image/png' and len(raw) >= 24 and raw.startswith(b'\x89PNG\r\n\x1a\n')
                 or mime == 'image/jpeg' and len(raw) >= 12 and raw.startswith(b'\xff\xd8\xff')
                 or mime == 'image/webp' and len(raw) >= 16 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')
        if not valid or len(raw) > MAX_IMAGE_BYTES:
            raise UserFacingError('图片内容与格式不匹配，请重新上传。')
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise UserFacingError('本次图片总大小不能超过 6 MB。')
        name = item.get('name')
        name = re.sub(r'[\x00-\x1f\x7f]', '', name)[:100] if isinstance(name, str) else '图片'
        images.append({'name': name or '图片', 'dataUrl': url})
    return images
