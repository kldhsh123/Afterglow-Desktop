"""Retention fixtures use temporary directories only; no installed core is run."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desktop_host.core_updates import prune_core_versions
from desktop_host.host import Manager
from desktop_host.storage import atomic_json, read_json


class CoreRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entries = []
        previous = None
        for version in ('0.3.9', '0.4.0', '0.4.1'):
            directory = self.root / 'components' / 'core' / version
            (directory / 'app').mkdir(parents=True)
            (directory / 'deps').mkdir()
            (directory / 'deps' / 'runtime.pyd').write_bytes(b'fixture')
            manifest = {'format': 1, 'id': 'core', 'version': version}
            atomic_json(directory / 'component.json', manifest)
            entry = {'version': version, 'path': str(directory), 'manifest': manifest, 'previous': previous}
            self.entries.append(entry)
            previous = entry
        self.old, self.previous, self.current = self.entries
        self.save()
        self.data = self.root / 'profiles/default/core/data/analysis/report.json'
        atomic_json(self.data, {'summary': 'Retained user data'})

    def save(self):
        atomic_json(self.root / 'installed.json', {'core': self.current})

    def host(self):
        host = Manager.__new__(Manager)
        host.root = self.root
        host.locale = 'zh-CN'
        host.core_directory = Path(self.current['path'])
        process = Mock(); process.poll.return_value = None
        host.children = {'core': process}
        host.core_request = Mock(return_value={'ok': True})
        host.identity_needs_restart = Mock(return_value=False)
        host.pending_settings = {}
        host.extensions = SimpleNamespace(children={}, states={}, start=Mock())
        host.ensure_idle = Mock()
        host.stop = Mock()
        host.start = Mock()
        return host

    def test_ready_core_keeps_current_and_previous_only(self):
        self.assertEqual(prune_core_versions(self.root, Path(self.current['path'])), [self.old['path']])
        self.assertFalse(Path(self.old['path']).exists())
        for entry in (self.current, self.previous):
            self.assertTrue((Path(entry['path']) / 'deps/runtime.pyd').exists())
        self.assertEqual(json.loads(self.data.read_text()), {'summary': 'Retained user data'})
        self.assertEqual(read_json(self.root / 'installed.json')['core'], self.current)
        self.assertEqual(prune_core_versions(self.root, Path(self.current['path'])), [])

    def test_unconfirmed_or_stale_running_version_cannot_clean(self):
        self.assertEqual(prune_core_versions(self.root, Path(self.previous['path'])), [])
        self.assertTrue(Path(self.old['path']).exists())

    def test_untracked_directories_and_other_instances_are_untouched(self):
        unknown = self.root / 'components/core/manual-files'
        unknown.mkdir(); (unknown / 'notes.txt').write_text('Keep')
        another = self.root / 'instances/other/components/core/0.1.0'
        another.mkdir(parents=True); (another / 'data.txt').write_text('Keep')
        self.old['previous'] = {'version': '0.1.0', 'path': str(another)}
        self.save()
        prune_core_versions(self.root, Path(self.current['path']))
        self.assertTrue((unknown / 'notes.txt').exists())
        self.assertTrue((another / 'data.txt').exists())

    def test_symlinked_historical_version_is_not_followed(self):
        outside = self.root / 'outside'
        outside.mkdir(); (outside / 'data.txt').write_text('Keep')
        link = self.root / 'components/core/linked'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Directory symlinks unavailable')
        self.old['previous'] = {'version': '0.1.0', 'path': str(link)}
        self.save()
        prune_core_versions(self.root, Path(self.current['path']))
        self.assertTrue(link.is_symlink())
        self.assertEqual((outside / 'data.txt').read_text(), 'Keep')

    def test_symlinked_component_root_prevents_all_cleanup(self):
        real = self.root / 'components/core'
        relocated = self.root / 'relocated-core'
        real.rename(relocated)
        try:
            real.symlink_to(relocated, target_is_directory=True)
        except (OSError, NotImplementedError):
            relocated.rename(real)
            self.skipTest('Directory symlinks unavailable')
        self.assertEqual(prune_core_versions(self.root, Path(self.current['path'])), [])
        self.assertTrue((relocated / self.old['version']).exists())

    def test_missing_or_mismatched_manifest_prevents_deletion(self):
        manifest = Path(self.old['path']) / 'component.json'
        manifest.unlink()
        prune_core_versions(self.root, Path(self.current['path']))
        self.assertTrue(Path(self.old['path']).exists())
        atomic_json(manifest, {'format': 1, 'id': 'other', 'version': self.old['version']})
        prune_core_versions(self.root, Path(self.current['path']))
        self.assertTrue(Path(self.old['path']).exists())

    def test_locked_directory_does_not_fail_core_health(self):
        host = self.host()
        with patch('desktop_host.core_updates.shutil.rmtree', side_effect=PermissionError('Locked')):
            with self.assertLogs('desktop_host.core_updates', level='WARNING'):
                self.assertTrue(host.dispatch('health', {})['ok'])
        self.assertTrue(Path(self.old['path']).exists())

    def test_health_cleans_once_per_running_process_after_ready(self):
        host = self.host()
        host.core_request.side_effect = ValueError('Not ready')
        with self.assertRaises(ValueError): host.dispatch('health', {})
        self.assertTrue(Path(self.old['path']).exists())
        host.core_request.side_effect = None
        with patch('desktop_host.host.prune_core_versions', wraps=prune_core_versions) as cleanup:
            host.dispatch('health', {})
            host.dispatch('health', {})
            cleanup.assert_called_once()
        self.assertFalse(Path(self.old['path']).exists())

    def test_old_process_health_cannot_clean_after_process_changes(self):
        host = self.host()
        def changed_process(*args, **kwargs):
            process = Mock(); process.poll.return_value = None
            host.children['core'] = process
            return {'ok': True}
        host.core_request.side_effect = changed_process
        host.dispatch('health', {})
        self.assertTrue(Path(self.old['path']).exists())

    def test_stopped_update_defers_cleanup_until_first_ready_health(self):
        host = self.host()
        host.children['core'].poll.return_value = 0
        atomic_json(self.root / 'installed.json', {'core': self.previous})
        with patch('desktop_host.host.prepare_source_update', return_value=self.current):
            host.update_core({})
        self.assertTrue(Path(self.old['path']).exists())
        host.start.assert_not_called()
        host.children['core'].poll.return_value = None
        host.dispatch('health', {})
        self.assertFalse(Path(self.old['path']).exists())

    def test_failed_update_never_cleans_historical_core_versions(self):
        host = self.host()
        atomic_json(self.root / 'installed.json', {'core': self.previous})
        host.core_request.side_effect = ValueError('Startup failed')
        process = host.children['core']
        process.poll.side_effect = [None, 1]
        with patch('desktop_host.host.prepare_source_update', return_value=self.current):
            with self.assertRaises(ValueError): host.update_core({})
        for entry in self.entries:
            self.assertTrue(Path(entry['path']).exists())

    def test_successful_update_cleans_only_after_ready(self):
        host = self.host()
        atomic_json(self.root / 'installed.json', {'core': self.previous})
        def ready(*args, **kwargs):
            self.assertTrue(Path(self.old['path']).exists())
            return {'ok': True}
        host.core_request.side_effect = ready
        with patch('desktop_host.host.prepare_source_update', return_value=self.current):
            self.assertTrue(host.update_core({})['ok'])
        self.assertFalse(Path(self.old['path']).exists())
