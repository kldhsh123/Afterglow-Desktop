import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_host.history_images import HistoryImages
from desktop_host.storage import atomic_json


class HistoricalImageTaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manager = SimpleNamespace(root=self.root, core_request=Mock(return_value={'ok': True}),
                                       identity_needs_restart=Mock(return_value=False), ensure_idle=Mock(),
                                       pending_settings={'services': {'vision': 'off'}}, stop=Mock(), start=Mock())

    def test_invalid_folder_and_disabled_vision_do_not_stop_running_core(self):
        service = HistoryImages(self.manager)
        with self.assertRaises(ValueError):
            service.start({'directory': '../missing'})
        with self.assertRaises(ValueError):
            service.start({'directory': str(self.root)})
        self.manager.stop.assert_not_called()

    def test_interrupted_task_is_not_presented_as_success_after_app_restart(self):
        atomic_json(self.root / 'history-images-task.json', {'id': 'old', 'status': 'running'})
        service = HistoryImages(self.manager)
        self.assertFalse(service.active())
        self.assertEqual(service.snapshot()['status'], 'cancelled')
        self.assertTrue(service.snapshot()['error'])

    def test_stop_cancels_owned_process_without_scheduling_core_restart(self):
        service = HistoryImages(self.manager)
        service.task = {'id': 'job', 'status': 'running'}
        service.process = Mock()
        service.process.poll.return_value = None
        service.restore = True
        service.cancel(restore=False)
        service.process.terminate.assert_called_once()
        self.assertTrue(service.cancelled.is_set())
        self.assertFalse(service.restore)
        self.manager.start.assert_not_called()

    def test_import_only_model_is_applied_to_worker_with_conversation_vision_off(self):
        self.manager.pending_settings = {'services': {'vision': 'off', 'imageImportVision': True},
                                         'providers': {'imageImportVision': {'model': 'history-vision'}}}
        self.manager.core_environment = {'VISION_ENABLED': 'false', 'VISION_MODEL': 'chat-vision'}
        self.manager.core_directory = self.root / 'component'
        self.manager.gateway = Mock(); self.manager.gateway.base.return_value = 'http://localhost/import/v1'
        self.manager.secrets = Mock(); self.manager.secrets.get.return_value = 'local-token'
        self.manager.extensions = SimpleNamespace(children={})
        self.manager.locale = 'en-US'
        service = HistoryImages(self.manager)
        with patch('desktop_host.history_images.threading.Thread') as thread:
            task = service.start({'directory': str(self.root)})
        worker_env = thread.call_args.kwargs['args'][2]
        self.assertEqual(task['status'], 'running')
        self.assertEqual(worker_env['VISION_MODEL'], 'history-vision')
        self.assertEqual(worker_env['VISION_ENABLED'], 'true')
        self.assertEqual(self.manager.core_environment['VISION_ENABLED'], 'false')
        self.assertEqual(self.manager.core_environment['VISION_MODEL'], 'chat-vision')
        self.manager.stop.assert_called_once_with('core')
