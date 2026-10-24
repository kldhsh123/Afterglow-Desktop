"""DPAPI-encrypted JSON for persisted WeChat context tokens and polling cursors."""
import base64
import json
from pathlib import Path

try:
    from .credentials import SecretStore
    from .storage import atomic_json, read_json
except ImportError:
    from credentials import SecretStore
    from storage import atomic_json, read_json


class ProtectedJsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def load_dict(self):
        envelope = read_json(self.path, {})
        if not envelope:
            return {}
        if not isinstance(envelope, dict):
            raise ValueError("Invalid protected state")
        if envelope.get("format") != "afterglow-dpapi-v1":
            # Migrate state left by earlier desktop previews; never write plaintext again.
            self.save_dict(envelope)
            return envelope
        raw = SecretStore.crypt(base64.b64decode(envelope["data"], validate=True), decrypt=True)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Invalid protected state")
        return result

    def save_dict(self, value):
        encrypted = SecretStore.crypt(json.dumps(value, ensure_ascii=False).encode())
        atomic_json(self.path, {"format": "afterglow-dpapi-v1", "data": base64.b64encode(encrypted).decode()})
