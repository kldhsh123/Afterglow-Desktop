"""OpenClaw Weixin HTTP API client.

This mirrors the JSON API used by `openclaw-weixin-main`:
- QR login uses `ilink/bot/get_bot_qrcode` and `ilink/bot/get_qrcode_status`
- inbound messages use long-poll `ilink/bot/getupdates`
- outbound text uses `ilink/bot/sendmessage`
"""

from __future__ import annotations

import base64
import os
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_BOT_TYPE = "3"
DEFAULT_CHANNEL_VERSION = "2.4.6"
DEFAULT_ILINK_APP_ID = "bot"
DEFAULT_BOT_AGENT = "Afterglow-WeixinBot/1.0"

MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2
MESSAGE_STATE_FINISH = 2
MESSAGE_ITEM_TEXT = 1
MESSAGE_ITEM_IMAGE = 2
MESSAGE_ITEM_VOICE = 3
MESSAGE_ITEM_FILE = 4
MESSAGE_ITEM_VIDEO = 5
UPLOAD_MEDIA_IMAGE = 1
UPLOAD_MEDIA_VIDEO = 2
UPLOAD_MEDIA_FILE = 3
UPLOAD_MEDIA_VOICE = 4


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


def _build_client_version(version: str) -> int:
    parts: list[int] = []
    for raw in version.split(".")[:3]:
        try:
            parts.append(int(raw))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


def _random_wechat_uin() -> str:
    raw = str(random.getrandbits(32)).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _generate_client_id() -> str:
    return f"afterglow-weixin:{int(time.time() * 1000)}-{os.urandom(4).hex()}"


@dataclass(frozen=True)
class WeixinLoginResult:
    account_id: str
    token: str
    base_url: str
    user_id: str = ""


class WeixinAPIError(RuntimeError):
    """Raised when the OpenClaw Weixin API returns an error or invalid JSON."""


