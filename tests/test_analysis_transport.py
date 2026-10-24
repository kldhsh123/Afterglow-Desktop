"""Source regression cases; execution is left to the user's verification run."""
import unittest

from desktop_host.analysis_transport import ANALYSIS_OUTPUT_TOKEN_LIMIT, AnalysisTrace, analysis_request, analysis_response


class AnalysisTransportTests(unittest.TestCase):
    def test_structured_analysis_uses_existing_non_thinking_mode_only_on_official_preset(self):
        payload = {'messages': [{'role': 'user', 'content': 'private'}], 'max_tokens': 6000}
        profile = {'channel': 'deepseek', 'model': 'deepseek-v4-pro', 'protocol': 'chat_completions'}
        request = analysis_request(profile, payload)
        self.assertEqual(request['max_tokens'], ANALYSIS_OUTPUT_TOKEN_LIMIT)
        self.assertEqual(request['thinking'], {'type': 'disabled'})
        self.assertNotIn('thinking', payload)
        responses = analysis_request({**profile, 'protocol': 'responses'}, payload)
        self.assertEqual(responses['max_tokens'], ANALYSIS_OUTPUT_TOKEN_LIMIT)
        self.assertEqual(responses['reasoning_effort'], 'none')
        custom = analysis_request({**profile, 'channel': 'custom'}, payload)
        self.assertEqual(custom['max_tokens'], ANALYSIS_OUTPUT_TOKEN_LIMIT)
        self.assertNotIn('thinking', custom)

    def test_reasoning_is_diagnostic_evidence_never_used_as_final_text(self):
        data = {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'PRIVATE'}}],
                'usage': {'completion_tokens': 6000, 'completion_tokens_details': {'reasoning_tokens': 6000}}}
        result, diagnostic = analysis_response(data, 'chat_completions')
        self.assertIsNone(result)
        self.assertEqual(diagnostic['reason'], 'output_limit')
        self.assertTrue(diagnostic['reasoning_present'])
        self.assertEqual(diagnostic['reasoning_tokens'], 6000)
        self.assertNotIn('PRIVATE', str(diagnostic))

    def test_empty_reasoning_only_and_malformed_responses_have_distinct_reasons(self):
        for data, reason in [
            ({'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}, 'empty'),
            ({'choices': [{'message': {'content': None, 'reasoning_content': 'PRIVATE'}}]}, 'reasoning_only'),
            ({'choices': []}, 'invalid_response'),
            ({'error': {'message': 'PRIVATE'}}, 'invalid_response'),
        ]:
            with self.subTest(reason=reason):
                result, diagnostic = analysis_response(data, 'chat_completions')
                self.assertIsNone(result)
                self.assertEqual(diagnostic['reason'], reason)
                self.assertNotIn('PRIVATE', str(diagnostic))

    def test_responses_output_limit_preserves_reasoning_usage(self):
        data = {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                'output': [{'type': 'reasoning', 'summary': [{'text': 'PRIVATE'}]}],
                'usage': {'output_tokens': 6000, 'output_tokens_details': {'reasoning_tokens': 6000}}}
        result, diagnostic = analysis_response(data, 'responses')
        self.assertIsNone(result)
        self.assertEqual(diagnostic['reason'], 'output_limit')
        self.assertEqual(diagnostic['completion_tokens'], 6000)
        self.assertEqual(diagnostic['reasoning_tokens'], 6000)
        self.assertNotIn('PRIVATE', str(diagnostic))

    def test_final_text_parts_are_normalized_but_refusals_are_not_analysis(self):
        data = {'choices': [{'message': {'content': [{'type': 'text', 'text': '{"events": []}'}]}}]}
        result, diagnostic = analysis_response(data, 'chat_completions')
        self.assertEqual(result['choices'][0]['message']['content'], '{"events": []}')
        self.assertEqual(diagnostic['reason'], 'ok')
        self.assertIsInstance(data['choices'][0]['message']['content'], list)
        data['choices'][0]['message']['refusal'] = 'PRIVATE'
        self.assertEqual(analysis_response(data, 'chat_completions')[1]['reason'], 'refused')

    def test_trace_is_bound_to_task_and_ignores_late_previous_run_responses(self):
        trace = AnalysisTrace()
        first = trace.begin(); trace.bind(first, 'old')
        trace.record(first, {'reason': 'empty'})
        second = trace.begin()
        trace.record(second, {'reason': 'ok'})  # A response can precede /start's reply.
        trace.bind(second, 'new')
        trace.record(first, {'reason': 'refused'})
        self.assertEqual(trace.snapshot('old'), [])
        self.assertEqual(trace.snapshot('new'), [{'reason': 'ok'}])
        copied = trace.snapshot('new'); copied[0]['reason'] = 'changed'
        self.assertEqual(trace.snapshot('new')[0]['reason'], 'ok')
