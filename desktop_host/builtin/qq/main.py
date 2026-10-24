"""Afterglow QQ Bot 主入口。

把 QQ 私聊（C2C）消息转发给本地 Afterglow `/v1/chat/completions`，
并把 Afterglow 的回复发回给用户。

会话连续性：以 `user_openid` 派生 `conversation_id`，每个 QQ 用户
在 Afterglow 后端视为独立会话，记忆由后端自行通过 LanceDB 维护。

运行：
    cp .env.example .env
    # 编辑 .env 填入 QQ_BOT_* 与 AFTERGLOW_*
    python main.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import random
import re
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from bindings import BindingStore
from extension_events import emit

from afterglow_client import (
    AfterglowClient,
    AfterglowError,
    AfterglowImage,
    HistoryCompressionConfig,
)
from qqbot import C2CMessage, QQBotAPI, QQBotGateway
from qqbot.schedule_tasks import QQScheduleTaskRunner

logger = logging.getLogger("afterglow.qqbot")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@dataclass(frozen=True)
class InboundImage:
    url: str
    media_type: str
    filename: str = ""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(f"缺少环境变量 {name}\n")
        sys.exit(1)
    return value


def _build_conversation_id(openid: str) -> str:
    """每个 QQ 用户固定一个会话 ID，让 Afterglow 自行维护记忆。"""
    return f"qq:{openid}"


def _build_client_message_id(openid: str, message_id: str, timestamp: str) -> str:
    """Afterglow 幂等消息 ID：同一 QQ 用户的一条气泡对应一个稳定 ID。"""
    message_id = message_id.strip()
    if message_id:
        return f"qq:{openid}:{message_id}"
    timestamp = timestamp.strip() or str(random.randint(0, 2**31 - 1))
    return f"qq:{openid}:missing-message-id:{timestamp}"


def _parse_bool(raw: str, *, default: bool) -> bool:
    raw = raw.strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _resolve_project_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    return path


def _parse_face_tags(text: str) -> str:
    """把 QQ 内置表情标签转换成可读文本。"""
    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        try:
            decoded = base64.b64decode(match.group(1), validate=False).decode("utf-8")
            data = json.loads(decoded)
        except Exception:
            return match.group(0)

        face_name = data.get("text") if isinstance(data, dict) else None
        if isinstance(face_name, str) and face_name.strip():
            return f"【表情: {face_name.strip()}】"
        return "【表情】"

    return re.sub(r'<faceType=\d+,faceId="[^"]*",ext="([^"]*)">', replace, text)


def _normalize_attachment_url(raw_url: Any) -> str | None:
    if not isinstance(raw_url, str):
        return None
    url = raw_url.strip()
    if not url:
        return None
    if url.startswith("//"):
        url = f"https:{url}"
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    return url


def _guess_attachment_media_type(attachment: dict[str, Any]) -> str | None:
    content_type = attachment.get("content_type")
    if isinstance(content_type, str) and content_type.lower().startswith("image/"):
        return content_type.split(";", 1)[0].lower()

    filename = attachment.get("filename")
    if isinstance(filename, str):
        guessed, _ = mimetypes.guess_type(filename)
        if guessed and guessed.startswith("image/"):
            return guessed

        ext = Path(filename).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return "image/jpeg" if ext in {".jpg", ".jpeg"} else f"image/{ext[1:]}"

    return None


def _extract_inbound_images(
    attachments: list[dict[str, Any]],
    *,
    max_images: int,
) -> list[InboundImage]:
    images: list[InboundImage] = []
    for attachment in attachments:
        if len(images) >= max_images:
            break
        if not isinstance(attachment, dict):
            continue

        media_type = _guess_attachment_media_type(attachment)
        url = _normalize_attachment_url(attachment.get("url"))
        if not media_type or not url:
            continue

        filename = attachment.get("filename")
        images.append(
            InboundImage(
                url=url,
                media_type=media_type,
                filename=filename if isinstance(filename, str) else "",
            )
        )
    return images


async def _download_image_data_url(
    image: InboundImage,
    *,
    timeout: float,
    max_bytes: int,
) -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Afterglow-QQBot/1.0"},
        ) as client:
            async with client.stream("GET", image.url) as resp:
                if resp.status_code >= 400:
                    logger.warning(
                        "下载 QQ 图片失败 status=%s url=%s",
                        resp.status_code,
                        image.url,
                    )
                    return None

                content_length = resp.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > max_bytes:
                            logger.warning(
                                "跳过过大的 QQ 图片 size=%s max=%s url=%s",
                                content_length,
                                max_bytes,
                                image.url,
                            )
                            return None
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning(
                            "跳过过大的 QQ 图片 size>%s url=%s",
                            max_bytes,
                            image.url,
                        )
                        return None
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        logger.warning("下载 QQ 图片失败：%s url=%s", exc, image.url)
        return None

    data = b"".join(chunks)
    if not data:
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{image.media_type};base64,{encoded}"


async def _build_afterglow_images(
    images: list[InboundImage],
    *,
    download_timeout: float,
    max_bytes: int,
    fallback_to_url: bool,
) -> list[AfterglowImage]:
    afterglow_images: list[AfterglowImage] = []
    for image in images:
        data_url = await _download_image_data_url(
            image,
            timeout=download_timeout,
            max_bytes=max_bytes,
        )
        if data_url:
            afterglow_images.append(AfterglowImage(url=data_url))
        elif fallback_to_url:
            afterglow_images.append(AfterglowImage(url=image.url))
    return afterglow_images


def _split_assistant_message(content: str) -> list[str]:
    """Split assistant content into QQ/WeChat-style bubbles.

    Afterglow uses two or more consecutive newlines as message separators.
    Single newlines remain inside the same message bubble.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[str] = []
    for segment in re.split(r"\n{2,}", normalized):
        segment = segment.strip("\n")
        if segment.strip():
            segments.append(segment)
    return segments


