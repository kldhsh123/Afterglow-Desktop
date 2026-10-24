import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_windows import package_core
from desktop_host.host import Manager
from desktop_host.storage import read_json

class ComponentPackageTests(unittest.TestCase):
    def test_prepared_core_installs_in_place_and_a_bad_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'source'; (source/'app'/'xuwen').mkdir(parents=True)
            (source/'app'/'xuwen'/'__init__.py').write_text('# Test fixture\n')
            # A real native dependency tree needs a manifest larger than 64 KB.
            dependency = source/'deps'/'native_dependency'
            dependency.mkdir(parents=True)
            for i in range(800):
                (dependency/f'module_{i:04d}.py').write_text('# Bundled dependency fixture\n')
            resources=root/'resources'; resources.mkdir()
            archive=resources/'packages'/'core.zip'
            entry=package_core(source, archive, '0.4.0')
            host=Manager.__new__(Manager); host.root=root/'data'; host.root.mkdir()
            host.children={}; host.catalog={'components':[entry]}; host.catalog_path=resources/'catalog.json'
            host.bundled_catalog = host.catalog
            result=host.install({'id':'core'})
            self.assertTrue(result['ok'])
            installed=read_json(host.root/'installed.json')['core']
            self.assertTrue((Path(installed['path'])/'app'/'xuwen'/'__init__.py').is_file())
            entry['sha256']='0'*64
            with self.assertRaises(ValueError): host.install({'id':'core'})

    def prepared_host(self, root):
        source = root / 'source'
        (source / 'app/xuwen').mkdir(parents=True)
        (source / 'app/xuwen/__init__.py').write_text('# Core fixture\n')
        resources = root / 'resources'
        archive = resources / 'packages/core.zip'
        entry = package_core(source, archive, '0.4.1')
        host = Manager.__new__(Manager)
        host.root = root / 'data'
        host.root.mkdir()
        host.children = {}
        host.bundled_catalog = {'format': 1, 'components': [entry]}
        host.catalog = host.bundled_catalog
        host.catalog_path = resources / 'catalog.json'
        return host, archive

    def test_old_online_catalog_cannot_override_the_bundled_install_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            host, archive = self.prepared_host(Path(temporary))
            host.catalog = {'format': 1, 'components': [{'id': 'core', 'version': '9.0.0', 'sha256': 'a' * 64,
                            'url': 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v1/missing.zip'}]}
            with patch('desktop_host.host.fetch_catalog') as fetch, patch('urllib.request.urlopen') as network:
                self.assertTrue(host.install({'id': 'core'})['ok'])
                fetch.assert_not_called()
                network.assert_not_called()
            self.assertTrue(archive.is_file())
            self.assertEqual(read_json(host.root / 'installed.json')['core']['version'], '0.4.1')

    def test_desktop_only_catalog_refresh_still_allows_offline_core_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            host, _ = self.prepared_host(Path(temporary))
            url = 'https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json'
            fresh = {'format': 1, 'updateUrl': url, 'components': [],
                     'desktop': {'version': '0.1.1', 'sha256': 'a' * 64,
                                 'url': 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v0.1.1/Afterglow-0.1.1-windows-x64-setup.exe'}}
            with patch('desktop_host.host.fetch_catalog', return_value=fresh) as fetch:
                self.assertTrue(host.dispatch('refresh_catalog', {'url': url})['ok'])
                fetch.assert_called_once_with(url, root=host.root)
            self.assertEqual(read_json(host.root / 'catalog.json')['components'], [])
            self.assertEqual(host.catalog['desktop']['version'], '0.1.1')
            with patch('urllib.request.urlopen') as network:
                self.assertTrue(host.install({'id': 'core'})['ok'])
                network.assert_not_called()

    def test_missing_local_resources_never_fall_back_to_a_remote_zip(self):
        for state in ('no_entry', 'missing_archive'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                host, archive = self.prepared_host(Path(temporary))
                if state == 'no_entry':
                    host.bundled_catalog = {'components': []}
                else:
                    archive.unlink()
                with patch('desktop_host.host.fetch_catalog') as fetch, patch('urllib.request.urlopen') as network:
                    with self.assertRaises(ValueError):
                        host.install({'id': 'core'})
                    fetch.assert_not_called()
                    network.assert_not_called()
                self.assertFalse((host.root / 'installed.json').exists())

    def test_manual_offline_package_import_is_still_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            host, archive = self.prepared_host(Path(temporary))
            host.bundled_catalog = {'components': []}
            with patch('urllib.request.urlopen') as network:
                self.assertTrue(host.install({'id': 'core', 'path': str(archive)})['ok'])
                network.assert_not_called()
