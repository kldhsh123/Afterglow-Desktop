from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from desktop_host.model_gateway import ModelBudget
from desktop_host.model_settings import concurrency_environment, model_scope


def profile(model='shared', limit=1, base='https://models.example/v1'):
    return {'channel': 'custom', 'baseUrl': base, 'model': model, 'concurrency': limit}


class ConfiguredModelBudgetTests(unittest.TestCase):
    def test_same_api_and_model_share_the_lower_role_limit(self):
        budget = ModelBudget(timeout=.01)
        main = profile(limit=8, base='https://MODELS.EXAMPLE:443/v1/')
        small = profile(limit=1)
        budget.configure({'deepseek': main, 'zhipu': small})
        with budget.acquire(*model_scope(main), limit=8):
            with self.assertRaises(TimeoutError):
                with budget.acquire(*model_scope(small), limit=8):
                    self.fail('Shared model exceeded its lower limit')
        with budget.acquire(*model_scope(small), limit=8):
            pass

    def test_embedding_reranking_and_different_api_bases_have_separate_slots(self):
        budget = ModelBudget(timeout=.01)
        embedding = profile(model='embedding')
        rerank = profile(model='rerank')
        other = profile(model='embedding', base='https://another.example/v1')
        budget.configure({'embedding': embedding, 'rerank': rerank, 'vision': other})
        with budget.acquire(*model_scope(embedding), limit=1):
            with budget.acquire(*model_scope(rerank), limit=1):
                with budget.acquire(*model_scope(other), limit=1):
                    pass

    def test_reconfiguration_does_not_forget_requests_already_running(self):
        budget = ModelBudget(timeout=.01)
        config = profile(limit=2)
        budget.configure({'deepseek': config})
        with budget.acquire(*model_scope(config), limit=2):
            budget.configure({'deepseek': {**config, 'concurrency': 1}})
            with self.assertRaises(TimeoutError):
                with budget.acquire(*model_scope(config), limit=2):
                    self.fail('Reconfiguration created an extra request slot')

    def test_core_workers_receive_effective_limits_without_enabling_features(self):
        providers = {'deepseek': profile(limit=6), 'zhipu': profile(limit=2),
                     'embedding': profile(model='embedding', limit=7),
                     'rerank': profile(limit=1)}
        environment = concurrency_environment(providers, active_roles=['deepseek', 'zhipu', 'embedding'])
        self.assertEqual(environment['EMBEDDING_MAX_CONCURRENCY'], '7')
        self.assertEqual(environment['LABEL_MAX_CONCURRENCY'], '2')
        self.assertEqual(environment['ANALYSIS_MAX_CONCURRENCY'], '2')
        self.assertEqual(environment['ANALYSIS_PROACTIVE_MAX_CONCURRENCY'], '2')
        self.assertFalse(any(name.endswith('_ENABLED') for name in environment))

    def test_errors_release_request_slots(self):
        budget = ModelBudget(1, timeout=.01)
        config = profile()
        with self.assertRaises(RuntimeError):
            with budget.acquire(*model_scope(config), limit=1):
                raise RuntimeError('Upstream failed')
        with budget.acquire(*model_scope(config), limit=1):
            pass


@unittest.skipUnless(sys.platform == "win32", "Cross-process model slots use Windows named mutexes")
class WindowsModelBudgetTests(unittest.TestCase):
    def test_separate_processes_share_slots_and_crashed_owners_release_them(self):
        root = str(Path(__file__).resolve().parents[1])
        provider = "fixture-" + uuid.uuid4().hex
        prefix = (f"import sys; sys.path.insert(0, {root!r}); "
                  "from desktop_host.model_gateway import ModelBudget; "
                  f"budget=ModelBudget(1, timeout=.2); provider={provider!r}\n")
        owner = subprocess.Popen([sys.executable, "-I", "-u", "-c", prefix +
                                  "with budget.acquire(provider, 'model'):\n print('held', flush=True)\n sys.stdin.read()"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(owner.stdout.readline().strip(), "held")
            contender = subprocess.run([sys.executable, "-I", "-c", prefix +
                                        "try:\n with budget.acquire(provider, 'model'): raise AssertionError('over capacity')\n"
                                        "except TimeoutError: print('queued')"],
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(contender.returncode, 0, contender.stderr)
            self.assertEqual(contender.stdout.strip(), "queued")
            with ModelBudget(1, timeout=.2).acquire(provider, "different-model"):
                pass
            owner.kill()
            owner.wait(timeout=5)
            # OS abandonment must reclaim the slot even without a finally block.
            with ModelBudget(1, timeout=.2).acquire(provider, "model"):
                pass
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)
            for stream in (owner.stdin, owner.stdout, owner.stderr):
                stream.close()
