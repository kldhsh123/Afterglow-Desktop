"""Refresh bundled upstream source while retaining verified Windows dependencies.

This prepares a core resource ZIP only. It does not compile the desktop app,
install dependencies, run an application, or create an installer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_host.storage import atomic_json


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def refresh_package(source, base, output, expected_sha256):
    source, base, output = Path(source).resolve(), Path(base).resolve(), Path(output).resolve()
    if output == base or output.exists():
        raise ValueError('Choose an unused output path; the base package is never overwritten.')
    if digest(base) != expected_sha256:
        raise ValueError('The existing core ZIP does not match its catalog checksum.')
    project = tomllib.loads((source / 'backend/pyproject.toml').read_text(encoding='utf-8'))['project']
    version = (source / 'VERSION').read_text(encoding='utf-8-sig').strip()
    if project.get('name') != 'xuwen' or version != project.get('version'):
        raise ValueError('The upstream VERSION and project metadata must match.')
    files = {}
    for path in sorted((source / 'backend/xuwen').rglob('*')):
        relative = path.relative_to(source / 'backend')
        if '__pycache__' in relative.parts or path.suffix in {'.pyc', '.pyo'} or path.name == '.env':
            continue
        if path.is_symlink():
            raise ValueError('Linked upstream source paths are not packaged.')
        if path.is_file():
            files['app/' + relative.as_posix()] = path
    for name in ('.env.example', 'pyproject.toml', 'README.md', 'uv.lock'):
        path = source / 'backend' / name
        if path.is_file():
            if path.is_symlink():
                raise ValueError('Linked upstream metadata is not packaged.')
            files['app/' + name] = path
    for name in ('VERSION', 'LICENSE'):
        path = source / name
        if path.is_file():
            if path.is_symlink():
                raise ValueError('Linked upstream metadata is not packaged.')
            files['app/' + name] = path
    if 'app/xuwen/chat_api/app.py' not in files:
        raise ValueError('The upstream core entrypoint is missing.')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with zipfile.ZipFile(base) as old:
            manifest = json.loads(old.read('component.json'))
            if (manifest.get('format') != 1 or manifest.get('id') != 'core'
                    or manifest.get('python') != '3.12' or manifest.get('platform') != 'windows-x86_64'
                    or not isinstance(manifest.get('files'), dict)):
                raise ValueError('The base package is not a verified Windows core.')
            metadata = old.read('app/pyproject.toml')
            if hashlib.sha256(metadata).hexdigest() != manifest['files'].get('app/pyproject.toml'):
                raise ValueError('The base project metadata checksum does not match.')
            previous = tomllib.loads(metadata.decode('utf-8-sig'))['project']
            if (project.get('requires-python') != previous.get('requires-python')
                    or sorted(project.get('dependencies', [])) != sorted(previous.get('dependencies', []))):
                raise ValueError('Dependency requirements changed; prepare a new Windows runtime instead.')
            inherited = {name: checksum for name, checksum in manifest['files'].items()
                         if name.startswith('deps/') or name == 'requirements-resolved.txt'}
            if not any(name.startswith('deps/') for name in inherited):
                raise ValueError('The base core contains no reusable dependencies.')
            checksums = {}
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                for index, (name, expected) in enumerate(sorted(inherited.items()), 1):
                    if '\\' in name or ':' in name or any(part in {'', '.', '..'} for part in name.split('/')):
                        raise ValueError('The base package contains an unsafe dependency path.')
                    hasher = hashlib.sha256()
                    with old.open(name) as reader, archive.open(name, 'w', force_zip64=True) as writer:
                        while chunk := reader.read(1024 * 1024):
                            hasher.update(chunk); writer.write(chunk)
                    if hasher.hexdigest() != expected:
                        raise ValueError('The dependency checksum does not match: ' + name)
                    checksums[name] = expected
                    if index % 1000 == 0:
                        print(f'Verified Windows dependency files: {index}/{len(inherited)}', flush=True)
                for name, path in files.items():
                    contents = path.read_bytes()
                    checksums[name] = hashlib.sha256(contents).hexdigest()
                    archive.writestr(name, contents)
                archive.writestr('component.json', json.dumps({
                    'format': 1, 'id': 'core', 'version': version, 'python': '3.12',
                    'platform': 'windows-x86_64', 'files': checksums,
                }, ensure_ascii=False, indent=2))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {'id': 'core', 'version': version, 'sha256': digest(output), 'bundled': 'packages/' + output.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-source', type=Path, required=True)
    args = parser.parse_args()
    resources = ROOT / 'src-tauri/resources'
    catalog_path = resources / 'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    old = next(entry for entry in catalog['components'] if entry['id'] == 'core')
    base = (resources / old['bundled']).resolve()
    if base.parent != (resources / 'packages').resolve():
        raise ValueError('The base core must be inside the bundled packages directory.')
    version = (args.core_source / 'VERSION').read_text(encoding='utf-8-sig').strip()
    if not version or any(character not in '0123456789.-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_' for character in version):
        raise ValueError('Invalid upstream core version.')
    output = resources / 'packages' / f'afterglow-core-{version}-windows-x64.zip'
    entry = refresh_package(args.core_source, base, output, old['sha256'])
    catalog['components'] = [entry]
    atomic_json(catalog_path, catalog)
    backup = ROOT / '开发缓存/核心运行包备份' / (base.stem + '.' + old['sha256'][:12] + '.zip')
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if digest(backup) != old['sha256']:
            raise ValueError('The existing backup has a different checksum; the previous bundled ZIP was retained.')
        base.unlink()
    else:
        shutil.move(str(base), str(backup))
    print(json.dumps({'core': entry, 'previousPackageBackup': str(backup)}, ensure_ascii=False), flush=True)
    print('Core resource prepared. Run npm run version:sync to refresh runtime metadata.', flush=True)


if __name__ == '__main__':
    main()
