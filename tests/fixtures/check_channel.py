"""Run each built-in channel in a separate interpreter with simulated platform peers."""
import asyncio
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

root = Path(sys.argv[1]).resolve()
channel = sys.argv[2]
state = Path(sys.argv[3])
sys.path[:0] = [str(root / 'desktop_host'), str(root / 'desktop_host' / 'builtin' / channel)]
from bindings import BindingStore

module = runpy.run_path(str(root / 'desktop_host' / 'builtin' / channel / 'main.py'), run_name='protocol_check')
namespace = module['main'].__globals__
bindings = BindingStore(state / 'bindings.sqlite3')
api = SimpleNamespace(aclose=AsyncMock(), send_c2c_text=AsyncMock(), send_text=AsyncMock())
core = SimpleNamespace(aclose=AsyncMock(), reset_history=lambda *_: None)
calls = []

async def chat(**kwargs):
    calls.append(kwargs)
    if kwargs['user_text'] == 'silent':
        return None
    return SimpleNamespace(content='answer', reply_delay_seconds=120, schedule_tasks=())
core.chat = chat

def message(content, number):
    return SimpleNamespace(user_openid='owner', user_id='owner', content=content, attachments=[],
                           message_id=str(number), timestamp='2026-10-21T10:00:00Z', timestamp_ms=1700000000000,
                           context_token='context', run_id='run', images=[], raw={})

class Gateway:
    def __init__(self, *args, **kwargs):
        pass
    def on_c2c_message(self, callback):
        self.callback = callback
        return callback
    on_message = on_c2c_message
    def stop(self):
        pass
    async def run(self):
        await self.callback(message('not bound', 1))
        assert not calls, 'An unbound sender reached Afterglow'
        rows = bindings.list()
        assert len(rows) == 1 and len(rows[0]['code']) == 6
        bindings.approve('owner', rows[0]['code'])
        await self.callback(message('hello', 2))
        assert len(calls) == 1
        assert calls[0]['conversation_id'] == ('qq:owner' if channel == 'qq' else 'weixin:account:owner')
        assert calls[0]['client_message_id'].endswith(':2')
        sender = api.send_c2c_text if channel == 'qq' else api.send_text
        assert sender.call_args_list[-1].args[1] == 'answer'
        previous = sender.call_count
        await self.callback(message('silent', 3))
        assert sender.call_count == previous, 'Silence was sent as a visible reply'
        bindings.revoke('owner')
        await self.callback(message('revoked', 4))
        assert len(calls) == 2, 'A revoked sender reached Afterglow'

class ContextStore:
    def __init__(self, *_):
        pass
    def get(self, *_):
        return 'context'

async def images(*args, **kwargs):
    return []

environment = {'QQ_BOT_APP_ID':'123', 'QQ_BOT_CLIENT_SECRET':'secret',
               'WEIXIN_BOT_TOKEN':'token', 'WEIXIN_BOT_ACCOUNT_ID':'account',
               'AFTERGLOW_API_KEY':'local', 'AFTERGLOW_BASE_URL':'http://127.0.0.1:9999',
               'AFTERGLOW_BINDINGS_PATH':str(state/'bindings.sqlite3'),
               'AFTERGLOW_HISTORY_DB_PATH':str(state/'history.sqlite3'),
               'AFTERGLOW_IMAGE_MAX_COUNT':'0', 'AFTERGLOW_SCHEDULE_TASKS_ENABLED':'false',
               'AFTERGLOW_HUMAN_DELAY':'false', 'AFTERGLOW_LANGUAGE':'en-US',
               'AFTERGLOW_MESSAGE_SEGMENT_MIN_DELAY':'0','AFTERGLOW_MESSAGE_SEGMENT_MAX_DELAY':'0'}
replacements = {'QQBotAPI': lambda **kwargs: api, 'QQBotGateway': Gateway} if channel == 'qq' else {
    'WeixinBotAPI': lambda **kwargs: api, 'WeixinGateway': Gateway, 'WeixinContextTokenStore': ContextStore,
    'extract_afterglow_image_data_urls': images}
replacements['AfterglowClient'] = lambda **kwargs: core
with patch.dict(os.environ, environment, clear=True), patch.dict(namespace, replacements), patch.object(sys, 'argv', ['main.py']):
    async def run():
        # Human delay is off; a 120-second suggested delay must never be used.
        with patch('asyncio.sleep', new_callable=AsyncMock) as sleep:
            await namespace['main']()
            assert not any(call.args and call.args[0] == 120 for call in sleep.call_args_list)
    asyncio.run(run())
assert api.aclose.await_count == 1 and core.aclose.await_count == 1
print(channel + ' protocol forwarding passed')
