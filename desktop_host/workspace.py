"""Dispatch to independent core managers without changing a live manager's root."""
import json
from pathlib import Path
import re
import threading
import uuid

try:
    from .i18n import set_language, tr
    from .paths import DataDirectoryLock
    from .storage import atomic_json
except ImportError:
    from i18n import set_language, tr
    from paths import DataDirectoryLock
    from storage import atomic_json


class Workspace:
    CONCURRENT_METHODS = frozenset({
        "bootstrap", "status", "health", "logs", "extension_status",
        "list_conversations", "get_conversation", "analysis_files",
        "analysis_status", "analysis_report", "analysis_diagnostics", "import_status",
        "analysis_cancel", "cancel_import", "debug_snapshot",
        "desktop_update_status", "history_images_status", "history_images_cancel", "stickers_list", "stickers_image",
        "start_update_checks", "check_repository_updates", "repository_update_status",
    })

    def __init__(self, root: Path, catalog: Path, factory):
        self.root, self.catalog, self.factory = root.resolve(), catalog, factory
        self.lock = DataDirectoryLock(self.root)
        self.managers = {}
        self.budget = None
        self.active = "default"
        self.guard = threading.RLock()
        self.operation_locks = {}
        self.cleanup_locks = {}
        self.closed = False
        path = self.root / "active_instance.json"
        if path.is_file():
            try:
                candidate = json.loads(path.read_text(encoding="utf-8")).get("id")
                if self.valid_id(candidate) and self.instance_path(candidate).is_dir():
                    self.active = candidate
            except (ValueError, TypeError):
                pass

    @staticmethod
    def valid_id(value):
        return isinstance(value, str) and bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,48}", value))

    def instance_path(self, key):
        if not self.valid_id(key):
            raise ValueError(tr("host.invalid_instance_name"))
        return self.root if key == "default" else self.root / "instances" / key

    def manager(self, key):
        with self.guard:
            return self._manager(key)

    def _manager(self, key):
        if self.closed:
            raise ValueError(tr("host.manager_closing"))
        path = self.instance_path(key)
        if key != "default" and not (path / "instance.json").is_file():
            raise ValueError(tr("host.instance_not_found"))
        if key not in self.managers:
            manager = self.factory(path, self.catalog)
            # Threads share one budget; ModelBudget also coordinates independent
            # Windows installation processes through OS-backed model slots.
            if self.budget is None:
                self.budget = manager.budget
            else:
                manager.budget = self.budget
            self.managers[key] = manager
            self.operation_locks[key] = threading.RLock()
            self.cleanup_locks[key] = threading.RLock()
        return self.managers[key]

    def list_instances(self):
        entries = [{"id": "default", "name": tr("instances.default"), "path": str(self.root)}]
        directory = self.root / "instances"
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if not self.valid_id(path.name) or path.name == "default" or path.is_symlink() or not (path / "instance.json").is_file():
                    continue
                meta = json.loads((path / "instance.json").read_text(encoding="utf-8"))
                entries.append({"id": path.name, "name": meta.get("name", path.name), "path": str(path)})
        with self.guard:
            managers = dict(self.managers)
        for entry in entries:
            manager = managers.get(entry["id"])
            entry["running"] = bool(manager and any(c.poll() is None for c in manager.children.values()))
        return entries

    def dispatch(self, method, args):
        if not isinstance(args, dict):
            raise ValueError(tr("host.invalid_request"))
        set_language(args.get("locale", "zh-CN"))
        if method == 'prepare_desktop_update':
            with self.guard:
                if self.closed:
                    raise ValueError(tr('host.manager_closing'))
                managers = list(self.managers.values())
            for manager in managers:
                process = manager.children.get('core')
                if process and process.poll() is None:
                    manager.ensure_idle()
            return {'ok': True}
        with self.guard:
            if self.closed:
                raise ValueError(tr("host.manager_closing"))
            if method in {"create_instance", "switch_instance"}:
                return self._metadata(method, args)
            key = args.get("instanceId", self.active)
            manager = self.manager(key)
            operation_lock = self.operation_locks[key]
        try:
            if method in self.CONCURRENT_METHODS:
                result = manager.dispatch(method, args)
            else:
                with operation_lock:
                    with self.guard:
                        if self.closed:
                            raise ValueError(tr("host.manager_closing"))
                    result = manager.dispatch(method, args)
            if method == "bootstrap":
                result.update({"instanceId": key, "instances": self.list_instances(), "installationDir": str(self.root)})
            return result
        finally:
            # If shutdown raced with a process start, clean up once more after
            # the operation returns; no worker may leave a late child running.
            if self.closed:
                with self.cleanup_locks[key]:
                    manager.close()

    def _metadata(self, method, args):
        if not isinstance(args, dict):
            raise ValueError(tr("host.invalid_request"))
        set_language(args.get("locale", "zh-CN"))
        if method == "create_instance":
            name = args.get("name", "")
            if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
                raise ValueError(tr("host.invalid_instance_name"))
            key = uuid.uuid4().hex[:16]
            path = self.instance_path(key)
            path.mkdir(parents=True, exist_ok=False)
            atomic_json(path / "instance.json", {"id": key, "name": name.strip()})
            return {"ok": True, "id": key, "message": tr("host.instance_created")}
        if method == "switch_instance":
            key = args.get("id")
            self.manager(key)
            self.active = key
            atomic_json(self.root / "active_instance.json", {"id": key})
            return {"ok": True, "id": key, "message": tr("host.instance_selected")}

    def redact(self, message):
        with self.guard:
            managers = list(self.managers.values())
        for manager in managers:
            message = manager.redact(message)
        return message

    def close(self):
        with self.guard:
            if self.closed:
                return
            self.closed = True
            managers = list(self.managers.items())
        try:
            for key, manager in managers:
                with self.cleanup_locks[key]:
                    manager.close()
        finally:
            self.lock.close()
