"""Debug opt-in, core configuration and scoped RPC regression coverage."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from desktop_host.debug import Debug, debug_environment, debug_preferences, sync_debug_environment
from desktop_host.host import Manager, validate_settings


class DebugPreferencesTests(unittest.TestCase):
    def test_existing_settings_default_to_disabled(self):
        self.assertEqual(validate_settings({'version': 1, 'preset': 'quick'})['debug'],
                         {'enabled': False, 'fullPayloads': False})
        self.assertEqual(debug_preferences({'enabled': False, 'fullPayloads': True}),
                         {'enabled': False, 'fullPayloads': False})
        for field in ('enabled', 'fullPayloads'):
            for invalid in (1, 'false', None):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    debug_preferences({field: invalid})

    def test_flags_override_inherited_environment_and_stale_env_values(self):
        self.assertEqual(debug_environment(None), {
            'DEBUG_ENDPOINTS_ENABLED': 'false', 'DEBUG_MODEL_FULL_PAYLOADS_ENABLED': 'false'})
        self.assertEqual(debug_environment({'enabled': True, 'fullPayloads': True}), {
            'DEBUG_ENDPOINTS_ENABLED': 'true', 'DEBUG_MODEL_FULL_PAYLOADS_ENABLED': 'true'})

    def test_env_edit_preserves_other_settings_and_other_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'profiles/default/core/.env'
            path.parent.mkdir(parents=True)
            path.write_text('# existing configuration\nSELF_NAME=我\nOPENAI_API_KEY=keep-this\n'
                            ' export DEBUG_ENDPOINTS_ENABLED = false\n'
                            'DEBUG_ENDPOINTS_ENABLED=false\nDEBUG_MODEL_FULL_PAYLOADS_ENABLED=true\n')
            sibling = root / 'instances/second'
            sync_debug_environment(sibling, {'enabled': False})
            other = (sibling / 'profiles/default/core/.env').read_text()
            sync_debug_environment(root, {'enabled': True, 'fullPayloads': False})
            first = path.read_text()
            self.assertIn('OPENAI_API_KEY=keep-this\n', first)
            self.assertIn('# existing configuration\nSELF_NAME=我\n', first)
            self.assertEqual(first.count('DEBUG_ENDPOINTS_ENABLED='), 1)
            self.assertIn('DEBUG_ENDPOINTS_ENABLED=true\n', first)
            self.assertIn('DEBUG_MODEL_FULL_PAYLOADS_ENABLED=false\n', first)
            sync_debug_environment(root, {'enabled': True, 'fullPayloads': False})
            self.assertEqual(path.read_text(), first)
            self.assertEqual((sibling / 'profiles/default/core/.env').read_text(), other)

    def test_save_settings_synchronizes_config_without_pretending_core_applied_it(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager.__new__(Manager)
            manager.root = Path(directory)
            manager.settings = Mock(return_value={'version': 1, 'preset': 'quick'})
            manager.secrets = Mock()
            manager.pending_settings = {'debug': {'enabled': False, 'fullPayloads': False}}
            Manager.dispatch(manager, 'save_settings', {'settings': {
                'version': 1, 'preset': 'quick', 'debug': {'enabled': True, 'fullPayloads': False}}})
            saved = json.loads((manager.root / 'settings.json').read_text())
            self.assertTrue(saved['debug']['enabled'])
            self.assertIn('DEBUG_ENDPOINTS_ENABLED=true', (manager.root / 'profiles/default/core/.env').read_text())
            self.assertFalse(manager.pending_settings['debug']['enabled'])


class DebugRpcTests(unittest.TestCase):
    def manager(self, enabled=True, applied=True, payloads=False, applied_payloads=False):
        return SimpleNamespace(
            settings=Mock(return_value={'debug': {'enabled': enabled, 'fullPayloads': payloads}}),
            pending_settings={'debug': {'enabled': applied, 'fullPayloads': applied_payloads}},
            core_request=Mock(return_value={}), chat_store=SimpleNamespace(get=Mock()),
            redact=lambda text: text.replace('actual-secret', '[redacted]'), identity_needs_restart=lambda: False)

    def test_disabled_or_unapplied_debug_cannot_access_endpoints(self):
        for enabled, applied in ((False, False), (False, True), (True, False)):
            manager = self.manager(enabled=enabled, applied=applied)
            with self.subTest(enabled=enabled, applied=applied), self.assertRaises(ValueError):
                Debug(manager).dispatch('debug_snapshot', {})
            manager.core_request.assert_not_called()

    def test_snapshot_redacts_credentials_and_requires_both_full_body_opt_ins(self):
        for desired, applied in ((False, False), (False, True), (True, False), (True, True)):
            manager = self.manager(payloads=desired, applied_payloads=applied)
            manager.core_request.side_effect = [
                {'model_chain': [{'request': {'prompt': 'private actual-secret'}, 'response': {'text': 'body'}, 'error': 'actual-secret'}]},
                {'key_configured': True}]
            result = Debug(manager).dispatch('debug_snapshot', {})
            record = result['stats']['model_chain'][0]
            self.assertNotIn('actual-secret', json.dumps(result))
            self.assertEqual(bool(record['request']), desired and applied)
            self.assertEqual(bool(record['response']), desired and applied)
            manager.core_request.assert_any_call('/debug/stats', timeout=20)
            manager.core_request.assert_any_call('/debug/config', timeout=20)

    def test_retrieval_validates_bounds_and_uses_desktop_conversation_scope(self):
        manager = self.manager()
        debug = Debug(manager)
        debug.dispatch('debug_search', {'query': '  memory  ', 'topK': 7, 'conversationId': 'local-id'})
        manager.chat_store.get.assert_called_once_with('local-id')
        manager.core_request.assert_called_once_with('/memory/search', {
            'query': 'memory', 'top_k': 7, 'conversation_id': 'desktop:local-id'})
        manager.core_request.reset_mock()
        for query, top_k in (('', 12), ('x' * 4001, 12), ('x', True), ('x', 0), ('x', 51), ('x', 1.5)):
            with self.subTest(query_length=len(query), top_k=top_k), self.assertRaises(ValueError):
                debug.dispatch('debug_search', {'query': query, 'topK': top_k})
        manager.core_request.assert_not_called()

    def test_unknown_conversation_does_not_reach_core(self):
        manager = self.manager()
        manager.chat_store.get.side_effect = ValueError('not in this instance')
        with self.assertRaises(ValueError):
            Debug(manager).dispatch('debug_search', {'query': 'x', 'conversationId': 'other-instance'})
        manager.core_request.assert_not_called()

    def test_reset_only_calls_metrics_endpoint(self):
        manager = self.manager()
        Debug(manager).dispatch('debug_reset_metrics', {})
        manager.core_request.assert_called_once_with('/debug/metrics/reset', {}, timeout=20)

    def test_proactive_requires_a_conversation_and_uses_original_endpoint(self):
        manager = self.manager()
        debug = Debug(manager)
        with self.assertRaises(ValueError):
            debug.dispatch('debug_proactive', {})
        manager.core_request.assert_not_called()
        debug.dispatch('debug_proactive', {'conversationId': 'local-id', 'topic_hint': 'topic'})
        manager.core_request.assert_called_once_with('/v1/companion/proactive', {
            'conversation_id': 'desktop:local-id', 'reason': 'manual', 'private_context': '', 'topic_hint': 'topic'})


if __name__ == '__main__':
    unittest.main()
