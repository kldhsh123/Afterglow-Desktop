"""Stage untouched source from the original repository beside the installed core.

Source archives have no independent release checksum. They are downloaded over
HTTPS directly from GitHub, bounded, validated, and recorded with a local SHA-256.
Existing native wheels are reused only when the upstream dependency declarations
and Python requirement match. No pip, shell command or application is run here.
"""
import hashlib
import logging
import shutil
import stat
import tomllib
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .downloads import fetch_metadata, NETWORK_ERRORS, _connection_error
    from .i18n import tr
    from .repository_updates import VERSION_FILES, parse_version
    from .storage import atomic_json, read_json
    from .updates import version_key
except ImportError:
    from downloads import fetch_metadata, NETWORK_ERRORS, _connection_error
    from i18n import tr
    from repository_updates import VERSION_FILES, parse_version
    from storage import atomic_json, read_json
    from updates import version_key

SOURCE_URL = 'https://github.com/kldhsh123/Afterglow/archive/refs/heads/main.zip'


def prune_core_versions(root, ready_path):
    """Retain the ready core and its immediate predecessor in this instance.

    Only directories recorded in the older installation history and bearing a
    matching core manifest are eligible. Unknown folders and linked roots are
    never removed. Installation metadata is left untouched so a concurrent
    update cannot have its selected version overwritten by health polling.
    """
    removed = []
    root = Path(root).resolve()
    components = root / 'components'
    directory = components / 'core'

    def linked(path):
        return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()

    def local_path(entry):
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            return None
        path = Path(entry['path'])
        if not path.is_absolute() or linked(path):
            return None
        resolved = path.resolve()
        return resolved if resolved.parent == directory else None

    try:
        if linked(components) or linked(directory) or not directory.is_dir():
            return removed
        current = read_json(root / 'installed.json', {}).get('core')
        current_path = local_path(current)
        if current_path is None or current_path != Path(ready_path).resolve():
            return removed
        previous = current.get('previous')
        if not isinstance(previous, dict):
            return removed
        previous_path = local_path(previous)
        if previous_path is None:
            return removed
        protected = {current_path, previous_path}
        entry = previous.get('previous')
        seen = set()
        while isinstance(entry, dict):
            candidate = entry
            entry = entry.get('previous')
            path = local_path(candidate)
            if path is None or path in protected or path in seen or not path.is_dir():
                continue
            seen.add(path)
            try:
                manifest = read_json(path / 'component.json', {})
                if (not isinstance(manifest, dict) or manifest.get('format') != 1
                        or manifest.get('id') != 'core' or manifest.get('version') != candidate.get('version')):
                    continue
                # A new update may have selected another version while health
                # was being checked. Let that process do its own later cleanup.
                latest = read_json(root / 'installed.json', {}).get('core')
                if local_path(latest) != current_path:
                    break
                shutil.rmtree(path)
                removed.append(str(path))
            except (OSError, ValueError) as error:
                logging.getLogger(__name__).warning('Could not remove historical core %s: %s', path, error)
    except (OSError, ValueError, AttributeError) as error:
        logging.getLogger(__name__).warning('Skipping core retention cleanup: %s', error)
    return removed


def prepare_source_update(root, current):
    version = fetch_metadata(VERSION_FILES['core'], lambda data: parse_version(data, 'core'), max_bytes=16384)
    if version_key(version) <= version_key(current['version']):
        return None
    stage = root / 'staging' / ('core-source-' + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    archive = stage / 'source.zip'
    destination = stage / 'component'
    try:
        digest, size = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(SOURCE_URL, timeout=30) as response, archive.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise ValueError(tr('host.the_download_exceeds_the_size_limit'))
                    digest.update(chunk)
                    output.write(chunk)
        except NETWORK_ERRORS as error:
            raise _connection_error(error) from None
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > 50000 or sum(item.file_size for item in entries) > 2 * 1024**3:
                raise ValueError(tr('host.the_package_exceeds_the_size_limit'))
            roots = {PurePosixPath(item.filename).parts[0] for item in entries if item.filename}
            if len(roots) != 1:
                raise ValueError(tr('updates.invalid_source'))
            prefix = next(iter(roots)) + '/'
            downloaded = parse_version(source.read(prefix + 'VERSION'), 'core')
            config = tomllib.loads(source.read(prefix + 'backend/pyproject.toml').decode('utf-8'))
            project = config.get('project', {})
            if downloaded != version or project.get('version') != version or project.get('name') != 'xuwen':
                raise ValueError(tr('updates.source_changed'))
            old = tomllib.loads((Path(current['path']) / 'app' / 'pyproject.toml').read_text(encoding='utf-8'))['project']
            if (sorted(project.get('dependencies', [])) != sorted(old.get('dependencies', []))
                    or project.get('requires-python') != old.get('requires-python')):
                raise ValueError(tr('updates.dependencies_changed'))
            app = destination / 'app'
            app.mkdir(parents=True)
            names = set()
            for item in entries:
                relative = item.filename.removeprefix(prefix)
                if relative.startswith('backend/xuwen/'):
                    target_name = relative.removeprefix('backend/')
                elif relative in {'backend/pyproject.toml', 'backend/.env.example', 'backend/README.md', 'backend/uv.lock'}:
                    target_name = relative.removeprefix('backend/')
                elif relative in {'VERSION', 'LICENSE'}:
                    target_name = relative
                else:
                    continue
                path = PurePosixPath(target_name)
                if ('\\' in target_name or ':' in target_name or path.is_absolute()
                        or any(part in {'', '.', '..'} for part in target_name.rstrip('/').split('/'))
                        or stat.S_ISLNK(item.external_attr >> 16)):
                    raise ValueError(tr('host.the_package_contains_an_unsafe_path'))
                reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
                if any(part.endswith(('.', ' ')) or part.split('.')[0].upper() in reserved for part in path.parts):
                    raise ValueError(tr('host.the_package_contains_a_windows_reserved_path'))
                folded = target_name.rstrip('/').casefold()
                if folded in names:
                    raise ValueError(tr('updates.invalid_source'))
                names.add(folded)
                target = app.joinpath(*path.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(item) as reader, target.open('wb') as writer:
                        shutil.copyfileobj(reader, writer)
            if not (app / 'xuwen' / 'chat_api' / 'app.py').is_file():
                raise ValueError(tr('updates.invalid_source'))
        shutil.copytree(Path(current['path']) / 'deps', destination / 'deps')
        resolved = Path(current['path']) / 'requirements-resolved.txt'
        if resolved.is_file():
            shutil.copy2(resolved, destination / resolved.name)
        manifest = {'format': 1, 'id': 'core', 'version': version, 'python': '3.12',
                    'platform': 'windows-x86_64', 'source': SOURCE_URL, 'sourceSha256': digest.hexdigest()}
        atomic_json(destination / 'component.json', manifest)
        target = root / 'components' / 'core' / (version + '-source-' + uuid.uuid4().hex[:8])
        target.parent.mkdir(parents=True, exist_ok=True)
        destination.replace(target)
        return {'version': version, 'path': str(target), 'manifest': manifest, 'previous': current}
    except (zipfile.BadZipFile, KeyError, tomllib.TOMLDecodeError):
        raise ValueError(tr('updates.invalid_source')) from None
    finally:
        shutil.rmtree(stage, ignore_errors=True)
