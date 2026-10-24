"""QQ Bot WebSocket Gateway 客户端（最小实现）。

实现完整的 op 协议生命周期：
- op=10 Hello             ← 服务端首条，含 heartbeat_interval
- op=2  Identify          → 客户端发，声明 intents / token / shard
- op=1  Heartbeat         → 客户端周期发，d=lastSeq
- op=11 HeartbeatACK      ← 服务端回
- op=0  Dispatch          ← 业务事件（READY / C2C_MESSAGE_CREATE ...）
- op=6  Resume            → 断线重连复用 session
- op=7  Reconnect         ← 服务端要求重连
- op=9  InvalidSession    ← 会话失效（按 d:bool 决定是否可 Resume）
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import websockets
from extension_events import emit
from websockets.exceptions import ConnectionClosed

from .api import QQBotAPI

logger = logging.getLogger("qqbot.gateway")


# QQ Intents 位掩码（详见 https://bot.q.qq.com/wiki/）
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30  # 频道公开消息
INTENT_DIRECT_MESSAGE = 1 << 12         # 频道私信
INTENT_GROUP_AND_C2C = 1 << 25          # 群聊 + C2C 私聊（本最小实现仅启用此项）
INTENT_INTERACTION = 1 << 26            # 按钮交互


@dataclass(frozen=True)
class C2CMessage:
    """C2C_MESSAGE_CREATE 事件的精简模型。"""

    message_id: str
    user_openid: str
    content: str
    timestamp: str
    attachments: list[dict[str, Any]]
    raw: dict[str, Any]  # 原始事件，便于业务侧按需取字段


C2CHandler = Callable[[C2CMessage], Awaitable[None]]


class QQBotGateway:
    """单账号 Gateway 长连接客户端。

    使用方式：
        api = QQBotAPI(app_id, secret)
        gw = QQBotGateway(api)

        @gw.on_c2c_message
        async def handle(msg): ...

        await gw.run()
    """

    # 仅启用 C2C/群聊 intent，最小项目无频道场景
    DEFAULT_INTENTS = INTENT_GROUP_AND_C2C

    # 断线重连退避序列（秒）
    RECONNECT_DELAYS = (1, 2, 5, 10, 30, 60)

    def __init__(self, api: QQBotAPI, *, intents: int | None = None) -> None:
        self.api = api
        self.intents = intents if intents is not None else self.DEFAULT_INTENTS

        self._c2c_handler: C2CHandler | None = None

        # session 状态：用于 Resume
        self._session_id: str | None = None
        self._last_seq: int | None = None

        self._stopping = asyncio.Event()
        self._reconnect_attempts = 0
        self._handler_tasks: set[asyncio.Task[None]] = set()

    # ----------------------------------------------------------- 事件注册

    def on_c2c_message(self, fn: C2CHandler) -> C2CHandler:
        """装饰器：注册 C2C 私聊消息回调。"""
        self._c2c_handler = fn
        return fn

    # ----------------------------------------------------------- 生命周期

    async def run(self) -> None:
        """阻塞运行，直到 stop() 被调用。带断线自动重连。"""
        while not self._stopping.is_set():
            try:
                await self._connect_once()
                self._reconnect_attempts = 0
            except Exception as exc:
                emit("state", state="reconnecting")
                if self._stopping.is_set():
                    break
                delay = self.RECONNECT_DELAYS[
                    min(self._reconnect_attempts, len(self.RECONNECT_DELAYS) - 1)
                ]
                self._reconnect_attempts += 1
                logger.warning("连接异常将在 %ds 后重连：%s", delay, exc)
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        if self._handler_tasks:
            await asyncio.gather(*self._handler_tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stopping.set()

    # ----------------------------------------------------------- 单次连接

    async def _connect_once(self) -> None:
        emit("state", state="connecting")
        gateway_url = await self.api.get_gateway_url()
        logger.info("连接 Gateway: %s", gateway_url)

        async with websockets.connect(gateway_url, max_size=None) as ws:
            heartbeat_task: asyncio.Task | None = None
            try:
                async for raw in ws:
                    payload = json.loads(raw)
                    op = payload.get("op")
                    seq = payload.get("s")
                    if seq is not None:
                        self._last_seq = seq

                    if op == 10:  # Hello
                        interval_ms = payload["d"]["heartbeat_interval"]
                        await self._identify_or_resume(ws)
                        heartbeat_task = asyncio.create_task(
                            self._heartbeat_loop(ws, interval_ms / 1000)
                        )

                    elif op == 0:  # Dispatch
                        await self._handle_dispatch(payload)

                    elif op == 11:  # Heartbeat ACK
                        logger.debug("Heartbeat ACK")

                    elif op == 7:  # 服务端要求重连
                        emit("state", state="reconnecting")
                        logger.info("服务端 op=7 要求重连")
                        await ws.close()
                        return  # 外层 run() 会进入重连分支

                    elif op == 9:  # Invalid Session
                        emit("state", state="reconnecting")
                        can_resume = bool(payload.get("d"))
                        logger.warning("收到 op=9 InvalidSession (can_resume=%s)", can_resume)
                        if not can_resume:
                            self._session_id = None
                            self._last_seq = None
                        await ws.close()
                        return
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()

    # ----------------------------------------------------------- Identify / Resume

    async def _identify_or_resume(self, ws: websockets.WebSocketClientProtocol) -> None:
        token = await self.api.get_access_token()
        if self._session_id and self._last_seq is not None:
            logger.info("尝试 Resume session=%s seq=%s", self._session_id, self._last_seq)
            await ws.send(json.dumps({
                "op": 6,
                "d": {
                    "token": f"QQBot {token}",
                    "session_id": self._session_id,
                    "seq": self._last_seq,
                },
            }))
        else:
            logger.info("发送 Identify intents=0x%x", self.intents)
            await ws.send(json.dumps({
                "op": 2,
                "d": {
                    "token": f"QQBot {token}",
                    "intents": self.intents,
                    "shard": [0, 1],
                },
            }))

    # ----------------------------------------------------------- 心跳循环

    async def _heartbeat_loop(
        self, ws: websockets.WebSocketClientProtocol, interval_sec: float
    ) -> None:
        try:
            while True:
                await asyncio.sleep(interval_sec)
                payload = json.dumps({"op": 1, "d": self._last_seq})
                await ws.send(payload)
                logger.debug("心跳发送 seq=%s", self._last_seq)
        except (ConnectionClosed, asyncio.CancelledError):
            return

    # ----------------------------------------------------------- 事件分发

    async def _handle_dispatch(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("t")
        data = payload.get("d") or {}

        if event_type == "READY":
            emit("state", state="connected")
            self._session_id = data.get("session_id")
            user = data.get("user", {})
            logger.info("READY: bot=%s session=%s", user.get("username"), self._session_id)
            return

        if event_type == "RESUMED":
            emit("state", state="connected")
            logger.info("RESUMED 成功")
            return

        if event_type == "C2C_MESSAGE_CREATE":
            await self._dispatch_c2c(data)
            return

        # 其余事件本最小实现忽略
        logger.debug("忽略事件 %s", event_type)

    async def _dispatch_c2c(self, data: dict[str, Any]) -> None:
        if self._c2c_handler is None:
            return
        msg = C2CMessage(
            message_id=data.get("id", ""),
            user_openid=(data.get("author") or {}).get("user_openid", ""),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
            attachments=data.get("attachments") or [],
            raw=data,
        )
        task = asyncio.create_task(self._run_c2c_handler(msg))
        self._handler_tasks.add(task)
        task.add_done_callback(self._on_c2c_handler_done)

    async def _run_c2c_handler(self, msg: C2CMessage) -> None:
        if self._c2c_handler is None:
            return
        try:
            await self._c2c_handler(msg)
        except Exception:
            logger.exception("C2C handler 异常")

    def _on_c2c_handler_done(self, task: asyncio.Task[None]) -> None:
        self._handler_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            # _run_c2c_handler 已记录异常；这里兜底防止未取异常告警。
            logger.exception("C2C handler task 异常")
