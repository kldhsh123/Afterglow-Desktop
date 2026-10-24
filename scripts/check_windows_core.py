"""Exercise the bundled, unmodified core on Windows with local fixture models.

No real model credentials or QQ/WeChat accounts are used. All data lives in a
temporary directory, and model requests terminate at a loopback HTTP server.
Run with src-tauri/resources/python/python.exe -I scripts/check_windows_core.py.
"""
from __future__ import annotations

import hashlib
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import threading
import time
from unittest.mock import patch
import urllib.request
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from desktop_host.host import Manager
from desktop_host.import_conversion import convert, validate_spec
from desktop_host.model_gateway import ModelGateway


MAPPING = {"messages_path": "messages", "sender_id": "who", "sender_name": "name",
           "text": "body", "timestamp": "when", "kind": ""}
REPLY = "Offline desktop verification reply."


class FixtureModels(BaseHTTPRequestHandler):
    calls = []
    image_calls = 0

    def log_message(self, *_):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        responses = self.path.endswith('/responses')
        if responses:
            data['messages'] = data.get('input', [])
        self.calls.append((self.path, data.get("model")))
        if any(isinstance(message.get('content'), list) and any(part.get('type') in {'image_url', 'input_image'} for part in message['content'])
               for message in data.get('messages', [])):
            FixtureModels.image_calls += 1
        if self.path.endswith("/embeddings"):
            inputs = data["input"]
            inputs = inputs if isinstance(inputs, list) else [inputs]
            vectors = []
            for index, value in enumerate(inputs):
                digest = hashlib.sha256(str(value).encode()).digest()
                vector = [0.0] * 4096
                for offset, byte in enumerate(digest):
                    vector[offset] = (byte + 1) / 256
                vectors.append({"object": "embedding", "index": index, "embedding": vector})
            response = {"object": "list", "data": vectors, "model": data["model"],
                        "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)}}
        elif self.path.endswith("/rerank"):
            response = {"results": [{"index": i, "relevance_score": .9 - i * .01}
                                     for i in range(len(data["documents"]))]}
        else:
            # Unknown-format detection must exercise the user's configured main
            # model through the same gateway as ordinary chat.
            messages = json.dumps(data.get("messages", []), ensure_ascii=False)
            mapping = MAPPING
            if 'messages_path' in messages and '/chat_records' in messages:
                mapping = {'messages_path': '/chat_records' if 'Local validation failed:' in messages else '/messages',
                           'sender_id': '/sender/user_id', 'sender_name': '/sender/name', 'text': '/body', 'timestamp': '/timestamp_ms', 'kind': '/category'}
            content = json.dumps(mapping) if "messages_path" in messages else REPLY
            response = {"id": "offline-fixture", "object": "chat.completion", "created": 1,
                        "model": data["model"], "choices": [{"index": 0,
                        "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            if responses:
                response = {'id': 'offline-response', 'status': 'completed', 'model': data['model'],
                            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': content}]}]}
        raw = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def until(operation, predicate, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = operation()
            if predicate(last):
                return last
        except (ValueError, OSError) as exc:
            last = str(exc)
        time.sleep(.25)
    raise AssertionError(f"Timed out waiting for core: {last}")


def run(root, origin, protocol='chat_completions', sample_export=None):
    catalog = ROOT / "src-tauri/resources/catalog.json"
    manager = Manager(root, catalog)
    real_gateway = ModelGateway

    def local_gateway(token, get_key, budget, profiles):
        profiles = {role: {**profile, "baseUrl": origin} for role, profile in profiles.items()}
        return real_gateway(token, get_key, budget, profiles)

    real_open = urllib.request.urlopen

    def offline_open(request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        target = urlsplit(url)
        if target.hostname == "offline.invalid":
            request = urllib.request.Request(origin + target.path.removeprefix("/v1"),
                                             request.data, dict(request.header_items()), method=request.get_method())
        elif target.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"Offline check attempted an external request: {target.hostname}")
        return real_open(request, *args, **kwargs)

    settings = {"version": 1, "preset": "balanced", "features": {"rerank": True, "policy": False, "rewrite": False},
                "services": {"vision": "main", "webSearch": False, "webFetch": False},
                "configured": True, "selfName": "Alice", "friendName": "Bob", "relationship": "friend",
                "providers": {role: {"channel": "custom", "baseUrl": "https://offline.invalid/v1", "model": model}
                              for role, model in {"deepseek": "fixture-main", "embedding": "fixture-embedding",
                                                  "rerank": "fixture-rerank", "zhipu": "fixture-small"}.items()}}
    for role in ('deepseek', 'zhipu'):
        settings['providers'][role]['protocol'] = protocol
    try:
        manager.dispatch("save_settings", {"settings": {**settings, "configured": False}})
        for role in settings["providers"]:
            manager.secrets.set(role, "offline-fixture-key", settings["providers"][role])
        manager.dispatch("save_settings", {"settings": settings})
        print("Installing original bundled core…", flush=True)
        manager.install({"id": "core"})
        with patch("desktop_host.host.ModelGateway", local_gateway), patch("urllib.request.urlopen", offline_open):
            print("Starting original core…", flush=True)
            manager.start("core")
            until(lambda: manager.core_request("/readyz", timeout=2), lambda result: bool(result))
            records = [{"who": "alice" if i % 2 == 0 else "bob", "name": "Alice" if i % 2 == 0 else "Bob",
                        "when": 1_761_000_000_000 + i * 60_000,
                        "body": text} for i, text in enumerate([
                            "Are we still walking by the river this weekend?", "Yes, let us meet at the old bridge.",
                            "I will bring coffee and our blue blanket.", "Great, I will bring the sandwiches.",
                            "Which time works best for you?", "Ten in the morning, before it gets crowded."])]
            payload = {"messages": records}
            source = root / "known.json"
            source.write_text(json.dumps(convert(payload, records, validate_spec(MAPPING), "fixture")), encoding="utf-8")
            print("Inspecting known format with original import extension…", flush=True)
            known = manager.inspect_files({"paths": [str(source)]})["uploaded"][0]
            assert not known.get("ai_converted"), known
            assert known["format"] == "afterglow_v1", known
            unknown = root / "unknown.json"
            unknown.write_text(json.dumps(payload), encoding="utf-8")
            print("Analyzing unknown format with configured main model…", flush=True)
            converted = manager.inspect_files({"paths": [str(unknown)]})["uploaded"][0]
            assert converted.get("ai_converted"), converted
            assert {c["uid"] for c in converted["candidates"]} == {"alice", "bob"}, converted
            same_format = root / 'another-export.json'
            same_format.write_text(json.dumps({'messages': [{**record, 'body': record['body'] + ' Again.'} for record in records]}), encoding='utf-8')
            reused = manager.inspect_files({'paths': [str(same_format)]})['uploaded'][0]
            assert reused.get('rule_reused') and not reused.get('error'), reused
            try:
                manager.start_import({"files": [converted["saved_as"]]})
            except ValueError:
                pass
            else:
                raise AssertionError("Import accepted missing self/other identities")
            print("Importing after explicit self/other confirmation…", flush=True)
            task = manager.start_import({"files": [converted["saved_as"]], "selfUid": "alice", "friendUid": "bob"})
            completed = until(lambda: manager.dispatch("import_status", {"id": task["task_id"]}),
                              lambda result: result.get("status") in {"done", "failed", "cancelled"}, 120)
            assert completed["status"] == "done", completed
            assert completed.get("report", {}).get("failed_chunks") == 0, completed
            print("Applying identity and restarting original core…", flush=True)
            manager.dispatch("restart", {})
            until(lambda: manager.core_request("/readyz", timeout=2), lambda result: bool(result))
            conversation = manager.chat_store.create()
            print("Sending through real core and desktop conversation storage…", flush=True)
            response = manager.send_chat({"conversationId": conversation["id"], "requestId": str(uuid.uuid4()),
                                          "content": "Where should we meet on our walk?"})
            assert REPLY in response["choices"][0]["message"]["content"], response
            stored = manager.chat_store.get(conversation["id"])
            assert stored["turns"][0]["state"] == "completed", stored
            print('Sending a persisted image through the original core and configured main model…', flush=True)
            data_url = 'data:image/jpeg;base64,' + base64.b64encode((ROOT / 'tests/fixtures/chat-image.jpg').read_bytes()).decode('ascii')
            image_reply = manager.send_chat({'conversationId': conversation['id'], 'requestId': str(uuid.uuid4()),
                                            'content': 'What can you see?', 'attachments': [{'name': 'chat-image.jpg', 'dataUrl': data_url, 'preview': data_url}]})
            assert REPLY in image_reply['choices'][0]['message']['content'], image_reply
            stored = manager.chat_store.get(conversation['id'])
            assert stored['turns'][-1]['attachments'][0]['preview'] == data_url
            assert FixtureModels.image_calls > 0
            assert any(path.endswith("/embeddings") for path, _ in FixtureModels.calls), FixtureModels.calls
            assert any(model == "fixture-main" for _, model in FixtureModels.calls), FixtureModels.calls
            print("Checking bundled QQ and WeChat transports against local platform peers…", flush=True)
            component = json.loads((root / "installed.json").read_text(encoding="utf-8"))["core"]["path"]
            for channel in ("qq", "weixin"):
                result = subprocess.run([sys.executable, "-I", str(ROOT / "tests/fixtures/check_channel_transport.py")],
                                        input=json.dumps({"root": str(ROOT), "state": str(root / (channel + "-transport")),
                                                          "channel": channel, "component": component,
                                                          "coreUrl": f"http://127.0.0.1:{manager.port}",
                                                          "coreToken": manager.secrets.get("local_api"), "expectedReply": REPLY}),
                                        capture_output=True, text=True, encoding="utf-8", timeout=65)
                assert result.returncode == 0, result.stdout + result.stderr
                print(result.stdout, flush=True)
            sample_result = None
            if sample_export:
                print('Checking supplied unknown-format export against the original core and local model…', flush=True)
                checked = manager.inspect_files({'paths': [str(sample_export)]})['uploaded'][0]
                assert checked.get('ai_converted') and not checked.get('error'), checked.get('error')
                assert len(checked['candidates']) == 2, 'Expected exactly two conversation participants'
                task = manager.start_import({'files': [checked['saved_as']], 'selfUid': checked['candidates'][0]['uid'], 'friendUid': checked['candidates'][1]['uid']})
                result = until(lambda: manager.dispatch('import_status', {'id': task['task_id']}), lambda value: value.get('status') in {'done', 'failed', 'cancelled'}, 180)
                assert result['status'] == 'done' and not result.get('report', {}).get('failed_chunks'), result
                sample_result = {'format': checked['format'], 'statistics': checked.get('conversion_stats'), 'importStatus': result['status']}
            print(json.dumps({"ok": True, "core": manager.inventory()[0]["version"],
                              'protocol': protocol, 'sampleExport': sample_result,
                              "knownFormat": known["format"], "aiConverted": True,
                              "importStatus": completed["status"], "modelCalls": len(FixtureModels.calls),
                              "chatPersisted": True, "channelTransports": ["qq", "weixin"],
                              "imageChat": True, "localRuleReused": True,
                              "importWarnings": completed.get("error", "")}, ensure_ascii=False), flush=True)
    except Exception:
        log = root / "logs/core.log"
        if log.is_file():
            print(log.read_text(encoding="utf-8")[-14000:], file=sys.stderr)
        raise
    finally:
        manager.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', choices=['chat_completions', 'responses'], default='chat_completions')
    parser.add_argument('--sample-export', type=Path)
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Run this check with the bundled Windows Python 3.12.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureModels)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="afterglow-core-check-") as temporary:
            run(Path(temporary), f"http://127.0.0.1:{server.server_port}/v1", args.protocol, args.sample_export)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
