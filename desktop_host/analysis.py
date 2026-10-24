"""Desktop controls for the original core's analysis task interface."""
import re
import threading
import uuid
from datetime import date

try:
    from .i18n import tr
    from .storage import atomic_json, read_json
except ImportError:
    from i18n import tr
    from storage import atomic_json, read_json


class Analysis:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.root
        self.guard = threading.RLock()

    def prompt_artifacts(self):
        """Gate each opt-in on the actual artifact consumed by the core.

        An empty report, a completed task or an unrelated timeline is not a
        personality/life result. Never infer availability from task status.
        """
        folder = self.root / 'profiles' / 'default' / 'core' / 'data' / 'analysis'
        def artifact(name):
            try:
                value = read_json(folder / name, {})
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}
        def entries(value):
            return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        def has_claim(item):
            return isinstance(item.get('claim'), str) and bool(item['claim'].strip())
        personality = artifact('personality_report.json')
        observations = [item for section in entries(personality.get('sections'))
                        for item in entries(section.get('observations'))]
        try:
            with (folder / 'personality_prompt_context.md').open(encoding='utf-8-sig') as source:
                context = source.read(12000).strip()
        except (OSError, ValueError):
            context = ''
        life = artifact('life_profile.json')
        habits = entries(life.get('habits'))
        return {'personalityPrompt': bool(context and any(has_claim(item) for item in observations)),
                'lifeContext': any(has_claim(item) and item.get('subject') == 'friend'
                                   and item.get('sensitive_relationship_context') is not True
                                   and isinstance(item.get('target_fields'), list) and bool(item['target_fields'])
                                   for item in habits)}

    def require_prompt_artifacts(self, preferences):
        if not any(preferences.values()):
            return
        available = self.prompt_artifacts()
        for key, error in [('personalityPrompt', 'analysis.personality_required'), ('lifeContext', 'analysis.life_required')]:
            if preferences.get(key) and not available[key]:
                raise ValueError(tr(error))

    def retryable_cache(self):
        """Quarantine known failed empty blocks so resume retries real failures.

        Valid blocks, source records and reports are untouched. A cached block
        with any useful partial result is retained for the original core.
        """
        folder = self.root / 'profiles' / 'default' / 'core' / 'data' / 'analysis'
        manifest = read_json(folder / 'manifest.json', {})
        if not isinstance(manifest, dict):
            return
        for item in manifest.get('skipped', []):
            block_id = item.get('block_id') if isinstance(item, dict) else None
            if not isinstance(block_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', block_id):
                continue
            path = folder / 'blocks' / (block_id + '.json')
            if not path.is_file():
                continue
            try:
                block = read_json(path)
            except (OSError, ValueError):
                continue
            fields = ('events', 'personality_observations', 'relationship_signals', 'life_habits', 'experimental_signals')
            if not isinstance(block, dict) or any(block.get(key) for key in fields):
                continue
            archive = folder / 'failures' / 'retry-cache'
            archive.mkdir(parents=True, exist_ok=True)
            path.replace(archive / (block_id + '-' + uuid.uuid4().hex + '.json'))

    def diagnostics(self, task=None):
        """Explain upstream skipped blocks without exposing their private chat inputs."""
        folder = self.root / 'profiles' / 'default' / 'core' / 'data' / 'analysis'
        task = task if task is not None else read_json(self.root / 'analysis-task.json', {})
        task = task if isinstance(task, dict) else {}
        trace = getattr(getattr(self.manager, 'gateway', None), 'analysis_trace', None)
        responses = trace.snapshot(task.get('task_id')) if trace else []
        responses = responses or task.get('model_responses', [])
        metadata = {'task_id': task.get('task_id'), 'model_responses': responses}
        if task.get('status') and task['status'] != 'done':
            # The core keeps the previous manifest until this run finishes.
            # Its counts/errors must never be presented as this run's outcome.
            return {**metadata, 'prompt_ready': self.prompt_artifacts(), 'has_reports': False,
                    'state': 'pending' if task['status'] not in {'failed', 'cancelled'} else 'empty',
                    'events': 0, 'observations': 0, 'blocks': 0, 'completed': 0, 'skipped': 0,
                    'failures': [], 'empty_reports': [], 'available_reports': [], 'directory': str(folder)}
        def artifact(name):
            try:
                value = read_json(folder / name, {})
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}
        timeline, personality = artifact('timeline.json'), artifact('personality_report.json')
        manifest = artifact('manifest.json')
        events = len(timeline.get('events') or [])
        observations = sum(len(section.get('observations') or []) for section in personality.get('sections', []) if isinstance(section, dict))
        failures = []
        for item in [*manifest.get('failed', []), *manifest.get('skipped', [])]:
            if not isinstance(item, dict):
                continue
            block_id = str(item.get('block_id', ''))
            if any(previous['block_id'] == block_id for previous in failures):
                continue
            entry = {'block_id': block_id, 'message': self.manager.redact(str(item.get('message') or item.get('error', '')))[:2000]}
            if re.fullmatch(r'[A-Za-z0-9_-]{1,160}', block_id):
                debug = artifact('failures/' + block_id + '.json')
                entry['stage'] = str(debug.get('stage', ''))[:100]
                entry['attempts'] = [{'error': self.manager.redact(str(attempt.get('error', '')))[:2000],
                                      'output_empty': not str(attempt.get('raw_output') or '').strip()}
                                     for attempt in debug.get('attempts', [])[-3:] if isinstance(attempt, dict)]
            failures.append(entry)
        targets = manifest.get('targets', [])
        validity = {name: valid for name, available, valid in [
            ('timeline', bool(timeline), bool(events or timeline.get('phases'))),
            ('personality', bool(personality), bool(observations or str(personality.get('summary', '')).strip())),
        ] if name in targets or (not targets and available)}
        empty = [name for name, valid in validity.items() if not valid]
        return {**metadata, 'prompt_ready': self.prompt_artifacts(), 'events': events, 'observations': observations, 'empty_reports': empty,
                'blocks': manifest.get('blocks', 0), 'completed': manifest.get('completed', 0),
                'skipped': len(manifest.get('skipped', [])), 'failures': failures,
                'state': 'empty' if empty and not any(validity.values()) else 'partial' if empty or failures else 'available',
                'available_reports': [name for name, present in [('timeline', bool(timeline)), ('personality', bool(personality)),
                                                                 ('proactive', bool(artifact('proactive_analysis.json')))] if present],
                'directory': str(folder), 'has_reports': bool(timeline or personality or manifest)}

    def dispatch(self, method, args):
        if method in {'analysis_start', 'analysis_status'}:
            # Serialize task-file mutations, including an old status request
            # finishing just as a new run is accepted.
            with self.guard:
                return self._dispatch(method, args)
        return self._dispatch(method, args)

    def _dispatch(self, method, args):
        manager = self.manager
        files = read_json(self.root / 'imported-files.json', [])
        if method == 'analysis_files':
            return {'files': files, 'task': read_json(self.root / 'analysis-task.json')}
        if method == 'analysis_diagnostics':
            return self.diagnostics()
        if method == 'analysis_report':
            report = args.get('report')
            if report not in {'timeline', 'personality', 'proactive'}:
                raise ValueError(tr('analysis.invalid_report'))
            return manager.core_request('/analysis/' + report)
        if method == 'analysis_start':
            if manager.identity_needs_restart():
                raise ValueError(tr('analysis.restart_identity'))
            selected = args.get('files')
            allowed = {item['saved_as'] for item in files}
            if not isinstance(selected, list) or not selected or any(not isinstance(item, str) or item not in allowed for item in selected):
                raise ValueError(tr('analysis.choose_imported_files'))
            timeline, personality = args.get('timeline'), args.get('personality')
            if type(timeline) is not bool or type(personality) is not bool or not (timeline or personality):
                raise ValueError(tr('analysis.choose_report'))
            since = args.get('since') or None
            if since is not None:
                try:
                    date.fromisoformat(since)
                except (ValueError, TypeError):
                    raise ValueError(tr('analysis.invalid_date')) from None
            manager.ensure_idle()
            if args.get('resume') is not False:
                self.retryable_cache()
            trace = getattr(getattr(manager, 'gateway', None), 'analysis_trace', None)
            run = trace.begin() if trace else None
            result = manager.core_request('/analysis/start', {'files': selected, 'timeline': timeline,
                                          'personality': personality, 'resume': args.get('resume') is not False, 'since': since})
            if trace:
                trace.bind(run, result.get('task_id'))
            atomic_json(self.root / 'analysis-task.json', result)
            return result
        task_id = args.get('id')
        if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', task_id):
            raise ValueError(tr('analysis.invalid_task'))
        if method == 'analysis_cancel':
            return manager.core_request('/analysis/' + task_id + '/cancel', {})
        result = manager.core_request('/analysis/' + task_id)
        trace = getattr(getattr(manager, 'gateway', None), 'analysis_trace', None)
        saved = read_json(self.root / 'analysis-task.json', {}) or {}
        responses = trace.snapshot(task_id) if trace else []
        result['model_responses'] = responses or (saved.get('model_responses', []) if saved.get('task_id') == task_id else [])
        # An old poll can still complete after /start; do not replace the new task.
        if not saved.get('task_id') or saved['task_id'] == task_id:
            if result.get('status') in {'done', 'failed', 'cancelled'}:
                result['diagnostics'] = self.diagnostics(result)
            atomic_json(self.root / 'analysis-task.json', result)
        return result
