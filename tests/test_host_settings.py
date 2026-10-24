import unittest

from desktop_host.host import Manager, validate_settings
from unittest.mock import Mock

QUICK = {"rerank": False, "policy": False, "rewrite": False}

class SettingsValidationTests(unittest.TestCase):
    def test_chat_roles_can_choose_either_official_channel(self):
        value = validate_settings({"version": 1, "preset": "quick", "providers": {
            "deepseek": {"channel": "zhipu", "model": "glm-4-flash"},
            "zhipu": {"channel": "deepseek", "model": "deepseek-chat"},
        }})
        self.assertEqual(value["providers"]["deepseek"]["channel"], "zhipu")
        self.assertEqual(value["providers"]["zhipu"]["channel"], "deepseek")

    def test_separate_xunfei_keys_have_independent_channels_and_models(self):
        result = validate_settings({"version": 1, "preset": "quick", "features": QUICK, "providers": {
            "embedding": {"channel": "xunfei", "model": "xop3qwen8bembedding"},
            "rerank": {"channel": "xunfei", "model": "xop3qwen8breranker"},
        }})
        self.assertEqual(result["providers"]["embedding"]["model"], "xop3qwen8bembedding")
        self.assertEqual(result["providers"]["rerank"]["model"], "xop3qwen8breranker")

    def test_custom_openai_channel_requires_https_and_model(self):
        base = {"version": 1, "preset": "quick", "features": QUICK, "providers": {"deepseek": {"channel": "custom", "baseUrl": "https://api.example.test/v1", "model": "chat-model"}}}
        self.assertEqual(validate_settings(base)["providers"]["deepseek"]["channel"], "custom")
        base["providers"]["deepseek"]["baseUrl"] = "http://api.example.test/v1"
        with self.assertRaises(ValueError):
            validate_settings(base)

    def test_legacy_xunfei_key_maps_to_embedding_only(self):
        result = validate_settings({"version": 1, "preset": "quick", "features": QUICK, "providers": {"xunfei": {"model": "legacy-model"}}})
        self.assertEqual(result["providers"]["embedding"]["model"], "legacy-model")
        self.assertEqual(result["providers"]["rerank"]["model"], "xop3qwen8breranker")

    def test_model_limits_migrate_and_persist_independently(self):
        result = validate_settings({'version': 1, 'preset': 'quick', 'providers': {
            'embedding': {'concurrency': 7}, 'rerank': {'concurrency': 2},
            'deepseek': {'channel': 'custom', 'concurrency': 64},
        }})
        self.assertEqual(result['providers']['embedding']['concurrency'], 7)
        self.assertEqual(result['providers']['rerank']['concurrency'], 2)
        self.assertEqual(result['providers']['deepseek']['concurrency'], 64)
        self.assertEqual(result['providers']['zhipu']['concurrency'], 20)
        self.assertNotIn('concurrency', result['providers']['search'])

    def test_invalid_model_limits_are_rejected_instead_of_silently_clamped(self):
        for value in (0, 65, -1, True, 2.5, '20', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings({'version': 1, 'preset': 'quick', 'providers': {'embedding': {'concurrency': value}}})


if __name__ == "__main__":
    unittest.main()


class ProviderFirstRunTests(unittest.TestCase):
    def test_swapped_chat_channels_use_the_role_key_and_chosen_model(self):
        host = Manager.__new__(Manager)
        host.settings = Mock(return_value=None)
        host.http = Mock(return_value={"choices": [{"message": {"content": "ok"}}]})
        for role, channel, model in [("deepseek", "zhipu", "glm-4-flash"), ("zhipu", "deepseek", "deepseek-chat")]:
            self.assertTrue(host.test_provider({"provider": role, "channel": channel, "model": model})["ok"])
            args = host.http.call_args.args
            self.assertEqual(args[0], channel)
            self.assertEqual(args[1], "/chat/completions")
            self.assertEqual(args[2]["model"], model)
            self.assertEqual(args[3], role)

    def test_official_main_model_discovery_does_not_require_a_model_to_be_chosen_first(self):
        host=Manager.__new__(Manager); host.settings=Mock(return_value=None)
        host.http=Mock(return_value={'data':[{'id':'available-model'}]})
        result=host.test_provider({'provider':'deepseek','channel':'deepseek','model':''})
        self.assertEqual(result['models'],['available-model'])
        host.http.assert_called_once_with('deepseek','/models')

    def test_skip_test_state_survives_backend_validation(self):
        value=validate_settings({'version':1,'preset':'quick','providers':{'deepseek':{'verification':'skipped'}}})
        self.assertEqual(value['providers']['deepseek']['verification'],'skipped')
