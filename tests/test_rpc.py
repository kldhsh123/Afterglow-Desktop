from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import ExitStack
from unittest.mock import Mock
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest

from desktop_host.rpc import RequestServer
from desktop_host.host import Manager
from desktop_host.extensions import Extensions
from desktop_host.workspace import Workspace


class Responses:
    def __init__(self):
        self.items = queue.Queue()

    def write(self, line):
        self.items.put(json.loads(line))

    def flush(self):
        pass

    def next(self):
        return self.items.get(timeout=3)


class TestManager:
    CONCURRENT_METHODS = Workspace.CONCURRENT_METHODS

    def __init__(self, root=None, catalog=None):
        self.started = threading.Event()
        self.release = threading.Event()
        self.query_started = threading.Event()
        self.query_release = threading.Event()
        self.saved = threading.Event()
        self.children = {}
        self.budget = object()
        self.closed = False

    def dispatch(self, method, args):
        if method == 'send_chat':
            self.started.set()
            if not self.release.wait(5):
                raise RuntimeError('blocked test request')
        if method == 'analysis_report':
            self.query_started.set()
            if not self.query_release.wait(5):
                raise RuntimeError('blocked test report')
        if method == 'save_settings':
            self.saved.set()
        if method == 'fail':
            raise ValueError('failed with secret-token')
        return {'method': method}

    def redact(self, message):
        return message.replace('secret-token', '[redacted]')

    def close(self):
        self.closed = True
        self.release.set()
        self.query_release.set()


class RpcTests(unittest.TestCase):
    def test_queries_and_cancel_return_before_blocking_generation(self):
        manager, output = TestManager(), Responses()
        server = RequestServer(manager, output, workers=1, query_workers=1)
        self.addCleanup(server.close)
        server.submit(json.dumps({'id': 1, 'method': 'send_chat'}))
        self.assertTrue(manager.started.wait(2))
        server.submit(json.dumps({'id': 2, 'method': 'health'}))
        response = output.next()
        self.assertEqual(response['id'], 2)
        server.submit(json.dumps({'id': 3, 'method': 'analysis_report'}))
        self.assertTrue(manager.query_started.wait(2))
        server.submit(json.dumps({'id': 4, 'method': 'cancel_import'}))
        self.assertEqual(output.next()['id'], 4)
        manager.release.set()
        self.assertEqual(output.next()['id'], 1)
        manager.query_release.set()
        self.assertEqual(output.next()['id'], 3)

    def test_errors_keep_request_id_and_redact_secrets(self):
        manager, output = TestManager(), Responses()
        server = RequestServer(manager, output)
        self.addCleanup(server.close)
        server.submit(json.dumps({'id': 7, 'method': 'fail'}))
        self.assertEqual(output.next(), {'id': 7, 'ok': False, 'error': 'failed with [redacted]'})
        for request in ['[]', '{', '{"id": true, "method": "health"}', '{"id": 8, "method": "health", "args": []}']:
            server.submit(request)
            self.assertFalse(output.next()['ok'])

    def test_legacy_requests_and_shutdown_remain_supported(self):
        manager, output = TestManager(), Responses()
        server = RequestServer(manager, output)
        server.submit('{"method":"health"}')
        self.assertEqual(output.next(), {'ok': True, 'result': {'method': 'health'}})
        server.close()
        server.close()
        self.assertTrue(manager.closed)

    def test_workspace_serializes_mutations_but_allows_queries_and_other_instances(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as cleanup:
            workspace = Workspace(Path(folder), Path(folder)/'catalog.json', TestManager)
            cleanup.callback(workspace.close)
            primary = workspace.manager('default')
            second = workspace.dispatch('create_instance', {'name': 'Second'})['id']
            with ThreadPoolExecutor(max_workers=3) as pool:
                slow = pool.submit(workspace.dispatch, 'send_chat', {'instanceId': 'default'})
                self.assertTrue(primary.started.wait(2))
                saved = pool.submit(workspace.dispatch, 'save_settings', {'instanceId': 'default'})
                try:
                    with self.assertRaises(TimeoutError):
                        saved.result(timeout=.05)
                    self.assertFalse(primary.saved.is_set())
                    self.assertEqual(workspace.dispatch('health', {})['method'], 'health')
                    self.assertEqual(workspace.dispatch('save_settings', {'instanceId': second})['method'], 'save_settings')
                    self.assertIs(workspace.manager(second).budget, primary.budget)
                finally:
                    primary.release.set()
                self.assertEqual(slow.result(timeout=2)['method'], 'send_chat')
                self.assertEqual(saved.result(timeout=2)['method'], 'save_settings')

    def test_workspace_cannot_start_new_work_after_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(Path(folder), Path(folder)/'catalog.json', TestManager)
            workspace.manager('default')
            workspace.close()
            with self.assertRaises(ValueError):
                workspace.dispatch('health', {})

    def test_transport_close_stops_core_and_both_extensions_in_every_managed_instance(self):
        processes = []

        def factory(root, catalog):
            manager = Manager.__new__(Manager)
            manager.root, manager.budget, manager.gateway = root, object(), Mock()
            manager.children = {'core': Mock()}
            manager.extensions = Extensions(manager)
            manager.extensions.children = {'qq': Mock(), 'weixin': Mock()}
            for process in [*manager.children.values(), *manager.extensions.children.values()]:
                process.poll.return_value = None
                process.terminate.side_effect = lambda child=process: setattr(child.poll, 'return_value', 0)
                processes.append(process)
            return manager

        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(Path(folder), Path(folder)/'catalog.json', factory)
            primary = workspace.manager('default')
            second_id = workspace.dispatch('create_instance', {'name': 'Second'})['id']
            secondary = workspace.manager(second_id)
            server = RequestServer(workspace, Responses())
            server.close()
            server.close()
            self.assertEqual(len(processes), 6)
            for process in processes:
                process.terminate.assert_called_once()
                process.wait.assert_called_once()
            for manager in (primary, secondary):
                self.assertTrue(manager.extensions.closing)
                manager.gateway.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
