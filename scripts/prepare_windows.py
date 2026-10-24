"""Build verified Windows resources without changing the upstream source tree.

Run using Windows CPython 3.12 x64. The embeddable archive is supplied together
with its independently verified SHA-256; this script never guesses a release URL.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024): h.update(data)
    return h.hexdigest()


def checked(command, **kwargs):
    subprocess.run([str(x) for x in command], check=True, **kwargs)


def package_core(directory: Path, output: Path, version: str):
    """The manifest matches the desktop installer's existing validation rules."""
    files = {file.relative_to(directory).as_posix(): digest(file) for file in sorted(directory.rglob('*'))
             if file.is_file() and file.name != 'component.json'}
    manifest = {'format': 1, 'id': 'core', 'version': version, 'python': '3.12', 'platform': 'windows-x86_64', 'files': files}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('component.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in files: archive.write(directory / name, name)
    return {'id': 'core', 'version': version, 'sha256': digest(output), 'bundled': 'packages/' + output.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-zip', type=Path, required=True)
    parser.add_argument('--python-sha256', required=True)
    parser.add_argument('--build-python', type=Path, default=Path(sys.executable),
                        help='Standard Python used for pure-Python source wheels; needed when this script runs in embeddable Python')
    parser.add_argument('--catalog-update-url', default='', help='Actual published GitHub release catalog URL (optional)')
    parser.add_argument('--core-source', type=Path, default=ROOT / '开发缓存' / 'Afterglow-main')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or platform.machine().lower() not in {'amd64','x86_64'}:
        parser.error('Use Windows CPython 3.12 x64 to prepare the Windows resources.')
    if len(args.python_sha256) != 64 or digest(args.python_zip) != args.python_sha256.lower():
        parser.error('The embeddable Python archive did not match the supplied SHA-256.')
    if args.catalog_update_url:
        sys.path.insert(0,str(ROOT))
        from desktop_host.catalog import release_url
        if not release_url(args.catalog_update_url, metadata=True): parser.error('Untrusted catalog release URL')
    backend = args.core_source.resolve() / 'backend'
    config = tomllib.loads((backend / 'pyproject.toml').read_text(encoding='utf-8'))
    version = config['project']['version']
    resources = ROOT / 'src-tauri' / 'resources'
    cache = ROOT / '开发缓存' / '构建'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('PIP_CACHE_DIR', str(cache / 'pip-cache'))
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('PYTHONUTF8', '1')
    wheelhouse = cache / 'wheels'
    wheelhouse.mkdir(exist_ok=True)
    # jieba currently ships an sdist only. Build it outside the embeddable
    # interpreter, whose isolated _pth deliberately ignores pip's build env.
    source_requirements = [item for item in config['project']['dependencies'] if item.startswith('jieba')]
    if source_requirements and not list(wheelhouse.glob('jieba-*-none-any.whl')):
        checked([args.build_python,'-m','pip','wheel','--no-deps','--wheel-dir',wheelhouse,*source_requirements])
    with tempfile.TemporaryDirectory(prefix='afterglow-windows-', dir=cache) as temporary:
        stage = Path(temporary); runtime = stage / 'python'; runtime.mkdir()
        with zipfile.ZipFile(args.python_zip) as archive:
            for item in archive.infolist():
                name = item.filename.replace('\\','/')
                if name.startswith('/') or ':' in name or '..' in name.split('/'):
                    parser.error('Unsafe path in Python archive.')
            archive.extractall(runtime)
        if not (runtime / 'python312._pth').is_file() or not (runtime / 'python.exe').is_file():
            parser.error('The archive is not an embeddable Windows Python 3.12 distribution.')
        (runtime / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\nimport site\n', encoding='utf-8')
        checked([sys.executable,'-m','pip','install','--no-compile','--target',runtime/'Lib/site-packages','-r',ROOT/'requirements-desktop.txt'])
        component = stage / 'core'; app = component / 'app'; app.mkdir(parents=True)
        shutil.copytree(backend / 'xuwen', app / 'xuwen', ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env'))
        for name in ('.env.example','pyproject.toml','README.md','uv.lock'):
            if (backend / name).is_file(): shutil.copy2(backend / name, app / name)
        for name in ('LICENSE','VERSION'):
            if (args.core_source / name).is_file(): shutil.copy2(args.core_source / name, app / name)
        requirements = stage / 'core-requirements.txt'
        requirements.write_text('\n'.join(config['project']['dependencies'])+'\n',encoding='utf-8')
        checked([sys.executable,'-m','pip','install','--no-compile','--only-binary=:all:',
                 '--find-links',wheelhouse,'--target',component/'deps','-r',requirements])
        freeze = subprocess.check_output([sys.executable,'-m','pip','freeze','--path',str(component/'deps')],text=True)
        (component / 'requirements-resolved.txt').write_text(freeze,encoding='utf-8')
        # Actual imports exercise native wheels and DLL lookup under _pth isolation.
        checked([runtime/'python.exe','-I','-c','import httpx,websockets,cryptography,regex; from cryptography.fernet import Fernet; Fernet.generate_key()'])
        smoke = stage / 'smoke.py'
        smoke.write_text('import sys,os\nfrom pathlib import Path\np=Path(sys.argv[1])\nsys.path[:0]=[str(p/"app"),str(p/"deps")]\nhandles=[os.add_dll_directory(str(x)) for x in (p/"deps").glob("*.libs")]\nimport pyarrow,numpy,lancedb,fastapi,uvicorn,orjson\nfrom xuwen.config import Settings\nfrom xuwen.chat_api.app import create_app\nprint("Core native imports OK")\n',encoding='utf-8')
        checked([runtime/'python.exe','-I',smoke,component])
        resolved_host = subprocess.check_output([sys.executable,'-m','pip','freeze','--path',str(runtime/'Lib/site-packages')],text=True)
        (runtime/'afterglow-runtime.json').write_text(json.dumps({
            'python': platform.python_version(), 'platform': 'windows-x86_64',
            'archiveSha256': args.python_sha256.lower(),
            'requirements': resolved_host.splitlines(),
        }, indent=2)+'\n', encoding='utf-8')
        output = stage / 'packages' / f'afterglow-core-{version}-windows-x64.zip'
        entry = package_core(component,output,version)
        # Replace prepared resources only after all builds and smoke checks pass.
        destination = resources / 'python'
        backup = resources / 'python.previous'
        if backup.exists(): shutil.rmtree(backup)
        if destination.exists(): destination.rename(backup)
        try: shutil.copytree(runtime,destination)
        except Exception:
            if destination.exists(): shutil.rmtree(destination)
            if backup.exists(): backup.rename(destination)
            raise
        if backup.exists(): shutil.rmtree(backup)
        (resources/'packages').mkdir(exist_ok=True)
        shutil.copy2(output,resources/'packages'/output.name)
        (resources/'catalog.json').write_text(json.dumps({'format':1,'components':[entry], **({'updateUrl':args.catalog_update_url} if args.catalog_update_url else {})},indent=2)+'\n',encoding='utf-8')
        print('Windows runtime and original core package prepared. Next: npm run desktop:build')


if __name__ == '__main__': main()
