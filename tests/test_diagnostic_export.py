import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import export_diagnostics


class DiagnosticExportTests(unittest.TestCase):
    def test_long_observation_is_labeled_not_silently_replaced(self):
        value = export_diagnostics.excerpt('x' * 3000 + 'DECISIVE END')
        self.assertTrue(value['truncated'])
        self.assertEqual(value['original_characters'], 3012)
        self.assertTrue(value['text'].endswith('DECISIVE END'))
        self.assertIn('[...]', value['text'])

    def test_short_observation_remains_exact(self):
        self.assertEqual(export_diagnostics.excerpt('Active: inactive (dead)'),
                         {'text': 'Active: inactive (dead)', 'original_characters': 23, 'truncated': False})

    def test_recursive_redaction_preserves_cause_and_numbers(self):
        original = {'cause': 'containerd_unavailable', 'score': .123, 'rows': [
            '/' + 'data/dds-data/user/model 192.168.0.222 Active: inactive (dead)',
            '/' + 'mnt/data', 'sk-' + 'a' * 24]}
        result = export_diagnostics.redact(original)
        self.assertEqual(result['cause'], original['cause'])
        self.assertEqual(result['score'], .123)
        self.assertIn('Active: inactive (dead)', result['rows'][0])
        self.assertNotIn('192.168', result['rows'][0])
        self.assertEqual(result['rows'][1], '<redacted-path>')
        self.assertEqual(result['rows'][2], '<redacted-token>')

    def test_server_preserves_original_steps_and_scores(self):
        spec = importlib.util.spec_from_file_location('dashboard', ROOT / 'scripts/dashboard.py')
        dashboard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dashboard)
        store = dashboard.Store()
        progress = store.progress()
        for case in ('case_0514', 'case_0143', 'case_0158', 'case_0000'):
            trace = store.case(case)['online_puct']
            self.assertTrue(all('output' not in s for s in trace['steps']))
            if 'diagnostic' in trace:
                detail = trace['diagnostic']
                self.assertEqual(len(trace['steps']), len(detail['observations']))
                self.assertLess(detail['integrity']['first_committed_ns'], detail['integrity']['feedback_released_ns'])
                self.assertEqual(detail['integrity']['new_inference_calls'], 0)
                expected = next(c['arms']['online_puct']['correct'] for c in progress['cases'] if c['case'] == case)
                self.assertEqual(trace['correct'], expected)


if __name__ == '__main__':
    unittest.main()
