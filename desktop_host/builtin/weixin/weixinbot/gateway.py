"""OpenClaw Weixin long-poll gateway."""

from __future__ import annotations

import asyncio
from extension_events import emit
from protected_state import ProtectedJsonStore
import contextlib
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from .api import (
    MESSAGE_ITEM_FILE,
    MESSAGE_ITEM_IMAGE,
    MESSAGE_ITEM_TEXT,
    MESSAGE_ITEM_VIDEO,
    MESSAGE_ITEM_VOICE,
    MESSAGE_TYPE_USER,
    WeixinBotAPI,
)

logger = logging.getLogger("weixinbot.gateway")


@dataclass(frozen=True)
class WeixinInboundImage:
    url: str
    filename: str = ""
    media_type: str = "image/*"


@dataclass(frozen=True)
class WeixinMessage:
    message_id: str
    user_id: str
    content: str
    timestamp_ms: int
    context_token: str
    run_id: str
    images: list[WeixinInboundImage]
    raw: dict[str, Any]


WeixinHandler = Callable[[WeixinMessage], Awaitable[None]]


def _is_media_item(item: dict[str, Any]) -> bool:
    return item.get("type") in {
        MESSAGE_ITEM_IMAGE,
        MESSAGE_ITEM_VIDEO,
        MESSAGE_ITEM_FILE,
        MESSAGE_ITEM_VOICE,
    }


def _body_from_item_list(item_list: list[Any] | None) -> str:
    if not item_list:
        return ""
    for raw_item in item_list:
        if not isinstance(raw_item, dict):
            continue
        item_type = raw_item.get("type")
        if item_type == MESSAGE_ITEM_TEXT:
            text_item = raw_item.get("text_item") or {}
            text = str(text_item.get("text") or "")
            ref = raw_item.get("ref_msg")
            if not isinstance(ref, dict):
                return text
            ref_item = ref.get("message_item")
            if isinstance(ref_item, dict) and _is_media_item(ref_item):
                return text
            parts: list[str] = []
            title = ref.get("title")
            if title:
                parts.append(str(title))
            if isinstance(ref_item, dict):
                ref_body = _body_from_item_list([ref_item])
                if ref_body:
                    parts.append(ref_body)
            if not parts:
                return text
            return f"[引用: {' | '.join(parts)}]\n{text}"

        if item_type == MESSAGE_ITEM_VOICE:
            voice_item = raw_item.get("voice_item") or {}
            voice_text = voice_item.get("text")
            if voice_text:
                return str(voice_text)
    return ""


def _extract_images(item_list: list[Any] | None) -> list[WeixinInboundImage]:
    images: list[WeixinInboundImage] = []
    if not item_list:
        return images
    for raw_item in item_list:
        if not isinstance(raw_item, dict) or raw_item.get("type") != MESSAGE_ITEM_IMAGE:
            continue
        image_item = raw_item.get("image_item") or {}
        url = image_item.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            images.append(WeixinInboundImage(url=url))
            continue
        media = image_item.get("media") or {}
        full_url = media.get("full_url")
        if isinstance(full_url, str) and full_url.startswith(("http://", "https://")):
            images.append(WeixinInboundImage(url=full_url))
    return images


class _JsonFileStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_dict(self) -> dict[str, Any]:
        try:
            if not self.path.is_file():
                return {}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("读取状态文件失败，忽略 path=%s", self.path)
            return {}

    def save_dict(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)


class WeixinContextTokenStore:
    """Persist latest context_token per user."""

    def __init__(self, path: str | Path) -> None:
        self._store = ProtectedJsonStore(path)
        self._tokens: dict[str, str] = {
            str(k): str(v)
            for k, v in self._store.load_dict().items()
            if isinstance(v, str) and v
        }

    def set(self, user_id: str, context_token: str) -> None:
        if not user_id or not context_token:
            return
        self._tokens[user_id] = context_token
        self._store.save_dict(self._tokens)

    def get(self, user_id: str) -> str:
        return self._tokens.get(user_id, "")


