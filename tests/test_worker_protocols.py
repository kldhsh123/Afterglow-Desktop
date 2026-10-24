import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('httpx') and importlib.util.find_spec('websockets'),
                     'Install requirements-dev.txt to run channel protocol checks')
class ChannelProtocolTests(unittest.TestCase):
    def test_both_bundled_handlers_keep_unbound_and_revoked_contacts_out_of_core(self):
        root = Path(__file__).resolve().parent.parent
        for channel in ('qq', 'weixin'):
            with self.subTest(channel=channel), tempfile.TemporaryDirectory() as state:
                result = subprocess.run([sys.executable, '-I', str(root/'tests'/'fixtures'/'check_channel.py'), str(root), channel, state],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('protocol forwarding passed', result.stdout)
