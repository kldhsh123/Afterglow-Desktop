"""Source update fixtures; no application, installer or network is executed."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from desktop_host.core_updates import prepare_source_update


def project(version, dependency='httpx>=0.27,<1'):
    return f'[project]\nname="xuwen"\nversion="{version}"\nrequires-python=">=3.12,<3.13"\ndependencies=["{dependency}"]\n'


class SourceUpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.old = self.root / 'components/core/0.4.0'
        (self.old / 'app').mkdir(parents=True)
        (self.old / 'app/pyproject.toml').write_text(project('0.4.0'))
        (self.old / 'deps').mkdir()
        (self.old / 'deps/native-wheel.pyd').write_bytes(b'existing native dependency')
        self.current = {'version': '0.4.0', 'path': str(self.old)}

    def archive(self, version='0.4.1', dependency='httpx>=0.27,<1', extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as source:
            source.writestr('Afterglow-main/VERSION', version)
            source.writestr('Afterglow-main/backend/pyproject.toml', project(version, dependency))
            source.writestr('Afterglow-main/backend/xuwen/chat_api/app.py', '# original source\n')
            if extra:
                source.writestr(*extra)
        return stream.getvalue()

    def prepare(self, data):
        with patch('desktop_host.core_updates.fetch_metadata', return_value='0.4.1'), patch(
                'desktop_host.core_updates.urllib.request.urlopen', return_value=io.BytesIO(data)):
            return prepare_source_update(self.root, self.current)

    def test_source_update_keeps_original_app_and_reuses_dependencies(self):
        result = self.prepare(self.archive())
        installed = Path(result['path'])
        self.assertEqual((installed / 'app/xuwen/chat_api/app.py').read_text(), '# original source\n')
        self.assertEqual((installed / 'deps/native-wheel.pyd').read_bytes(), b'existing native dependency')
        self.assertEqual(result['previous'], self.current)
        self.assertEqual(len(result['manifest']['sourceSha256']), 64)
        self.assertFalse((self.root / 'installed.json').exists())
        self.assertTrue((self.old / 'app/pyproject.toml').exists())

    def test_changed_dependencies_leave_installed_core_untouched(self):
        with self.assertRaises(ValueError):
            self.prepare(self.archive(dependency='httpx>=0.29,<1'))
        self.assertEqual(len(list((self.root / 'components/core').iterdir())), 1)
        self.assertFalse(list((self.root / 'staging').iterdir()))

    def test_version_race_and_path_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare(self.archive(version='0.4.2'))
        with self.assertRaises(ValueError):
            self.prepare(self.archive(extra=('Afterglow-main/backend/xuwen/../../escape.py', 'bad')))
        self.assertFalse((self.root / 'escape.py').exists())

    def test_current_version_never_downloads_source(self):
        with patch('desktop_host.core_updates.fetch_metadata', return_value='0.4.0'), patch(
                'desktop_host.core_updates.urllib.request.urlopen') as download:
            self.assertIsNone(prepare_source_update(self.root, self.current))
            download.assert_not_called()
