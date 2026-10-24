"""Loopback transport for upstream models; no Afterglow inference logic lives here."""
from __future__ import annotations

import hmac
import hashlib
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
try:
    from .model_protocol import prepare_request, chat_response, stream_chunks
    from .model_settings import concurrency, model_scope
    from .analysis_transport import AnalysisTrace, analysis_request, analysis_response
except ImportError:
    from model_protocol import prepare_request, chat_response, stream_chunks
    from model_settings import concurrency, model_scope
    from analysis_transport import AnalysisTrace, analysis_request, analysis_response

BASES = {"deepseek": "https://api.deepseek.com/v1", "xunfei": "https://maas-api.cn-huabei-1.xf-yun.com/v2", "zhipu": "https://open.bigmodel.cn/api/paas/v4"}
MODELS = {"xunfei": {"xop3qwen8bembedding", "xop3qwen8breranker"}, "zhipu": {"glm-4-flash"}}


class ModelBudget:
    """One shared budget per API base/model, across core features and tests."""
    def __init__(self, limit=20, timeout=60):
        if type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError("Model concurrency must be between 1 and 64")
        self.limit = limit
        self.timeout = timeout
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._pools = {}
        self._limits = {}

    def configure(self, profiles):
        limits = {}
        for role, profile in profiles.items():
            if role == 'search' or not profile.get('model') or not profile.get('baseUrl'):
                continue
            scope = model_scope(profile)
            limit = concurrency(profile)
            limits[scope] = min(limits.get(scope, limit), limit)
        with self._condition:
            self._limits = limits
            self._condition.notify_all()

    @contextmanager
    def acquire(self, provider, model, limit=None):
        requested = self.limit if limit is None else limit
        if type(requested) is not int or not 1 <= requested <= 64:
            raise ValueError('Model concurrency must be an integer between 1 and 64')
        scope = (provider, model)
        deadline = time.monotonic() + self.timeout
        # One active-request counter per model. Never create a fresh semaphore
        # when settings change: old requests may still be draining.
        with self._condition:
            while True:
                effective = min(requested, self._limits.get(scope, requested))
                active = self._pools.get(scope, 0)
                if active < effective:
                    self._pools[scope] = active + 1
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Model queue timed out')
                self._condition.wait(remaining)
        try:
            if sys.platform == "win32":
                with windows_model_slot(provider, model, effective, max(0, deadline - time.monotonic())):
                    yield
            else:
                yield
        finally:
            with self._condition:
                remaining = self._pools[scope] - 1
                if remaining:
                    self._pools[scope] = remaining
                else:
                    del self._pools[scope]
                self._condition.notify_all()


