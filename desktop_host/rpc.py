"""Multiplexed JSON-lines transport for the desktop manager.

Query/cancel workers are reserved so a slow model or download does not prevent
the window from observing or cancelling work. Workspace owns mutation ordering.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

try:
    from .i18n import set_language, tr
except ImportError:
    from i18n import set_language, tr


class RequestServer:
    def __init__(self, manager, output, workers=6, query_workers=2, limit=64):
        self.manager, self.output = manager, output
        self.operations = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="desktop-operation")
        self.queries = ThreadPoolExecutor(max_workers=query_workers, thread_name_prefix="desktop-query")
        self.controls = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desktop-cancel")
        self.output_lock = threading.Lock()
        self.lock = threading.Lock()
        self.pending = set()
        self.limit = limit
        self.closed = False

    def send(self, response):
        encoded = json.dumps(response, ensure_ascii=False)
        with self.output_lock:
            self.output.write(encoded + "\n")
            self.output.flush()

    def execute(self, request):
        request_id = request.get("id")
        try:
            result = self.manager.dispatch(request["method"], request.get("args", {}))
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": self.manager.redact(str(exc))}
        if request_id is not None:
            response["id"] = request_id
        try:
            self.send(response)
        except (BrokenPipeError, OSError, ValueError):
            # The desktop window has closed; close() still cleans up its processes.
            pass
        finally:
            if request_id is not None:
                with self.lock:
                    self.pending.discard(request_id)

    def submit(self, line):
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError(tr("host.invalid_request"))
            candidate = request.get("id")
            if candidate is not None:
                if type(candidate) is not int or not 0 < candidate < 2**64:
                    raise ValueError(tr("host.invalid_request"))
                request_id = candidate
            if not isinstance(request.get("method"), str) or not isinstance(request.get("args", {}), dict):
                raise ValueError(tr("host.invalid_request"))
            set_language(request.get("args", {}).get("locale", "zh-CN"))
            if request_id is None:
                # Compatibility with older development launchers: no ID is serial.
                self.execute(request)
                return
            with self.lock:
                if self.closed:
                    raise ValueError(tr("host.manager_closing"))
                if request_id in self.pending:
                    raise ValueError(tr("host.duplicate_request"))
                if len(self.pending) >= self.limit:
                    raise ValueError(tr("host.too_many_requests"))
                self.pending.add(request_id)
            pool = (self.controls if request["method"] in {"cancel_import", "analysis_cancel", "history_images_cancel"}
                    else self.queries if request["method"] in self.manager.CONCURRENT_METHODS else self.operations)
            try:
                pool.submit(self.execute, request)
            except RuntimeError:
                with self.lock:
                    self.pending.discard(request_id)
                raise
        except (TypeError, ValueError, RuntimeError) as exc:
            response = {"ok": False, "error": self.manager.redact(str(exc))}
            if request_id is not None:
                response["id"] = request_id
            self.send(response)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        # Closing the core first releases blocked local HTTP calls and stops the
        # bundled channel workers. Do not wait for HTTP workers before cleanup.
        try:
            self.manager.close()
        finally:
            self.operations.shutdown(wait=True, cancel_futures=True)
            self.queries.shutdown(wait=True, cancel_futures=True)
            self.controls.shutdown(wait=True, cancel_futures=True)
