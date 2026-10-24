"""Own the lifetime of the original offline historical-image import process."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

try:
    from .i18n import tr, set_language
    from .storage import atomic_json, read_json
    from .services import image_import_environment
except ImportError:
    from i18n import tr, set_language
    from storage import atomic_json, read_json
    from services import image_import_environment

TERMINAL = {'done', 'failed', 'cancelled'}


class HistoryImages:
    def __init__(self, manager):
        self.manager = manager
        self.guard = threading.RLock()
        self.process = None
        self.thread = None
        self.cancelled = threading.Event()
        self.closed = False
        self.restore = False
        self.task = read_json(manager.root / 'history-images-task.json')
        if self.task and self.task.get('status') not in TERMINAL:
            self.task.update(status='cancelled', error=tr('media.interrupted'))
            self._save()

    def _save(self):
        atomic_json(self.manager.root / 'history-images-task.json', self.task)

    def active(self):
        with self.guard:
            return bool(self.task and self.task.get('status') not in TERMINAL)

    def snapshot(self):
        with self.guard:
            return json.loads(json.dumps(self.task)) if self.task else None

    def start(self, args):
        manager = self.manager
        directory = args.get('directory')
        if not isinstance(directory, str) or not Path(directory).is_absolute() or not Path(directory).is_dir():
            raise ValueError(tr('media.choose_directory'))
        if manager.identity_needs_restart():
            raise ValueError(tr('analysis.restart_identity'))
        manager.core_request('/readyz')
        manager.ensure_idle()
        settings = getattr(manager, 'pending_settings', {})
        if settings.get('services', {}).get('vision', 'off') == 'off' and not settings.get('services', {}).get('imageImportVision'):
            raise ValueError(tr('media.vision_required'))
        environment = dict(getattr(manager, 'core_environment', {}))
        component = getattr(manager, 'core_directory', None)
        if not environment or component is None:
            raise ValueError(tr('media.restart_required'))
        if settings.get('services', {}).get('imageImportVision'):
            environment.update(image_import_environment(settings, manager.gateway, manager.secrets.get('local_api')))
        reconnect = [name for name, child in manager.extensions.children.items() if child.poll() is None]
        manager.stop('core')
        with self.guard:
            if self.closed:
                raise ValueError(tr('host.manager_closing'))
            self.cancelled.clear()
            self.restore = True
            self.task = {'id': uuid.uuid4().hex, 'status': 'running', 'directory': str(Path(directory).resolve()),
                         'started_at': time.time(), 'report': None, 'error': '', 'restart_error': ''}
            self._save()
            self.thread = threading.Thread(target=self._run, args=(component, directory, environment, reconnect, manager.locale),
                                           name='history-images', daemon=True)
            self.thread.start()
            return self.snapshot()

    def cancel(self, restore=True):
        with self.guard:
            if not self.active():
                return self.snapshot()
            if not restore:
                self.restore = False
            self.cancelled.set()
            process = self.process
            if process and process.poll() is None:
                process.terminate()
        return self.snapshot()

    def close(self):
        with self.guard:
            self.closed = True
        self.cancel(restore=False)
        if self.thread:
            self.thread.join(timeout=12)
        with self.guard:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=3)

    def _run(self, component, directory, environment, reconnect, language):
        set_language(language)
        manager = self.manager
        result = None
        final = 'failed'
        try:
            with self.guard:
                if self.cancelled.is_set() or self.closed:
                    final = 'cancelled'
                else:
                    self.process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).with_name('history_images_worker.py')),
                                                     str(component), directory], cwd=manager.root / 'profiles' / 'default' / 'core',
                                                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                    stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            process = self.process
            if process:
                log = manager.root / 'logs' / 'history-images.log'
                log.parent.mkdir(exist_ok=True)
                with log.open('a', encoding='utf-8') as output:
                    for raw in iter(process.stdout.readline, b''):
                        line = manager.redact(raw.decode('utf-8', errors='replace'))
                        if line.startswith('AFTERGLOW_IMAGE_RESULT:'):
                            result = json.loads(line.split(':', 1)[1])
                        else:
                            output.write(line)
                            output.flush()
                code = process.wait()
                final = 'cancelled' if self.cancelled.is_set() else 'done' if code == 0 and result and result.get('ok') else 'failed'
            with self.guard:
                self.task['report'] = result.get('report') if result else None
                self.task['error'] = '' if final != 'failed' else (result or {}).get('error') or tr('media.worker_failed')
        except Exception as error:
            with self.guard:
                self.task['error'] = manager.redact(str(error))[:2000]
        finally:
            try:
                with self.guard:
                    should_restore = self.restore and not self.closed
                    self.task['status'] = 'restoring'
                    self._save()
                    if should_restore:
                        manager.start('core')
                if should_restore:
                    deadline = time.monotonic() + 90
                    ready = False
                    while time.monotonic() < deadline:
                        with self.guard:
                            if self.closed or not self.restore:
                                break
                        try:
                            manager.core_request('/readyz', timeout=3)
                            ready = True
                            break
                        except ValueError:
                            time.sleep(.5)
                    else:
                        raise ValueError(tr('updates.core_start_failed'))
                    if ready:
                        with self.guard:
                            if not self.closed and self.restore:
                                for name in reconnect:
                                    manager.extensions.start(name)
            except Exception as error:
                with self.guard:
                    self.task['restart_error'] = manager.redact(str(error))[:2000]
            with self.guard:
                self.task['status'] = final
                self.task['finished_at'] = time.time()
                self.process = None
                self._save()
