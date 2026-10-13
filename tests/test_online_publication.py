import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import publish_online
from online_protocol import Ledger, immutable


class OnlinePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.run_path = Path(cls.temp.name)
        cls.ids = [f'case_{i:04d}' for i in range(754)]
        cls.gold = {'fault_object': 'app/subject', 'root_cause': 'code_busy_loop'}
        seed = {'version': 0, 'rules': []}
        immutable(cls.run_path / 'online_plan.json', {'cases': cls.ids, 'initial_harness': seed,
                  'mode': 'puct', 'budget': 72, 'code_hash': 'frozen'})
        ledger = Ledger(cls.run_path)
        harness = seed
        for index, case in enumerate(cls.ids):
            immutable(cls.run_path / 'sealed_evaluation/cases' / (case + '.json'), {'label': cls.gold})
            dispatch = ledger.reserve(case, harness)
            trace = {'case': case, 'code_hash': 'frozen', 'request_hash': dispatch['request_hash'],
                     'healthy': True, 'tool_calls': 1, 'wall_sec': .1,
                     'prediction': cls.gold if index % 2 == 0 else {},
                     'steps': [{'tool': 'Check', 'arguments': {}, 'elapsed_sec': .1,
                                'error': None, 'output': 'Private raw tool output'}]}
            ledger.commit_first(case, trace)
            ledger.release_feedback(case)
            accepted = index == 100
            if accepted:
                harness = {'version': 1, 'rules': [{'id': 'online_01234567890123456789',
                                                   'cause': 'code_busy_loop', 'target': 'app'}]}
            ledger.commit_update(case, harness, {'decision': 'accepted' if accepted else 'no_update',
                                                'accepted_rule_hashes': ['01234567890123456789'] if accepted else []})
        cls.summary = dict(ledger.summary(), audited=True, unique_cases=754,
                           physical_diagnosis_starts=754, pending_updates=0,
                           zero_forbidden_worker_access=True, source_hashes_verified=True)
        immutable(cls.run_path / 'online_summary.json', cls.summary)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def build(self, summary=None, runtime='frozen'):
        original = publish_online.read

        def load(path):
            return summary if summary is not None and Path(path).name == 'online_summary.json' else original(path)

        with patch.object(publish_online, 'read', side_effect=load), patch.object(publish_online, 'code_hash', return_value=runtime):
            return publish_online.build(self.run_path)

    def test_complete_first_answer_bundle_uses_dispatch_version(self):
        bundle = self.build()
        progress = bundle['progress']
        self.assertEqual(progress['method_family'], 'online_single_pass')
        self.assertEqual(progress['summary']['metrics']['online_puct']['correct'], 377)
        self.assertEqual(progress['cases'][100]['harness_version'], 0)
        self.assertEqual(progress['cases'][101]['harness_version'], 1)
        self.assertEqual(progress['timeline'][100]['accepted_rule_ids'], ['online_01234567890123456789'])
        self.assertEqual(progress['summary']['retrospective_predictions'], 0)
        self.assertTrue(progress['summary']['prior_public_benchmark_use'])
        self.assertNotIn('gold', progress['cases'][0])
        self.assertNotIn('output', bundle['cases'][self.ids[0]]['online_puct']['steps'][0])
        self.assertNotIn('Private raw tool output', json.dumps(bundle))

    def test_incomplete_or_pending_run_cannot_publish(self):
        for updates in ({'status': 'running'}, {'pending_updates': 1}, {'unique_cases': 753},
                        {'physical_diagnosis_starts': 755}, {'audited': False}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.build(dict(self.summary, **updates))

    def test_access_or_source_audit_failure_cannot_publish(self):
        for key in ('zero_forbidden_worker_access', 'source_hashes_verified'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.build(dict(self.summary, **{key: False}))

    def test_runtime_change_cannot_publish(self):
        with self.assertRaises(ValueError):
            self.build(runtime='modified')

    def test_wrong_accuracy_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, 'score mismatch'):
            self.build(dict(self.summary, correct=754))

    def test_final_readme_replaces_only_accuracy_section(self):
        text = '# Method\n\n## 总体准确率\n\nOld interim result\n\n## 三个逐模块案例\n\nKeep original examples\n'
        updated = publish_online.update_accuracy_readme(text, self.summary)
        self.assertIn('377/754 = 50.00%', updated)
        self.assertIn('80% 目标未达到', updated)
        self.assertNotIn('Old interim result', updated)
        self.assertIn('Keep original examples', updated)
        self.assertIn('异常和不健康诊断计错', updated)

    def test_invalid_or_duplicate_accuracy_sections_rejected(self):
        for text in ('# No accuracy', '## 总体准确率\nOld\n## 总体准确率\nDuplicate'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                publish_online.update_accuracy_readme(text, self.summary)

    def test_compact_readme_remains_unchanged(self):
        text = (ROOT / 'README.md').read_text()
        self.assertEqual(publish_online.update_accuracy_readme(text, self.summary), text)
        self.assertNotIn('## 总体准确率', text)
        self.assertIn('https://sysuhjk0410.github.io/EvoJev/', text)

    def test_serving_change_discloses_only_public_metadata(self):
        path = self.run_path / 'advisor_context_256k_transition.json'
        path.write_text(json.dumps({'phase': 'ready_and_resumed', 'first_answers_unchanged': True,
            'no_case_retake': True, 'old_context': 16384, 'new_context': 262144,
            'first_answers_before': 458, 'effective_for_advisor_requests_after_first_index': 457,
            'old_command': '/private/example', 'old_pid': 1}))
        try:
            value = publish_online.serving_changes(self.run_path)[0]
            self.assertEqual(value['first_answers_already_committed'], 458)
            self.assertNotIn('old_command', value)
            self.assertNotIn('old_pid', value)
            self.assertFalse(value['prior_failed_updates_retried'])
        finally:
            path.unlink()


if __name__ == '__main__':
    unittest.main()
