import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop_host.host import Manager, validate_settings
from desktop_host.credentials import SecretStore, model_scope
from desktop_host.services import optional_environment, image_import_environment, required_roles, search_test


def complete_settings(**services):
    return {"version": 1, "preset": "quick", "services": services, "providers": {
        "deepseek": {"model": "main-model"},
        "vision": {"channel": "custom", "baseUrl": "https://vision.example/v1", "model": "vision-model"},
        "search": {"channel": "searxng", "baseUrl": "https://search.example", "model": ""},
    }}


class OptionalServiceTests(unittest.TestCase):
    def test_old_settings_keep_optional_services_off(self):
        value = validate_settings({"version": 1, "preset": "quick"})
        self.assertEqual(value["services"], {"vision": "off", "webSearch": False, "webFetch": False, "imageImportVision": False})
        self.assertNotIn("vision", required_roles(value))
        self.assertNotIn("imageImportVision", required_roles(value))

    def test_dedicated_image_model_is_optional_and_has_its_own_protocol_and_worker_environment(self):
        value = complete_settings(vision='off', imageImportVision=True)
        value['providers']['imageImportVision'] = {'channel': 'custom', 'baseUrl': 'https://history.example/v1',
                                                 'model': 'history-model', 'protocol': 'responses', 'concurrency': 2}
        settings = validate_settings(value, require_complete=True)
        self.assertIn('imageImportVision', required_roles(settings))
        self.assertNotIn('vision', required_roles(settings))
        gateway = Mock(); gateway.base.side_effect = lambda route: 'http://localhost/' + route + '/v1'
        chat = optional_environment(settings, gateway, 'local-token', lambda *args: '', 'zh-CN')
        worker = image_import_environment(settings, gateway, 'local-token')
        self.assertEqual(chat['VISION_ENABLED'], 'false')
        self.assertEqual(worker['VISION_ENABLED'], 'true')
        self.assertEqual(worker['VISION_MODEL'], 'history-model')
        self.assertEqual(worker['VISION_API_URL'], 'http://localhost/custom_imageImportVision/v1')
        self.assertEqual(worker['VISION_API_KEY'], 'local-token')
        settings['services']['imageImportVision'] = False
        self.assertEqual(image_import_environment(settings, gateway, 'local-token'), {})
        self.assertEqual(settings['providers']['imageImportVision']['protocol'], 'responses')
        self.assertEqual(settings['providers']['imageImportVision']['concurrency'], 2)
        value['providers']['imageImportVision']['model'] = ''
        with self.assertRaises(ValueError):
            validate_settings(value, require_complete=True)

    def test_complete_settings_require_models_even_on_official_channels(self):
        with self.assertRaises(ValueError):
            validate_settings({"version": 1, "preset": "quick"}, require_complete=True)
        value = complete_settings(vision="separate", webSearch=True)
        self.assertIn("vision", required_roles(validate_settings(value, require_complete=True)))
        value["providers"]["vision"]["model"] = ""
        with self.assertRaises(ValueError):
            validate_settings(value, require_complete=True)

    def test_search_url_must_be_https_and_match_supported_protocol(self):
        for channel, url in [("custom", "https://search.example"), ("tavily", "http://search.example"), ("searxng", "https://key@search.example")]:
            value = complete_settings(webSearch=True)
            value["providers"]["search"].update(channel=channel, baseUrl=url)
            with self.assertRaises(ValueError):
                validate_settings(value)

    def test_configured_state_cannot_save_without_required_credentials(self):
        host = Manager.__new__(Manager)
        host.model_key = Mock(return_value="")
        with self.assertRaises(ValueError):
            host.dispatch("save_settings", {"settings": {**complete_settings(), "configured": True}})

    def test_original_core_receives_selected_services_and_link_only_mode(self):
        gateway = Mock(); gateway.base.return_value = "http://localhost/vision/v1"
        settings = validate_settings(complete_settings(vision="separate", webSearch=True, webFetch=True))
        env = optional_environment(settings, gateway, "local-token", lambda *args: "search-secret", "en-US")
        self.assertEqual(env["VISION_API_KEY"], "local-token")
        self.assertEqual(env["VISION_MODEL"], "vision-model")
        self.assertEqual(env["WEB_SEARCH_BASE_URL"], "https://search.example")
        self.assertEqual(env["WEB_SEARCH_API_KEY"], "search-secret")
        self.assertEqual(env["WEB_SEARCH_PROVIDER"], "searxng")
        self.assertEqual(env["WEB_SEARCH_LANGUAGE"], "en-US")
        settings["services"] = {"vision": "main", "webSearch": False, "webFetch": True}
        env = optional_environment(settings, gateway, "local-token", lambda *args: self.fail("Disabled search accessed a key"), "zh-CN")
        self.assertEqual(env["CHAT_MODEL_SUPPORTS_VISION"], "true")
        self.assertEqual(env["WEB_ACCESS_ENABLED"], "true")
        self.assertEqual(env["WEB_SEARCH_MAX_RESULTS"], "0")
        self.assertEqual(env["WEB_FETCH_ENABLED"], "true")

    def test_search_credentials_are_bound_to_server_origin(self):
        a = {"channel": "searxng", "baseUrl": "https://one.example"}
        b = {"channel": "searxng", "baseUrl": "https://two.example"}
        self.assertNotEqual(model_scope(a), model_scope(b))
        with tempfile.TemporaryDirectory() as directory, patch.object(SecretStore, "crypt", side_effect=lambda data, decrypt=False: data):
            store = SecretStore(Path(directory))
            store.set("search", "test-secret", a)
            self.assertEqual(store.get("search", a), "test-secret")
            self.assertEqual(store.get("search", b), "")

    def test_search_connectivity_matches_upstream_protocols(self):
        for channel in ("tavily", "searxng"):
            response = Mock(); response.read.return_value = b'{"results": []}'
            opener = Mock(); opener.open.return_value.__enter__ = Mock(return_value=response)
            opener.open.return_value.__exit__ = Mock(return_value=False)
            with patch("desktop_host.services.urllib.request.build_opener", return_value=opener):
                self.assertTrue(search_test({"channel": channel, "baseUrl": "https://search.example"}, "test-key", "en-US")["ok"])
            request = opener.open.call_args.args[0]
            if channel == "tavily":
                self.assertEqual(json.loads(request.data)["api_key"], "test-key")
                self.assertEqual(request.full_url, "https://search.example/search")
            else:
                self.assertIn("format=json", request.full_url)
                self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
