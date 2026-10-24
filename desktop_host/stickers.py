"""Bounded desktop transport for the original core's sticker library."""
import base64
import re
import urllib.error
import urllib.request
from urllib.parse import quote

try:
    from .chat_images import read_sources
    from .i18n import tr
    from .model_gateway import NoRedirect
except ImportError:
    from chat_images import read_sources
    from i18n import tr
    from model_gateway import NoRedirect

MAX_BYTES = 2 * 1024 * 1024


class Stickers:
    def __init__(self, manager):
        self.manager = manager

    def dispatch(self, method, args):
        manager = self.manager
        if method == 'stickers_list':
            owner = args.get('owner')
            if owner is not None and owner not in {'self', 'ai', 'shared'}:
                raise ValueError(tr('stickers.invalid'))
            return manager.core_request('/v1/stickers' + ('?owner=' + owner if owner else ''))
        name = args.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[\w\u4e00-\u9fff-]{1,32}', name):
            raise ValueError(tr('stickers.invalid_name'))
        path = '/v1/stickers/' + quote(name, safe='')
        if method == 'stickers_image':
            # Readiness guard and authentication stay local; redirects are forbidden.
            proc = manager.children.get('core')
            if manager.port is None or proc is None or proc.poll() is not None:
                raise ValueError(tr('analysis.core_needed'))
            request = urllib.request.Request(f'http://127.0.0.1:{manager.port}' + path + '/image',
                                             headers={'Authorization': 'Bearer ' + manager.secrets.get('local_api')})
            try:
                with urllib.request.build_opener(NoRedirect).open(request, timeout=12) as response:
                    mime = response.headers.get_content_type()
                    raw = response.read(MAX_BYTES + 1)
            except (urllib.error.URLError, TimeoutError, OSError):
                raise ValueError(tr('stickers.image_failed')) from None
            if len(raw) > MAX_BYTES or mime not in {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'}:
                raise ValueError(tr('stickers.invalid'))
            return {'dataUrl': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')}
        if method == 'stickers_delete':
            return manager.core_request(path, method='DELETE')
        description, owner, tags = args.get('description'), args.get('owner'), args.get('tags', [])
        if (not isinstance(description, str) or not 1 <= len(description.strip()) <= 200
                or owner not in {'self', 'ai', 'shared'} or not isinstance(tags, list)
                or len(tags) > 20 or any(not isinstance(tag, str) or not 1 <= len(tag) <= 40 for tag in tags)):
            raise ValueError(tr('stickers.invalid'))
        payload = {'description': description.strip(), 'owner': owner, 'tags': tags}
        if method == 'stickers_update':
            return manager.core_request(path, payload, method='PATCH')
        if method == 'stickers_create':
            source = args.get('path')
            if not isinstance(source, str):
                raise ValueError(tr('stickers.invalid'))
            image = read_sources([source])['images'][0]['dataUrl']
            if len(base64.b64decode(image.split(',', 1)[1])) > MAX_BYTES:
                raise ValueError(tr('stickers.size_limit'))
            return manager.core_request('/v1/stickers', {**payload, 'name': name, 'data_url': image})
        raise ValueError(tr('host.unsupported_manager_operation'))
