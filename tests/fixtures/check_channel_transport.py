"""Run the actual launcher and adapter transports against loopback platform peers.

Input is a private JSON line containing test paths and a temporary core token.
Only platform addresses and the lifetime of the gateway are substituted. The
launcher, handler, API client, gateway, core client and history store are real.
"""
import asyncio
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import runpy
import sqlite3
import sys
import threading
import time
from unittest.mock import patch

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

config = json.loads(sys.stdin.readline())
root, state = Path(config['root']), Path(config['state'])
channel = config['channel']
source = root / 'desktop_host' / 'builtin' / channel
sys.path[:0] = [str(root / 'desktop_host'), str(source), str(Path(config['component']) / 'deps')]
from bindings import BindingStore

state.mkdir(parents=True, exist_ok=True)
BindingStore(state / 'bindings.sqlite3').trust_owner('owner')
sent = threading.Event()
stop_peer = threading.Event()
outbound, requests = [], []
websocket_url = ''


class PlatformPeer(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        assert channel == 'qq' and self.path == '/gateway', self.path
        assert self.headers['Authorization'] == 'QQBot fixture-token'
        requests.append(self.path)
        self.respond({'url': websocket_url})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(self.path)
        if self.path == '/token':
            assert payload == {'appId': '123', 'clientSecret': 'fixture-secret'}
            return self.respond({'access_token': 'fixture-token', 'expires_in': 7200})
        if channel == 'qq':
            assert self.path == '/v2/users/owner/messages', self.path
            assert self.headers['Authorization'] == 'QQBot fixture-token'
            assert payload['msg_id'] == 'transport-1'
            outbound.append(payload['content'])
            self.respond({'id': 'sent-1'})
            sent.set()
            return
        assert self.headers['Authorization'] == 'Bearer fixture-token'
        if self.path.endswith('/getupdates'):
            first = requests.count(self.path) == 1
            if not first:
                time.sleep(.05)
            return self.respond({'ret': 0, 'get_updates_buf': 'cursor-1', 'msgs': [{
                'message_type': 1, 'from_user_id': 'owner', 'message_id': 'transport-1',
                'create_time_ms': 1761000000000, 'context_token': 'fixture-context', 'run_id': 'fixture-run',
                'item_list': [{'type': 1, 'text_item': {'text': 'Where is our walk meeting place?'}}],
            }] if first else []})
        if self.path.endswith('/sendmessage'):
            message = payload['msg']
            assert message['to_user_id'] == 'owner'
            assert message['context_token'] == 'fixture-context'
            outbound.append(message['item_list'][0]['text_item']['text'])
            self.respond({'ret': 0})
            sent.set()
            return
        assert self.path.endswith(('/notifystart', '/notifystop')), self.path
        self.respond({'ret': 0})


server = ThreadingHTTPServer(('127.0.0.1', 0), PlatformPeer)
server.daemon_threads = True
worker = threading.Thread(target=server.serve_forever, daemon=True)
worker.start()
origin = 'http://127.0.0.1:' + str(server.server_port)


def websocket_peer():
    import websockets

    async def receive(ws):
        await ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 1000}}))
        identify = json.loads(await ws.recv())
        assert identify['op'] == 2 and identify['d']['token'] == 'QQBot fixture-token'
        await ws.send(json.dumps({'op': 0, 't': 'READY', 's': 1, 'd': {'session_id': 'fixture-session'}}))
        await ws.send(json.dumps({'op': 0, 't': 'C2C_MESSAGE_CREATE', 's': 2, 'd': {
            'id': 'transport-1', 'author': {'user_openid': 'owner'},
            'content': 'Where is our walk meeting place?', 'timestamp': '2026-10-22T10:00:00Z',
        }}))
        while not stop_peer.is_set():
            try:
                await asyncio.wait_for(ws.recv(), .1)
                await ws.send(json.dumps({'op': 11}))
            except asyncio.TimeoutError:
                pass

    async def serve():
        global websocket_url
        async with websockets.serve(receive, '127.0.0.1', 0) as ws_server:
            websocket_url = 'ws://127.0.0.1:' + str(ws_server.sockets[0].getsockname()[1])
            while not stop_peer.is_set():
                await asyncio.sleep(.05)
    asyncio.run(serve())


