"""Bounded image attachments for desktop chat; only local image bytes reach the core."""
import base64
import hashlib
from pathlib import Path
import re
import shutil

try:
    from .i18n import tr
    from .chat_store import valid_uuid
except ImportError:
    from i18n import tr
    from chat_store import valid_uuid


MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def image_data(value, maximum=MAX_IMAGE_BYTES):
    if not isinstance(value, str) or len(value) > maximum * 4 // 3 + 128:
        raise ValueError(tr('chat.image_invalid'))
    prefix = 'data:image/jpeg;base64,'
    if not value.startswith(prefix):
        raise ValueError(tr('chat.image_invalid'))
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except ValueError:
        raise ValueError(tr('chat.image_invalid')) from None
    if len(raw) > maximum or not raw.startswith(b'\xff\xd8\xff') or not raw.endswith(b'\xff\xd9'):
        raise ValueError(tr('chat.image_invalid'))
    return raw


def read_sources(paths):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 4:
        raise ValueError(tr('chat.image_limit'))
    result = []
    for value in paths:
        if not isinstance(value, str):
            raise ValueError(tr('chat.image_invalid'))
        path = Path(value)
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(tr('chat.image_source_limit'))
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError(tr('chat.image_source_limit'))
        if raw.startswith(b'\xff\xd8\xff'): mime = 'image/jpeg'
        elif raw.startswith(b'\x89PNG\r\n\x1a\n'): mime = 'image/png'
        elif raw.startswith((b'GIF87a', b'GIF89a')): mime = 'image/gif'
        elif raw.startswith(b'RIFF') and raw[8:12] == b'WEBP': mime = 'image/webp'
        else: raise ValueError(tr('chat.image_invalid'))
        result.append({'name': path.name, 'dataUrl': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')})
    return {'images': result}


class ChatImages:
    def __init__(self, root):
        self.root = root / 'chat-images'

    def directory(self, conversation_id):
        if not valid_uuid(conversation_id):
            raise ValueError(tr('host.invalid_conversation_id'))
        return self.root / conversation_id

    def save(self, conversation_id, values):
        if not isinstance(values, list) or len(values) > 4:
            raise ValueError(tr('chat.image_limit'))
        directory = self.directory(conversation_id)
        pending, result = [], []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError(tr('chat.image_invalid'))
            name = value.get('name', '')
            if not isinstance(name, str) or not 1 <= len(name) <= 240 or any(ord(c) < 32 for c in name):
                raise ValueError(tr('chat.image_invalid'))
            preview = value.get('preview')
            image_data(preview, 80 * 1024)
            if 'dataUrl' in value:
                raw = image_data(value['dataUrl'])
                key = hashlib.sha256(raw).hexdigest()
                pending.append((directory / (key + '.jpg'), raw))
            else:
                key = value.get('id')
                if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key) or not (directory / (key + '.jpg')).is_file():
                    raise ValueError(tr('chat.image_missing'))
            result.append({'id': key, 'name': name, 'preview': preview})
        if pending:
            directory.mkdir(parents=True, exist_ok=True)
            for path, raw in pending:
                path.write_bytes(raw)
        return result

    def content(self, conversation_id, text, attachments):
        if not attachments:
            return text
        directory = self.directory(conversation_id)
        parts = [{'type': 'text', 'text': text}] if text else []
        for attachment in attachments:
            key = attachment['id']
            if not re.fullmatch(r'[a-f0-9]{64}', key):
                raise ValueError(tr('chat.image_invalid'))
            path = directory / (key + '.jpg')
            if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError(tr('chat.image_missing'))
            data = 'data:image/jpeg;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
            image_data(data)
            parts.append({'type': 'image_url', 'image_url': {'url': data}})
        return parts

    def delete(self, conversation_id):
        shutil.rmtree(self.directory(conversation_id), ignore_errors=True)
