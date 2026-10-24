"""Afterglow OpenAI 兼容 API 客户端（仅 chat completions 子集）。

职责（SRP）：把"用户文本 + 会话标识"翻译成对 Afterglow `/v1/chat/completions`
的一次调用，并返回应当回复的内容与 Afterglow 扩展字段；若 Afterglow 判定本轮
应当沉默则返回 None。

会话历史（辅助上下文）：
  Afterglow 后端虽然通过 `conversation_id` 在 LanceDB 维护 live memory，
  但 OpenAI 协议本身的 messages 数组也是后端 prompt 的直接输入。客户端在
  本地 SQLite 里保留每个会话的最近 N 轮 user/assistant 消息一起送给后端，能让
  后端无需检索就拿到当前轮上下文，对短期连贯性更准。
  可选的 OpenAI-compatible 历史压缩会把较早历史替换为摘要，继续保留最近几轮原文。

  - 沉默轮（policy/finish_reason/sentinel 命中）不写入历史，避免下一轮把
    "[silent]" 当成真实回复
  - 调用失败（抛 AfterglowError）也不写入历史，避免污染后续上下文
  - per-conversation `asyncio.Lock` 保证同一会话的请求严格按顺序更新历史
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("afterglow.client")

# 默认沉默 sentinel（与 Afterglow 后端 SILENCE_RESPONSE_SENTINEL 默认值一致）
DEFAULT_SILENCE_SENTINEL = "[silent]"

# 默认保留的最近轮数（一轮 = 一条 user + 一条 assistant）
DEFAULT_HISTORY_MAX_TURNS = 6
DEFAULT_HISTORY_DB_PATH = Path(__file__).with_name("data") / "chat_history.sqlite3"


class AfterglowError(RuntimeError):
    """Afterglow 调用层异常。"""


@dataclass(frozen=True)
class HistoryCompressionConfig:
    """OpenAI-compatible API settings for local history compression."""

    api_key: str = ""
    model: str = ""
    base_url: str = "https://api.openai.com"
    trigger_turns: int = 0
    trigger_tokens: int = 0
    keep_turns: int = 3
    timeout: float = 60.0
    max_output_tokens: int = 800

    @property
    def enabled(self) -> bool:
        has_trigger = self.trigger_turns > 0 or self.trigger_tokens > 0
        return bool(self.api_key and self.model and has_trigger)


@dataclass(frozen=True)
class ScheduleTask:
    """Afterglow schedule_tasks extension item."""

    id: str
    trigger_at: str
    recurrence: str | None
    message: str
    title: str = ""
    source: str = "extractor"


@dataclass(frozen=True)
class AfterglowReply:
    """Afterglow visible reply content plus supported extension fields.

    content is empty only when Afterglow is silent but still returned schedule_tasks.
    """

    content: str
    reply_delay_seconds: float = 0.0
    schedule_tasks: tuple[ScheduleTask, ...] = ()


@dataclass(frozen=True)
class AfterglowImage:
    """Image input for OpenAI-compatible multimodal chat content."""

    url: str


class LocalHistoryStore:
    """SQLite-backed short-term chat history store."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn = self._connect(self._db_path)
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def load(self, conversation_id: str) -> list[dict[str, str]]:
        row = self._conn.execute(
            "SELECT messages_json FROM chat_histories WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return []

        try:
            messages = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("本地聊天历史损坏，忽略 conversation_id=%s", conversation_id)
            return []

        if not isinstance(messages, list):
            logger.warning("本地聊天历史格式异常，忽略 conversation_id=%s", conversation_id)
            return []

        clean_messages: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"system", "user", "assistant"} and isinstance(content, str):
                clean_messages.append({"role": role, "content": content})

        return clean_messages

    def save(self, conversation_id: str, messages: list[dict[str, str]]) -> None:
        self._conn.execute(
            """
            INSERT INTO chat_histories (conversation_id, messages_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                json.dumps(messages, ensure_ascii=False, separators=(",", ":")),
                int(time.time()),
            ),
        )
        self._conn.commit()

    def reset(self, conversation_id: str) -> None:
        self._conn.execute(
            "DELETE FROM chat_histories WHERE conversation_id = ?",
            (conversation_id,),
        )
        self._conn.commit()

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_histories (
                conversation_id TEXT PRIMARY KEY,
                messages_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _estimate_text_tokens(text: str) -> int:
    cjk_chars = 0
    other_chars = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            cjk_chars += 1
        elif not char.isspace():
            other_chars += 1
    return cjk_chars + max(1, (other_chars + 3) // 4)


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    total = 0
    for message in messages:
        total += 4
        total += _estimate_text_tokens(message.get("role", ""))
        total += _estimate_text_tokens(message.get("content", ""))
    return total


def _completed_turn_count(messages: list[dict[str, str]]) -> int:
    return sum(1 for message in messages if message.get("role") == "assistant")


def _last_turn_messages(
    messages: list[dict[str, str]],
    keep_turns: int,
) -> list[dict[str, str]]:
    if keep_turns <= 0:
        return []
    keep_count = keep_turns * 2
    recent = [message for message in messages if message.get("role") != "system"]
    return recent[-keep_count:]


class OpenAIHistoryCompressor:
    """Compresses local history through an OpenAI Chat Completions compatible API."""

    def __init__(self, config: HistoryCompressionConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(timeout=config.timeout)
        self._url = _chat_completions_url(config.base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    def should_compress(self, messages: list[dict[str, str]]) -> bool:
        if not self._config.enabled:
            return False

        if (
            self._config.trigger_turns > 0
            and _completed_turn_count(messages) >= self._config.trigger_turns
        ):
            return True

        return (
            self._config.trigger_tokens > 0
            and _estimate_messages_tokens(messages) >= self._config.trigger_tokens
        )

    async def maybe_compress(
        self,
        conversation_id: str,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not self.should_compress(messages):
            return messages

        recent_messages = _last_turn_messages(messages, self._config.keep_turns)
        old_messages = messages[: len(messages) - len(recent_messages)]
        if not old_messages:
            return messages

        try:
            summary = await self._summarize(old_messages)
        except Exception as exc:
            logger.warning(
                "压缩聊天历史失败，保留原始历史 conversation_id=%s：%s",
                conversation_id,
                exc,
            )
            return messages

        logger.info(
            "已压缩聊天历史 conversation_id=%s turns=%d tokens~=%d",
            conversation_id,
            _completed_turn_count(messages),
            _estimate_messages_tokens(messages),
        )
        return [
            {
                "role": "system",
                "content": (
                    "以下是之前对话的压缩摘要。请把它作为上下文参考，"
                    "但优先遵循用户当前消息和系统/开发者约束。\n\n"
                    f"{summary}"
                ),
            },
            *recent_messages,
        ]

    async def _summarize(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是聊天记录压缩器。请用中文压缩对话历史，保留："
                        "用户偏好、长期事实、未完成任务、重要约定、最近目标、"
                        "必要的上下文和关键结论。删除寒暄、重复和无关细节。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请把下面的历史压缩成一段可继续对话使用的摘要。"
                        "不要续写对话，不要编造缺失信息。\n\n"
                        f"{self._format_transcript(messages)}"
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": self._config.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        resp = await self._client.post(self._url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise AfterglowError(f"摘要 API 返回 {resp.status_code}：{resp.text[:500]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise AfterglowError(f"摘要 API 响应非 JSON：{resp.text[:200]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise AfterglowError(f"摘要 API 响应缺少 choices：{data}")

        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        summary = (content or "").strip()
        if not summary:
            raise AfterglowError(f"摘要 API 返回空内容：{data}")
        return summary

    @staticmethod
    def _format_transcript(messages: list[dict[str, str]]) -> str:
        lines: list[str] = []
        role_names = {
            "system": "已有摘要/系统上下文",
            "user": "用户",
            "assistant": "助手",
        }
        for message in messages:
            role = role_names.get(message.get("role", ""), message.get("role", "未知"))
            content = message.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)


class AfterglowClient:
    """单实例长连接客户端（asyncio）。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        model: str = "afterglow",
        timeout: float = 120.0,
        silence_sentinel: str = DEFAULT_SILENCE_SENTINEL,
        history_max_turns: int = DEFAULT_HISTORY_MAX_TURNS,
        history_db_path: str | Path = DEFAULT_HISTORY_DB_PATH,
        history_compression: HistoryCompressionConfig | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._silence_sentinel = silence_sentinel
        # 一轮 = 2 条消息（user + assistant）；0 表示不携带历史
        self._history_max_messages = max(history_max_turns, 0) * 2
        # 聊天接口可能较慢（检索 + 主模型生成），timeout 默认放宽到 120s
        self._client = httpx.AsyncClient(timeout=timeout)

        # 每个 conversation_id 一份本地历史 + 一把锁，保证同会话顺序更新
        self._history_store = LocalHistoryStore(history_db_path)
        self._history_compressor: OpenAIHistoryCompressor | None = None
        if history_compression and self._history_max_messages > 0:
            if history_compression.enabled:
                self._history_compressor = OpenAIHistoryCompressor(history_compression)
            elif (
                history_compression.trigger_turns > 0
                or history_compression.trigger_tokens > 0
            ):
                logger.warning(
                    "聊天历史压缩阈值已配置，但 API key 或 model 为空，压缩未启用"
                )
        self._locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        finally:
            try:
                if self._history_compressor is not None:
                    await self._history_compressor.aclose()
            finally:
                self._history_store.close()

    # --------------------------------------------------------------- history

    def _get_lock(self, conversation_id: str) -> asyncio.Lock:
        """惰性创建 per-conversation 锁。setdefault 在单线程 asyncio 下原子。"""
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation_id] = lock
        return lock

    def reset_history(self, conversation_id: str) -> None:
        """清空指定会话的客户端侧历史（不影响后端 live memory）。"""
        self._history_store.reset(conversation_id)

    # ---------------------------------------------------------------- chat

    async def chat(
        self,
        *,
        conversation_id: str,
        user_text: str,
        images: list[AfterglowImage] | None = None,
        caller_id: str | None = None,
        client_message_id: str | None = None,
    ) -> AfterglowReply | None:
        """单轮请求 Afterglow，返回需要发给用户的内容。

        :param conversation_id: 稳定标识（同一 QQ 用户复用同一 ID，让后端维护记忆）
        :param user_text: 用户原文
        :param images: 当前轮用户发送的图片。仅随当前请求发送，不写入本地历史。
        :param caller_id: Afterglow 扩展字段；同一调用方的并发请求可互相取消/合并。
        :param client_message_id: Afterglow 扩展字段；调用方生成的单条用户消息幂等 ID。
        :return: 回复内容与扩展字段；若判定沉默则返回 None
        :raises AfterglowError: 网络/鉴权/协议错误
        """
        images = images or []
        lock = self._get_lock(conversation_id)
        async with lock:
            history = await self._prepare_history(conversation_id)

        user_content = self._build_user_content(user_text, images)
        # OpenAI 标准 messages：已完成回复的历史 + 当前这一条 user 消息。
        # 未完成的旧用户气泡由 Afterglow 根据 caller_id/client_message_id 队列合并。
        messages: list[dict[str, Any]] = [
            *history,
            {"role": "user", "content": user_content},
        ]

        payload: dict[str, Any] = {
            # model 字段 Afterglow 视为占位（实际用 .env 配的 CHAT_MODEL），但传一下兼容性更好
            "model": self._model,
            "messages": messages,
            "stream": False,
            "conversation_id": conversation_id,
        }
        if caller_id:
            payload["caller_id"] = caller_id
        if client_message_id:
            payload["client_message_id"] = client_message_id

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/v1/chat/completions"

        try:
            resp = await self._client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise AfterglowError(f"请求 Afterglow 失败：{exc}") from exc

        if resp.status_code >= 400:
            raise AfterglowError(
                f"Afterglow 返回 {resp.status_code}：{resp.text[:500]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise AfterglowError(f"Afterglow 响应非 JSON：{resp.text[:200]}") from exc

        reply = self._extract_reply(data)

        # 仅在非沉默 / 非失败时把这一轮追加到历史。多条 QQ 气泡分发只发生在
        # 调用方展示层；历史里保留完整 assistant content，维持 OpenAI 协议语义。
        if reply is not None and reply.content:
            async with lock:
                await self._append_history(
                    conversation_id,
                    self._build_history_user_text(user_text, images),
                    reply.content,
                )

        return reply

    @staticmethod
    def _build_user_content(
        user_text: str,
        images: list[AfterglowImage],
    ) -> str | list[dict[str, Any]]:
        text = user_text.strip()
        if not images:
            return text

        parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": text or "用户发送了图片/表情包，请根据图片内容自然回复。",
            }
        ]
        for image in images:
            if image.url:
                parts.append({"type": "image_url", "image_url": {"url": image.url}})
        return parts

    @staticmethod
    def _build_history_user_text(
        user_text: str,
        images: list[AfterglowImage],
    ) -> str:
        text = user_text.strip()
        if not images:
            return text

        image_note = "[图片]" if len(images) == 1 else f"[图片 x{len(images)}]"
        if text:
            return f"{text}\n{image_note}"
        return image_note

    async def _prepare_history(self, conversation_id: str) -> list[dict[str, str]]:
        """读取本地历史，并在需要时先压缩。"""
        if self._history_max_messages <= 0:
            return []

        history = self._history_store.load(conversation_id)
        if self._history_compressor is not None:
            compressed = await self._history_compressor.maybe_compress(
                conversation_id,
                history,
            )
            if compressed != history:
                self._history_store.save(conversation_id, compressed)
            return compressed

        trimmed = self._trim_history(history)
        if trimmed != history:
            self._history_store.save(conversation_id, trimmed)
        return trimmed

    async def _append_history(
        self, conversation_id: str, user_text: str, assistant_text: str
    ) -> None:
        """追加一轮对话，并按上限裁尾。"""
        if self._history_max_messages <= 0:
            return

        history = [
            *self._history_store.load(conversation_id),
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
        if self._history_compressor is not None:
            history = await self._history_compressor.maybe_compress(
                conversation_id,
                history,
            )
        else:
            history = self._trim_history(history)
        self._history_store.save(conversation_id, history)

    def _trim_history(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        if self._history_max_messages <= 0:
            return []
        return history[-self._history_max_messages :]

    # --------------------------------------------------------------- parse

    def _extract_reply(self, data: dict[str, Any]) -> AfterglowReply | None:
        """从 OpenAI 兼容响应中提取回复，识别 Afterglow 的沉默信号。

        沉默/取消判断：
          1. `policy.should_reply == false`（Afterglow 扩展字段，最权威）
          2. `choices[0].finish_reason == "silenced"`
          3. `choices[0].finish_reason == "cancelled"`（旧请求已被新请求取代）
          4. content 文本等于 sentinel（默认 "[silent]"）
        """
        # 1. policy 顶层字段（最准确）
        policy = data.get("policy") or {}
        if policy.get("should_reply") is False:
            logger.info("Afterglow 决策沉默：%s", policy.get("reason") or policy)
            silent_reply = self._extract_silent_schedule_tasks(data)
            if silent_reply is not None:
                return silent_reply
            return None

        choices = data.get("choices") or []
        if not choices:
            raise AfterglowError(f"Afterglow 响应缺少 choices：{data}")

        choice = choices[0] or {}
        finish_reason = choice.get("finish_reason")
        message = choice.get("message") or {}
        content = message.get("content")

        # content 可能是 list（多模态），简单兜底
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        content = (content or "").strip()

        # 2. finish_reason
        if finish_reason == "silenced":
            logger.info("Afterglow finish_reason=silenced，跳过回复")
            silent_reply = self._extract_silent_schedule_tasks(data)
            if silent_reply is not None:
                return silent_reply
            return None

        if finish_reason == "cancelled":
            logger.info("Afterglow finish_reason=cancelled，跳过旧请求回复")
            return None

        # 3. sentinel 字符串
        if content == self._silence_sentinel:
            logger.info("Afterglow 返回 sentinel %r，跳过回复", self._silence_sentinel)
            silent_reply = self._extract_silent_schedule_tasks(data)
            if silent_reply is not None:
                return silent_reply
            return None

        if not content:
            # 非沉默但空内容：当作异常上抛，避免静默丢消息
            raise AfterglowError(f"Afterglow 返回空内容：{data}")

        return AfterglowReply(
            content=content,
            reply_delay_seconds=self._extract_reply_delay_seconds(data),
            schedule_tasks=self._extract_schedule_tasks(data),
        )

    def _extract_silent_schedule_tasks(
        self, data: dict[str, Any]
    ) -> AfterglowReply | None:
        schedule_tasks = self._extract_schedule_tasks(data)
        if not schedule_tasks:
            return None

        logger.info("Afterglow 本轮沉默，但保留 %d 条 schedule_tasks", len(schedule_tasks))
        return AfterglowReply(content="", schedule_tasks=schedule_tasks)

    def _extract_reply_delay_seconds(self, data: dict[str, Any]) -> float:
        policy = data.get("policy") or {}
        raw_delay = policy.get("reply_delay_seconds", 0)
        try:
            delay = float(raw_delay)
        except (TypeError, ValueError):
            logger.warning("忽略非法 reply_delay_seconds=%r", raw_delay)
            return 0.0
        return max(0.0, delay)

    def _extract_schedule_tasks(
        self, data: dict[str, Any]
    ) -> tuple[ScheduleTask, ...]:
        raw_tasks = data.get("schedule_tasks")
        if raw_tasks is None:
            return ()
        if not isinstance(raw_tasks, list):
            logger.warning("忽略非法 schedule_tasks 字段：%r", raw_tasks)
            return ()

        tasks: list[ScheduleTask] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                logger.warning("忽略非法 ScheduleTask：%r", raw_task)
                continue

            task_id = raw_task.get("id")
            trigger_at = raw_task.get("trigger_at")
            message = raw_task.get("message")
            if not (
                isinstance(task_id, str)
                and task_id.strip()
                and isinstance(trigger_at, str)
                and trigger_at.strip()
                and isinstance(message, str)
                and message.strip()
            ):
                logger.warning("忽略缺少必填字段的 ScheduleTask：%r", raw_task)
                continue

            recurrence = raw_task.get("recurrence")
            if recurrence is not None and not isinstance(recurrence, str):
                logger.warning(
                    "ScheduleTask recurrence 类型异常，按一次性任务处理：%r",
                    raw_task,
                )
                recurrence = None

            title = raw_task.get("title")
            source = raw_task.get("source")
            tasks.append(
                ScheduleTask(
                    id=task_id.strip(),
                    trigger_at=trigger_at.strip(),
                    recurrence=recurrence.strip() if recurrence else None,
                    message=message.strip(),
                    title=title.strip() if isinstance(title, str) else "",
                    source=(
                        source.strip()
                        if isinstance(source, str) and source
                        else "extractor"
                    ),
                )
            )

        return tuple(tasks)
