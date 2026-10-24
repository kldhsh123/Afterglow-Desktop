"""Built-in QQ/WeChat lifecycle and desktop configuration, isolated per instance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit

try:
    from .bindings import BindingStore
    from .extension_events import PREFIX
    from .i18n import set_language, tr
    from .storage import atomic_json, read_json
except ImportError:
    from bindings import BindingStore
    from extension_events import PREFIX
    from i18n import set_language, tr
    from storage import atomic_json, read_json


def weixin_base_url(value):
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if (parsed.scheme != "https" or not (hostname == "weixin.qq.com" or hostname.endswith(".weixin.qq.com"))
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise ValueError(tr("extensions.invalid_weixin_host"))
    return value.rstrip("/")


class Extensions:
    IDS = {"qq", "weixin"}

    def __init__(self, manager, popen=subprocess.Popen):
        self.manager = manager
        self.root = manager.root / "extensions"
        self.popen = popen
        self.children = {}
        self.states = {}
        self.lock = threading.RLock()
        self.closing = False

    def _id(self, extension):
        if extension not in self.IDS:
            raise ValueError(tr("host.unknown_component"))
        return extension

    def bindings(self, extension):
        return BindingStore(self.root / self._id(extension) / "bindings.sqlite3")

    def status(self):
        saved = read_json(self.manager.root / "extensions.json", {})
        available = set(self.manager.secrets.available())
        result = []
        with self.lock:
            for extension in ("qq", "weixin"):
                process = self.children.get(extension)
                running = process is not None and process.poll() is None
                state = dict(self.states.get(extension, {}))
                if not running and state.get("state") in {"connecting", "connected", "reconnecting", "login", "scanned", "verify"}:
                    state = {"state": "error", "error": tr("host.extension_exited_check_its_log")}
                contacts = self.bindings(extension).list()
                ready = {"qq_app_id", "qq_secret"}.issubset(available) if extension == "qq" else "weixin_token" in available
                result.append({"id": extension, "name": "QQ" if extension == "qq" else "WeChat", "running": running,
                               "state": state.get("state", "stopped"), "error": state.get("error", ""),
                               "configured": saved.get(extension, {}).get("enabled", False), "credentialsReady": ready,
                               "qrContent": state.get("qrContent", ""), "verifyCodeRequired": state.get("state") == "verify",
                               "pendingUsers": [{**user, "openid": user["uid"]} for user in contacts if not user["authorized"]],
                               "contacts": [user for user in contacts if user["authorized"]]})
        return result

    def save(self, args):
        extension = self._id(args.get("id"))
        data = args.get("settings")
        if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
            raise ValueError(tr("host.invalid_extension_settings"))
        process = self.children.get(extension)
        if process and process.poll() is None:
            raise ValueError(tr("host.stop_the_extension_before_changing_its_settings"))
        if extension == "qq":
            app_id, secret = data.get("appId", ""), data.get("clientSecret", "")
            if not isinstance(app_id, str) or not isinstance(secret, str) or (app_id and not re.fullmatch(r"[0-9]{1,40}", app_id)):
                raise ValueError(tr("host.invalid_extension_settings"))
            if app_id:
                self.manager.secrets.set("qq_app_id", app_id)
            if secret:
                self.manager.secrets.set("qq_secret", secret)
        saved = read_json(self.manager.root / "extensions.json", {})
        saved[extension] = {"enabled": data["enabled"]}
        atomic_json(self.manager.root / "extensions.json", saved)
        return {"ok": True, "message": tr("host.extension_settings_saved")}

    def _configuration(self, extension, login):
        manager = self.manager
        core = read_json(manager.root / "installed.json", {}).get("core")
        if not core:
            raise ValueError(tr("host.install_the_component_first"))
        if not login and getattr(manager, "identity_needs_restart", lambda: False)():
            raise ValueError(tr("analysis.restart_identity"))
        process = manager.children.get("core")
        if not login and (not process or process.poll() is not None or not manager.port):
            raise ValueError(tr("host.start_the_afterglow_core_before_connecting_a_channel"))
        if not login:
            manager.core_request("/readyz", timeout=3)
        data = self.root / extension
        data.mkdir(parents=True, exist_ok=True)
        settings = manager.settings() or {}
        delay = settings.get("humanDelay") is True
        environment = {"AFTERGLOW_BASE_URL": f"http://127.0.0.1:{manager.port}",
                       "AFTERGLOW_API_KEY": manager.secrets.get("local_api"), "AFTERGLOW_MODEL": "afterglow",
                       "AFTERGLOW_HISTORY_DB_PATH": str(data / "chat-history.sqlite3"),
                       "AFTERGLOW_SCHEDULE_TASKS_ENABLED": "false", "AFTERGLOW_IMAGE_MAX_COUNT": "0",
                       "AFTERGLOW_BINDINGS_PATH": str(data / "bindings.sqlite3"),
                       "AFTERGLOW_LANGUAGE": manager.locale, "AFTERGLOW_HUMAN_DELAY": str(delay).lower(),
                       "AFTERGLOW_MESSAGE_SEGMENT_MIN_DELAY": "1.5" if delay else "0",
                       "AFTERGLOW_MESSAGE_SEGMENT_MAX_DELAY": "3" if delay else "0",
                       "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        if extension == "qq":
            app_id, secret = manager.secrets.get("qq_app_id"), manager.secrets.get("qq_secret")
            if not app_id or not secret:
                raise ValueError(tr("host.enter_the_qq_bot_app_id_and_client_secret"))
            environment.update(QQ_BOT_APP_ID=app_id, QQ_BOT_CLIENT_SECRET=secret)
        elif not login:
            token = manager.secrets.get("weixin_token")
            if not token:
                raise ValueError(tr("host.scan_the_wechat_login_qr_code_first"))
            account = read_json(data / "account.json", {})
            environment.update(WEIXIN_BOT_TOKEN=token, WEIXIN_BOT_ACCOUNT_ID=account.get("accountId", "default"),
                               WEIXIN_BOT_BASE_URL=weixin_base_url(account.get("baseUrl", "https://ilinkai.weixin.qq.com")),
                               WEIXIN_SYNC_STATE_PATH=str(data / "sync.json"),
                               WEIXIN_CONTEXT_TOKENS_PATH=str(data / "context-tokens.json"),
                               WEIXIN_OUTBOUND_TEMP_DIR=str(data / "outbound-media"))
        return {"extension": extension, "component": core["path"], "login": login, "environment": environment}

    def start(self, extension, login=False):
        extension = self._id(extension)
        with self.lock:
            if self.closing:
                raise ValueError(tr("extensions.shutting_down"))
            existing = self.children.get(extension)
            if existing and existing.poll() is None:
                return {"ok": True, "message": tr("host.extension_already_running")}
            config = self._configuration(extension, login)
            env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
            env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            process = self.popen([sys.executable, "-u", str(Path(__file__).with_name("launch_extension.py"))],
                                 cwd=self.root / extension, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.children[extension] = process
            self.states[extension] = {"state": "login" if login else "connecting", "error": ""}
            process.stdin.write((json.dumps(config, ensure_ascii=False) + "\n").encode())
            process.stdin.flush()
            for kind, stream in (("events", process.stdout), ("log", process.stderr)):
                threading.Thread(target=self._collect, args=(extension, process, stream, kind, self.manager.locale), daemon=True).start()
        return {"ok": True, "message": tr("host.weixin_qr_code_requested" if login else "host.extension_start_requested")}

    def _collect(self, extension, process, stream, kind, language):
        set_language(language)
        logdir = self.manager.root / "logs"
        logdir.mkdir(exist_ok=True)
        with (logdir / (extension + ".log")).open("a", encoding="utf-8") as output:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip()
                if kind == "events" and line.startswith(PREFIX):
                    try:
                        self._event(extension, process, json.loads(line[len(PREFIX):]))
                    except (ValueError, TypeError, KeyError, OSError):
                        with self.lock:
                            if self.children.get(extension) is process:
                                self.states[extension] = {"state": "error", "error": tr("extensions.invalid_event")}
                    continue
                # Unknown stdout is intentionally not a log sink: it can contain login material.
                if kind == "log":
                    output.write(self.manager.redact(line) + "\n")
                    output.flush()
        if kind == "events":
            returncode = process.wait()
            with self.lock:
                if self.children.get(extension) is process:
                    state = self.states.setdefault(extension, {})
                    if state.get("state") not in {"stopped", "expired", "error", "authenticated"}:
                        state.update(state="stopped" if returncode == 0 else "error",
                                     error="" if returncode == 0 else tr("host.extension_exited_check_its_log"))
                        state.pop("qrContent", None)

    def _event(self, extension, process, event):
        with self.lock:
            if self.children.get(extension) is not process or self.closing or self.states.get(extension, {}).get("state") == "stopped":
                return
            kind = event.get("event")
            state = self.states.setdefault(extension, {})
            if kind == "state" and event.get("state") in {"connecting", "connected", "reconnecting", "login", "scanned", "verify", "expired", "error"}:
                state["state"] = event["state"]
                if state["state"] not in {"login", "scanned", "verify"}:
                    state.pop("qrContent", None)
                state["error"] = "" if state["state"] != "error" else tr("host.weixin_login_failed_check_the_connection")
            elif kind == "qr" and extension == "weixin":
                content = event.get("content")
                if not isinstance(content, str) or not 1 <= len(content) <= 4096:
                    raise ValueError("Invalid QR payload")
                state.update(state="login", qrContent=content, error="")
            elif kind == "credentials" and extension == "weixin":
                token, account_id = event.get("token"), event.get("accountId")
                if not isinstance(token, str) or not isinstance(account_id, str) or not account_id:
                    raise ValueError("Missing credentials")
                base_url = weixin_base_url(event.get("baseUrl", "https://ilinkai.weixin.qq.com"))
                self.manager.secrets.set("weixin_token", token)
                atomic_json(self.root / "weixin" / "account.json", {"accountId": account_id, "baseUrl": base_url})
                owner = event.get("ownerUid")
                if isinstance(owner, str) and owner:
                    self.bindings("weixin").trust_owner(owner)
                state.clear()
                state["state"] = "authenticated"

    def verify(self, code):
        with self.lock:
            process = self.children.get("weixin")
            if not process or process.poll() is not None or self.states.get("weixin", {}).get("state") != "verify":
                raise ValueError(tr("host.weixin_login_is_not_waiting_for_a_verification_code"))
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{1,16}", code):
                raise ValueError(tr("host.invalid_weixin_verification_code"))
            process.stdin.write((code + "\n").encode())
            process.stdin.flush()
            self.states["weixin"]["state"] = "scanned"
        return {"ok": True, "message": tr("host.weixin_verification_code_submitted")}

    def contact(self, extension, uid, code=None, revoke=False):
        store = self.bindings(extension)
        try:
            store.revoke(uid) if revoke else store.approve(uid, code)
        except ValueError:
            raise ValueError(tr("host.qq_binding_code_does_not_match")) from None
        return {"ok": True, "message": tr("extensions.contact_removed" if revoke else "host.qq_user_binding_confirmed")}

    def stop(self, extension):
        extension = self._id(extension)
        with self.lock:
            process = self.children.get(extension)
            self.states[extension] = {"state": "stopped", "error": ""}
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        return {"ok": True, "message": tr("host.component_stopped")}

    def close(self):
        self.closing = True
        for extension in self.IDS:
            self.stop(extension)
