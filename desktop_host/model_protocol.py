"""Translate the desktop's Chat Completions contract at the upstream boundary."""
import json


def prepare_request(profile, payload):
    if profile.get('protocol', 'chat_completions') != 'responses':
        return '/chat/completions', payload
    items = []
    for message in payload.get('messages', []):
        if message.get('role') == 'tool':
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': message.get('content') or ''})
            continue
        content = message.get('content')
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get('type') == 'text':
                    parts.append({'type': 'output_text' if message['role'] == 'assistant' else 'input_text', 'text': part['text']})
                elif part.get('type') == 'image_url':
                    image = part['image_url']
                    parts.append({'type': 'input_image', 'image_url': image['url'], **({'detail': image['detail']} if 'detail' in image else {})})
                else:
                    raise ValueError('Unsupported content for Responses API')
            content = parts
        if content is not None:
            items.append({'role': message['role'], 'content': content})
        for call in message.get('tool_calls', []):
            items.append({'type': 'function_call', 'call_id': call['id'], **call['function']})
    result = {'model': payload['model'], 'input': items, 'store': False}
    for name in ('temperature', 'top_p', 'stream', 'parallel_tool_calls'):
        if name in payload:
            result[name] = payload[name]
    if 'max_completion_tokens' in payload or 'max_tokens' in payload:
        result['max_output_tokens'] = payload.get('max_completion_tokens', payload.get('max_tokens'))
    if 'response_format' in payload:
        format_ = payload['response_format']
        if format_.get('type') == 'json_schema':
            format_ = {'type': 'json_schema', **format_['json_schema']}
        result['text'] = {'format': format_}
    if 'reasoning_effort' in payload:
        result['reasoning'] = {'effort': payload['reasoning_effort']}
    if 'tools' in payload:
        result['tools'] = [{'type': 'function', **tool['function']} for tool in payload['tools']]
    if 'tool_choice' in payload:
        choice = payload['tool_choice']
        result['tool_choice'] = {'type': 'function', 'name': choice['function']['name']} if isinstance(choice, dict) else choice
    return '/responses', result


def chat_response(response):
    if response.get('error') or response.get('status') in {'failed', 'cancelled'}:
        raise ValueError('Responses API did not complete the request')
    text, calls, refusal = [], [], []
    for item in response.get('output', []):
        if item.get('type') == 'message':
            for part in item.get('content', []):
                if part.get('type') == 'output_text':
                    text.append(part.get('text', ''))
                elif part.get('type') == 'refusal':
                    refusal.append(part.get('refusal', ''))
        elif item.get('type') == 'function_call':
            calls.append({'id': item['call_id'], 'type': 'function', 'function': {'name': item['name'], 'arguments': item['arguments']}})
    if not text and not calls and not refusal:
        raise ValueError('Responses API returned no message')
    message = {'role': 'assistant', 'content': ''.join(text) or None}
    if calls:
        message['tool_calls'] = calls
    if refusal:
        message['refusal'] = ''.join(refusal)
    result = {'id': response.get('id', 'desktop-response'), 'object': 'chat.completion',
              'created': response.get('created_at', 0), 'model': response.get('model', ''),
              'choices': [{'index': 0, 'message': message, 'finish_reason': 'length' if response.get('status') == 'incomplete' else 'tool_calls' if calls else 'stop'}]}
    if isinstance(response.get('usage'), dict):
        usage = response['usage']
        result['usage'] = {'prompt_tokens': usage.get('input_tokens', 0), 'completion_tokens': usage.get('output_tokens', 0), 'total_tokens': usage.get('total_tokens', 0)}
    return result


def stream_chunks(response):
    """Convert Responses text SSE into Chat Completions SSE incrementally."""
    metadata = {'id': 'desktop-response', 'object': 'chat.completion.chunk', 'created': 0, 'model': ''}
    tool_indices = {}
    def chunk(delta, finish=None):
        return ('data: ' + json.dumps({**metadata, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode()
    data = []
    for raw in response:
        line = raw.decode('utf-8').rstrip('\r\n')
        if line.startswith('data:'):
            data.append(line[5:].lstrip())
        elif not line and data:
            event = json.loads('\n'.join(data)); data = []
            kind = event.get('type')
            if kind == 'response.created':
                value = event.get('response', {})
                metadata.update(id=value.get('id', metadata['id']), model=value.get('model', ''), created=value.get('created_at', 0))
                yield chunk({'role': 'assistant', 'content': ''})
            elif kind == 'response.output_text.delta':
                yield chunk({'content': event['delta']})
            elif kind == 'response.refusal.delta':
                yield chunk({'refusal': event['delta']})
            elif kind == 'response.output_item.added' and event.get('item', {}).get('type') == 'function_call':
                item = event['item']
                index = len(tool_indices)
                tool_indices[event['output_index']] = index
                yield chunk({'tool_calls': [{'index': index, 'id': item['call_id'], 'type': 'function', 'function': {'name': item['name'], 'arguments': item.get('arguments', '')}}]})
            elif kind == 'response.function_call_arguments.delta':
                if event.get('output_index') not in tool_indices:
                    raise ValueError('Responses stream contains an unknown tool call')
                yield chunk({'tool_calls': [{'index': tool_indices[event['output_index']], 'function': {'arguments': event['delta']}}]})
            elif kind in {'error', 'response.failed'}:
                raise ValueError('Responses API stream failed')
            elif kind in {'response.completed', 'response.incomplete'}:
                yield chunk({}, 'length' if kind == 'response.incomplete' else 'tool_calls' if tool_indices else 'stop')
                yield b'data: [DONE]\n\n'
                return
    raise ValueError('Responses API stream ended before completion')
