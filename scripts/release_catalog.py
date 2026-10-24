"""Prepare release metadata from actual local artifacts. This does not publish."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_host.versioning import desktop_version


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024): value.update(block)
    return value.hexdigest()


def prepare(tag, destination):
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', tag):
        raise ValueError('Use a plain GitHub release tag')
    metadata = json.loads((ROOT / 'version.json').read_text())
    version = desktop_version(metadata)
    if tag != 'v' + version:
        raise ValueError('Release tag must match the desktop version: v' + version)
    installer = ROOT / 'artifacts' / ('Afterglow-' + version + '-windows-x64-setup.exe')
    built = json.loads(installer.with_suffix('.exe.build.json').read_text())
    if built['version'] != version or built['sha256'] != digest(installer):
        raise ValueError('The installer checksum or version does not match the build record')
    destination.mkdir(parents=True, exist_ok=False)
    base = 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/' + tag + '/'
    # The full installer already includes the verified core and dependencies.
    # Keep an empty component list for compatibility with existing clients;
    # they restore their bundled catalog instead of downloading a core ZIP.
    release = {'format': 1, 'desktop': {'version': version, 'url': base + installer.name, 'sha256': built['sha256']},
               'components': []}
    for source in (installer, installer.with_suffix('.exe.sha256')):
        shutil.copy2(source, destination / source.name)
    (destination / 'catalog.json').write_text(json.dumps(release, indent=2) + '\n')
    (destination / 'PUBLISHING.txt').write_text(
        'These are local release assets, not a published release.\n'
        'After review and authorization, publish the installer, SHA-256 file and catalog.json\n'
        'together on the Afterglow-Desktop GitHub release with tag ' + tag + '.\n'
        'The core is included in the installer; do not upload a separate core ZIP.\n'
        'Only configure the catalog URL after the uploaded assets are accessible.\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.tag, args.output.resolve()))