class WeixinGateway:
    """Long-poll OpenClaw Weixin and dispatch user messages."""

    RECONNECT_DELAYS = (1, 2, 5, 10, 30, 60)

    def __init__(
        self,
        api: WeixinBotAPI,
        *,
        sync_state_path: str | Path,
        context_token_store: WeixinContextTokenStore,
        notify_lifecycle: bool = True,
    ) -> None:
        self.api = api
        self._sync_store = ProtectedJsonStore(sync_state_path)
        self.context_tokens = context_token_store
        self.notify_lifecycle = notify_lifecycle
        self._handler: WeixinHandler | None = None
        self._stopping = asyncio.Event()
        self._handler_tasks: set[asyncio.Task[None]] = set()
        self._reconnect_attempts = 0

    def on_message(self, fn: WeixinHandler) -> WeixinHandler:
        self._handler = fn
        return fn

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        if self.notify_lifecycle:
            with contextlib.suppress(Exception):
                await self.api.notify_start()
        try:
            while not self._stopping.is_set():
                try:
                    await self._poll_once()
                    self._reconnect_attempts = 0
                except Exception as exc:
                    emit("state", state="reconnecting")
                    if self._stopping.is_set():
                        break
                    delay = self.RECONNECT_DELAYS[
                        min(self._reconnect_attempts, len(self.RECONNECT_DELAYS) - 1)
                    ]
                    self._reconnect_attempts += 1
                    logger.warning("微信长轮询异常，将在 %ds 后重试：%s", delay, exc)
                    try:
                        await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
        finally:
            if self.notify_lifecycle:
                with contextlib.suppress(Exception):
                    await self.api.notify_stop()
            if self._handler_tasks:
                await asyncio.gather(*self._handler_tasks, return_exceptions=True)

    async def _poll_once(self) -> None:
        state = self._sync_store.load_dict()
        get_updates_buf = state.get("get_updates_buf")
        resp = await self.api.get_updates(
            get_updates_buf=get_updates_buf if isinstance(get_updates_buf, str) else ""
        )

        if "get_updates_buf" in resp and isinstance(resp.get("get_updates_buf"), str):
            self._sync_store.save_dict({"get_updates_buf": resp["get_updates_buf"]})

        ret = resp.get("ret")
        if ret not in (None, 0):
            raise RuntimeError(
                f"getupdates ret={ret} errcode={resp.get('errcode')} errmsg={resp.get('errmsg')}"
            )

        emit("state", state="connected")

        timeout_ms = resp.get("longpolling_timeout_ms")
        if isinstance(timeout_ms, (int, float)) and timeout_ms > 0:
            self.api.long_poll_timeout = max(5.0, float(timeout_ms) / 1000 + 5.0)

        msgs = resp.get("msgs") or []
        if not isinstance(msgs, list):
            return
        for raw_msg in msgs:
            if isinstance(raw_msg, dict):
                await self._dispatch_raw(raw_msg)

    async def _dispatch_raw(self, raw_msg: dict[str, Any]) -> None:
        if self._handler is None:
            return
        if raw_msg.get("message_type") != MESSAGE_TYPE_USER:
            return

        user_id = str(raw_msg.get("from_user_id") or "")
        if not user_id:
            return

        context_token = str(raw_msg.get("context_token") or "")
        if context_token:
            self.context_tokens.set(user_id, context_token)

        item_list = raw_msg.get("item_list")
        msg = WeixinMessage(
            message_id=str(raw_msg.get("message_id") or raw_msg.get("seq") or ""),
            user_id=user_id,
            content=_body_from_item_list(item_list if isinstance(item_list, list) else None),
            timestamp_ms=int(raw_msg.get("create_time_ms") or 0),
            context_token=context_token,
            run_id=str(raw_msg.get("run_id") or ""),
            images=_extract_images(item_list if isinstance(item_list, list) else None),
            raw=raw_msg,
        )
        task = asyncio.create_task(self._run_handler(msg))
        self._handler_tasks.add(task)
        task.add_done_callback(self._on_handler_done)

    async def _run_handler(self, msg: WeixinMessage) -> None:
        if self._handler is None:
            return
        try:
            await self._handler(msg)
        except Exception:
            logger.exception("Weixin handler 异常")

    def _on_handler_done(self, task: asyncio.Task[None]) -> None:
        self._handler_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("Weixin handler task 异常")
