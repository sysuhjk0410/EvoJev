import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from active_full import ARMS, predict, score
from grounded import digest
from search_experiment import ARMS as GATE_ARMS, cross_incident_quality, learn, next_residual


class ActiveProtocolTests(unittest.TestCase):
    def put(self, root, name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_learn_resume_preserves_accepted_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = {'schema': 'example'}
            key = digest(artifact)
            candidate = {'version': 4, 'rules': [{'id': 'accepted'}], 'experience_sha': key}
            self.put(root, 'protocol.json', {'historical_pool': ['h']})
            self.put(root, 'historical_memory.json', {'h': {}})
            self.put(root, 'candidate_harness.json', candidate)
            self.put(root, 'experience_learning.json', {'artifact_hash': key, 'code_hash': 'frozen'})
            self.put(root, 'experiences/' + key + '.json', artifact)
            with patch('search_experiment.code_hash', return_value='frozen'), patch('search_experiment.fit') as fit:
                learn(root)
            fit.assert_not_called()
            self.assertEqual(json.loads((root / 'candidate_harness.json').read_text()), candidate)

    def test_learn_refuses_changed_code_without_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = {'schema': 'example'}
            key = digest(artifact)
            self.put(root, 'protocol.json', {'historical_pool': ['h']})
            self.put(root, 'historical_memory.json', {'h': {}})
            self.put(root, 'candidate_harness.json', {'experience_sha': key, 'rules': ['kept']})
            self.put(root, 'experience_learning.json', {'artifact_hash': key, 'code_hash': 'old'})
            self.put(root, 'experiences/' + key + '.json', artifact)
            with patch('search_experiment.code_hash', return_value='new'), self.assertRaises(ValueError):
                learn(root)
            self.assertEqual(json.loads((root / 'candidate_harness.json').read_text())['rules'], ['kept'])

    def test_full_test_cannot_start_without_actual_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root, 'development_summary.json', {'passed': False})
            with self.assertRaises(ValueError):
                predict(root)
            self.assertFalse((root / 'search_test_predictions.json').exists())

    def test_duplicate_plan_rejected_before_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root, 'development_summary.json', {'passed': True})
            self.put(root, 'advisor_stopped.json', {})
            self.put(root, 'candidate_harness.json', {'rules': []})
            self.put(root, 'protocol.json', {'test': ['one'] * 754})
            with self.assertRaises(ValueError):
                predict(root)
            self.assertFalse((root / 'frozen_active.json').exists())

    def test_scoring_cannot_open_labels_for_partial_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root, 'search_test_predictions.json', {'status': 'running', 'cases': {}})
            self.put(root, 'protocol.json', {'test': ['one']})
            self.put(root, 'frozen_active.json', {})
            with self.assertRaises(ValueError):
                score(root)

    def test_six_budget_matched_arms_cover_4524_predictions(self):
        self.assertEqual(ARMS, GATE_ARMS)
        self.assertEqual(len(ARMS) * 754, 4524)
        self.assertIn('coverage_puct', ARMS)

    def test_proposal_case_is_excluded_from_generalization_support(self):
        quality = {'per_historical_case': {'proposal': {'correct': 20, 'wrong': 0},
                                           'other': {'correct': 0, 'wrong': 1}}}
        result = cross_incident_quality(quality, 'proposal')
        self.assertEqual(result['precision'], 0)
        self.assertEqual(result['supporting_incidents'], 0)
        quality['per_historical_case']['other'] = {'correct': 2, 'wrong': 0}
        self.assertEqual(cross_incident_quality(quality, 'proposal')['supporting_incidents'], 1)

    def test_residual_selection_skips_repaired_cases_and_prior_attempts(self):
        labels = {case: {'fault_object': 'app/alpha', 'root_cause': 'secret_fault'} for case in ('a', 'b', 'c')}
        state = {'completed': ['b'], 'events': [], 'memory': {
            'a': {'prediction': labels['a']}, 'b': {'prediction': {}}, 'c': {'prediction': {}}}}
        source = {case: {'evidence': []} for case in labels}
        self.assertEqual(next_residual(['a', 'b', 'c'], state, labels, source), 'c')

    def test_residual_selection_balances_cause_classes(self):
        labels = {'a': {'fault_object': 'app/alpha', 'root_cause': 'secret_fault'},
                  'b': {'fault_object': 'app/alpha', 'root_cause': 'secret_fault'},
                  'c': {'fault_object': 'app/beta', 'root_cause': 'cpu_fault'}}
        state = {'completed': ['a'], 'events': [{'case': 'a'}],
                 'memory': {case: {'prediction': {}} for case in labels}}
        source = {case: {'evidence': []} for case in labels}
        self.assertEqual(next_residual(['a', 'b', 'c'], state, labels, source), 'c')


if __name__ == '__main__':
    unittest.main()
