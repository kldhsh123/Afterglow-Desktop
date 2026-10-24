import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_host.bindings import BindingStore
from desktop_host.extensions import Extensions, weixin_base_url
from desktop_host.storage import atomic_json


class MemorySecrets:
    def __init__(self):
        self.values = {'qq_app_id': '1234', 'qq_secret': 'qq-secret', 'local_api': 'local-secret'}

    def get(self, key):
        return self.values.get(key, '')

    def set(self, key, value):
        self.values[key] = value

    def available(self):
        return list(self.values)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = BindingStore(Path(self.temp.name) / 'bindings.sqlite3')

    def test_only_matching_current_code_grants_access_and_revoke_removes_it(self):
        code = self.store.request('person-a')
        self.assertFalse(self.store.authorized('person-a'))
        self.assertEqual(code, self.store.request('person-a'))
        with self.assertRaises(ValueError):
            self.store.approve('person-a', 'x' * 6)
        with self.assertRaises(ValueError):
            self.store.approve('person-b', code)
        self.store.approve('person-a', code)
        self.assertTrue(self.store.authorized('person-a'))
        self.store.revoke('person-a')
        self.assertFalse(self.store.authorized('person-a'))

    def test_expired_codes_and_other_instances_never_authorize_contacts(self):
        with patch('desktop_host.bindings.time.time', return_value=1000):
            code = self.store.request('person-a')
        with patch('desktop_host.bindings.time.time', return_value=1601):
            with self.assertRaises(ValueError):
                self.store.approve('person-a', code)
            self.assertEqual(self.store.list(), [])
        other = BindingStore(Path(self.temp.name) / 'second' / 'bindings.sqlite3')
        other.trust_owner('person-a')
        self.assertFalse(self.store.authorized('person-a'))

    def test_two_process_views_share_binding_state_without_lost_updates(self):
        second = BindingStore(self.store.path)
        code = self.store.request('person-a')
        second.request('person-b')
        second.approve('person-a', code)
        self.assertTrue(self.store.authorized('person-a'))
        self.assertEqual(len(self.store.list()), 2)


class ExtensionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        core = Mock()
        core.poll.return_value = None
        self.manager = SimpleNamespace(root=root, secrets=MemorySecrets(), children={'core': core}, port=12345,
                                       locale='en-US', settings=lambda: {'humanDelay': False},
                                       core_request=Mock(return_value={'ok': True}), redact=lambda value: value)
        atomic_json(root / 'installed.json', {'core': {'path': str(root / 'core')}})
        self.child = Mock()
        self.child.poll.return_value = None
        self.child.stdin = io.BytesIO()
        self.child.stdout = io.BytesIO()
        self.child.stderr = io.BytesIO()
        self.spawn = Mock(return_value=self.child)
        self.extensions = Extensions(self.manager, popen=self.spawn)

    def start(self, extension='qq', login=False):
        with patch('desktop_host.extensions.threading.Thread'):
            self.extensions.start(extension, login=login)

    def test_start_uses_pipe_credentials_and_real_ready_events(self):
        self.start()
        args, kwargs = self.spawn.call_args
        self.assertNotIn('qq-secret', str(args))
        self.assertNotIn('qq-secret', str(kwargs.get('env')))
        config = json.loads(self.child.stdin.getvalue())
        self.assertEqual(config['environment']['QQ_BOT_CLIENT_SECRET'], 'qq-secret')
        self.assertEqual(config['environment']['AFTERGLOW_MESSAGE_SEGMENT_MAX_DELAY'], '0')
        self.assertEqual(self.extensions.status()[0]['state'], 'connecting')
        self.extensions._event('qq', self.child, {'event': 'state', 'state': 'connected'})
        self.assertEqual(self.extensions.status()[0]['state'], 'connected')
        self.extensions._event('qq', self.child, {'event': 'state', 'state': 'reconnecting'})
        self.assertEqual(self.extensions.status()[0]['state'], 'reconnecting')

    def test_qr_content_is_not_downloaded_and_tokens_are_not_in_status(self):
        self.start('weixin', login=True)
        self.extensions._event('weixin', self.child, {'event': 'qr', 'content': 'https://weixin.qq.com/qr/test'})
        self.assertEqual(self.extensions.status()[1]['qrContent'], 'https://weixin.qq.com/qr/test')
        self.extensions._event('weixin', self.child, {'event': 'state', 'state': 'verify'})
        self.extensions.verify('123456')
        self.extensions._event('weixin', self.child, {'event': 'credentials', 'token': 'wx-secret',
                               'accountId': 'bot-a', 'ownerUid': 'owner-a', 'baseUrl': 'https://ilinkai.weixin.qq.com'})
        self.assertNotIn('wx-secret', json.dumps(self.extensions.status()))
        self.assertEqual(self.manager.secrets.get('weixin_token'), 'wx-secret')
        self.assertTrue(self.extensions.bindings('weixin').authorized('owner-a'))
        self.assertEqual(self.extensions.status()[1]['state'], 'authenticated')

    def test_cancel_ignores_late_credentials_and_closes_running_worker(self):
        self.start('weixin', login=True)
        self.extensions.stop('weixin')
        self.child.terminate.assert_called_once()
        self.extensions._event('weixin', self.child, {'event': 'credentials', 'token': 'late-secret',
                               'accountId': 'bot', 'baseUrl': 'https://ilinkai.weixin.qq.com'})
        self.assertEqual(self.manager.secrets.get('weixin_token'), '')
        self.assertEqual(self.extensions.status()[1]['state'], 'stopped')

    def test_untrusted_login_host_does_not_store_token(self):
        self.start('weixin', login=True)
        with self.assertRaises(ValueError):
            self.extensions._event('weixin', self.child, {'event': 'credentials', 'token': 'secret',
                                   'accountId': 'bot', 'baseUrl': 'https://attacker.example'})
        self.assertEqual(self.manager.secrets.get('weixin_token'), '')
        for value in ('https://', 'http://ilinkai.weixin.qq.com', 'https://ilinkai.weixin.qq.com.attacker.example',
                      'https://user:pass@ilinkai.weixin.qq.com', 'https://ilinkai.weixin.qq.com:8443'):
            with self.assertRaises(ValueError):
                weixin_base_url(value)

    def test_connection_requires_ready_core_but_login_can_be_configured_first(self):
        self.manager.children = {}
        with self.assertRaises(ValueError):
            self.start()
        self.start('weixin', login=True)
        self.manager.core_request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
