import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop_host.import_conversion import convert, make_sample, validate_spec, format_signature, read_export, describe_structure, MAX_EXPORT_BYTES
from desktop_host.model_gateway import ModelBudget
from desktop_host.host import Manager
from desktop_host.storage import read_json


class ImportConversionTests(unittest.TestCase):
    def test_malformed_json_reaches_model_analysis_and_preserves_the_whole_source(self):
        text = '{"sender":"Alice","timestamp":1700000000,"text":"Hi"}\n{"sender":"Bob","timestamp":1700000001,"text":"Hello"}\nExport completed.'
        mapping = {'format': 'text', 'record_pattern': r'^\{"sender":"(?P<sender_name>[^"]+)","timestamp":(?P<timestamp>\d+),"text":"(?P<text>[^"]+)"\}$'}
        response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'choices': [{'message': {'content': json.dumps(mapping)}, 'finish_reason': 'stop'}]}).encode()
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory); host.budget = ModelBudget()
            host.settings = Mock(return_value={'version': 1, 'preset': 'quick', 'providers': {'deepseek': {'channel': 'custom', 'baseUrl': 'https://model.example/v1', 'model': 'fixture-model'}}})
            host.model_key = Mock(return_value='fixture-key')
            source = host.root / 'malformed.json'; source.write_text(text)
            with patch('desktop_host.host.urllib.request.urlopen', return_value=response) as upstream:
                output = host._convert_unknown_import(source)
            self.assertEqual(len(read_json(output)['messages']), 2)
            self.assertEqual(upstream.call_count, 1)
            prompt = json.loads(upstream.call_args.args[0].data)['messages'][1]['content']
            self.assertIn('Export completed.', prompt)
            self.assertEqual(source.read_text(), text)

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '开发缓存/test_synapse_chat.json').is_file(), 'Development export is not present')
    def test_development_synapse_export_converts_locally_with_mocked_mapping(self):
        source = Path(__file__).resolve().parents[1] / '开发缓存/test_synapse_chat.json'
        mapping = {'messages_path': '/chat_records', 'sender_id': 'sender.user_id', 'sender_name': 'sender.name', 'text': 'body', 'timestamp': 'timestamp_ms'}
        response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'choices': [{'message': {'content': '```json\n' + json.dumps(mapping) + '\n```'}, 'finish_reason': 'stop'}]}).encode()
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory); host.budget = ModelBudget()
            host.settings = Mock(return_value={'version': 1, 'preset': 'quick', 'providers': {'deepseek': {'channel': 'custom', 'baseUrl': 'https://model.example/v1', 'model': 'fixture-model'}}})
            host.model_key = Mock(return_value='fixture-key')
            with patch('desktop_host.host.urllib.request.urlopen', return_value=response) as upstream:
                output = host._convert_unknown_import(source)
            result = read_json(output)
            self.assertEqual(len(result['messages']), 1000)
            self.assertEqual(result['desktop_conversion']['source_records'], 1005)
            self.assertEqual(result['desktop_conversion']['skipped_records'], 5)
            self.assertEqual({p['role'] for p in result['participants']}, {'unknown'})
            self.assertEqual(upstream.call_count, 1)
            self.assertNotIn('thinking', json.loads(upstream.call_args.args[0].data))

    def test_empty_reasoning_response_retries_with_more_output_budget(self):
        payload = [{'uid': 'a', 'text': 'First', 'time': 1700000000}, {'uid': 'b', 'text': 'Second', 'time': 1700000001}]
        mapping = {'messages_path': '', 'sender_id': 'uid', 'text': 'text', 'timestamp': 'time'}
        replies = []
        for answer in [
            {'choices': [{'message': {'content': '', 'reasoning_content': 'PRIVATE REASONING MUST NOT BECOME A MAPPING'}, 'finish_reason': 'length'}]},
            {'choices': [{'message': {'content': '```json\n' + json.dumps(mapping) + '\n```'}, 'finish_reason': 'stop'}]},
        ]:
            response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
            response.read.return_value = json.dumps(answer).encode(); replies.append(response)
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory); host.budget = ModelBudget()
            host.settings = Mock(return_value={'version': 1, 'preset': 'quick', 'providers': {'deepseek': {'channel': 'deepseek', 'model': 'deepseek-v4-pro'}}})
            host.model_key = Mock(return_value='fixture-key')
            path = host.root / 'unknown.json'; path.write_text(json.dumps(payload))
            with patch('desktop_host.host.urllib.request.urlopen', side_effect=replies) as upstream:
                output = host._convert_unknown_import(path)
            self.assertEqual(len(read_json(output)['messages']), 2)
            requests = [json.loads(call.args[0].data) for call in upstream.call_args_list]
            self.assertEqual(requests[0]['thinking'], {'type': 'disabled'})
            self.assertGreater(requests[1]['max_tokens'], requests[0]['max_tokens'])
            self.assertNotIn('PRIVATE REASONING', json.dumps(requests[1]))
            self.assertEqual({p['role'] for p in read_json(output)['participants']}, {'unknown'})

    def test_repeated_empty_response_has_a_useful_error_instead_of_json_decoder_details(self):
        payload = [{'uid': 'a', 'text': 'First', 'time': 1700000000}, {'uid': 'b', 'text': 'Second', 'time': 1700000001}]
        response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}).encode()
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory); host.budget = ModelBudget()
            host.settings = Mock(return_value={'version': 1, 'preset': 'quick', 'providers': {'deepseek': {'channel': 'custom', 'baseUrl': 'https://model.example/v1', 'model': 'user-model'}}})
            host.model_key = Mock(return_value='fixture-key')
            path = host.root / 'unknown.json'; path.write_text(json.dumps(payload))
            with patch('desktop_host.host.urllib.request.urlopen', return_value=response) as upstream:
                with self.assertRaises(ValueError) as caught: host._convert_unknown_import(path)
            self.assertNotIn('Expecting value', str(caught.exception))
            self.assertTrue('empty' in str(caught.exception).lower() or '空' in str(caught.exception))
            self.assertEqual(upstream.call_count, 2)
            self.assertFalse((host.root / 'import-conversions').exists())

    def test_responses_incomplete_answer_retries_without_parsing_reasoning(self):
        payload = [{'uid': 'a', 'text': 'First', 'time': 1700000000}, {'uid': 'b', 'text': 'Second', 'time': 1700000001}]
        mapping = {'messages_path': '', 'sender_id': 'uid', 'text': 'text', 'timestamp': 'time'}
        replies = []
        for answer in [
            {'status': 'incomplete', 'output': [{'type': 'reasoning', 'summary': []}]},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(mapping)}]}]},
        ]:
            response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
            response.read.return_value = json.dumps(answer).encode(); replies.append(response)
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory); host.budget = ModelBudget()
            host.settings = Mock(return_value={'version': 1, 'preset': 'quick', 'providers': {'deepseek': {'channel': 'deepseek', 'protocol': 'responses', 'model': 'deepseek-v4-pro'}}})
            host.model_key = Mock(return_value='fixture-key')
            path = host.root / 'unknown.json'; path.write_text(json.dumps(payload))
            with patch('desktop_host.host.urllib.request.urlopen', side_effect=replies) as upstream:
                output = host._convert_unknown_import(path)
            self.assertEqual(len(read_json(output)['messages']), 2)
            requests = [json.loads(call.args[0].data) for call in upstream.call_args_list]
            self.assertEqual(requests[0]['reasoning'], {'effort': 'none'})
            self.assertEqual(requests[0]['max_output_tokens'], 4096)
            self.assertEqual(requests[1]['max_output_tokens'], 8192)
            self.assertTrue(all(call.args[0].full_url.endswith('/responses') for call in upstream.call_args_list))

    def test_unknown_export_repairs_incorrect_container_mapping(self):
        payload = {'conversation': {'participants': [{'id': 'a'}, {'id': 'b'}]}, 'chat_records': [
            {'sender': {'user_id': 'a', 'name': 'Alice'}, 'body': 'Hi', 'timestamp_ms': 1700000000000},
            {'sender': {'user_id': 'b', 'name': 'Bob'}, 'body': 'Hello', 'timestamp_ms': 1700000001000},
            {'sender': None, 'body': 'System event', 'timestamp_ms': 1700000002000},
        ]}
        self.assertIn('/chat_records: array, 3 entries', describe_structure(payload))
        self.assertNotIn('System event', describe_structure(payload))
        mapping = {'messages_path': '/chat_records', 'sender_id': 'sender.user_id', 'sender_name': 'sender.name', 'text': 'body', 'timestamp': 'timestamp_ms'}
        replies = []
        for spec in ({**mapping, 'messages_path': 'messages'}, mapping):
            response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
            response.read.return_value = json.dumps({'choices': [{'message': {'content': json.dumps(spec)}}]}).encode()
            replies.append(response)
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory); host.budget = ModelBudget()
            host.settings = Mock(return_value={'version': 1, 'preset': 'quick', 'providers': {'deepseek': {'channel': 'custom', 'baseUrl': 'https://model.example/v1', 'model': 'test-model'}}})
            host.model_key = Mock(return_value='local-test-key')
            path = host.root / 'example.json'; path.write_text(json.dumps(payload))
            with patch('desktop_host.host.urllib.request.urlopen', side_effect=replies) as upstream:
                output = host._convert_unknown_import(path)
            self.assertEqual(upstream.call_count, 2)
            sent = json.loads(upstream.call_args_list[0].args[0].data)
            self.assertIn('/chat_records', sent['messages'][1]['content'])
            result = read_json(output)
            self.assertEqual(len(result['messages']), 2)
            self.assertEqual(result['desktop_conversion']['skipped_records'], 1)
            self.assertEqual({p['role'] for p in result['participants']}, {'unknown'})

    def test_declarative_mapping_converts_records_and_keeps_roles_unknown(self):
        payload = {"messages": [
            {"from": {"id": "a", "name": "Alice"}, "body": "Hi", "time": 1700000000},
            {"from": {"id": "b", "name": "Bob"}, "body": "Hello", "time": 1700000001},
        ]}
        spec = validate_spec({"messages_path": "messages", "sender_id": "from.id", "sender_name": "from.name", "text": "body", "timestamp": "time"})
        result = convert(payload, payload["messages"], spec, "conversation")
        self.assertEqual(result["messages"][0]["timestamp_ms"], 1700000000000)
        self.assertEqual({p["role"] for p in result["participants"]}, {"unknown"})
        self.assertEqual(result["participants"][0]["uid"], "a")

    def test_unicode_pointer_paths_zero_uid_default_kind_and_stable_ids(self):
        payload = {"聊天记录": [
            {"发送 人": {"账号.id": 0}, "消息": "Hi", "时间": 1700000000},
            {"发送 人": {"账号.id": 1}, "消息": "Hello", "时间": 1700000001},
        ]}
        spec = validate_spec({"messages_path": "$.聊天记录", "sender_id": "/发送 人/账号.id", "text": "消息", "timestamp": "时间"})
        first = convert(payload, [], spec, "first")
        second = convert(payload, [], spec, "second")
        self.assertEqual(first["messages"][0]["sender_uid"], "0")
        self.assertEqual(first["messages"][0]["kind"], "text")
        self.assertEqual(first["messages"][0]["id"], second["messages"][0]["id"])
        self.assertNotEqual(first["messages"][0]["id"], first["messages"][1]["id"])
        self.assertEqual(first["desktop_conversion"]["skipped_records"], 0)
        self.assertTrue(all("sender_role" not in m for m in first["messages"]))

    def test_large_json_header_does_not_swallow_random_records_or_cut_json(self):
        records = [{"text": "x" * 800} for _ in range(500)]
        sample = make_sample(json.dumps({"messages": records}), records)
        self.assertLessEqual(len(sample), 48000)
        selected = [line.split("] ", 1)[1] for line in sample.splitlines() if line.startswith("[record ")]
        self.assertGreater(len(selected), 30)
        self.assertTrue(all(isinstance(json.loads(item), dict) for item in selected))

    def test_invalid_paths_are_rejected_consistently(self):
        with self.assertRaises(ValueError):
            validate_spec({"messages_path": "$messages", "sender_id": "id", "text": "text", "timestamp": "time"})

    def test_saved_rule_is_reused_for_another_file_of_the_same_structure(self):
        first = [{'uid': 'a', 'text': 'First', 'time': 1700000000}, {'uid': 'b', 'text': 'Second', 'time': 1700000001}]
        second = [{'uid': 'c', 'text': 'New text', 'time': 1700000100}, {'uid': 'd', 'text': 'Another text', 'time': 1700000101}]
        self.assertEqual(format_signature(first, first), format_signature(second, second))
        with tempfile.TemporaryDirectory() as directory:
            host = Manager.__new__(Manager); host.root = Path(directory)
            host.settings = Mock(side_effect=AssertionError('A compatible local rule must not call a model'))
            spec = validate_spec({'messages_path': '', 'sender_id': 'uid', 'text': 'text', 'timestamp': 'time'})
            host._save_converted_import(host.root / 'import-conversions/first.json', convert(first, first, spec, 'first'), spec, 'user-model', format_signature(first, first))
            source = host.root / 'second.json'; source.write_text(json.dumps(second))
            output = host._convert_unknown_import(source)
            metadata = read_json(output.with_suffix('.mapping.json'))
            self.assertTrue(metadata['reused'])
            self.assertEqual(metadata['identity_previews'], {'c': 'New text', 'd': 'Another text'})
            self.assertEqual({p['role'] for p in read_json(output)['participants']}, {'unknown'})
            with self.assertRaises(AssertionError): host._convert_unknown_import(source, force_analysis=True)

    def test_oversized_unknown_exports_fail_before_loading_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'large.json'
            with path.open('wb') as stream: stream.truncate(MAX_EXPORT_BYTES + 1)
            with self.assertRaises(ValueError): read_export(path)

    def test_text_rule_preserves_roles_and_handles_explicit_date_format(self):
        text = "2026/01/01 12:00 Alice: Hello\n2026/01/01 12:01 Bob: Hi"
        spec = validate_spec({"format": "text", "record_pattern": r"^(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}) (?P<sender_name>[^:]+): (?P<text>[^\n]+)$", "timestamp_format": "%Y/%m/%d %H:%M"})
        result = convert({"_text": text}, [], spec, "conversation")
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual({p["role"] for p in result["participants"]}, {"unknown"})
        self.assertEqual(result["messages"][0]["kind"], "text")
        self.assertGreater(result["messages"][1]["timestamp_ms"], result["messages"][0]["timestamp_ms"])

    def test_mapping_does_not_allow_code_or_unusable_fields(self):
        with self.assertRaises(ValueError):
            validate_spec({"messages_path": "__import__('os')", "sender_id": "id", "text": "text", "timestamp": "time"})
        with self.assertRaises(ValueError):
            validate_spec({"messages_path": "messages", "sender_id": "id", "text": "text"})

    def test_random_sample_contains_at_most_300_later_lines(self):
        sample = make_sample("\n".join(f"line-{i}" for i in range(500)))
        self.assertIn("[line 1] line-0", sample)
        self.assertIn("[line 20] line-19", sample)
        self.assertEqual(sample.count("[line "), 320)

    def test_json_record_sampling_keeps_complete_records_and_caps_count(self):
        records = [{"message": f"value-{i}"} for i in range(500)]
        sample = make_sample('{"messages":[]}', records)
        sampled = [line for line in sample.splitlines() if line.startswith("[record ")]
        self.assertEqual(len(sampled), 300)
        self.assertTrue(all(line.endswith("}") for line in sampled))


if __name__ == "__main__":
    unittest.main()