peer = None
if channel == 'qq':
    peer = threading.Thread(target=websocket_peer, daemon=True)
    peer.start()
    deadline = time.monotonic() + 5
    while not websocket_url:
        assert time.monotonic() < deadline, 'WebSocket fixture failed to start'
        time.sleep(.02)
    from qqbot import api as platform_api
    from qqbot.gateway import QQBotGateway as Gateway
    platform_api.API_BASE, platform_api.TOKEN_URL = origin, origin + '/token'
else:
    from weixinbot.gateway import WeixinGateway as Gateway

real_run = Gateway.run


async def finite_gateway(self):
    task = asyncio.create_task(real_run(self))
    try:
        deadline = time.monotonic() + 50
        while not sent.is_set():
            if task.done():
                await task
                raise AssertionError('Gateway stopped before replying')
            if time.monotonic() >= deadline:
                raise AssertionError('No reply through real platform transports')
            await asyncio.sleep(.05)
        # Allow the HTTP reply and history transaction to finish before shutdown.
        await asyncio.sleep(.1)
        self.stop()
        stop_peer.set()
        await asyncio.wait_for(task, 3)
    finally:
        self.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


environment = {
    'QQ_BOT_APP_ID': '123', 'QQ_BOT_CLIENT_SECRET': 'fixture-secret',
    'WEIXIN_BOT_TOKEN': 'fixture-token', 'WEIXIN_BOT_ACCOUNT_ID': 'fixture-account',
    'WEIXIN_BOT_BASE_URL': origin,
    'WEIXIN_SYNC_STATE_PATH': str(state / 'sync.json'),
    'WEIXIN_CONTEXT_TOKENS_PATH': str(state / 'context.json'),
    'AFTERGLOW_BASE_URL': config['coreUrl'], 'AFTERGLOW_API_KEY': config['coreToken'],
    'AFTERGLOW_BINDINGS_PATH': str(state / 'bindings.sqlite3'),
    'AFTERGLOW_HISTORY_DB_PATH': str(state / 'history.sqlite3'),
    'AFTERGLOW_IMAGE_MAX_COUNT': '0', 'AFTERGLOW_SCHEDULE_TASKS_ENABLED': 'false',
    'AFTERGLOW_HUMAN_DELAY': 'false', 'AFTERGLOW_LANGUAGE': 'en-US',
    'AFTERGLOW_MESSAGE_SEGMENT_MIN_DELAY': '0', 'AFTERGLOW_MESSAGE_SEGMENT_MAX_DELAY': '0',
}
launcher_input = {'extension': channel, 'component': config['component'], 'environment': environment}
try:
    with patch.object(Gateway, 'run', finite_gateway), patch.object(sys, 'stdin', io.StringIO(json.dumps(launcher_input) + '\n')):
        launcher = runpy.run_path(str(root / 'desktop_host' / 'launch_extension.py'), run_name='transport_fixture')
        launcher['main']()
    assert sent.is_set() and config['expectedReply'] in ''.join(outbound), outbound
    with contextlib.closing(sqlite3.connect(state / 'history.sqlite3')) as connection:
        rows = connection.execute('SELECT conversation_id, messages_json FROM chat_histories').fetchall()
    expected_conversation = 'qq:owner' if channel == 'qq' else 'weixin:fixture-account:owner'
    assert len(rows) == 1 and rows[0][0] == expected_conversation, rows
    assert config['expectedReply'] in rows[0][1], rows
    print(json.dumps({'channel': channel, 'transportPassed': True, 'historyPersisted': True, 'requests': requests}))
finally:
    stop_peer.set()
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)
    if peer:
        peer.join(timeout=3)
