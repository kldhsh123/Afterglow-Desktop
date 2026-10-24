import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
import sys
from unittest.mock import patch

from desktop_host.repository_updates import RepositoryChecks, VERSION_FILES, parse_version
from desktop_host.post_install_check import check_after_install


class RepositoryUpdateTests(unittest.TestCase):
    def test_both_repository_version_formats(self):
        self.assertEqual(parse_version(b"v0.4.0\n", "core"), "0.4.0")
        self.assertEqual(parse_version(b'{"baseVersion":"0.1.0","internalBuild":12}', "desktop"),
                         "0.1.0-internal.12")
        self.assertEqual(parse_version(b'{"baseVersion":"0.1.0","internalBuild":16,"channel":"stable"}', "desktop"),
                         "0.1.0")
        for channel in (None, True, 'release', ''):
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                parse_version(json.dumps({'baseVersion': '0.1.0', 'internalBuild': 16, 'channel': channel}).encode(), 'desktop')
        for payload in (b"<html>error</html>", b"0.4.0;command", b"../../0.4.0"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_version(payload, "core")
        for build in (True, -1, "12", 0):
            with self.subTest(build=build), self.assertRaises(ValueError):
                parse_version(json.dumps({"baseVersion": "0.1.0", "internalBuild": build}).encode(), "desktop")

    def test_both_version_files_use_verified_download_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = RepositoryChecks(Path(directory))
            payloads = [io.BytesIO(b"0.4.0\n"), io.BytesIO(b'{"baseVersion":"0.1.0","internalBuild":12}')]
            with patch("desktop_host.downloads.urllib.request.urlopen", side_effect=payloads) as fetch:
                checks._check()
            self.assertEqual([call.args[0] for call in fetch.call_args_list], list(VERSION_FILES.values()))
            self.assertEqual(checks.snapshot()["core"]["version"], "0.4.0")
            self.assertEqual(checks.snapshot()["desktop"]["version"], "0.1.0-internal.12")
            self.assertFalse(json.loads(checks.path.read_text())["checking"])

    def test_post_install_check_checks_both_sources_in_the_selected_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('desktop_host.repository_updates.fetch_metadata', side_effect=['0.4.1', '0.1.0-internal.6']) as fetch:
                check_after_install(directory)
            self.assertEqual([call.args[0] for call in fetch.call_args_list], list(VERSION_FILES.values()))
            root = Path(directory) / 'AfterglowData'
            self.assertTrue(all(call.kwargs['max_bytes'] == 16384 for call in fetch.call_args_list))
            cached = json.loads((root / 'repository-versions.json').read_text())
            self.assertEqual(cached['core']['version'], '0.4.1')
            self.assertEqual(cached['desktop']['version'], '0.1.0-internal.6')

    def test_post_install_entry_point_imports_with_isolated_python(self):
        entry = Path(__file__).resolve().parents[1] / 'desktop_host/post_install_check.py'
        result = subprocess.run([sys.executable, '-I', str(entry), '--help'],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--install-dir', result.stdout)

    def test_offline_check_preserves_cached_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "repository-versions.json").write_text(json.dumps({"core": {"version": "0.4.0"}}))
            checks = RepositoryChecks(root)
            with patch("desktop_host.repository_updates.fetch_metadata", side_effect=OSError("offline")):
                checks._check()
            self.assertEqual(checks.snapshot()["core"]["version"], "0.4.0")
            self.assertTrue(checks.snapshot()["core"]["failed"])
            self.assertFalse(checks.snapshot()["checking"])

    def test_start_returns_while_network_is_waiting_and_runs_once(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def blocked(url, validate, **kwargs):
            entered.set()
            release.wait(3)
            if url == VERSION_FILES["desktop"]:
                finished.set()
                return "0.1.0-internal.12"
            return "0.4.0"
        with tempfile.TemporaryDirectory() as directory:
            checks = RepositoryChecks(Path(directory))
            with patch("desktop_host.repository_updates.fetch_metadata", side_effect=blocked) as fetch:
                try:
                    self.assertTrue(checks.start()["checking"])
                    self.assertTrue(entered.wait(1))
                    self.assertTrue(checks.start()["checking"])
                    self.assertEqual(fetch.call_count, 1)
                finally:
                    release.set()
                    self.assertTrue(finished.wait(2))
                    # Join the background writer before its temporary root is removed.
                    for thread in threading.enumerate():
                        if thread.name == "repository-versions": thread.join(2)


if __name__ == "__main__":
    unittest.main()
