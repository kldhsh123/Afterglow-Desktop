"""Check both upstream version files without delaying startup or shutdown.

Core source updates use the original repository. Desktop executable updates
still require a published, SHA-256-verified release catalog.
"""
import json
import re
import threading
import time

try:
    from .downloads import fetch_metadata
    from .storage import atomic_json, read_json
    from .versioning import desktop_version
except ImportError:
    from downloads import fetch_metadata
    from storage import atomic_json, read_json
    from versioning import desktop_version


VERSION_FILES = {
    "core": "https://github.com/kldhsh123/Afterglow/raw/refs/heads/main/VERSION",
    "desktop": "https://github.com/kldhsh123/Afterglow-Desktop/raw/refs/heads/main/version.json",
}


def parse_version(data, component):
    if component == "core":
        value = data.decode("utf-8-sig").strip().removeprefix("v")
    else:
        value = desktop_version(json.loads(data.decode("utf-8-sig")))
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-internal\.\d+)?", value):
        raise ValueError("Invalid repository version")
    return value


class RepositoryChecks:
    def __init__(self, root):
        self.root = root
        self.path = root / "repository-versions.json"
        cached = read_json(self.path, {})
        self.results = {}
        for component in VERSION_FILES:
            entry = cached.get(component) if isinstance(cached, dict) else None
            if isinstance(entry, dict) and isinstance(entry.get("version"), str):
                value = entry["version"]
                if re.fullmatch(r"\d+\.\d+\.\d+(?:-internal\.\d+)?", value):
                    self.results[component] = {**entry, "cached": True}
        self.guard = threading.Lock()
        self.started = False
        self.checking = False

    def snapshot(self):
        with self.guard:
            return {"checking": self.checking,
                    **{name: dict(value) for name, value in self.results.items()}}

    def start(self, force=False):
        with self.guard:
            if not self.started or (force and not self.checking):
                self.started = self.checking = True
                # A slow connection must not delay closing the application.
                threading.Thread(target=self._check, name="repository-versions", daemon=True).start()
        return self.snapshot()

    def _check(self):
        try:
            for component, url in VERSION_FILES.items():
                try:
                    value = fetch_metadata(url, lambda data: parse_version(data, component), max_bytes=16384)
                    entry = {"version": value, "checkedAt": time.time(), "cached": False, "failed": False}
                except Exception:
                    with self.guard:
                        previous = dict(self.results.get(component, {}))
                    entry = {**previous, "failed": True}
                with self.guard:
                    self.results[component] = entry
            with self.guard:
                self.checking = False
            atomic_json(self.path, self.snapshot())
        finally:
            with self.guard:
                self.checking = False
