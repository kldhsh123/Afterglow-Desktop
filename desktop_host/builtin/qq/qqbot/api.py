"""QQ Bot REST API 客户端（最小实现）。

仅封装 C2C 私聊场景必需的 4 个动作：
1. get_access_token   —— 获取并缓存 token（提前 5 分钟续期）
2. get_gateway_url    —— 拉取 WebSocket 网关地址
3. send_c2c_text      —— 发送文本消息
4. send_c2c_image     —— 上传本地图片 + 发送媒体消息
"""

from __future__ import annotations

import asyncio
import base64
import os
import random
import time
from enum import IntEnum
from pathlib import Path
from typing import Any

import httpx

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"


class MediaFileType(IntEnum):
    """富媒体类型，与 QQ 开放平台一致。"""

    IMAGE = 1
    VIDEO = 2
    VOICE = 3
    FILE = 4


def _next_msg_seq() -> int:
    """生成 0~65535 的消息序号。

    同一 msg_id 下 msg_seq 不可重复（平台会去重），
    使用 "时间戳低位 XOR 随机数" 的无状态算法避免碰撞。
    """
    return ((int(time.time() * 1000) % 100_000_000) ^ random.randint(0, 65535)) % 65536


class QQBotAPI:
    """单账号 REST 客户端，自带 token 缓存与并发安全。"""

    # 提前刷新阈值：到期前 5 分钟即视为过期
    REFRESH_AHEAD_SEC = 5 * 60

    def __init__(self, app_id: str, client_secret: str, *, timeout: float = 30.0) -> None:
        self.app_id = app_id.strip()
        self.client_secret = client_secret.strip()
        self._client = httpx.AsyncClient(timeout=timeout)
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ token

    async def get_access_token(self) -> str:
        """返回有效 token，过期时自动续期。"""
        now = time.time()
        if self._token and now < self._token_expires_at - self.REFRESH_AHEAD_SEC:
            return self._token

        # 并发安全：多协程同时发现过期时，只有第一个真正发请求
        async with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expires_at - self.REFRESH_AHEAD_SEC:
                return self._token

            resp = await self._client.post(
                TOKEN_URL,
                json={"appId": self.app_id, "clientSecret": self.client_secret},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token")
            if not token:
                raise RuntimeError(f"获取 access_token 失败：{data}")
            self._token = token
            self._token_expires_at = now + int(data.get("expires_in", 7200))
            return token

    # ------------------------------------------------------------------ request

    async def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        token = await self.get_access_token()
        url = f"{API_BASE}{path}"
        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }
        resp = await self._client.request(method, url, headers=headers, json=json)
        if resp.status_code >= 400:
            raise RuntimeError(f"API {method} {path} 失败 [{resp.status_code}]: {resp.text}")
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------ gateway

    async def get_gateway_url(self) -> str:
        data = await self._request("GET", "/gateway")
        return data["url"]

    # ------------------------------------------------------------------ 文本

    async def send_c2c_text(
        self,
        openid: str,
        content: str,
        *,
        msg_id: str | None = None,
    ) -> dict[str, Any]:
        """发送 C2C 文本消息。

        :param openid: 用户 openid（事件 author.user_openid）
        :param content: 文本内容
        :param msg_id: 被动回复时必填（即事件携带的消息 id），主动消息留空
        """
        body: dict[str, Any] = {
            "content": content,
            "msg_type": 0,
            "msg_seq": _next_msg_seq(),
        }
        if msg_id:
            body["msg_id"] = msg_id
        return await self._request("POST", f"/v2/users/{openid}/messages", json=body)

    # ------------------------------------------------------------------ 媒体

    async def upload_c2c_media(
        self,
        openid: str,
        file_type: MediaFileType,
        *,
        file_data_b64: str | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        """上传媒体素材，返回包含 file_info 的响应。

        QQ 开放平台要求"先上传 → 再发媒体消息"两步走。
        file_data_b64 与 url 至少传一个：
        - file_data_b64：标准 Base64 字符串（不带 data: 前缀）
        - url：公网可访问的资源直链
        """
        if not file_data_b64 and not url:
            raise ValueError("upload_c2c_media 需要 file_data_b64 或 url 至少一个")

        body: dict[str, Any] = {
            "file_type": int(file_type),
            "srv_send_msg": False,
        }
        if file_data_b64:
            body["file_data"] = file_data_b64
        if url:
            body["url"] = url
        return await self._request("POST", f"/v2/users/{openid}/files", json=body)

    async def send_c2c_media_message(
        self,
        openid: str,
        file_info: str,
        *,
        msg_id: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """以 msg_type=7 发送富媒体消息。file_info 来自 upload_c2c_media 的响应。"""
        body: dict[str, Any] = {
            "msg_type": 7,
            "media": {"file_info": file_info},
            "msg_seq": _next_msg_seq(),
        }
        if msg_id:
            body["msg_id"] = msg_id
        if content:
            body["content"] = content
        return await self._request("POST", f"/v2/users/{openid}/messages", json=body)

    # ------------------------------------------------------------------ 图片便捷方法

    async def send_c2c_image_file(
        self,
        openid: str,
        file_path: str | os.PathLike[str],
        *,
        msg_id: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """读本地图片 → Base64 → 上传 → 发媒体消息（一站式）。"""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"图片不存在：{path}")
        data_b64 = base64.b64encode(path.read_bytes()).decode("ascii")

        upload = await self.upload_c2c_media(
            openid, MediaFileType.IMAGE, file_data_b64=data_b64
        )
        return await self.send_c2c_media_message(
            openid, upload["file_info"], msg_id=msg_id, content=content
        )

    async def send_c2c_image_url(
        self,
        openid: str,
        image_url: str,
        *,
        msg_id: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """直接用公网 URL 走"平台拉取"上传路径（不下载到本地）。"""
        upload = await self.upload_c2c_media(
            openid, MediaFileType.IMAGE, url=image_url
        )
        return await self.send_c2c_media_message(
            openid, upload["file_info"], msg_id=msg_id, content=content
        )
