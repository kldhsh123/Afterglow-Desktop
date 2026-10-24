import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from desktop_host.host import Manager
from types import SimpleNamespace


class ImportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = Manager.__new__(Manager)
        self.host.root = Path(self.temp.name)
        self.host.uploaded = {'checked.json': {
            'name': 'records.json', 'saved_as': 'checked.json', 'format': 'afterglow_v1', 'error': '', 'ai_converted': True,
            'candidates': [{'uid': 'a', 'name': 'Alice'}, {'uid': 'b', 'name': 'Bob'}],
        }}
        self.host.settings = Mock(return_value={})
        self.host.ensure_idle = Mock()
        self.host.core_request = Mock(side_effect=[{'ok': True}, {'task_id': 'task1', 'status': 'running'}])

    def test_converted_export_requires_explicit_distinct_identities(self):
        for values in ({}, {'selfUid': 'a'}, {'selfUid': 'a', 'friendUid': 'a'},
                       {'selfUid': 'a', 'friendUid': 'absent'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.host.start_import({'files': ['checked.json'], **values})
        self.host.core_request.assert_not_called()

    def test_user_can_choose_either_participant_as_self_before_import(self):
        result = self.host.start_import({'files': ['checked.json'], 'selfUid': 'b', 'friendUid': 'a'})
        self.assertEqual(result['task_id'], 'task1')
        self.assertEqual(self.host.core_request.call_args_list[0].args,
                         ('/config/values', {'values': {'SELF_UID': 'b', 'FRIEND_UID': 'a',
                          'SELF_NAME': 'Bob', 'FRIEND_NAME': 'Alice'}}))
        self.assertEqual(self.host.core_request.call_args_list[1].args[0], '/config/import/start')

    def test_batch_with_different_accounts_cannot_reuse_the_wrong_mapping(self):
        self.host.uploaded['second.json'] = {'name': 'second.json', 'format': 'afterglow_v1',
                                           'candidates': [{'uid': 'a', 'name': 'Alice'}, {'uid': 'c', 'name': 'Other'}]}
        with self.assertRaises(ValueError):
            self.host.start_import({'files': ['checked.json', 'second.json'], 'selfUid': 'a', 'friendUid': 'b'})
        self.host.core_request.assert_not_called()

    def test_multiple_accounts_can_map_to_the_same_people_across_files(self):
        self.host.uploaded['second.json'] = {'name': 'wechat.json', 'format': 'afterglow_v1',
                                           'candidates': [{'uid': 'wx-a', 'name': 'Alice WeChat'},
                                                          {'uid': 'wx-b', 'name': 'Bob WeChat'}]}
        result = self.host.start_import({'files': ['checked.json', 'second.json'],
                                        'selfUids': ['a', 'wx-a'], 'friendUids': ['b', 'wx-b']})
        self.assertEqual(result['task_id'], 'task1')
        values = self.host.core_request.call_args_list[0].args[1]['values']
        self.assertEqual(values['SELF_UID'], 'a,wx-a')
        self.assertEqual(values['FRIEND_UID'], 'b,wx-b')
        self.assertEqual(json.loads((self.host.root / 'identity.json').read_text()), values)

    def test_multiple_account_selections_cannot_overlap_or_use_unknown_accounts(self):
        for values in ({'selfUids': ['a'], 'friendUids': ['a', 'b']},
                       {'selfUids': [], 'friendUids': ['b']},
                       {'selfUids': ['a', 'missing'], 'friendUids': ['b']},
                       {'selfUids': ['a', None], 'friendUids': ['b']}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.host.start_import({'files': ['checked.json'], **values})
        self.host.core_request.assert_not_called()

    def test_duplicate_selection_is_written_once(self):
        self.host.start_import({'files': ['checked.json'], 'selfUids': ['a', 'a'], 'friendUids': ['b']})
        self.assertEqual(self.host.core_request.call_args_list[0].args[1]['values']['SELF_UID'], 'a')

    def test_unrecognized_and_uninspected_files_never_start_import(self):
        with self.assertRaises(ValueError):
            self.host.start_import({'files': ['arbitrary.json'], 'selfUid': 'a', 'friendUid': 'b'})
        self.host.uploaded['checked.json']['error'] = 'conversion failed'
        with self.assertRaises(ValueError):
            self.host.start_import({'files': ['checked.json'], 'selfUid': 'a', 'friendUid': 'b'})
        self.host.core_request.assert_not_called()


class UnknownFormatFallbackTests(unittest.TestCase):
    def test_core_unknown_error_still_uses_conversion_and_requires_user_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.json"; source.write_text('{"messages": []}')
            converted = root / "converted.json"; converted.write_text('{}')
            host = Manager.__new__(Manager); host.root = root; host.port = 12345; host.locale = 'en-US'; host.uploaded = {}
            host.secrets = SimpleNamespace(get=lambda name: 'local-key')
            host.core_request = Mock(return_value={})
            host._convert_unknown_import = Mock(return_value=converted)
            host._upload_import_file = Mock(return_value={'uploaded':[{'saved_as':'converted-upload.json','format':'afterglow_v1','error':'',
                   'candidates':[{'uid':'a','name':'Alice','role_hint':'unknown'},{'uid':'b','name':'Bob','role_hint':'unknown'}]}]})
            connection = Mock()
            connection.getresponse.return_value = SimpleNamespace(status=200, read=lambda limit: json.dumps({'uploaded':[
                {'saved_as':'original-upload.json','format':'unknown','error':'No import extension recognizes this chat file.'}]}).encode())
            with patch('desktop_host.host.http.client.HTTPConnection',return_value=connection):
                result = host.inspect_files({'paths':[str(source)]})
            host._convert_unknown_import.assert_called_once_with(source)
            record = result['uploaded'][0]
            self.assertTrue(record['ai_converted'])
            self.assertEqual({c['role_hint'] for c in record['candidates']},{'unknown'})
            self.assertEqual(record['name'],'source.json')
            # Inspection never starts import, even after creating the extension.
            self.assertEqual(host.core_request.call_args_list[0].args,('/readyz',))
            self.assertEqual(host.core_request.call_count,1)
