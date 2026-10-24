import tempfile
import unittest
from pathlib import Path

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
            result=host.install({'id':'core'})
            self.assertTrue(result['ok'])
            installed=read_json(host.root/'installed.json')['core']
            self.assertTrue((Path(installed['path'])/'app'/'xuwen'/'__init__.py').is_file())
            entry['sha256']='0'*64
            with self.assertRaises(ValueError): host.install({'id':'core'})
