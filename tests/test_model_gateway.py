import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from desktop_host.model_gateway import ModelBudget, ModelGateway


class Upstream(BaseHTTPRequestHandler):
    seen = []
    reply = None

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.seen.append((self.path, json.loads(body), self.headers.get("Authorization")))
        value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}], "status": "completed"} if self.path.endswith('/responses') else {"choices": [{"message": {"content": "ok"}}]}
        if self.reply is not None:
            value = self.reply
        result = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


class ModelGatewayTests(unittest.TestCase):
    def test_analysis_route_has_separate_request_policy_with_shared_main_credentials(self):
        Upstream.seen = []
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        roles = []
        def key(role, endpoint):
            roles.append(role)
            return 'main-key'
        gateway = ModelGateway('local-token', key, ModelBudget(), {
            'deepseek': {'channel': 'deepseek', 'model': 'deepseek-v4-pro',
                         'baseUrl': f'http://127.0.0.1:{upstream.server_port}/v1'},
        })
        try:
            run = gateway.analysis_trace.begin(); gateway.analysis_trace.bind(run, 'analysis1')
            for route in ('analysis', 'custom_deepseek'):
                body = {'model': 'placeholder', 'messages': [{'role': 'user', 'content': 'PRIVATE'}], 'max_tokens': 6000}
                request = Request(gateway.base(route) + '/chat/completions', json.dumps(body).encode(), {'Authorization': 'Bearer local-token'})
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
            self.assertEqual(roles, ['deepseek', 'deepseek'])
            self.assertEqual(Upstream.seen[0][1]['thinking'], {'type': 'disabled'})
            self.assertNotIn('thinking', Upstream.seen[1][1])
            self.assertEqual(Upstream.seen[0][1]['max_tokens'], 20000)
            metadata = gateway.analysis_trace.snapshot('analysis1')
            self.assertEqual(len(metadata), 1)
            self.assertEqual(metadata[0]['reason'], 'ok')
            self.assertNotIn('PRIVATE', str(metadata))
            self.assertNotIn('main-key', str(metadata))
        finally:
            gateway.close(); upstream.shutdown(); upstream.server_close()

    def test_empty_analysis_records_reason_before_core_can_treat_it_as_json(self):
        class EmptyUpstream(Upstream):
            reply = {'choices': [{'message': {'content': '', 'reasoning_content': 'PRIVATE'}, 'finish_reason': 'length'}],
                     'usage': {'completion_tokens': 6000}}
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), EmptyUpstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        gateway = ModelGateway('local-token', lambda *args: 'main-key', ModelBudget(), {
            'deepseek': {'channel': 'custom', 'model': 'custom-reasoner',
                         'baseUrl': f'http://127.0.0.1:{upstream.server_port}/v1'},
        })
        try:
            run = gateway.analysis_trace.begin(); gateway.analysis_trace.bind(run, 'analysis1')
            body = {'model': 'placeholder', 'messages': [], 'max_tokens': 6000}
            request = Request(gateway.base('analysis') + '/chat/completions', json.dumps(body).encode(), {'Authorization': 'Bearer local-token'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=3)
            self.assertEqual(caught.exception.code, 422)
            caught.exception.close()
            metadata = gateway.analysis_trace.snapshot('analysis1')
            self.assertEqual(metadata[0]['reason'], 'output_limit')
            self.assertTrue(metadata[0]['reasoning_present'])
            self.assertNotIn('PRIVATE', str(metadata))
            self.assertNotIn('thinking', EmptyUpstream.seen[-1][1])
        finally:
            gateway.close(); upstream.shutdown(); upstream.server_close()

    def test_image_import_model_keeps_its_own_credentials_and_responses_protocol(self):
        Upstream.seen = []
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        gateway = ModelGateway('local-token', lambda role, endpoint: 'image-key' if role == 'imageImportVision' else 'wrong-key', ModelBudget(), {
            'imageImportVision': {'channel': 'custom', 'model': 'history-image', 'protocol': 'responses',
                                  'baseUrl': f'http://127.0.0.1:{upstream.server_port}/v1'},
        })
        try:
            body = {'model': 'placeholder', 'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,fixture'}}]}]}
            request = Request(gateway.base('custom_imageImportVision') + '/chat/completions', json.dumps(body).encode(), {'Authorization': 'Bearer local-token'})
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
            path, payload, auth = Upstream.seen[0]
            self.assertEqual(path, '/v1/responses')
            self.assertEqual(payload['model'], 'history-image')
            self.assertEqual(payload['input'][0]['content'][0]['type'], 'input_image')
            self.assertEqual(auth, 'Bearer image-key')
        finally:
            gateway.close(); upstream.shutdown(); upstream.server_close()

    def test_responses_protocol_is_used_for_the_original_core_chat_contract(self):
        Upstream.seen = []
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        gateway = ModelGateway('local-token', lambda *args: 'user-key', ModelBudget(), {
            'deepseek': {'channel': 'custom', 'baseUrl': f'http://127.0.0.1:{upstream.server_port}/v1', 'model': 'chosen', 'protocol': 'responses'},
        })
        try:
            body = {'model': 'core-placeholder', 'messages': [{'role': 'user', 'content': 'Hello'}], 'max_tokens': 100}
            with urlopen(Request(gateway.base('custom_deepseek') + '/chat/completions', json.dumps(body).encode(), {'Authorization': 'Bearer local-token'}), timeout=3) as response:
                self.assertEqual(json.loads(response.read())['choices'][0]['message']['content'], 'ok')
            path, payload, auth = Upstream.seen[0]
            self.assertEqual(path, '/v1/responses')
            self.assertEqual(payload['input'], [{'role': 'user', 'content': 'Hello'}])
            self.assertEqual(payload['max_output_tokens'], 100)
            self.assertFalse(payload['store'])
            self.assertEqual(auth, 'Bearer user-key')
        finally:
            gateway.close(); upstream.shutdown(); upstream.server_close()

    def test_image_role_uses_its_own_model_and_preserves_multimodal_content(self):
        Upstream.seen = []
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        gateway = ModelGateway("local-token", lambda role, endpoint=None: "image-key" if role == "vision" else "wrong-key", ModelBudget(20), {
            "vision": {"channel": "custom", "baseUrl": f"http://127.0.0.1:{upstream.server_port}/v1", "model": "chosen-vision"},
        })
        parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}}]
        try:
            request = Request(gateway.base("custom_vision") + "/chat/completions",
                              json.dumps({"model": "placeholder", "messages": [{"role": "user", "content": parts}]}).encode(),
                              {"Authorization": "Bearer local-token", "Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(Upstream.seen[0][1]["model"], "chosen-vision")
            self.assertEqual(Upstream.seen[0][1]["messages"][0]["content"], parts)
            self.assertEqual(Upstream.seen[0][2], "Bearer image-key")
        finally:
            gateway.close()
            upstream.shutdown()
            upstream.server_close()

    def test_custom_models_forward_chat_path_model_and_credentials(self):
        Upstream.seen = []
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        gateway = ModelGateway("local-token", lambda role, endpoint=None: "secret", ModelBudget(20), {
            "deepseek": {"channel": "custom", "baseUrl": f"http://127.0.0.1:{upstream.server_port}/v1", "model": "chosen-chat"},
        })
        try:
            request = Request(gateway.base("custom_deepseek") + "/chat/completions",
                              json.dumps({"model": "core-placeholder", "messages": []}).encode(),
                              {"Authorization": "Bearer local-token", "Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                self.assertEqual(json.loads(response.read())["choices"][0]["message"]["content"], "ok")
            self.assertEqual(Upstream.seen[0][0], "/v1/chat/completions")
            self.assertEqual(Upstream.seen[0][1]["model"], "chosen-chat")
            self.assertEqual(Upstream.seen[0][2], "Bearer secret")
        finally:
            gateway.close()
            upstream.shutdown()
            upstream.server_close()


if __name__ == "__main__":
    unittest.main()
