"""Read-only release metadata; only original-project release assets are allowed."""
import json
import re
import urllib.request
from urllib.parse import urlsplit
try:
    from .i18n import tr
    from .downloads import fetch_metadata
except ImportError:
    from i18n import tr
    from downloads import fetch_metadata


def release_url(value, metadata=False, desktop=False):
    if not isinstance(value, str): return False
    parsed = urlsplit(value)
    repositories = ('Afterglow-Desktop',) if desktop else ('Afterglow', 'Afterglow-Desktop')
    return (parsed.scheme == 'https' and parsed.netloc == 'github.com' and not parsed.query and not parsed.fragment
            and any(parsed.path.startswith('/kldhsh123/' + repo + '/releases/' + segment)
                    for repo in repositories for segment in (('download/', 'latest/download/') if metadata else ('download/',))))


def validate_catalog(result):
    entries = result.get('components') if isinstance(result, dict) else None
    if not isinstance(result,dict) or result.get('format') != 1 or not isinstance(entries, list) or len(entries) > 1:
        raise ValueError(tr('updates.invalid_catalog'))
    for entry in entries:
        if (not isinstance(entry, dict) or entry.get('id') != 'core'
            or not isinstance(entry.get('version'), str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',entry['version'])
            or not isinstance(entry.get('sha256'), str) or not re.fullmatch(r'[a-fA-F0-9]{64}',entry['sha256'])
            or not release_url(entry.get('url'))):
            raise ValueError(tr('updates.invalid_catalog'))
    desktop = result.get('desktop')
    if desktop is not None and (not isinstance(desktop, dict)
        or not isinstance(desktop.get('version'), str)
        or not re.fullmatch(r'\d+\.\d+\.\d+(?:-internal\.\d+)?', desktop['version'])
        or not isinstance(desktop.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', desktop['sha256'])
        or not release_url(desktop.get('url'), desktop=True) or not urlsplit(desktop['url']).path.endswith('-windows-x64-setup.exe')):
        raise ValueError(tr('updates.invalid_catalog'))
    return {'format': 1, 'components': entries, **({'desktop': desktop} if desktop else {})}


def fetch_catalog(url, root=None):
    if not release_url(url, metadata=True):
        raise ValueError(tr('host.the_component_source_is_outside_the_builtin_allowlist'))
    return {**fetch_metadata(url, lambda data: validate_catalog(json.loads(data))), 'updateUrl': url}