@contextmanager
def windows_model_slot(provider, model, limit, timeout):
    """Share model slots across installations; abandoned mutexes recover on crash.

    A named semaphore loses permits if its owner is killed. One named Windows
    mutex per slot lets the OS transfer abandoned slots to a waiting request.
    Names contain only a hash of provider/model, never credentials or chat data.
    """
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
    kernel.WaitForMultipleObjects.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    namespace = hashlib.sha256(json.dumps([provider, model], ensure_ascii=False).encode()).hexdigest()
    handles, acquired = [], None
    try:
        for index in range(limit):
            handle = kernel.CreateMutexW(None, False, f"Local\\Afterglow.ModelBudget.v1.{namespace}.{index}")
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
        array = (wintypes.HANDLE * len(handles))(*handles)
        result = kernel.WaitForMultipleObjects(len(handles), array, False, max(0, int(timeout * 1000)))
        if result == 0x102:
            raise TimeoutError("Model queue timed out")
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        index = result - 0x80 if 0x80 <= result < 0x80 + len(handles) else result
        if index >= len(handles):
            raise OSError("Unexpected Windows model-slot result")
        acquired = handles[index]
        yield
    finally:
        if acquired is not None:
            kernel.ReleaseMutex(acquired)
        for handle in handles:
            kernel.CloseHandle(handle)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ModelGateway:
    def __init__(self, token, get_key, budget, profiles=None, active_roles=None):
        self.token, self.get_key, self.budget = token, get_key, budget
        self.profiles = profiles or {}
        self.analysis_trace = AnalysisTrace()
        budget.configure({role: profile for role, profile in self.profiles.items()
                          if active_roles is None or role in active_roles})
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def fail(self, status, message):
                data = json.dumps({"error": {"message": message, "type": "desktop_gateway"}}).encode()
                if getattr(self, '_forward_started', False):
                    self.close_connection = True
                    if getattr(self, '_streaming', False):
                        self.wfile.write(b'data: ' + data + b'\n\n')
                        self.wfile.flush()
                    return
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                self.close_connection = True

            def do_POST(self):
                self.connection.settimeout(180)
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + owner.token):
                    return self.fail(401, "Invalid local model token")
                parts = urlsplit(self.path)
                match = __import__("re").fullmatch(r"/([^/]+)/v1/(chat/completions|embeddings|rerank)", parts.path)
                if parts.query or not match:
                    return self.fail(404, "Unknown model route")
                provider, endpoint = match.groups()
                if provider not in BASES and provider not in {"custom_" + role for role in owner.profiles} and not (provider == 'analysis' and 'deepseek' in owner.profiles):
                    return self.fail(404, "Unknown model route")
                return self.forward(provider, endpoint)

            def forward(self, provider, endpoint):
                self._forward_started = False
                self._analysis_run = owner.analysis_trace.current() if provider == 'analysis' else None
                self._analysis_meta = {}
                def record(diagnostic):
                    owner.analysis_trace.record(self._analysis_run, {**self._analysis_meta, **diagnostic})
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 16 * 1024 * 1024:
                        return self.fail(413, "Invalid model payload size")
                    raw = self.rfile.read(size)
                    payload = json.loads(raw)
                    model = payload.get("model")
                    if not isinstance(model, str) or not model or len(model) > 160:
                        return self.fail(400, "Missing model")
                    role = 'deepseek' if provider == 'analysis' else provider.removeprefix("custom_") if provider.startswith("custom_") else None
                    if role and role not in owner.profiles:
                        return self.fail(404, "Custom model channel is not configured")
                    if role:
                        endpoint_expected = {"deepseek": "chat/completions", "embedding": "embeddings", "rerank": "rerank", "zhipu": "chat/completions", "vision": "chat/completions", "imageImportVision": "chat/completions"}[role]
                        if endpoint != endpoint_expected:
                            return self.fail(400, "Endpoint does not match configured channel")
                        model = owner.profiles[role]["model"]
                        payload["model"] = model
                        raw = json.dumps(payload, ensure_ascii=False).encode()
                    if not role and provider in MODELS and model not in MODELS[provider]:
                        return self.fail(400, "Model is not configured")
                    allowed = {"xunfei": {"embeddings": "xop3qwen8bembedding", "rerank": "xop3qwen8breranker"}, "zhipu": {"chat/completions": "glm-4-flash"}}
                    if not role and provider in allowed and allowed[provider].get(endpoint) != model:
                        return self.fail(400, "Model endpoint mismatch")
                    if not role and provider == "deepseek" and endpoint != "chat/completions":
                        return self.fail(400, "Unsupported main model endpoint")
                    profile = owner.profiles[role] if role else None
                    if provider == 'analysis':
                        if payload.get('stream'):
                            return self.fail(400, 'Offline analysis requires a non-streaming request')
                        payload = analysis_request(profile, payload)
                        raw = json.dumps(payload, ensure_ascii=False).encode()
                        self._analysis_meta = {'protocol': profile.get('protocol', 'chat_completions')}
                        limit = payload.get('max_completion_tokens', payload.get('max_tokens'))
                        if type(limit) is int:
                            self._analysis_meta['requested_tokens'] = limit
                    key_name = role if role else ({"xunfei": {"embeddings": "embedding", "rerank": "rerank"}, "zhipu": {"chat/completions": "zhipu"}}.get(provider, {}).get(endpoint, provider))
                    key = owner.get_key(key_name, endpoint)
                    if not key:
                        return self.fail(503, "Provider credentials are missing")
                    responses = endpoint == 'chat/completions' and profile and profile.get('protocol') == 'responses'
                    if responses:
                        target, payload = prepare_request(profile, payload)
                        raw = json.dumps(payload, ensure_ascii=False).encode()
                    else:
                        target = '/' + endpoint
                    upstream = profile['baseUrl'].rstrip('/') + target if profile else BASES[provider] + target
                    request = urllib.request.Request(upstream, raw, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                    budget_profile = profile or {'baseUrl': BASES[provider], 'model': model, 'channel': provider}
                    budget_provider, budget_model = model_scope(budget_profile)
                    with owner.budget.acquire(budget_provider, budget_model, concurrency(budget_profile)):
                        try:
                            response = urllib.request.build_opener(NoRedirect).open(request, timeout=150)
                        except urllib.error.HTTPError as error:
                            record({'reason': 'http_error', 'http_status': error.code})
                            return self.fail(error.code if error.code in {400, 401, 402, 403, 404, 429} else 502, "Provider request failed")
                        with response:
                            if provider == 'analysis':
                                raw_result = response.read(16 * 1024 * 1024 + 1)
                                try:
                                    if len(raw_result) > 16 * 1024 * 1024:
                                        raise ValueError('Response too large')
                                    result = json.loads(raw_result)
                                except (ValueError, UnicodeDecodeError):
                                    record({'reason': 'invalid_response'})
                                    return self.fail(422, 'Analysis service did not return a valid JSON response')
                                normalized, diagnostic = analysis_response(result, self._analysis_meta['protocol'])
                                record(diagnostic)
                                if normalized is None:
                                    return self.fail(422, 'Analysis model returned no usable final answer: ' + diagnostic['reason'])
                                body = json.dumps(normalized, ensure_ascii=False).encode()
                                self.send_response(200)
                                self.send_header('Content-Type', 'application/json')
                                self.send_header('Content-Length', str(len(body)))
                                self.end_headers()
                                self.wfile.write(body)
                                return
                            if responses and not payload.get('stream'):
                                result = json.loads(response.read(16 * 1024 * 1024 + 1))
                                body = json.dumps(chat_response(result), ensure_ascii=False).encode()
                                self.send_response(200)
                                self.send_header('Content-Type', 'application/json')
                                self.send_header('Content-Length', str(len(body)))
                                self.end_headers()
                                self.wfile.write(body)
                                return
                            self.send_response(response.status)
                            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                            self.send_header("Connection", "close")
                            self.end_headers()
                            self._forward_started = True
                            self._streaming = bool(payload.get('stream'))
                            self.close_connection = True
                            chunks = stream_chunks(response) if responses else iter(lambda: response.read1(65536), b'')
                            for chunk in chunks:
                                self.wfile.write(chunk)
                                self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except (ValueError, TypeError):
                    self.fail(400, "Invalid model request")
                except (OSError, TimeoutError):
                    record({'reason': 'unavailable'})
                    self.fail(502, "Model service is unavailable")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def base(self, provider):
        return f"http://127.0.0.1:{self.server.server_port}/{provider}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
