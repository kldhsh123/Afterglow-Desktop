"""Check stable release metadata without building or running the desktop app."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from desktop_host.host import Manager
from desktop_host.catalog import validate_catalog
from desktop_host.versioning import desktop_version
from scripts.release_catalog import prepare


ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionTests(unittest.TestCase):
    def test_stable_and_legacy_internal_versions(self):
        self.assertEqual(desktop_version({'baseVersion': '0.1.0', 'internalBuild': 15}), '0.1.0-internal.15')
        self.assertEqual(desktop_version({'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'internal'}), '0.1.0-internal.16')
        self.assertEqual(desktop_version({'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'stable'}), '0.1.0')

    def test_host_compares_stable_releases_and_does_not_offer_an_internal_downgrade(self):
        manager = Manager.__new__(Manager)
        metadata = {'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'stable'}
        for release, available in [('0.1.0', False), ('0.1.0-internal.99', False), ('0.1.1', True)]:
            with self.subTest(release=release), patch('desktop_host.host.read_json', return_value=metadata):
                manager.catalog = {'desktop': {'version': release}}
                status = manager.desktop_update_status()
                self.assertEqual(status['currentVersion'], '0.1.0')
                self.assertEqual(status['available'], available)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_javascript_and_python_agree_on_supported_metadata(self):
        cases = [{'baseVersion': '0.1.0', 'internalBuild': 16},
                 {'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'stable'},
                 {'baseVersion': '0.1.1', 'internalBuild': 17, 'channel': 'internal'},
                 {'baseVersion': '0.1.0', 'internalBuild': 65535, 'channel': 'internal'}]
        invalid = [None, {}, {'baseVersion': 'bad', 'internalBuild': 16},
                   {'baseVersion': '0.1.0\n', 'internalBuild': 16},
                   {'baseVersion': '０.１.０', 'internalBuild': 16},
                   {'baseVersion': '65536.0.0', 'internalBuild': 16}]
        invalid += [{'baseVersion': '0.1.0', 'internalBuild': build} for build in (True, 0, -1, 65536, '16')]
        invalid += [{'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': channel}
                    for channel in (None, True, '', 'release')]
        module = (ROOT / 'scripts/version_metadata.mjs').as_uri()
        script = ('import { desktopVersion } from ' + json.dumps(module) + ';'
                  'import { readFileSync } from "node:fs";'
                  'console.log(JSON.stringify(JSON.parse(readFileSync(0,"utf8")).map(value => {'
                  'try {return desktopVersion(value)} catch {return null}})))')
        result = subprocess.run(['node', '--input-type=module', '-e', script],
                                input=json.dumps(cases + invalid), capture_output=True, text=True, check=True, timeout=15)
        self.assertEqual(json.loads(result.stdout), [desktop_version(case) for case in cases] + [None] * len(invalid))
        for case in invalid:
            with self.subTest(metadata=case), self.assertRaises(ValueError):
                desktop_version(case)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_sync_and_bump_keep_all_metadata_on_stable_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('scripts/version.mjs', 'scripts/version_metadata.mjs', 'scripts/runtime_catalog.mjs',
                         'version.json', 'package.json', 'package-lock.json', 'src-tauri/tauri.conf.json',
                         'src-tauri/Cargo.toml', 'src-tauri/Cargo.lock', 'src-tauri/resources/catalog.json'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            metadata = {'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'stable'}
            (root / 'version.json').write_text(json.dumps(metadata))
            run = lambda *args: subprocess.run(['node', str(root / 'scripts/version.mjs'), *args],
                                               capture_output=True, text=True, timeout=15)
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '0.1.0')
            for name in ('package.json', 'package-lock.json', 'src-tauri/tauri.conf.json'):
                self.assertEqual(json.loads((root / name).read_text())['version'], '0.1.0')
            lock = json.loads((root / 'package-lock.json').read_text())
            self.assertEqual(lock['packages']['']['version'], '0.1.0')
            self.assertIn('name = "afterglow-desktop"\nversion = "0.1.0"', (root / 'src-tauri/Cargo.lock').read_text())
            self.assertIn('version = "0.1.0"', (root / 'src-tauri/Cargo.toml').read_text())
            catalog = json.loads((root / 'src-tauri/resources/runtime-catalog.json').read_text())
            self.assertTrue(catalog['components'][0]['bundled'].startswith('packages/'))
            self.assertNotIn('url', catalog['components'][0])
            bumped = run('--bump')
            self.assertEqual(bumped.returncode, 0, bumped.stderr)
            self.assertEqual(bumped.stdout.strip(), '0.1.1')
            self.assertEqual(json.loads((root / 'version.json').read_text()),
                             {'baseVersion': '0.1.1', 'internalBuild': 17, 'channel': 'stable'})
            for name in ('package.json', 'package-lock.json', 'src-tauri/tauri.conf.json'):
                self.assertEqual(json.loads((root / name).read_text())['version'], '0.1.1')
            self.assertIn('name = "afterglow-desktop"\nversion = "0.1.1"', (root / 'src-tauri/Cargo.lock').read_text())
            catalog = json.loads((root / 'src-tauri/resources/runtime-catalog.json').read_text())
            self.assertNotIn('url', catalog['components'][0])
            again = run('--bump')
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(again.stdout.strip(), '0.1.2')
            self.assertEqual(json.loads((root / 'version.json').read_text())['internalBuild'], 18)


class ReleaseCatalogTests(unittest.TestCase):
    def test_release_tag_must_match_version_before_creating_any_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'version.json').write_text(json.dumps({'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'stable'}))
            output = root / 'release'
            with patch('scripts.release_catalog.ROOT', root), self.assertRaisesRegex(ValueError, 'v0.1.0'):
                prepare('v0.1.1', output)
            self.assertFalse(output.exists())

    def test_generated_catalog_only_requires_the_desktop_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'version.json').write_text(json.dumps({'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': 'stable'}))
            installer = root / 'artifacts/Afterglow-0.1.0-windows-x64-setup.exe'
            installer.parent.mkdir()
            installer.write_bytes(b'non-executable release fixture')
            checksum = hashlib.sha256(installer.read_bytes()).hexdigest()
            installer.with_suffix('.exe.build.json').write_text(json.dumps({'version': '0.1.0', 'sha256': checksum}))
            installer.with_suffix('.exe.sha256').write_text(checksum + '  ' + installer.name + '\n')
            # Release preparation needs no separate core ZIP or source catalog:
            # the verified full installer already contains the runtime package.
            output = root / 'release'
            with patch('scripts.release_catalog.ROOT', root):
                prepare('v0.1.0', output)
            catalog = validate_catalog(json.loads((output / 'catalog.json').read_text()))
            self.assertEqual(catalog['desktop']['version'], '0.1.0')
            self.assertEqual(catalog['desktop']['sha256'], checksum)
            self.assertEqual(catalog['desktop']['url'],
                             'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v0.1.0/' + installer.name)
            self.assertEqual(catalog['components'], [])
            self.assertEqual({file.name for file in output.iterdir()},
                             {installer.name, installer.name + '.sha256', 'catalog.json', 'PUBLISHING.txt'})
            self.assertNotIn('.zip', (output / 'catalog.json').read_text())

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_runtime_catalog_only_keeps_verified_local_core_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = root / 'src-tauri/resources'
            resources.mkdir(parents=True)
            entry = {'id': 'core', 'version': '0.4.1', 'sha256': 'a' * 64, 'bundled': 'packages/core.zip',
                     'url': 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v0.1.0/core.zip'}
            (resources / 'catalog.json').write_text(json.dumps({'format': 1, 'components': [entry]}))
            module = (ROOT / 'scripts/runtime_catalog.mjs').as_uri()
            script = ('import { writeRuntimeCatalog } from ' + json.dumps(module) + ';'
                      'writeRuntimeCatalog(process.argv[1]);')
            result = subprocess.run(['node', '--input-type=module', '-e', script, str(root)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            catalog = json.loads((resources / 'runtime-catalog.json').read_text())
            self.assertEqual(catalog['components'], [{key: value for key, value in entry.items() if key != 'url'}])
            self.assertEqual(catalog['updateUrl'],
                             'https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json')
