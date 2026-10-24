"""Small resource fixtures; never build or launch a desktop executable."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.refresh_bundled_core import digest, refresh_package


def project(version, dependency='httpx>=0.27,<1'):
    return f'[project]\nname="xuwen"\nversion="{version}"\nrequires-python=">=3.12,<3.13"\ndependencies=["{dependency}"]\n'


class BundledCoreRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Afterglow-0.4.1'
        code = self.source / 'backend/xuwen/chat_api'
        code.mkdir(parents=True)
        (code / 'app.py').write_text('# untouched upstream 0.4.1\n')
        (code / '.env').write_text('DO_NOT_PACKAGE=secret')
        (code / '__pycache__').mkdir()
        (code / '__pycache__/app.pyc').write_bytes(b'stale cache')
        (self.source / 'VERSION').write_text('0.4.1\n')
        (self.source / 'LICENSE').write_text('Upstream license')
        (self.source / 'backend/pyproject.toml').write_text(project('0.4.1'))
        self.base = self.root / 'core-0.4.0.zip'
        self.output = self.root / 'core-0.4.1.zip'

    def old_package(self, extra=None, corrupt=False):
        files = {'app/pyproject.toml': project('0.4.0').encode(),
                 'app/xuwen/obsolete.py': b'Old code', 'deps/native.pyd': b'Native Windows dependency',
                 'requirements-resolved.txt': b'httpx==0.28.1\n'}
        if extra: files.update(extra)
        manifest = {'format': 1, 'id': 'core', 'version': '0.4.0', 'python': '3.12',
                    'platform': 'windows-x86_64',
                    'files': {name: hashlib.sha256(contents).hexdigest() for name, contents in files.items()}}
        with zipfile.ZipFile(self.base, 'w') as archive:
            for name, contents in files.items():
                archive.writestr(name, b'Corrupted dependency' if corrupt and name == 'deps/native.pyd' else contents)
            archive.writestr('component.json', json.dumps(manifest))
        return digest(self.base)

    def test_source_is_replaced_and_windows_dependencies_are_preserved(self):
        checksum = self.old_package()
        entry = refresh_package(self.source, self.base, self.output, checksum)
        self.assertEqual(entry['version'], '0.4.1')
        self.assertEqual(entry['sha256'], digest(self.output))
        self.assertEqual(digest(self.base), checksum)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read('app/xuwen/chat_api/app.py'), b'# untouched upstream 0.4.1\n')
            self.assertEqual(archive.read('deps/native.pyd'), b'Native Windows dependency')
            self.assertEqual(archive.read('requirements-resolved.txt'), b'httpx==0.28.1\n')
            self.assertNotIn('app/xuwen/obsolete.py', archive.namelist())
            self.assertFalse(any('__pycache__' in name or name.endswith('/.env') for name in archive.namelist()))
            manifest = json.loads(archive.read('component.json'))
            for name, expected in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)

    def test_changed_requirements_abort_without_modifying_base(self):
        checksum = self.old_package()
        (self.source / 'backend/pyproject.toml').write_text(project('0.4.1', 'httpx>=0.29,<1'))
        with self.assertRaisesRegex(ValueError, 'Dependency requirements changed'):
            refresh_package(self.source, self.base, self.output, checksum)
        self.assertFalse(self.output.exists())
        self.assertEqual(digest(self.base), checksum)

    def test_bad_base_hash_and_corrupted_dependencies_are_rejected(self):
        checksum = self.old_package(corrupt=True)
        for expected in ('0' * 64, checksum):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                refresh_package(self.source, self.base, self.output, expected)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_unsafe_dependency_paths_are_not_copied(self):
        checksum = self.old_package({'deps/../outside': b'Unsafe'})
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            refresh_package(self.source, self.base, self.output, checksum)
        self.assertFalse(self.output.exists())

    def test_version_mismatch_and_existing_output_are_rejected(self):
        checksum = self.old_package()
        (self.source / 'VERSION').write_text('0.4.2')
        with self.assertRaisesRegex(ValueError, 'metadata must match'):
            refresh_package(self.source, self.base, self.output, checksum)
        self.output.write_bytes(b'Existing archive')
        with self.assertRaises(ValueError):
            refresh_package(self.source, self.base, self.output, checksum)
        self.assertEqual(self.output.read_bytes(), b'Existing archive')
