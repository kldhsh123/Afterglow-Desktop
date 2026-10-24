import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

from desktop_host.updates import stage_installer, version_key
from desktop_host.host import Manager


class DesktopUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = b'MZtest-installer'
        self.release = {'version': '0.1.0-internal.3', 'sha256': hashlib.sha256(self.payload).hexdigest(),
                        'url': 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v0.1.0-internal.3/Afterglow-0.1.0-internal.3-windows-x64-setup.exe'}
        self.catalog = {'format': 1, 'desktop': self.release, 'components': []}

    def test_verified_installer_is_staged_without_running_it(self):
        self.catalog['components'] = [{'id': 'core', 'bundled': 'packages/core.zip'}]
        with patch('desktop_host.updates.urllib.request.urlopen', return_value=io.BytesIO(self.payload)):
            staged = stage_installer(self.root, self.catalog, '0.1.0-internal.2')
        self.assertEqual(Path(staged['path']).read_bytes(), self.payload)
        self.assertEqual(staged['sha256'], self.release['sha256'])
        self.assertFalse(list(self.root.glob('updates/*.download')))

    def test_corrupt_download_does_not_become_an_executable(self):
        with patch('desktop_host.updates.urllib.request.urlopen', return_value=io.BytesIO(b'MZdamaged')):
            with self.assertRaises(ValueError): stage_installer(self.root, self.catalog, '0.1.0-internal.2')
        self.assertEqual(list((self.root / 'updates').iterdir()), [])

    def test_current_older_and_untrusted_releases_are_not_downloaded(self):
        with patch('desktop_host.updates.urllib.request.urlopen') as download:
            for current in ('0.1.0-internal.3', '0.1.0-internal.12', '0.1.0'):
                with self.subTest(current=current), self.assertRaises(ValueError): stage_installer(self.root, self.catalog, current)
            self.release['url'] = 'https://example.test/Afterglow-windows-x64-setup.exe'
            with self.assertRaises(ValueError): stage_installer(self.root, self.catalog, '0.1.0-internal.2')
            download.assert_not_called()

    def test_internal_versions_sort_numerically(self):
        self.assertGreater(version_key('0.1.0-internal.12'), version_key('0.1.0-internal.3'))
        self.assertGreater(version_key('0.1.0'), version_key('0.1.0-internal.100'))
        self.assertGreater(version_key('0.2.0-internal.1'), version_key('0.1.0'))

    def running_host(self):
        host = Manager.__new__(Manager)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        host.root = Path(temporary.name)
        from desktop_host.storage import atomic_json
        atomic_json(host.root / 'installed.json', {'core': {'version': '0.4.0', 'path': 'old-core'}})
        core = Mock(); core.poll.return_value = None
        channel = Mock(); channel.poll.return_value = None
        host.children = {'core': core}
        host.extensions = SimpleNamespace(children={'qq': channel}, states={'qq': {'state': 'connected'}}, start=Mock())
        host.ensure_idle = Mock(); host.stop = Mock(); host.start = Mock()
        host.core_request = Mock(return_value={'ok': True})
        host.install = Mock(return_value={'ok': True, 'message': 'Installed'})
        return host

    def test_one_click_core_update_checks_tasks_restarts_and_reconnects(self):
        host = self.running_host()
        with patch('desktop_host.host.prepare_source_update', return_value={'version': '0.4.1', 'path': 'new-core'}):
            self.assertTrue(host.update_core({})['ok'])
        host.ensure_idle.assert_called_once()
        host.stop.assert_called_once_with('core')
        host.install.assert_not_called()
        host.start.assert_called_once_with('core')
        host.extensions.start.assert_called_once_with('qq')

    def test_active_import_prevents_core_update_before_any_changes(self):
        host = self.running_host()
        host.ensure_idle.side_effect = ValueError('Import is running')
        with self.assertRaises(ValueError): host.update_core({})
        host.stop.assert_not_called(); host.install.assert_not_called()

    def test_failed_core_download_restarts_previous_core(self):
        host = self.running_host()
        with patch('desktop_host.host.prepare_source_update', side_effect=ValueError('Download interrupted')):
            with self.assertRaisesRegex(ValueError, 'interrupted'): host.update_core({})
        host.stop.assert_not_called()
        host.start.assert_not_called()
