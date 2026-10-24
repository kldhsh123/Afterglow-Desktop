"""Adapt structured offline requests and retain metadata, never private output.

The original core still owns batching, prompts, parsing and report generation.
The gateway does not retry requests here; it does reserve a larger output
ceiling for structured analysis so reasoning cannot consume the whole budget.
"""
import threading
import uuid

try:
    from .model_protocol import chat_response
except ImportError:
    from model_protocol import chat_response


# Analysis blocks can contain many structured findings. The original core's
# default is 6,000 tokens, which can be consumed by reasoning before the final
# JSON is emitted. Raise the ceiling for analysis only; chat replies and import
# conversion keep their own limits.
ANALYSIS_OUTPUT_TOKEN_LIMIT = 20_000


def analysis_request(profile, payload):
    result = dict(payload)
    requested = result.get('max_completion_tokens', result.get('max_tokens'))
    if isinstance(requested, int) and requested < ANALYSIS_OUTPUT_TOKEN_LIMIT:
        if 'max_completion_tokens' in result:
            result['max_completion_tokens'] = ANALYSIS_OUTPUT_TOKEN_LIMIT
        else:
            result['max_tokens'] = ANALYSIS_OUTPUT_TOKEN_LIMIT
    # Same opt-out as the existing import mapping adapter, only for the built-in
    # DeepSeek v4 preset. A custom channel never receives vendor-specific fields.
    if profile.get('channel') == 'deepseek' and profile.get('model', '').startswith('deepseek-v4-'):
        if profile.get('protocol') == 'responses':
            result['reasoning_effort'] = 'none'
        else:
            result['thinking'] = {'type': 'disabled'}
    return result


def analysis_response(data, protocol):
    """Return usable final text or a classified failure without leaking content."""
    diagnostic = {'protocol': protocol, 'reason': 'invalid_response', 'content_chars': 0,
                  'reasoning_present': False}
    if not isinstance(data, dict):
        return None, diagnostic
    usage = data.get('usage')
    if isinstance(usage, dict):
        output = 'output_tokens' if protocol == 'responses' else 'completion_tokens'
        details = usage.get(output + '_details')
        for key, value in [('completion_tokens', usage.get(output)),
                           ('reasoning_tokens', details.get('reasoning_tokens') if isinstance(details, dict) else None)]:
            if type(value) is int and value >= 0:
                diagnostic[key] = value
        diagnostic['reasoning_present'] = bool(diagnostic.get('reasoning_tokens'))
    normalized = data
    if protocol == 'responses':
        output = data.get('output')
        if isinstance(output, list):
            diagnostic['reasoning_present'] |= any(isinstance(item, dict) and item.get('type') == 'reasoning' for item in output)
        status = data.get('status')
        diagnostic['finish_reason'] = status if status in {'completed', 'incomplete', 'failed', 'cancelled'} else 'unknown'
        if status == 'incomplete':
            details = data.get('incomplete_details')
            diagnostic['reason'] = 'output_limit' if isinstance(details, dict) and details.get('reason') == 'max_output_tokens' else 'incomplete'
            return None, diagnostic
        if data.get('error') or status in {'failed', 'cancelled'}:
            return None, diagnostic
        try:
            normalized = chat_response(data)
        except (ValueError, KeyError, TypeError, AttributeError):
            diagnostic['reason'] = 'reasoning_only' if diagnostic['reasoning_present'] else 'empty' if isinstance(output, list) else 'invalid_response'
            return None, diagnostic
    if normalized.get('error'):
        return None, diagnostic
    choices = normalized.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, diagnostic
    choice = choices[0]
    message = choice.get('message')
    if not isinstance(message, dict):
        return None, diagnostic
    finish = choice.get('finish_reason')
    if protocol != 'responses':
        diagnostic['finish_reason'] = finish if finish in {'stop', 'length', 'content_filter', 'tool_calls', 'function_call'} else 'unknown'
    diagnostic['reasoning_present'] |= bool(message.get('reasoning_content') or message.get('reasoning'))
    content = message.get('content')
    if isinstance(content, list):
        content = ''.join(part['text'] for part in content if isinstance(part, dict)
                          and part.get('type') in {'text', 'output_text'} and isinstance(part.get('text'), str))
    if isinstance(content, str):
        diagnostic['content_chars'] = len(content)
    if message.get('refusal') or finish == 'content_filter':
        diagnostic['reason'] = 'refused'
    elif finish == 'length':
        diagnostic['reason'] = 'output_limit'
    elif isinstance(content, str) and content.strip():
        diagnostic['reason'] = 'ok'
        return {**normalized, 'choices': [{**choice, 'message': {**message, 'content': content}}, *choices[1:]]}, diagnostic
    else:
        diagnostic['reason'] = 'reasoning_only' if diagnostic['reasoning_present'] else 'empty'
    return None, diagnostic


class AnalysisTrace:
    """Track one analysis run; late responses cannot contaminate the next run."""
    def __init__(self):
        self._lock = threading.Lock()
        self._run = None
        self._task = None
        self._responses = []

    def begin(self):
        with self._lock:
            self._run, self._task, self._responses = uuid.uuid4().hex, None, []
            return self._run

    def bind(self, run, task):
        with self._lock:
            if run == self._run:
                self._task = task

    def current(self):
        with self._lock:
            return self._run

    def record(self, run, diagnostic):
        with self._lock:
            if run is not None and run == self._run:
                self._responses.append(dict(diagnostic))
                del self._responses[:-120]

    def snapshot(self, task):
        with self._lock:
            return [dict(item) for item in self._responses] if task is not None and task == self._task else []
