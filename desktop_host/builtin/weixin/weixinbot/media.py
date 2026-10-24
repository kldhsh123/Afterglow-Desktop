"""Weixin CDN media download/upload helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .api import (
    DEFAULT_CDN_BASE_URL,
    MESSAGE_ITEM_FILE,
    MESSAGE_ITEM_IMAGE,
    MESSAGE_ITEM_TEXT,
    MESSAGE_ITEM_VIDEO,
    UPLOAD_MEDIA_FILE,
    UPLOAD_MEDIA_IMAGE,
    UPLOAD_MEDIA_VIDEO,
    WeixinBotAPI,
)

MAX_INBOUND_MEDIA_BYTES = 100 * 1024 * 1024
MAX_REMOTE_MEDIA_BYTES = 100 * 1024 * 1024

EXTENSION_TO_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@dataclass(frozen=True)
class UploadedFileInfo:
    filekey: str
    download_encrypted_query_param: str
    aeskey_hex: str
    file_size: int
    file_size_ciphertext: int


def aes_ecb_padded_size(size: int) -> int:
    return ((size + 16) // 16) * 16


def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def parse_aes_key(aes_key_base64: str) -> bytes:
    decoded = base64.b64decode(aes_key_base64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and re.fullmatch(rb"[0-9a-fA-F]{32}", decoded):
        return bytes.fromhex(decoded.decode("ascii"))
    raise ValueError(f"aes_key must decode to 16 raw bytes or 32-char hex, got {len(decoded)} bytes")


def encode_aes_key_for_message(aeskey_hex: str) -> str:
    return base64.b64encode(aeskey_hex.encode("ascii")).decode("ascii")


def build_cdn_download_url(encrypted_query_param: str, cdn_base_url: str) -> str:
    return (
        f"{cdn_base_url.rstrip('/')}/download"
        f"?encrypted_query_param={quote(encrypted_query_param)}"
    )


def build_cdn_upload_url(*, upload_param: str, filekey: str, cdn_base_url: str) -> str:
    return (
        f"{cdn_base_url.rstrip('/')}/upload"
        f"?encrypted_query_param={quote(upload_param)}&filekey={quote(filekey)}"
    )


def get_mime_from_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return EXTENSION_TO_MIME.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _guess_image_mime(buf: bytes) -> str:
    if buf.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if buf.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if buf.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if buf.startswith(b"RIFF") and buf[8:12] == b"WEBP":
        return "image/webp"
    if buf.startswith(b"BM"):
        return "image/bmp"
    return "image/jpeg"


async def _fetch_bytes(url: str, *, max_bytes: int = MAX_INBOUND_MEDIA_BYTES) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"CDN download {resp.status_code}: {await resp.aread()!r}")
            content_length = resp.headers.get("content-length")
            if content_length is not None and int(content_length) > max_bytes:
                raise RuntimeError(f"media too large: {content_length} > {max_bytes}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"media too large: > {max_bytes}")
                chunks.append(chunk)
            return b"".join(chunks)


async def download_and_decrypt_media(
    media: dict[str, Any],
    *,
    aes_key_base64: str | None,
    cdn_base_url: str = DEFAULT_CDN_BASE_URL,
) -> bytes:
    full_url = media.get("full_url")
    encrypted_query_param = str(media.get("encrypt_query_param") or "")
    if isinstance(full_url, str) and full_url:
        url = full_url
    elif encrypted_query_param:
        url = build_cdn_download_url(encrypted_query_param, cdn_base_url)
    else:
        raise ValueError("media needs full_url or encrypt_query_param")

    data = await _fetch_bytes(url)
    if not aes_key_base64:
        return data
    return decrypt_aes_ecb(data, parse_aes_key(aes_key_base64))


async def extract_afterglow_image_data_urls(
    item_list: list[Any] | None,
    *,
    cdn_base_url: str = DEFAULT_CDN_BASE_URL,
    max_images: int,
) -> list[str]:
    if max_images <= 0 or not item_list:
        return []

    images: list[str] = []
    for image_item in _iter_image_items(item_list):
        if len(images) >= max_images:
            break
        try:
            image_url = await _image_item_to_afterglow_url(
                image_item,
                cdn_base_url=cdn_base_url,
            )
        except Exception:
            continue
        if image_url:
            images.append(image_url)
    return images


def _iter_image_items(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        image_item = node.get("image_item")
        if isinstance(image_item, dict) and id(image_item) not in seen:
            seen.add(id(image_item))
            found.append(image_item)

        if node.get("type") == MESSAGE_ITEM_IMAGE and isinstance(image_item, dict):
            return

        for child in node.values():
            if isinstance(child, (dict, list)):
                walk(child)

    walk(value)
    return found


async def _image_item_to_afterglow_url(
    image_item: dict[str, Any],
    *,
    cdn_base_url: str,
) -> str | None:
    direct_url = image_item.get("url")
    if isinstance(direct_url, str) and direct_url.startswith(("http://", "https://")):
        return direct_url

    aes_key_base64 = None
    aeskey_hex = image_item.get("aeskey")
    if isinstance(aeskey_hex, str) and aeskey_hex:
        aes_key_base64 = base64.b64encode(bytes.fromhex(aeskey_hex)).decode("ascii")

    media_candidates = [image_item.get("media"), image_item.get("thumb_media")]
    for media in media_candidates:
        if not isinstance(media, dict):
            continue
        media_aes_key = aes_key_base64
        if media_aes_key is None and isinstance(media.get("aes_key"), str):
            media_aes_key = media["aes_key"]
        if not (media.get("full_url") or media.get("encrypt_query_param")):
            continue

        data = await download_and_decrypt_media(
            media,
            aes_key_base64=media_aes_key,
            cdn_base_url=cdn_base_url,
        )
        mime = _guess_image_mime(data)
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    return None


async def upload_buffer_to_cdn(
    *,
    buf: bytes,
    upload_full_url: str | None,
    upload_param: str | None,
    filekey: str,
    cdn_base_url: str,
    aeskey: bytes,
) -> str:
    ciphertext = encrypt_aes_ecb(buf, aeskey)
    if upload_full_url and upload_full_url.strip():
        url = upload_full_url.strip()
    elif upload_param:
        url = build_cdn_upload_url(
            upload_param=upload_param,
            filekey=filekey,
            cdn_base_url=cdn_base_url,
        )
    else:
        raise RuntimeError("CDN upload URL missing")

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(1, 4):
            try:
                resp = await client.post(
                    url,
                    content=ciphertext,
                    headers={"Content-Type": "application/octet-stream"},
                )
                if 400 <= resp.status_code < 500:
                    raise RuntimeError(f"CDN upload client error {resp.status_code}: {resp.text[:300]}")
                if resp.status_code != 200:
                    raise RuntimeError(f"CDN upload server error {resp.status_code}")
                download_param = resp.headers.get("x-encrypted-param")
                if not download_param:
                    raise RuntimeError("CDN upload response missing x-encrypted-param")
                return download_param
            except Exception as exc:
                last_error = exc
                if "client error" in str(exc) or attempt >= 3:
                    break
    raise last_error or RuntimeError("CDN upload failed")


async def upload_file_to_weixin(
    api: WeixinBotAPI,
    *,
    file_path: str | os.PathLike[str],
    to_user_id: str,
    cdn_base_url: str,
    media_type: int,
) -> UploadedFileInfo:
    path = Path(file_path)
    plaintext = path.read_bytes()
    filekey = os.urandom(16).hex()
    aeskey = os.urandom(16)
    upload_info = await api.get_upload_url(
        filekey=filekey,
        media_type=media_type,
        to_user_id=to_user_id,
        rawsize=len(plaintext),
        rawfilemd5=hashlib.md5(plaintext).hexdigest(),
        filesize=aes_ecb_padded_size(len(plaintext)),
        aeskey=aeskey.hex(),
        no_need_thumb=True,
    )
    download_param = await upload_buffer_to_cdn(
        buf=plaintext,
        upload_full_url=upload_info.get("upload_full_url"),
        upload_param=upload_info.get("upload_param"),
        filekey=filekey,
        cdn_base_url=cdn_base_url,
        aeskey=aeskey,
    )
    return UploadedFileInfo(
        filekey=filekey,
        download_encrypted_query_param=download_param,
        aeskey_hex=aeskey.hex(),
        file_size=len(plaintext),
        file_size_ciphertext=aes_ecb_padded_size(len(plaintext)),
    )


async def download_remote_media_to_temp(url: str, dest_dir: str | os.PathLike[str]) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in EXTENSION_TO_MIME:
        suffix = ".bin"

    data = await _fetch_bytes(url, max_bytes=MAX_REMOTE_MEDIA_BYTES)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="weixin-remote-", suffix=suffix, dir=dest)
    os.close(handle)
    path = Path(name)
    path.write_bytes(data)
    return path


def resolve_media_path(media_url: str, *, temp_dir: str | os.PathLike[str]) -> tuple[str, bool]:
    if media_url.startswith("file://"):
        return urlparse(media_url).path, False
    if media_url.startswith(("http://", "https://")):
        return media_url, True
    return str(Path(media_url).expanduser().resolve()), False


def parse_media_directives(content: str) -> tuple[str, list[str]]:
    text_lines: list[str] = []
    media_urls: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("MEDIA:"):
            media = stripped.removeprefix("MEDIA:").strip()
            if media:
                media_urls.append(media)
        else:
            text_lines.append(line)
    return "\n".join(text_lines).strip(), media_urls


async def send_media_file(
    api: WeixinBotAPI,
    *,
    file_path: str | os.PathLike[str],
    to_user_id: str,
    text: str = "",
    context_token: str = "",
    run_id: str = "",
    cdn_base_url: str = DEFAULT_CDN_BASE_URL,
) -> str:
    path = Path(file_path)
    mime = get_mime_from_filename(path.name)
    if mime.startswith("video/"):
        uploaded = await upload_file_to_weixin(
            api,
            file_path=path,
            to_user_id=to_user_id,
            cdn_base_url=cdn_base_url,
            media_type=UPLOAD_MEDIA_VIDEO,
        )
        item = {
            "type": MESSAGE_ITEM_VIDEO,
            "video_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_encrypted_query_param,
                    "aes_key": encode_aes_key_for_message(uploaded.aeskey_hex),
                    "encrypt_type": 1,
                },
                "video_size": uploaded.file_size_ciphertext,
            },
        }
    elif mime.startswith("image/"):
        uploaded = await upload_file_to_weixin(
            api,
            file_path=path,
            to_user_id=to_user_id,
            cdn_base_url=cdn_base_url,
            media_type=UPLOAD_MEDIA_IMAGE,
        )
        item = {
            "type": MESSAGE_ITEM_IMAGE,
            "image_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_encrypted_query_param,
                    "aes_key": encode_aes_key_for_message(uploaded.aeskey_hex),
                    "encrypt_type": 1,
                },
                "mid_size": uploaded.file_size_ciphertext,
            },
        }
    else:
        uploaded = await upload_file_to_weixin(
            api,
            file_path=path,
            to_user_id=to_user_id,
            cdn_base_url=cdn_base_url,
            media_type=UPLOAD_MEDIA_FILE,
        )
        item = {
            "type": MESSAGE_ITEM_FILE,
            "file_item": {
                "media": {
                    "encrypt_query_param": uploaded.download_encrypted_query_param,
                    "aes_key": encode_aes_key_for_message(uploaded.aeskey_hex),
                    "encrypt_type": 1,
                },
                "file_name": path.name,
                "len": str(uploaded.file_size),
            },
        }

    last_id = ""
    if text:
        last_id = await api.send_message_items(
            to_user_id,
            [{"type": MESSAGE_ITEM_TEXT, "text_item": {"text": text}}],
            context_token=context_token,
            run_id=run_id,
        )
    last_id = await api.send_message_items(
        to_user_id,
        [item],
        context_token=context_token,
        run_id=run_id,
    )
    return last_id
