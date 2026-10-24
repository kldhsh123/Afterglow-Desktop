"""QR login helper for OpenClaw Weixin."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from extension_events import emit
from extensions import weixin_base_url

from .api import DEFAULT_BASE_URL, DEFAULT_BOT_TYPE, WeixinBotAPI, WeixinLoginResult

logger = logging.getLogger("weixinbot.login")


def _print_qrcode_url(url: str) -> None:
    emit("qr", content=url)


async def _read_stdin(prompt: str) -> str:
    emit("state", state="verify")
    return await asyncio.to_thread(input)


async def login_with_qr(
    *,
    timeout: float = 480.0,
    bot_type: str = DEFAULT_BOT_TYPE,
    api_base_url: str = DEFAULT_BASE_URL,
) -> WeixinLoginResult | None:
    """Run QR login and return bot credentials."""

    api = WeixinBotAPI(base_url=api_base_url, token="", timeout=35.0)
    try:
        qr_resp = await api.fetch_login_qrcode(bot_type=bot_type)
        qrcode = str(qr_resp.get("qrcode") or "")
        qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
        if not qrcode or not qrcode_url:
            raise RuntimeError(f"服务器未返回二维码：{qr_resp}")
        _print_qrcode_url(qrcode_url)

        deadline = time.monotonic() + max(timeout, 30.0)
        scanned_printed = False
        verify_code = ""
        poll_base_url = api_base_url

        while time.monotonic() < deadline:
            api.base_url = poll_base_url.rstrip("/")
            try:
                status_resp = await api.poll_login_status(
                    qrcode=qrcode,
                    verify_code=verify_code,
                    timeout=35.0,
                )
            except httpx.TimeoutException:
                status_resp = {"status": "wait"}

            status = status_resp.get("status")
            if status == "wait":
                print(".", end="", flush=True)
            elif status == "scaned":
                emit("state", state="scanned")
                if verify_code:
                    verify_code = ""
                if not scanned_printed:
                    print("\n已扫码，等待手机确认...")
                    scanned_printed = True
            elif status == "need_verifycode":
                verify_code = (
                    await _read_stdin("\n请输入手机微信显示的数字验证码：")
                ).strip()
                continue
            elif status == "verify_code_blocked":
                emit("state", state="error")
                print("\n验证码多次错误，请稍后重试。")
                return None
            elif status == "expired":
                emit("state", state="expired")
                print("\n二维码已过期，请重新运行登录。")
                return None
            elif status == "binded_redirect":
                emit("state", state="error")
                print("\n此 OpenClaw 已连接过微信，服务器未下发新凭据。")
                return None
            elif status == "scaned_but_redirect":
                redirect_host = status_resp.get("redirect_host")
                if redirect_host:
                    poll_base_url = weixin_base_url(f"https://{redirect_host}")
                    logger.info("扫码状态重定向到 %s", poll_base_url)
            elif status == "confirmed":
                account_id = str(status_resp.get("ilink_bot_id") or "")
                token = str(status_resp.get("bot_token") or "")
                base_url = weixin_base_url(str(status_resp.get("baseurl") or poll_base_url or DEFAULT_BASE_URL))
                user_id = str(status_resp.get("ilink_user_id") or "")
                if not account_id or not token:
                    raise RuntimeError(f"登录成功但缺少 account/token：{_redacted_status(status_resp)}")
                print("\n微信登录成功。")
                return WeixinLoginResult(
                    account_id=account_id,
                    token=token,
                    base_url=base_url,
                    user_id=user_id,
                )
            else:
                logger.debug("未知登录状态：%s", status_resp)

            await asyncio.sleep(1.0)

        emit("state", state="expired")
        return None
    finally:
        await api.aclose()


def _redacted_status(data: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(data)
    if redacted.get("bot_token"):
        redacted["bot_token"] = "***"
    return redacted
