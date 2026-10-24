"""Build the website-styled Windows setup without running the installer.

NSIS handles Windows installation only. The desktop UI remains Vue/Tauri so
future macOS packaging does not depend on a Windows UI framework or .NET.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from package_portable import ROOT, digest, desktop_version
from check_installer_resources import verify_installer_ui


def quote(value):
    return str(value).replace('$', '$$').replace('"', '$\\"')


def verify_bootstrapper(path):
    if not path.is_file():
        raise ValueError('Microsoft WebView2 bootstrapper is missing. Download it from the official Microsoft link.')
    windows_path = str(path) if os.name == 'nt' else subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
    powershell = 'powershell.exe' if os.name == 'nt' else '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
    escaped = windows_path.replace("'", "''")
    command = "$s=Get-AuthenticodeSignature -LiteralPath '" + escaped + "'; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation'){exit 1}; $s.SignerCertificate.Thumbprint"
    signature = subprocess.check_output([powershell, '-NoProfile', '-NonInteractive', '-Command', command], text=True).strip()
    return {'sha256': digest(path), 'signerThumbprint': signature}


def compile_installer(compiler, folder, output):
    command = [str(compiler), '-V3', str(folder / 'installer.nsi')]
    print('[Afterglow] 正在生成安装包，每 15 秒报告状态 / Building installer; status every 15s', flush=True)
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=folder)
    try:
        while True:
            try:
                result = process.wait(timeout=15)
                break
            except subprocess.TimeoutExpired:
                try:
                    size = f'{output.stat().st_size / (1024 * 1024):.1f} MiB'
                except OSError:
                    size = '—'
                elapsed = int(time.monotonic() - started)
                print(f'[Afterglow] 安装包仍在生成 / Installer build running: {elapsed}s; '
                      f'临时输出 / temporary output: {size}', flush=True)
    except BaseException:
        # Stop only the compiler launched here if this build is interrupted.
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    if result:
        raise subprocess.CalledProcessError(result, command)


def build(payload, compiler, output=None):
    metadata = json.loads((ROOT / 'version.json').read_text())
    version = desktop_version(metadata)
    manifest = json.loads((payload / 'portable-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != version:
        raise ValueError('Payload and source version differ. Rebuild the portable payload.')
    actual = {str(path.relative_to(payload)).replace('\\', '/') for path in payload.rglob('*') if path.is_file()}
    if actual != set(manifest['files']) | {'portable-manifest.json'}:
        raise ValueError('Payload contains unexpected files. Do not package a used installation.')
    for name, expected in manifest['files'].items():
        path = (payload / name).resolve()
        if payload not in path.parents or digest(path) != expected:
            raise ValueError(f'Payload checksum mismatch: {name}')
    output = output or ROOT / 'artifacts' / f'Afterglow-{version}-windows-x64-setup.exe'
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    windows_version = metadata['baseVersion'] + '.' + str(metadata['internalBuild'])
    bootstrapper = ROOT / '开发缓存/工具链/MicrosoftEdgeWebview2Setup.exe'
    webview = verify_bootstrapper(bootstrapper)
    # Compile original resources only; never run the installer during a build.
    from build_installer_ui import build as build_ui
    from build_installer_skin import build as build_skin
    build_ui()
    build_skin()
    cache = ROOT / '开发缓存' / '构建'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='installer-', dir=cache) as temp:
        folder = Path(temp)
        setup = folder / 'setup.exe'
        values = {'VERSION': version, 'WINDOWS_VERSION': windows_version, 'BUILD': metadata['internalBuild'],
                  'PAYLOAD': payload, 'OUTPUT': setup, 'ICON': ROOT / 'src-tauri/icons/icon.ico',
                  'WEBVIEW_BOOTSTRAPPER': bootstrapper,
                  'INSTALLER_UI': ROOT / 'src-tauri/icons/installer-ui.dll',
                  'INSTALLER_SKIN': ROOT / 'src-tauri/icons/installer-skin.dll',
                  'INSTALLER_SIDEBAR': ROOT / 'src-tauri/icons/installer-sidebar.bmp',
                  'INSTALLER_LOCALES': ROOT / 'locales/installer',
                  'INSTALLER_PAGES': ROOT / 'scripts/installer-pages.nsh'}
        (folder / 'build-config.nsh').write_text(''.join(f'!define {key} "{quote(value)}"\n' for key, value in values.items()), encoding='utf-8')
        uninstall = []
        for child in sorted(payload.iterdir()):
            if child.name == '.afterglow-portable':
                # Retain the harmless marker so a later reinstall can recognize
                # this application's folder without rejecting preserved data.
                continue
            if child.is_symlink() or child.name in {'AfterglowData', 'installation.ini', 'Uninstall.exe'}:
                raise ValueError('Unexpected payload entry')
            path = '$INSTDIR\\' + quote(child.name)
            uninstall.append(f'RMDir /r "{path}"' if child.is_dir() else f'Delete "{path}"')
        (folder / 'uninstall-files.nsh').write_text('\n'.join(uninstall) + '\n', encoding='utf-8')
        shutil.copy2(ROOT / 'scripts/windows-installer.nsi', folder / 'installer.nsi')
        compile_installer(compiler, folder, setup)
        # Ordinary launches must contain the confirmation, progress and finish
        # pages. A successful compiler exit alone cannot establish this.
        verify_installer_ui(setup)
        # Publish only after compression and resource validation succeed.
        created = False
        try:
            with setup.open('rb') as source, output.open('xb') as destination:
                created = True
                shutil.copyfileobj(source, destination)
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    (output.with_suffix('.exe.sha256')).write_text(digest(output) + '  ' + output.name + '\n')
    (output.with_suffix('.exe.build.json')).write_text(json.dumps({'version': version, 'internalBuild': metadata['internalBuild'], 'sha256': digest(output), 'frontend': 'nsis-website', 'webviewBootstrapper': webview}, indent=2) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--makensis', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    compiler = args.makensis or shutil.which('makensis')
    if not compiler:
        compiler = ROOT / '开发缓存/工具链/nsis/usr/bin/makensis'
        os.environ.setdefault('NSISDIR', str(ROOT / '开发缓存/工具链/nsis/usr/share/nsis'))
    print(build(args.payload.resolve(), Path(compiler).resolve(), args.output.resolve() if args.output else None))
