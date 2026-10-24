import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_host.protected_state import ProtectedJsonStore


class ProtectedStateTests(unittest.TestCase):
    def test_plaintext_state_is_migrated_and_encrypted_state_roundtrips(self):
        # DPAPI itself is tested on Windows; this test covers envelope/migration behavior.
        def crypt(value, decrypt=False):
            return bytes(b ^ 0xA5 for b in value)
        with tempfile.TemporaryDirectory() as directory, patch('desktop_host.protected_state.SecretStore.crypt', side_effect=crypt):
            path = Path(directory) / 'context.json'
            path.write_text(json.dumps({'owner': 'private-context-token'}))
            store = ProtectedJsonStore(path)
            self.assertEqual(store.load_dict(), {'owner': 'private-context-token'})
            self.assertNotIn('private-context-token', path.read_text())
            self.assertEqual(store.load_dict(), {'owner': 'private-context-token'})
            store.save_dict({'owner': 'replacement'})
            self.assertEqual(store.load_dict(), {'owner': 'replacement'})

    def test_windows_dpapi_roundtrip(self):
        import sys
        if sys.platform != 'win32':
            self.skipTest('Windows DPAPI requires Windows')
        from desktop_host.credentials import SecretStore
        original = b'afterglow-desktop-dpapi-smoke'
        encrypted = SecretStore.crypt(original)
        self.assertNotEqual(encrypted, original)
        self.assertEqual(SecretStore.crypt(encrypted, decrypt=True), original)
