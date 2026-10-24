"""Stage verified desktop installers; the native shell applies them after exit."""
import hashlib
from pathlib import Path
import re
import urllib.request
import uuid

try:
    from .catalog import validate_catalog
    from .i18n import tr
    from .downloads import download_verified
except ImportError:
    from catalog import validate_catalog
    from i18n import tr
    from downloads import download_verified


def version_key(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-internal\.(\d+))?', value or '')
    if not match:
        raise ValueError(tr('updates.invalid_catalog'))
    major, minor, patch, internal = match.groups()
    return int(major), int(minor), int(patch), int(internal) if internal is not None else 2**63


def stage_installer(root, catalog, current_version):
    release = validate_catalog({'format': 1, 'components': [], 'desktop': catalog.get('desktop')}).get('desktop')
    if not release or version_key(release['version']) <= version_key(current_version):
        raise ValueError(tr('updates.no_desktop_update'))
    directory = root / 'updates'
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (uuid.uuid4().hex + '.download')
    target = directory / ('Afterglow-' + release['version'] + '-windows-x64-setup.exe')
    if target.is_file():
        with target.open('rb') as stream:
            valid_executable = stream.read(2) == b'MZ'
        if valid_executable:
            with target.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == release['sha256']:
                    return {'path': str(target), 'sha256': release['sha256'], 'version': release['version']}
    try:
        download_verified(release['url'], temporary, release['sha256'], 512 * 1024 * 1024, executable=True)
        temporary.replace(target)
        return {'path': str(target), 'sha256': release['sha256'], 'version': release['version']}
    finally:
        temporary.unlink(missing_ok=True)
