import io
import json
import unittest

from desktop_host.model_protocol import prepare_request, chat_response, stream_chunks


class ModelProtocolTests(unittest.TestCase):
    def test_chat_completions_is_the_backwards_compatible_default(self):
        payload = {'model': 'chosen', 'messages': []}
        self.assertEqual(prepare_request({}, payload), ('/chat/completions', payload))

    def test_responses_maps_images_json_schema_and_token_limit(self):
        endpoint, payload = prepare_request({'protocol': 'responses'}, {
            'model': 'chosen', 'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': 'Describe'}, {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,fixture'}}]}],
            'max_tokens': 100, 'response_format': {'type': 'json_schema', 'json_schema': {'name': 'mapping', 'schema': {'type': 'object'}}},
        })
        self.assertEqual(endpoint, '/responses')
        self.assertEqual(payload['input'][0]['content'][1]['type'], 'input_image')
        self.assertEqual(payload['text']['format']['name'], 'mapping')
        self.assertEqual(payload['max_output_tokens'], 100)
        self.assertNotIn('messages', payload)
        self.assertFalse(payload['store'])

    def test_reasoning_output_is_not_mixed_into_visible_reply(self):
        response = {'status': 'completed', 'output': [{'type': 'reasoning', 'summary': []},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Visible'}]}],
            'usage': {'input_tokens': 5, 'output_tokens': 3, 'total_tokens': 8}}
        result = chat_response(response)
        self.assertEqual(result['choices'][0]['message']['content'], 'Visible')
        self.assertEqual(result['usage']['total_tokens'], 8)
        with self.assertRaises(ValueError): chat_response({'status': 'failed'})

    def test_stream_preserves_text_deltas_and_rejects_truncated_completion(self):
        events = [{'type': 'response.created', 'response': {'id': 'resp1', 'model': 'chosen'}},
                  {'type': 'response.output_text.delta', 'delta': 'Hello'},
                  {'type': 'response.completed', 'response': {'status': 'completed'}}]
        source = io.BytesIO(''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode())
        chunks = b''.join(stream_chunks(source))
        self.assertIn(b'Hello', chunks)
        self.assertTrue(chunks.endswith(b'data: [DONE]\n\n'))
        with self.assertRaises(ValueError): list(stream_chunks(io.BytesIO(b'')))

    def test_stream_preserves_function_calls_and_arguments(self):
        events = [
            {'type': 'response.output_item.added', 'output_index': 1, 'item': {'type': 'function_call', 'call_id': 'call1', 'name': 'lookup', 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta', 'output_index': 1, 'delta': '{"query":"hello"}'},
            {'type': 'response.completed', 'response': {'status': 'completed'}},
        ]
        source = io.BytesIO(''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode())
        chunks = b''.join(stream_chunks(source))
        self.assertIn(b'call1', chunks)
        self.assertIn(b'lookup', chunks)
        self.assertIn(b'"finish_reason": "tool_calls"', chunks)
