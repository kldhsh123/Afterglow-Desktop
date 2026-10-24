import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from desktop_host.downloads import github_url, download_verified, fetch_metadata
from desktop_host.catalog import release_url

URL = 'https://github.com/kldhsh123/Afterglow/archive/refs/tags/v0.4.0.zip'


class DownloadTests(unittest.TestCase):
    def test_only_direct_github_urls_are_accepted(self):
        self.assertEqual(github_url(URL), URL)
        self.assertTrue(release_url('https://github.com/kldhsh123/Afterglow-Desktop/releases/download/v1/app.zip'))
        for url in [
            'https://github.com.evil.test/kldhsh123/Afterglow/file',
            'https://third-party.example/' + URL,
            'http://github.com/kldhsh123/Afterglow/file',
            'https://user@github.com/kldhsh123/Afterglow/file',
        ]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError): github_url(url)
                self.assertFalse(release_url(url))

    def test_success_keeps_the_verified_direct_asset(self):
        payload = b'MZverified installer'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset.download'
            with patch('desktop_host.downloads.urllib.request.urlopen', return_value=io.BytesIO(payload)) as upstream:
                used = download_verified(URL, path, hashlib.sha256(payload).hexdigest(), 100, executable=True)
            self.assertEqual(used, URL)
            self.assertEqual(upstream.call_count, 1)
            self.assertEqual(upstream.call_args.args[0], URL)
            self.assertEqual(path.read_bytes(), payload)

    def test_network_failure_stops_after_one_direct_request_and_shows_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset.download'
            with patch('desktop_host.downloads.urllib.request.urlopen', side_effect=URLError('offline')) as upstream:
                with self.assertRaisesRegex(ValueError, 'offline'):
                    download_verified(URL, path, '0' * 64, 100)
            self.assertEqual(upstream.call_count, 1)
            self.assertEqual(upstream.call_args.args[0], URL)
            self.assertFalse(path.exists())

    def test_bad_checksum_leaves_no_installable_file_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset.download'
            with patch('desktop_host.downloads.urllib.request.urlopen', return_value=io.BytesIO(b'wrong')) as upstream:
                with self.assertRaises(ValueError): download_verified(URL, path, '0' * 64, 100)
            self.assertEqual(upstream.call_count, 1)
            self.assertFalse(path.exists())

    def test_interrupted_stream_leaves_no_partial_file(self):
        class BrokenStream(io.BytesIO):
            def read(self, size=-1):
                if self.tell(): raise http.client.IncompleteRead(b'partial')
                return super().read(3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset.download'
            with patch('desktop_host.downloads.urllib.request.urlopen', return_value=BrokenStream(b'partial')) as upstream:
                with self.assertRaises(ValueError): download_verified(URL, path, '0' * 64, 100)
            self.assertEqual(upstream.call_count, 1)
            self.assertFalse(path.exists())

    def test_metadata_uses_one_direct_request(self):
        with patch('desktop_host.downloads.urllib.request.urlopen', return_value=io.BytesIO(b'{"format":1}')) as upstream:
            self.assertEqual(fetch_metadata(URL, json.loads), {'format': 1})
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(upstream.call_args.args[0], URL)

    def test_invalid_metadata_stops_without_another_source(self):
        with patch('desktop_host.downloads.urllib.request.urlopen', return_value=io.BytesIO(b'<html>blocked</html>')) as upstream:
            with self.assertRaises(ValueError): fetch_metadata(URL, json.loads)
        self.assertEqual(upstream.call_count, 1)

    def test_metadata_connection_failure_reports_the_direct_failure(self):
        with patch('desktop_host.downloads.urllib.request.urlopen', side_effect=TimeoutError()) as upstream:
            with self.assertRaises(ValueError): fetch_metadata(URL, json.loads)
        self.assertEqual(upstream.call_count, 1)

    def test_download_limits_and_executable_signature_still_apply(self):
        for payload, limit in [(b'MZtoo large', 2), (b'not a Windows executable', 100)]:
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'asset.download'
                with patch('desktop_host.downloads.urllib.request.urlopen', return_value=io.BytesIO(payload)):
                    with self.assertRaises(ValueError):
                        download_verified(URL, path, hashlib.sha256(payload).hexdigest(), limit, executable=True)
                self.assertFalse(path.exists())