async def _send_assistant_reply(
    api: QQBotAPI,
    *,
    openid: str,
    msg_id: str,
    content: str,
    split_messages: bool,
    segment_delay_min: float,
    segment_delay_max: float,
) -> None:
    if split_messages:
        segments = _split_assistant_message(content)
    else:
        segments = [content]

    if not segments:
        return

    for index, segment in enumerate(segments):
        if index > 0:
            await asyncio.sleep(random.uniform(segment_delay_min, segment_delay_max))
        await api.send_c2c_text(openid, segment, msg_id=msg_id)


async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Desktop owns configuration; never read another installation's .env.

    app_id = _require_env("QQ_BOT_APP_ID")
    client_secret = _require_env("QQ_BOT_CLIENT_SECRET")
    afterglow_base = _require_env("AFTERGLOW_BASE_URL")
    afterglow_key = _require_env("AFTERGLOW_API_KEY")
    afterglow_model = os.environ.get("AFTERGLOW_MODEL", "afterglow")
    afterglow_timeout = float(os.environ.get("AFTERGLOW_TIMEOUT", "120"))
    image_max_count = max(0, int(os.environ.get("AFTERGLOW_IMAGE_MAX_COUNT", "4")))
    image_download_timeout = float(
        os.environ.get("AFTERGLOW_IMAGE_DOWNLOAD_TIMEOUT", "20")
    )
    image_max_bytes = max(
        1,
        int(os.environ.get("AFTERGLOW_IMAGE_MAX_BYTES", str(8 * 1024 * 1024))),
    )
    image_fallback_to_url = _parse_bool(
        os.environ.get("AFTERGLOW_IMAGE_FALLBACK_TO_URL", "true"),
        default=True,
    )
    silence_sentinel = os.environ.get("AFTERGLOW_SILENCE_SENTINEL", "[silent]")
    history_max_turns = int(os.environ.get("AFTERGLOW_HISTORY_MAX_TURNS", "6"))
    history_db_raw = os.environ.get(
        "AFTERGLOW_HISTORY_DB_PATH",
        "data/chat_history.sqlite3",
    )
    history_db_path = _resolve_project_path(history_db_raw)
    history_compression = HistoryCompressionConfig(
        api_key=os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_API_KEY", "").strip(),
        model=os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_MODEL", "").strip(),
        base_url=os.environ.get(
            "AFTERGLOW_HISTORY_COMPRESSION_BASE_URL",
            "https://api.openai.com",
        ).strip(),
        trigger_turns=int(
            os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_TRIGGER_TURNS", "0")
        ),
        trigger_tokens=int(
            os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_TRIGGER_TOKENS", "0")
        ),
        keep_turns=int(
            os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_KEEP_TURNS", "3")
        ),
        timeout=float(os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_TIMEOUT", "60")),
        max_output_tokens=int(
            os.environ.get("AFTERGLOW_HISTORY_COMPRESSION_MAX_OUTPUT_TOKENS", "800")
        ),
    )
    error_reply = os.environ.get("AFTERGLOW_ERROR_REPLY", "").strip()
    binding_store = BindingStore(Path(os.environ["AFTERGLOW_BINDINGS_PATH"]))
    split_messages = _parse_bool(
        os.environ.get("AFTERGLOW_SPLIT_ASSISTANT_MESSAGES", "true"),
        default=True,
    )
    segment_delay_min = float(
        os.environ.get("AFTERGLOW_MESSAGE_SEGMENT_MIN_DELAY", "1.5")
    )
    segment_delay_max = float(
        os.environ.get("AFTERGLOW_MESSAGE_SEGMENT_MAX_DELAY", "3.0")
    )
    if segment_delay_min < 0:
        segment_delay_min = 0.0
    if segment_delay_max < segment_delay_min:
        segment_delay_max = segment_delay_min
    schedule_tasks_enabled = _parse_bool(
        os.environ.get("AFTERGLOW_SCHEDULE_TASKS_ENABLED", "true"),
        default=True,
    )
    schedule_db_path = _resolve_project_path(
        os.environ.get("AFTERGLOW_SCHEDULE_DB_PATH", "data/schedule_tasks.sqlite3")
    )
    schedule_poll_interval = float(
        os.environ.get("AFTERGLOW_SCHEDULE_POLL_INTERVAL", "1.0")
    )

    logger.info("Desktop contact authorization is enabled")

    api = QQBotAPI(app_id=app_id, client_secret=client_secret)
    gw = QQBotGateway(api)
    afterglow = AfterglowClient(
        base_url=afterglow_base,
        api_key=afterglow_key,
        model=afterglow_model,
        timeout=afterglow_timeout,
        silence_sentinel=silence_sentinel,
        history_max_turns=history_max_turns,
        history_db_path=history_db_path,
        history_compression=history_compression,
    )
    schedule_runner: QQScheduleTaskRunner | None = None
    if schedule_tasks_enabled:
        schedule_runner = QQScheduleTaskRunner(
            api,
            schedule_db_path,
            poll_interval=schedule_poll_interval,
        )
        await schedule_runner.start()

    @gw.on_c2c_message
    async def on_c2c(msg: C2CMessage) -> None:
        if not msg.user_openid:
            return
        if not binding_store.authorized(msg.user_openid):
            code = binding_store.request(msg.user_openid)
            if code:
                text = (f"Afterglow binding code: {code}. Ask the desktop owner to confirm this contact."
                        if os.environ.get("AFTERGLOW_LANGUAGE") == "en-US"
                        else f"Afterglow 绑定码：{code}。请让桌面应用所有者确认绑定，10 分钟内有效。")
                await api.send_c2c_text(msg.user_openid, text, msg_id=msg.message_id)
            return
        text = _parse_face_tags(msg.content).strip()
        inbound_images = _extract_inbound_images(
            msg.attachments,
            max_images=image_max_count,
        )
        if not text and not inbound_images:
            return  # QQ 空消息直接忽略，避免无意义请求
        logger.info(
            "收到私聊 openid=%s len=%d images=%d",
            msg.user_openid,
            len(text),
            len(inbound_images),
        )

        conversation_id = _build_conversation_id(msg.user_openid)

        try:
            afterglow_images = await _build_afterglow_images(
                inbound_images,
                download_timeout=image_download_timeout,
                max_bytes=image_max_bytes,
                fallback_to_url=image_fallback_to_url,
            )
            if inbound_images and not afterglow_images:
                logger.warning("收到图片但未能构造可发送给 Afterglow 的图片输入")
                if not text:
                    text = "用户发送了图片/表情包，但图片下载失败，无法查看图片内容。"
            reply = await afterglow.chat(
                conversation_id=conversation_id,
                user_text=text,
                images=afterglow_images,
                caller_id=conversation_id,
                client_message_id=_build_client_message_id(
                    msg.user_openid,
                    msg.message_id,
                    msg.timestamp,
                ),
            )
        except AfterglowError as exc:
            logger.error("Afterglow 调用失败：%s", exc)
            if error_reply:
                # 仅在用户配置了兜底回复时才回，避免和"沉默策略"语义冲突
                try:
                    await api.send_c2c_text(
                        msg.user_openid, error_reply, msg_id=msg.message_id
                    )
                except Exception:
                    logger.exception("发送兜底回复失败")
            return

        if reply is None:
            # Afterglow 决策沉默，不发任何消息
            return

        if schedule_runner is not None:
            await schedule_runner.add_tasks(msg.user_openid, reply.schedule_tasks)
        elif reply.schedule_tasks:
            logger.info(
                "收到 %d 条 schedule_tasks，但 AFTERGLOW_SCHEDULE_TASKS_ENABLED=false，已忽略",
                len(reply.schedule_tasks),
            )

        if not reply.content:
            return

        try:
            if os.environ.get("AFTERGLOW_HUMAN_DELAY") == "true" and reply.reply_delay_seconds > 0:
                await asyncio.sleep(reply.reply_delay_seconds)
            await _send_assistant_reply(
                api,
                openid=msg.user_openid,
                msg_id=msg.message_id,
                content=reply.content,
                split_messages=split_messages,
                segment_delay_min=segment_delay_min,
                segment_delay_max=segment_delay_max,
            )
        except Exception:
            logger.exception("发送 C2C 文本失败 openid=%s", msg.user_openid)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, gw.stop)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler，由 KeyboardInterrupt 兜底
            pass

    try:
        await gw.run()
    finally:
        if schedule_runner is not None:
            await schedule_runner.stop()
        await api.aclose()
        await afterglow.aclose()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
