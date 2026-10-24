import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from desktop_host.analysis import Analysis
from desktop_host.storage import atomic_json
from desktop_host.host import Manager
from desktop_host.analysis_transport import AnalysisTrace

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manager = SimpleNamespace(root=self.root, identity_needs_restart=Mock(return_value=False), ensure_idle=Mock(),
                                       core_request=Mock(return_value={'task_id':'analysis1','status':'pending'}), redact=lambda value: value)
        self.analysis = Analysis(self.manager)
        atomic_json(self.root / 'imported-files.json', [{'name':'chat.json','saved_as':'/uploads/chat.json'}])

    def test_only_identity_confirmed_sources_can_start_core_analysis(self):
        with self.assertRaises(ValueError):
            self.analysis.dispatch('analysis_start', {'files':['/outside/private.json'],'timeline':True,'personality':False})
        self.manager.core_request.assert_not_called()
        self.analysis.dispatch('analysis_start', {'files':['/uploads/chat.json'],'timeline':True,'personality':False,'since':'2026-01-01'})
        self.manager.core_request.assert_called_once_with('/analysis/start', {'files':['/uploads/chat.json'],'timeline':True,'personality':False,'resume':True,'since':'2026-01-01'})

    def test_unapplied_identity_and_invalid_report_never_reach_core(self):
        self.manager.identity_needs_restart.return_value=True
        with self.assertRaises(ValueError):
            self.analysis.dispatch('analysis_start', {'files':['/uploads/chat.json'],'timeline':True,'personality':True})
        with self.assertRaises(ValueError):
            self.analysis.dispatch('analysis_report', {'report':'../config/values'})
        self.manager.core_request.assert_not_called()

    def test_empty_reports_include_skipped_block_diagnostics_without_raw_chat(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        atomic_json(folder / 'timeline.json', {'events': [], 'phases': []})
        atomic_json(folder / 'personality_report.json', {'summary': '', 'sections': []})
        atomic_json(folder / 'manifest.json', {'targets': ['timeline', 'personality'], 'blocks': 4, 'completed': 4,
                                             'failed': [], 'skipped': [{'block_id': 'b1', 'message': 'Invalid JSON'}]})
        atomic_json(folder / 'failures/b1.json', {'block': {'text': 'PRIVATE CHAT'}, 'stage': 'map',
                                                 'attempts': [{'error': 'Expected object', 'raw_output': 'PRIVATE MODEL OUTPUT'}]})
        result = self.analysis.dispatch('analysis_diagnostics', {})
        self.assertEqual(result['state'], 'empty')
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['failures'][0]['attempts'][0]['error'], 'Expected object')
        self.assertNotIn('PRIVATE', str(result))

    def test_resume_retries_failed_empty_cache_but_preserves_valuable_blocks(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        atomic_json(folder / 'manifest.json', {'skipped': [{'block_id': 'empty'}, {'block_id': 'partial'}]})
        atomic_json(folder / 'blocks/empty.json', {'events': [], 'personality_observations': []})
        atomic_json(folder / 'blocks/partial.json', {'events': [{'title': 'Useful finding'}]})
        self.analysis.retryable_cache()
        self.assertFalse((folder / 'blocks/empty.json').exists())
        self.assertTrue((folder / 'blocks/partial.json').exists())
        self.assertEqual(len(list((folder / 'failures/retry-cache').glob('empty-*.json'))), 1)

    def test_fresh_analysis_passes_resume_false_to_original_core(self):
        self.analysis.dispatch('analysis_start', {'files': ['/uploads/chat.json'], 'timeline': True, 'personality': True, 'resume': False})
        self.assertIs(self.manager.core_request.call_args.args[1]['resume'], False)

    def test_older_timeline_does_not_mask_new_empty_personality_report(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        atomic_json(folder / 'timeline.json', {'events': [{'title': 'Older event'}]})
        atomic_json(folder / 'personality_report.json', {'summary': '', 'sections': []})
        atomic_json(folder / 'manifest.json', {'targets': ['personality'], 'blocks': 1, 'completed': 1})
        self.assertEqual(self.analysis.diagnostics()['state'], 'empty')

    def test_running_task_does_not_show_previous_manifest_errors(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        atomic_json(folder / 'manifest.json', {'blocks': 4, 'completed': 4, 'skipped': [{'block_id': 'old'}]})
        atomic_json(self.root / 'analysis-task.json', {'task_id': 'new', 'status': 'running'})
        result = self.analysis.dispatch('analysis_diagnostics', {})
        self.assertEqual(result['state'], 'pending')
        self.assertFalse(result['has_reports'])
        self.assertEqual(result['completed'], 0)
        self.assertEqual(result['failures'], [])
        self.assertTrue((folder / 'manifest.json').exists())

    def test_model_metadata_persists_with_task_but_late_old_poll_cannot_replace_new_task(self):
        trace = AnalysisTrace()
        self.manager.gateway = SimpleNamespace(analysis_trace=trace)
        self.analysis.dispatch('analysis_start', {'files': ['/uploads/chat.json'], 'timeline': True, 'personality': True})
        trace.record(trace.current(), {'reason': 'reasoning_only', 'reasoning_tokens': 6000})
        self.manager.core_request.return_value = {'task_id': 'analysis1', 'status': 'failed'}
        result = self.analysis.dispatch('analysis_status', {'id': 'analysis1'})
        self.assertEqual(result['diagnostics']['model_responses'][0]['reason'], 'reasoning_only')
        self.manager.gateway = None  # Diagnostics survive gateway shutdown.
        self.assertEqual(self.analysis.diagnostics()['model_responses'][0]['reasoning_tokens'], 6000)
        atomic_json(self.root / 'analysis-task.json', {'task_id': 'new', 'status': 'running'})
        self.analysis.dispatch('analysis_status', {'id': 'analysis1'})
        from desktop_host.storage import read_json
        self.assertEqual(read_json(self.root / 'analysis-task.json')['task_id'], 'new')

    def test_completed_tasks_empty_reports_and_other_instances_do_not_unlock_prompts(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        atomic_json(self.root / 'analysis-task.json', {'status': 'done'})
        atomic_json(folder / 'timeline.json', {'events': [{'title': 'Timeline only'}]})
        atomic_json(folder / 'personality_report.json', {'summary': '', 'sections': [{'observations': []}]})
        atomic_json(folder / 'life_profile.json', {'habits': []})
        (folder / 'personality_prompt_context.md').write_text('Header without observations', encoding='utf-8')
        sibling = self.root / 'instances/other/profiles/default/core/data/analysis'
        atomic_json(sibling / 'personality_report.json', {'sections': [{'observations': [{'claim': 'Other person'}]}]})
        self.assertEqual(self.analysis.diagnostics()['prompt_ready'], {'personalityPrompt': False, 'lifeContext': False})
        for key in ('personalityPrompt', 'lifeContext'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analysis.require_prompt_artifacts({key: True})
        self.analysis.require_prompt_artifacts({'personalityPrompt': False, 'lifeContext': False})

    def test_personality_needs_observations_and_the_actual_prompt_file(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        atomic_json(folder / 'personality_report.json', {'sections': [{'observations': [{'claim': 'Prefers concise replies'}]}]})
        self.assertFalse(self.analysis.prompt_artifacts()['personalityPrompt'])
        (folder / 'personality_prompt_context.md').write_text('   ', encoding='utf-8')
        self.assertFalse(self.analysis.prompt_artifacts()['personalityPrompt'])
        (folder / 'personality_prompt_context.md').write_text('Personality reference: concise replies', encoding='utf-8')
        self.analysis.require_prompt_artifacts({'personalityPrompt': True})
        self.assertEqual(self.analysis.prompt_artifacts(), {'personalityPrompt': True, 'lifeContext': False})
        with self.assertRaises(ValueError):
            self.analysis.require_prompt_artifacts({'lifeContext': True})

    def test_life_needs_their_actual_habits_and_tolerates_damaged_artifacts(self):
        folder = self.root / 'profiles/default/core/data/analysis'
        for habits in ([], [None], [{'claim': '  ', 'subject': 'friend', 'target_fields': ['availability']}],
                       [{'claim': 'User routine', 'subject': 'self', 'target_fields': ['availability']}],
                       [{'claim': 'Sensitive routine', 'subject': 'friend', 'sensitive_relationship_context': True, 'target_fields': ['availability']}],
                       [{'claim': 'Unusable habit', 'subject': 'friend', 'target_fields': []}]):
            with self.subTest(habits=habits):
                atomic_json(folder / 'life_profile.json', {'habits': habits})
                self.assertFalse(self.analysis.prompt_artifacts()['lifeContext'])
        atomic_json(folder / 'life_profile.json', {'habits': [{'claim': 'Usually available after dinner', 'subject': 'friend', 'target_fields': ['availability']}]})
        self.analysis.require_prompt_artifacts({'lifeContext': True})
        self.assertFalse(self.analysis.prompt_artifacts()['personalityPrompt'])
        (folder / 'life_profile.json').write_text('{incomplete', encoding='utf-8')
        self.assertFalse(self.analysis.prompt_artifacts()['lifeContext'])

    def test_rpc_cannot_save_enabled_analysis_without_its_artifacts(self):
        manager = Manager.__new__(Manager)
        manager.root = self.root
        for key in ('personalityPrompt', 'lifeContext'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Manager.dispatch(manager, 'save_settings', {'settings': {
                    'version': 1, 'preset': 'quick', 'analysis': {key: True}}})
        self.assertFalse((self.root / 'settings.json').exists())
