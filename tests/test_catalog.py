import io
import json
import unittest
from unittest.mock import patch
from desktop_host.catalog import fetch_catalog, release_url, validate_catalog

class CatalogTests(unittest.TestCase):
    def test_only_expected_release_origins_are_accepted(self):
        self.assertTrue(release_url('https://github.com/kldhsh123/Afterglow/releases/download/v1/core.zip'))
        self.assertFalse(release_url('https://github.com.evil.test/kldhsh123/Afterglow/releases/download/v1/core.zip'))
        self.assertFalse(release_url('https://github.com/other/Afterglow/releases/download/v1/core.zip'))
        self.assertTrue(release_url('https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json',metadata=True))

    def test_invalid_metadata_never_supplies_a_download(self):
        url='https://github.com/kldhsh123/Afterglow/releases/latest/download/catalog.json'
        for payload in ([],{'format':1,'components':[{'id':'core','version':'1','url':'https://evil.test/core.zip','sha256':'0'*64}]}):
            with self.subTest(payload=payload), patch('desktop_host.catalog.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ValueError): fetch_catalog(url)

    def test_desktop_manifest_accepts_only_official_versioned_installers(self):
        release = {'version': '0.1.0-internal.3', 'sha256': 'a' * 64,
                   'url': 'https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v0.1.0-internal.3/Afterglow-0.1.0-internal.3-windows-x64-setup.exe'}
        self.assertEqual(validate_catalog({'format': 1, 'components': [], 'desktop': release})['desktop'], release)
        for changes in ({'url': release['url'].replace('Afterglow-Desktop', 'Afterglow')}, {'version': '../../bad'},
                        {'sha256': 'x' * 64}, {'url': release['url'] + '?untrusted=true'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_catalog({'format': 1, 'components': [], 'desktop': {**release, **changes}})