class WeixinBotAPI:
    """Small async client for the OpenClaw Weixin API."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        token: str = "",
        timeout: float = 15.0,
        long_poll_timeout: float = 35.0,
        channel_version: str = DEFAULT_CHANNEL_VERSION,
        ilink_app_id: str = DEFAULT_ILINK_APP_ID,
        bot_agent: str = DEFAULT_BOT_AGENT,
        route_tag: str = "",
    ) -> None:
        self.base_url = base_url.strip().rstrip("/") or DEFAULT_BASE_URL
        self.token = token.strip()
        self.timeout = timeout
        self.long_poll_timeout = long_poll_timeout
        self.channel_version = channel_version.strip() or DEFAULT_CHANNEL_VERSION
        self.ilink_app_id = ilink_app_id.strip() or DEFAULT_ILINK_APP_ID
        self.bot_agent = bot_agent.strip() or DEFAULT_BOT_AGENT
        self.route_tag = route_tag.strip()
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _base_info(self) -> dict[str, Any]:
        return {
            "channel_version": self.channel_version,
            "bot_agent": self.bot_agent,
        }

    def _common_headers(self) -> dict[str, str]:
        headers = {
            "iLink-App-Id": self.ilink_app_id,
            "iLink-App-ClientVersion": str(_build_client_version(self.channel_version)),
        }
        if self.route_tag:
            headers["SKRouteTag"] = self.route_tag
        return headers

    def _headers(self, *, authorized: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": _random_wechat_uin(),
            **self._common_headers(),
        }
        if authorized and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _post(
        self,
        endpoint: str,
        *,
        body: dict[str, Any] | None = None,
        authorized: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        url = _ensure_trailing_slash(self.base_url) + endpoint.lstrip("/")
        payload = body or {}
        resp = await self._client.post(
            url,
            json=payload,
            headers=self._headers(authorized=authorized),
            timeout=timeout if timeout is not None else self.timeout,
        )
        if resp.status_code >= 400:
            raise WeixinAPIError(f"POST {endpoint} 返回 {resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise WeixinAPIError(f"POST {endpoint} 响应非 JSON: {resp.text[:200]}") from exc
        if not isinstance(data, dict):
            raise WeixinAPIError(f"POST {endpoint} 响应不是对象: {data!r}")
        return data

    async def _get(
        self,
        endpoint: str,
        *,
        authorized: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        url = _ensure_trailing_slash(self.base_url) + endpoint.lstrip("/")
        resp = await self._client.get(
            url,
            headers=self._headers(authorized=True) if authorized else self._common_headers(),
            timeout=timeout if timeout is not None else self.timeout,
        )
        if resp.status_code >= 400:
            raise WeixinAPIError(f"GET {endpoint} 返回 {resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise WeixinAPIError(f"GET {endpoint} 响应非 JSON: {resp.text[:200]}") from exc
        if not isinstance(data, dict):
            raise WeixinAPIError(f"GET {endpoint} 响应不是对象: {data!r}")
        return data

    async def fetch_login_qrcode(self, *, bot_type: str = DEFAULT_BOT_TYPE) -> dict[str, Any]:
        query = urlencode({"bot_type": bot_type})
        return await self._post(
            f"ilink/bot/get_bot_qrcode?{query}",
            body={"local_token_list": []},
            authorized=False,
        )

    async def poll_login_status(
        self,
        *,
        qrcode: str,
        verify_code: str = "",
        timeout: float = 35.0,
    ) -> dict[str, Any]:
        params = {"qrcode": qrcode}
        if verify_code:
            params["verify_code"] = verify_code
        return await self._get(
            f"ilink/bot/get_qrcode_status?{urlencode(params)}",
            authorized=False,
            timeout=timeout,
        )

    async def notify_start(self) -> dict[str, Any]:
        return await self._post(
            "ilink/bot/msg/notifystart",
            body={"base_info": self._base_info()},
        )

    async def notify_stop(self) -> dict[str, Any]:
        return await self._post(
            "ilink/bot/msg/notifystop",
            body={"base_info": self._base_info()},
        )

    async def get_updates(self, *, get_updates_buf: str = "") -> dict[str, Any]:
        try:
            return await self._post(
                "ilink/bot/getupdates",
                body={
                    "get_updates_buf": get_updates_buf,
                    "base_info": self._base_info(),
                },
                timeout=self.long_poll_timeout,
            )
        except httpx.TimeoutException:
            return {"ret": 0, "msgs": [], "get_updates_buf": get_updates_buf}

    async def send_text(
        self,
        to_user_id: str,
        text: str,
        *,
        context_token: str = "",
        run_id: str = "",
    ) -> str:
        client_id = _generate_client_id()
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": MESSAGE_TYPE_BOT,
                "message_state": MESSAGE_STATE_FINISH,
                "item_list": [
                    {"type": MESSAGE_ITEM_TEXT, "text_item": {"text": text}},
                ],
            },
            "base_info": self._base_info(),
        }
        if context_token:
            body["msg"]["context_token"] = context_token
        if run_id:
            body["msg"]["run_id"] = run_id

        data = await self._post("ilink/bot/sendmessage", body=body)
        ret = data.get("ret")
        if ret not in (None, 0):
            raise WeixinAPIError(f"sendmessage ret={ret} errmsg={data.get('errmsg')}")
        return client_id

    async def get_upload_url(
        self,
        *,
        filekey: str,
        media_type: int,
        to_user_id: str,
        rawsize: int,
        rawfilemd5: str,
        filesize: int,
        aeskey: str,
        no_need_thumb: bool = True,
    ) -> dict[str, Any]:
        return await self._post(
            "ilink/bot/getuploadurl",
            body={
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": rawsize,
                "rawfilemd5": rawfilemd5,
                "filesize": filesize,
                "no_need_thumb": no_need_thumb,
                "aeskey": aeskey,
                "base_info": self._base_info(),
            },
        )

    async def send_message_items(
        self,
        to_user_id: str,
        items: list[dict[str, Any]],
        *,
        context_token: str = "",
        run_id: str = "",
    ) -> str:
        client_id = _generate_client_id()
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": MESSAGE_TYPE_BOT,
                "message_state": MESSAGE_STATE_FINISH,
                "item_list": items,
            },
            "base_info": self._base_info(),
        }
        if context_token:
            body["msg"]["context_token"] = context_token
        if run_id:
            body["msg"]["run_id"] = run_id

        data = await self._post("ilink/bot/sendmessage", body=body)
        ret = data.get("ret")
        if ret not in (None, 0):
            raise WeixinAPIError(f"sendmessage ret={ret} errmsg={data.get('errmsg')}")
        return client_id

    async def get_config(self, *, ilink_user_id: str, context_token: str = "") -> dict[str, Any]:
        return await self._post(
            "ilink/bot/getconfig",
            body={
                "ilink_user_id": ilink_user_id,
                "context_token": context_token,
                "base_info": self._base_info(),
            },
        )

    async def send_typing(
        self,
        *,
        ilink_user_id: str,
        typing_ticket: str,
        status: int = 1,
    ) -> None:
        await self._post(
            "ilink/bot/sendtyping",
            body={
                "ilink_user_id": ilink_user_id,
                "typing_ticket": typing_ticket,
                "status": status,
                "base_info": self._base_info(),
            },
        )
