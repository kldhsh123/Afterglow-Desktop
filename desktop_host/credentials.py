"""Windows DPAPI credentials for the desktop and its built-in extensions."""
import base64
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import threading

try:
    from .i18n import tr
    from .storage import atomic_json, read_json
except ImportError:
    from i18n import tr
    from storage import atomic_json, read_json

BASES = {"deepseek", "xunfei", "zhipu"}
_LOCK = threading.RLock()
MODEL_ROLES = {"deepseek", "embedding", "rerank", "zhipu", "vision", "imageImportVision", "search"}


def model_scope(profile):
    channel = profile.get("channel", "custom")
    origin = profile.get("baseUrl", "").strip().rstrip("/") if channel in {"custom", "tavily", "searxng"} else channel
    return hashlib.sha256(json.dumps([channel, origin], ensure_ascii=False).encode()).hexdigest()


class SecretStore:
    def __init__(self, root: Path):
        self.path = root / "credentials.json"

    @staticmethod
    def crypt(data: bytes, decrypt=False) -> bytes:
        if sys.platform != "win32":
            raise ValueError(tr('host.credentials_use_windows_dpapi_configure_them_in_the'))
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        src, out = Blob(len(data), buffer), Blob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)):
            raise OSError(tr('host.windows_could_not_read_or_protect_this_credential'))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)

    def get(self, name: str, profile=None) -> str:
        values = read_json(self.path, {})
        if profile is not None and values.get("_model_bindings", {}).get(name) != model_scope(profile):
            return ""
        encoded = values.get(name) or (values.get("xunfei") if name == "embedding" else None)
        return self.crypt(base64.b64decode(encoded), True).decode() if encoded else ""

    def set(self, name: str, value: str, profile=None) -> None:
        if name not in {*BASES, *MODEL_ROLES, "local_api", "qq_app_id", "qq_secret", "weixin_token"}:
            raise ValueError(tr('host.unsupported_credential_type'))
        if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(c in value for c in "\r\n\0"):
            raise ValueError(tr('host.invalid_api_key'))
        with _LOCK:
            values = read_json(self.path, {})
            values[name] = base64.b64encode(self.crypt(value.strip().encode())).decode()
            bindings = values.setdefault("_model_bindings", {})
            if name in MODEL_ROLES:
                if profile is not None:
                    bindings[name] = model_scope(profile)
                else:
                    bindings.pop(name, None)
            atomic_json(self.path, values)

    def bind_existing_model_keys(self, profiles):
        """Migrate legacy role-only keys against saved settings, never a draft."""
        with _LOCK:
            values = read_json(self.path, {})
            bindings = values.setdefault("_model_bindings", {})
            changed = False
            for role, profile in profiles.items():
                if role in MODEL_ROLES and (values.get(role) or role == "embedding" and values.get("xunfei")) and role not in bindings:
                    bindings[role] = model_scope(profile)
                    changed = True
            if changed:
                atomic_json(self.path, values)

    def available(self) -> list[str]:
        return [name for name in read_json(self.path, {}) if not name.startswith("_")]

    def delete(self, name: str):
        with _LOCK:
            values = read_json(self.path, {})
            values.pop(name, None)
            values.get("_model_bindings", {}).pop(name, None)
            atomic_json(self.path, values)
