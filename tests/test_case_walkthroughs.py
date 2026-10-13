import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import export_case_walkthroughs as export
from grounded import digest


class CaseWalkthroughTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name)
        self.ids = ['case_0001', 'case_0002', 'case_0003']
        self.put('online_plan.json', {'cases': self.ids})
        self.objects = {'app/subject': 'Application subject'}
        self.types = {'cause': {'target': 'app', 'description': 'Observed failure'}}
        self.rule = {'id': 'rule', 'cause': 'cause', 'target': 'app', 'checks': ['GetErrorLogs'],
                     'positive': [{'tool': 'GetErrorLogs', 'all': ['direct error']}], 'negative': []}
        self.harness = {'version': 0, 'rules': [self.rule]}
        for i, case in enumerate(self.ids):
            task = {'query': 'Find the failure.', 'namespace': 'boutique'}
            steps = [{'tool': 'GetAlerts', 'arguments': {}, 'output': '{"alerts": []}', 'error': None, 'elapsed_sec': 0},
                     {'tool': 'GetResources', 'arguments': {'resource_type': 'pods', 'name': '', 'namespace': 'boutique'},
                      'output': 'NAME STATUS\nsubject-123 Error', 'error': None, 'elapsed_sec': 0},
                     {'tool': 'GetErrorLogs', 'arguments': {'app_name': 'subject'}, 'output': 'direct error',
                      'error': None, 'elapsed_sec': 0}]
            prediction = {'fault_object': 'app/subject', 'root_cause': 'cause'}
            trace = {'steps': steps, 'search_tree': [{'action': {'tool': 'GetErrorLogs', 'arguments': {'app_name': 'subject'}},
                      'new_evidence_step': 2, 'planning': {'simulations': 96, 'nodes': []}}],
                     'evidence': export.scoped_rows(steps, self.objects), 'component_scores': {'app/subject': 1.0},
                     'bank': [dict(prediction, probability=1.0, jev_probability=1.0, explicit_proof=True, joint_score=.5)],
                     'supported_pairs': [dict(prediction, rule='rule', witnesses=[])], 'verified_candidate_constraint': True,
                     'harness_hash': digest(self.harness), 'prediction': prediction, 'healthy': True,
                     'max_tool_calls': 72, 'tool_calls': 3, 'wall_sec': 1.0}
            first = {'trace': trace, 'request_hash': case, 'committed_ns': 10, 'trace_hash': digest(trace)}
            self.put('public/cases/' + case + '/task.json', task)
            self.put('online/first/' + case + '.json', first)
            self.put('online/dispatches/' + case + '.json', {'index': i, 'request_hash': case, 'payload': {'harness': self.harness}})
            self.put('online/feedback/' + case + '.json', {'label': prediction, 'correct': True,
                                                        'released_ns': 20, 'first_hash': digest(first)})
            self.put('online/updates/' + case + '.json', {'harness': self.harness, 'event': {'decision': 'no_update',
                      'completed_feedback_cases': i + 1}, 'effective_from_index': i + 1,
                      'before_hash': digest(self.harness), 'after_hash': digest(self.harness), 'first_hash': digest(first)})
            self.put('online/proposals/' + case + '.json', {'decision': 'no_update', 'rule': None})

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, value):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def build(self):
        with patch.object(export, 'catalog', return_value=(None, self.types)), patch.object(export, 'objects_for', return_value=self.objects):
            return export.build(self.run, self.ids)

    def test_three_real_io_examples_and_snapshot(self):
        bundle = self.build()
        self.assertEqual(bundle['accuracy_snapshot']['correct'], 3)
        self.assertEqual(bundle['accuracy_snapshot']['accuracy'], 1.0)
        self.assertFalse(bundle['accuracy_snapshot']['audited'])
        self.assertEqual(len(bundle['cases']), 3)
        case = bundle['cases'][0]
        self.assertEqual(len(case['modules']), 9)
        self.assertEqual(len(case['original_acquired_tool_outputs']), 3)
        self.assertFalse(case['modules'][0]['input']['ground_truth_available_to_solver'])
        self.assertEqual(case['modules'][5]['provenance'], 'single-candidate identity; no neural call')
        self.assertEqual(case['integrity']['new_tool_calls'], 0)
        self.assertEqual(case['integrity']['new_JEV_calls'], 0)
        self.assertEqual(case['integrity']['new_advisor_calls'], 0)

    def test_uncompleted_example_is_rejected(self):
        (self.run / 'online/updates/case_0001.json').unlink()
        with self.assertRaisesRegex(ValueError, 'completed update'):
            self.build()

    def test_feedback_cannot_precede_commit(self):
        path = self.run / 'online/feedback/case_0001.json'
        feedback = export.read(path)
        feedback['released_ns'] = 5
        self.put(str(path.relative_to(self.run)), feedback)
        with self.assertRaisesRegex(ValueError, 'after the first answer'):
            self.build()

    def test_trace_mutation_is_rejected(self):
        path = self.run / 'online/first/case_0001.json'
        first = export.read(path)
        first['trace']['prediction']['root_cause'] = 'wrong'
        self.put(str(path.relative_to(self.run)), first)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.build()

    def test_ranking_cache_mismatch_is_rejected(self):
        payload = {'state': 'text', 'questions': [{'options': {'0': 'only candidate'}}]}
        self.put('scores/' + export.ranking_digest(payload) + '.json', {'0': .5})
        with self.assertRaisesRegex(ValueError, 'differs from the committed trace'):
            export.ranking(self.run, payload, {'0': 1.0})

    def test_unicode_ranking_uses_original_cache_serialization(self):
        payload = {'state': 'observed …', 'questions': [{'options': {'0': 'first', '1': 'second'}}]}
        distribution = {'0': .8, '1': .2}
        self.put('scores/' + export.ranking_digest(payload) + '.json', distribution)
        result = export.ranking(self.run, payload)
        self.assertEqual(result['output'], distribution)
        self.assertEqual(result['provenance'], 'persisted ranking cache')


if __name__ == '__main__':
    unittest.main()
