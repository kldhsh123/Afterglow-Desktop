"""Afterglow Weixin Bot main entry.

Connects OpenClaw Weixin long-poll messages to Afterglow `/v1/chat/completions`
and sends Afterglow replies back to Weixin.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import random
import re
import signal
import sys
from bindings import BindingStore
from extension_events import emit

from afterglow_client import (
    AfterglowClient,
    AfterglowError,
    AfterglowImage,
    HistoryCompressionConfig,
)
from weixinbot.api import (
    DEFAULT_BASE_URL,
    DEFAULT_BOT_AGENT,
    DEFAULT_BOT_TYPE,
    DEFAULT_CDN_BASE_URL,
    DEFAULT_CHANNEL_VERSION,
    DEFAULT_ILINK_APP_ID,
    WeixinBotAPI,
)
from weixinbot.gateway import WeixinContextTokenStore, WeixinGateway, WeixinMessage
from weixinbot.login import login_with_qr
from weixinbot.media import (
    download_remote_media_to_temp,
    extract_afterglow_image_data_urls,
    parse_media_directives,
    resolve_media_path,
    send_media_file,
)
from weixinbot.schedule_tasks import WeixinScheduleTaskRunner

logger = logging.getLogger("afterglow.weixinbot")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(f"缺少环境变量 {name}\n")
        sys.exit(1)
    return value


def _parse_bool(raw: str, *, default: bool) -> bool:
    raw = raw.strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _parse_command_set(raw: str, *, default: set[str]) -> set[str]:
    raw = raw.strip()
    if not raw:
        return default
    return {item.strip() for item in raw.split(",") if item.strip()}


def _resolve_project_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    return path


def _build_client_message_id(user_id: str, message_id: str, timestamp_ms: int) -> str:
    message_id = message_id.strip()
    if message_id:
        return f"weixin:{user_id}:{message_id}"
    return f"weixin:{user_id}:missing-message-id:{timestamp_ms or random.randint(0, 2**31 - 1)}"


def _split_assistant_message(content: str) -> list[str]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[str] = []
    for segment in re.split(r"\n{2,}", normalized):
        segment = segment.strip("\n")
        if segment.strip():
            segments.append(segment)
    return segments


def _summarize_item_types(raw: dict) -> str:
    item_list = raw.get("item_list")
    if not isinstance(item_list, list):
        return "none"
    types: list[str] = []
    for item in item_list:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        keys = ",".join(sorted(k for k in item.keys() if k.endswith("_item") or k == "ref_msg"))
        types.append(f"{item_type}:{keys or '-'}")
    return "|".join(types) or "none"


def _is_clear_context_command(text: str, commands: set[str]) -> bool:
    normalized = text.strip()
    return bool(normalized and normalized in commands)


def _configure_library_logging() -> None:
    httpx_level = os.environ.get("HTTPX_LOG_LEVEL", "WARNING").upper()
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(httpx_level)


async def _send_assistant_reply(
    api: WeixinBotAPI,
    *,
    user_id: str,
    context_token: str,
    run_id: str,
    content: str,
    cdn_base_url: str,
    outbound_temp_dir: Path,
    split_messages: bool,
    segment_delay_min: float,
    segment_delay_max: float,
) -> None:
    text_without_media, media_urls = parse_media_directives(content)
    segments = (
        _split_assistant_message(text_without_media)
        if split_messages
        else ([text_without_media] if text_without_media else [])
    )
    for index, segment in enumerate(segments):
        if index > 0:
            await asyncio.sleep(random.uniform(segment_delay_min, segment_delay_max))
        await api.send_text(
            user_id,
            segment,
            context_token=context_token,
            run_id=run_id,
        )

    for media_index, media_url in enumerate(media_urls):
        if segments or media_index > 0:
            await asyncio.sleep(random.uniform(segment_delay_min, segment_delay_max))
        resolved, is_remote = resolve_media_path(media_url, temp_dir=outbound_temp_dir)
        cleanup_path: Path | None = None
        if is_remote:
            cleanup_path = await download_remote_media_to_temp(resolved, outbound_temp_dir)
            resolved = str(cleanup_path)
        try:
            await send_media_file(
                api,
                file_path=resolved,
                to_user_id=user_id,
                context_token=context_token,
                run_id=run_id,
                cdn_base_url=cdn_base_url,
            )
        finally:
            if cleanup_path is not None:
                try:
                    cleanup_path.unlink()
                except OSError:
                    pass


async def _run_login(args: argparse.Namespace) -> int:
    result = await login_with_qr(
        timeout=args.login_timeout,
        bot_type=args.bot_type,
        api_base_url=args.login_base_url,
    )
    if result is None:
        return 1

    emit("credentials", token=result.token, accountId=result.account_id,
         baseUrl=result.base_url, ownerUid=result.user_id)
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Afterglow Weixin Bot adapter")
    parser.add_argument("--login", action="store_true", help="扫码登录并输出微信 bot 凭据")
    parser.add_argument("--login-timeout", type=float, default=480.0, help="扫码登录等待秒数")
    parser.add_argument("--login-base-url", default=DEFAULT_BASE_URL, help="扫码登录 API base URL")
    parser.add_argument("--bot-type", default=DEFAULT_BOT_TYPE, help="OpenClaw Weixin bot_type")
    return parser


async def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Desktop configuration is supplied only over the private parent pipe.

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _configure_library_logging()

    if args.login:
        return await _run_login(args)

    token = _require_env("WEIXIN_BOT_TOKEN")
    account_id = os.environ.get("WEIXIN_BOT_ACCOUNT_ID", "default").strip() or "default"
    weixin_base = os.environ.get("WEIXIN_BOT_BASE_URL", DEFAULT_BASE_URL).strip()
    weixin_cdn_base = os.environ.get("WEIXIN_CDN_BASE_URL", DEFAULT_CDN_BASE_URL).strip()
    weixin_timeout = float(os.environ.get("WEIXIN_BOT_TIMEOUT", "15"))
    weixin_long_poll_timeout = float(os.environ.get("WEIXIN_BOT_LONG_POLL_TIMEOUT", "35"))
    weixin_channel_version = os.environ.get(
        "WEIXIN_CHANNEL_VERSION",
        DEFAULT_CHANNEL_VERSION,
    ).strip()
    weixin_ilink_app_id = os.environ.get(
        "WEIXIN_ILINK_APP_ID",
        DEFAULT_ILINK_APP_ID,
    ).strip()
    weixin_bot_agent = os.environ.get("WEIXIN_BOT_AGENT", DEFAULT_BOT_AGENT).strip()
    weixin_route_tag = os.environ.get("WEIXIN_ROUTE_TAG", "").strip()
    notify_lifecycle = _parse_bool(
        os.environ.get("WEIXIN_NOTIFY_LIFECYCLE", "true"),
        default=True,
    )

    afterglow_base = _require_env("AFTERGLOW_BASE_URL")
    afterglow_key = _require_env("AFTERGLOW_API_KEY")
    afterglow_model = os.environ.get("AFTERGLOW_MODEL", "afterglow")
    afterglow_timeout = float(os.environ.get("AFTERGLOW_TIMEOUT", "120"))
    image_max_count = max(0, int(os.environ.get("AFTERGLOW_IMAGE_MAX_COUNT", "4")))
    conversation_id = os.environ.get(
        "AFTERGLOW_CONVERSATION_ID",
        f"weixin:{account_id}:owner",
    ).strip()
    if not conversation_id:
        conversation_id = f"weixin:{account_id}:owner"
    silence_sentinel = os.environ.get("AFTERGLOW_SILENCE_SENTINEL", "[silent]")
    history_max_turns = int(os.environ.get("AFTERGLOW_HISTORY_MAX_TURNS", "6"))
    history_db_path = _resolve_project_path(
        os.environ.get("AFTERGLOW_HISTORY_DB_PATH", "data/chat_history.sqlite3")
    )
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
    clear_context_commands = _parse_command_set(
        os.environ.get("AFTERGLOW_CLEAR_CONTEXT_COMMANDS", ""),
        default={"/clear_context", "/reset_context", "清空上下文"},
    )
    clear_context_reply = os.environ.get(
        "AFTERGLOW_CLEAR_CONTEXT_REPLY",
        "已清空本地上下文。",
    ).strip()
    split_messages = _parse_bool(
        os.environ.get("AFTERGLOW_SPLIT_ASSISTANT_MESSAGES", "true"),
        default=True,
    )
    segment_delay_min = max(
        0.0,
        float(os.environ.get("AFTERGLOW_MESSAGE_SEGMENT_MIN_DELAY", "1.5")),
    )
    segment_delay_max = float(
        os.environ.get("AFTERGLOW_MESSAGE_SEGMENT_MAX_DELAY", "3.0")
    )
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
    sync_state_path = _resolve_project_path(
        os.environ.get(
            "WEIXIN_SYNC_STATE_PATH",
            f"data/{account_id}.sync.json",
        )
    )
    context_tokens_path = _resolve_project_path(
        os.environ.get(
            "WEIXIN_CONTEXT_TOKENS_PATH",
            f"data/{account_id}.context-tokens.json",
        )
    )
    outbound_temp_dir = _resolve_project_path(
        os.environ.get("WEIXIN_OUTBOUND_TEMP_DIR", "data/outbound-media")
    )

    logger.info("微信适配器使用单所有者会话 conversation_id=%s", conversation_id)

    api = WeixinBotAPI(
        base_url=weixin_base,
        token=token,
        timeout=weixin_timeout,
        long_poll_timeout=weixin_long_poll_timeout,
        channel_version=weixin_channel_version,
        ilink_app_id=weixin_ilink_app_id,
        bot_agent=weixin_bot_agent,
        route_tag=weixin_route_tag,
    )
    context_tokens = WeixinContextTokenStore(context_tokens_path)
    binding_store = BindingStore(Path(os.environ["AFTERGLOW_BINDINGS_PATH"]))
    gateway = WeixinGateway(
        api,
        sync_state_path=sync_state_path,
        context_token_store=context_tokens,
        notify_lifecycle=notify_lifecycle,
    )
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
    schedule_runner: WeixinScheduleTaskRunner | None = None
    if schedule_tasks_enabled:
        schedule_runner = WeixinScheduleTaskRunner(
            api,
            schedule_db_path,
            context_token_store=context_tokens,
            poll_interval=schedule_poll_interval,
        )
        await schedule_runner.start()

    @gateway.on_message
    async def on_weixin_message(msg: WeixinMessage) -> None:
        # Each authorized account keeps separate live memory and short-term context.
        conversation_id = f"weixin:{account_id}:{msg.user_id}"
        if not binding_store.authorized(msg.user_id):
            code = binding_store.request(msg.user_id)
            if code:
                prompt = (f"Afterglow binding code: {code}. Ask the desktop owner to confirm this contact."
                          if os.environ.get("AFTERGLOW_LANGUAGE") == "en-US"
                          else f"Afterglow 绑定码：{code}。请让桌面应用所有者确认绑定，10 分钟内有效。")
                await api.send_text(msg.user_id, prompt, context_token=msg.context_token, run_id=msg.run_id)
            return
        text = msg.content.strip()
        if _is_clear_context_command(text, clear_context_commands):
            afterglow.reset_history(conversation_id)
            logger.info(
                "已按命令清空本地上下文 conversation_id=%s user_id=%s",
                conversation_id,
                msg.user_id,
            )
            if clear_context_reply:
                try:
                    await api.send_text(
                        msg.user_id,
                        clear_context_reply,
                        context_token=msg.context_token or context_tokens.get(msg.user_id),
                        run_id=msg.run_id,
                    )
                except Exception:
                    logger.exception("发送清空上下文确认失败")
            return

        logger.info(
            "微信消息结构 user_id=%s item_types=%s gateway_images=%d",
            msg.user_id,
            _summarize_item_types(msg.raw),
            len(msg.images),
        )
        try:
            image_urls = await extract_afterglow_image_data_urls(
                msg.raw.get("item_list") if isinstance(msg.raw.get("item_list"), list) else None,
                cdn_base_url=weixin_cdn_base,
                max_images=image_max_count,
            )
        except Exception:
            logger.exception("微信图片下载/解密失败 user_id=%s", msg.user_id)
            image_urls = []
            if not text:
                text = "用户发送了图片/表情包，但图片下载或解密失败，无法查看图片内容。"
        if not image_urls and msg.images and image_max_count > 0:
            image_urls = [image.url for image in msg.images[:image_max_count] if image.url]
        afterglow_images = [AfterglowImage(url=url) for url in image_urls]
        if not text and not afterglow_images:
            return
        logger.info(
            "收到微信私聊 user_id=%s len=%d images=%d",
            msg.user_id,
            len(text),
            len(afterglow_images),
        )

        try:
            reply = await afterglow.chat(
                conversation_id=conversation_id,
                user_text=text,
                images=afterglow_images,
                caller_id=conversation_id,
                client_message_id=_build_client_message_id(
                    msg.user_id,
                    msg.message_id,
                    msg.timestamp_ms,
                ),
            )
        except AfterglowError as exc:
            logger.error("Afterglow 调用失败：%s", exc)
            if error_reply:
                try:
                    await api.send_text(
                        msg.user_id,
                        error_reply,
                        context_token=msg.context_token or context_tokens.get(msg.user_id),
                        run_id=msg.run_id,
                    )
                except Exception:
                    logger.exception("发送兜底回复失败")
            return

        if reply is None:
            return

        if reply.schedule_tasks:
            logger.info("Afterglow 返回 schedule_tasks=%d", len(reply.schedule_tasks))
        if schedule_runner is not None:
            await schedule_runner.add_tasks(msg.user_id, reply.schedule_tasks)
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
                user_id=msg.user_id,
                context_token=msg.context_token or context_tokens.get(msg.user_id),
                run_id=msg.run_id,
                content=reply.content,
                cdn_base_url=weixin_cdn_base,
                outbound_temp_dir=outbound_temp_dir,
                split_messages=split_messages,
                segment_delay_min=segment_delay_min,
                segment_delay_max=segment_delay_max,
            )
        except Exception:
            logger.exception("发送微信文本失败 user_id=%s", msg.user_id)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, gateway.stop)
        except NotImplementedError:
            pass

    try:
        await gateway.run()
    finally:
        if schedule_runner is not None:
            await schedule_runner.stop()
        await afterglow.aclose()
        await api.aclose()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
