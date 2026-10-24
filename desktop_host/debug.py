"""Desktop access to the installed core's existing debug interfaces."""
import json
import os
from pathlib import Path
import re
import tempfile

try:
    from .i18n import tr
except ImportError:
    from i18n import tr


def debug_preferences(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or any(type(value.get(key, False)) is not bool for key in ('enabled', 'fullPayloads')):
        raise ValueError(tr('debug.invalid_preferences'))
    return {'enabled': value.get('enabled') is True,
            'fullPayloads': value.get('enabled') is True and value.get('fullPayloads') is True}


def debug_environment(preferences):
    value = debug_preferences(preferences)
    return {'DEBUG_ENDPOINTS_ENABLED': str(value['enabled']).lower(),
            'DEBUG_MODEL_FULL_PAYLOADS_ENABLED': str(value['fullPayloads']).lower()}


def sync_debug_environment(root: Path, preferences):
    """Change only our two keys; retain unrelated configuration and comments."""
    path = root / 'profiles' / 'default' / 'core' / '.env'
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    values = debug_environment(preferences)
    lines, found = [], set()
    for line in content.splitlines():
        match = re.match(r'^\s*(?:export\s+)?(DEBUG_ENDPOINTS_ENABLED|DEBUG_MODEL_FULL_PAYLOADS_ENABLED)\s*=', line)
        if match:
            key = match[1]
            if key not in found:
                lines.append(key + '=' + values[key])
                found.add(key)
        else:
            lines.append(line)
    lines.extend(key + '=' + value for key, value in values.items() if key not in found)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=path.parent,
                                         prefix='.env-debug-', delete=False) as output:
            temporary = Path(output.name)
            output.write('\n'.join(lines) + '\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Debug:
    def __init__(self, manager):
        self.manager = manager

    def dispatch(self, method, args):
        manager = self.manager
        desired = debug_preferences((manager.settings() or {}).get('debug'))
        applied = debug_preferences((getattr(manager, 'pending_settings', None) or {}).get('debug'))
        if not desired['enabled']:
            raise ValueError(tr('debug.disabled'))
        if not applied['enabled']:
            raise ValueError(tr('debug.apply_required'))
        if method == 'debug_snapshot':
            stats = manager.core_request('/debug/stats', timeout=20)
            config = manager.core_request('/debug/config', timeout=20)
            if not (desired['fullPayloads'] and applied['fullPayloads']):
                for record in stats.get('model_chain', []):
                    record['request'] = {}
                    record['response'] = {}
            # Core credentials are normally local gateway tokens; redact both
            # those and real upstream keys before sending diagnostics to Vue.
            return json.loads(manager.redact(json.dumps({'stats': stats, 'config': config}, ensure_ascii=False)))
        if method == 'debug_reset_metrics':
            return manager.core_request('/debug/metrics/reset', {}, timeout=20)
        conversation_id = args.get('conversationId')
        scope = None
        if conversation_id:
            manager.chat_store.get(conversation_id)
            scope = 'desktop:' + conversation_id
        if method == 'debug_search':
            query, top_k = args.get('query'), args.get('topK', 12)
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 4000 or type(top_k) is not int or not 1 <= top_k <= 50:
                raise ValueError(tr('debug.invalid_search'))
            result = manager.core_request('/memory/search', {'query': query.strip(), 'top_k': top_k,
                                                           'conversation_id': scope})
        elif method == 'debug_proactive':
            if scope is None:
                raise ValueError(tr('debug.conversation_required'))
            if manager.identity_needs_restart():
                raise ValueError(tr('analysis.restart_identity'))
            fields = {}
            for field, maximum in [('reason', 100), ('private_context', 8000), ('topic_hint', 2000)]:
                value = args.get(field, 'manual' if field == 'reason' else '')
                if not isinstance(value, str) or len(value) > maximum:
                    raise ValueError(tr('debug.invalid_proactive'))
                fields[field] = value
            result = manager.core_request('/v1/companion/proactive', {'conversation_id': scope, **fields})
        else:
            raise ValueError(tr('host.unsupported_manager_operation'))
        return json.loads(manager.redact(json.dumps(result, ensure_ascii=False)))
