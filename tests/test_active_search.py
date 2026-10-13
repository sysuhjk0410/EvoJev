import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from contrastive_experience import Experience, document, fit, normalize, probe_model
from puct_planner import CoverageEvaluator, CoverageState, choose
from cloudops_evolution import JevRanker
from active_search import ActiveSearch, unhealthy_pod_owners
from unittest.mock import patch


class ActiveSearchTests(unittest.TestCase):
    def test_single_candidate_needs_no_model_call(self):
        ranker = object.__new__(JevRanker)
        self.assertEqual(ranker.rank('state', 'question', {'one': 'only choice'}), {'one': 1})

    def test_identity_invariance(self):
        a = normalize('alpha-55c2-x45 refused 172.20.1.6 at case_0012', {'app/alpha': 'alpha'})
        b = normalize('beta-6628-z67 refused 172.20.2.7 at case_0782', {'app/beta': 'beta'})
        self.assertEqual(a, b)

    def test_ownership_no_cross_subject_join(self):
        objects = {'app/alpha': 'a', 'app/beta': 'b'}
        rows = [{'object': 'app/alpha', 'tool': 'GetErrorLogs', 'text': 'healthy', 'id': 's0l0'},
                {'object': 'app/beta', 'tool': 'GetErrorLogs', 'text': 'secret not found', 'id': 's1l0'}]
        self.assertNotIn('secret', document(rows, 'app/alpha', objects))
        self.assertIn('secret', document(rows, 'app/beta', objects))

    def test_alert_accepts_only_observed_metric_schema(self):
        row = {'object': 'app/alpha', 'tool': 'GetAlerts', 'text': '{"injection_type":"busy_loop_fault","evidence":["latency high"]}', 'id': 's0l0'}
        text = document([row], 'app/alpha', {'app/alpha': ''})
        self.assertNotIn('busy_loop_fault', text)
        self.assertIn('latency', text)

    def test_rollout_never_executes_snapshot(self):
        state = CoverageState(np.asarray([[.9, 0], [0, .9]]), np.asarray([.5, .5]), 2)
        result = CoverageEvaluator(np.asarray([.5, .5]), np.random.RandomState(1)).evaluate(state)
        self.assertEqual(state.selected, [])
        self.assertAlmostEqual(result[0], .9)

    def test_repeated_planned_action_rejected(self):
        state = CoverageState(np.ones((2, 2)), np.asarray([.5, .5]), 2)
        state.apply_action(0)
        with self.assertRaises(ValueError):
            state.apply_action(0)

    def test_clone_does_not_mutate_parent(self):
        state = CoverageState(np.ones((2, 2)), np.asarray([.5, .5]), 2)
        other = state.clone()
        other.apply_action(1)
        self.assertEqual(state.selected, [])

    def test_source_macro_is_charged_two_planning_calls(self):
        state = CoverageState(np.ones((3, 2)), np.asarray([.5, .5]), 2, [2, 1, 1])
        state.apply_action(0)
        self.assertTrue(state.is_terminal())
        self.assertEqual(state.legal_actions(), [])

    def test_real_open_spiel_puct_reproducible(self):
        try:
            import open_spiel
        except ImportError:
            self.skipTest('OpenSpiel must be installed for planning integration')
        first = choose([[.9, .9], [.01, .01]], [.5, .5], [.5, .5], seed=1)
        second = choose([[.9, .9], [.01, .01]], [.5, .5], [.5, .5], seed=1)
        self.assertEqual(first, second)
        self.assertEqual(first[0], 0)
        self.assertEqual(first[1]['simulations'], 96)

    def test_small_information_units_do_not_let_prior_dominate(self):
        try:
            import open_spiel
        except ImportError:
            self.skipTest('OpenSpiel must be installed for planning integration')
        selected, trace = choose([[.009], [.0001]], [1], [.1, .9], seed=1, depth=1,
                                 objective='historical_pairwise_evidence_separation')
        self.assertEqual(selected, 0)
        self.assertAlmostEqual(trace['exploration_utility_scale'], .009)
        self.assertEqual(trace['model'], 'historical_pairwise_evidence_separation')

    def test_invalid_gain_fails_before_search(self):
        with self.assertRaises(ValueError):
            choose([[float('nan')]], [1], [1])

    def test_fractional_cost_is_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            choose([[.9]], [1], [1], costs=[1.5])
        with self.assertRaises(ValueError):
            CoverageState(np.ones((1, 1)), np.ones(1), 3, costs=[float('nan')])

    def test_discount_rewards_earlier_information(self):
        early = CoverageState(np.asarray([[.9, 0], [0, .1]]), np.asarray([.5, .5]), 2, discount=.95)
        late = early.clone()
        early.apply_action(0)
        early.apply_action(1)
        late.apply_action(1)
        late.apply_action(0)
        self.assertGreater(early.returns()[0], late.returns()[0])

    def test_probe_rates_do_not_count_unacquired_checks_as_negatives(self):
        vectorizer = SimpleNamespace(vocabulary_={'geterrorlogs__secret': 0, 'describeresource__pending': 1})
        classes = ['__background__', 'secret_fault', 'scheduler_fault']
        model = probe_model(['geterrorlogs__secret', 'geterrorlogs__healthy', 'describeresource__pending'],
                            ['secret_fault', '__background__', 'scheduler_fault'], vectorizer, classes,
                            np.asarray([[0, 0], [2, 0], [0, 2]]))
        logs = model['geterrorlogs']
        self.assertEqual(logs['observed_documents']['scheduler_fault'], 0)
        self.assertEqual(logs['rates']['scheduler_fault'], logs['pooled_rates'])
        self.assertEqual(logs['observed_documents']['secret_fault'], 1)

    def example_experience(self, probes=True):
        model = {'schema': 'contrastive_source_bound_v1', 'vocabulary': {'geterrorlogs__secret': 0},
                 'idf': [1], 'classes': ['__background__', 'secret_fault', 'cpu_fault'],
                 'coef': [[0], [1], [-1]], 'intercept': [0, 0, 0]}
        if probes:
            model['tool_probe_model'] = {'geterrorlogs': {'features': ['secret'],
                'rates': {'__background__': [.5], 'secret_fault': [.99], 'cpu_fault': [.01]},
                'pooled_rates': [.5], 'observed_documents': {'__background__': 30, 'secret_fault': 30, 'cpu_fault': 30}}}
        return Experience(model, {'secret_fault': {'target': 'app'}, 'cpu_fault': {'target': 'app'}})

    def test_pairwise_separation_prefers_discriminating_acquired_tool(self):
        experience = self.example_experience()
        hypotheses = [{'fault_object': 'app/alpha', 'root_cause': 'secret_fault', 'probability': .5},
                      {'fault_object': 'app/alpha', 'root_cause': 'cpu_fault', 'probability': .5}]
        gains, weights, used = experience.separation([
            {'tool': 'GetErrorLogs', 'object': 'app/alpha'},
            {'tool': 'DescribeResource', 'object': 'app/alpha'},
            {'tool': 'GetErrorLogs', 'object': 'app/unrelated'}], hypotheses, [[.5, .5]] * 3)
        self.assertTrue(used)
        self.assertGreater(gains[0][0], gains[1][0])
        self.assertEqual(gains[1], gains[2])
        self.assertEqual(weights, [.25])

    def test_legacy_experience_uses_explicit_coverage_fallback(self):
        experience = self.example_experience(probes=False)
        hypotheses = [{'probability': .6}, {'probability': .4}]
        self.assertEqual(experience.separation([], hypotheses, [[.8, .2]]), ([[.8, .2]], [.6, .4], False))

    def test_invalid_probe_probabilities_rejected(self):
        data = self.example_experience().data
        data['tool_probe_model']['geterrorlogs']['rates']['secret_fault'] = [float('nan')]
        with self.assertRaises(ValueError):
            Experience(data, {})

    def test_public_payload_with_answer_is_rejected(self):
        search = object.__new__(ActiveSearch)
        with self.assertRaises(ValueError):
            search.run(None, {'query': 'q', 'namespace': 'boutique', 'gold': 'secret'}, {})

    def test_unhealthy_owner_comes_only_from_observed_pod_state(self):
        rows = [{'object': 'app/alpha', 'tool': 'GetResources', 'arguments': {'resource_type': 'pods'}, 'text': 'alpha-123 0/1 CreateContainerConfigError'},
                {'object': 'app/beta', 'tool': 'GetResources', 'arguments': {'resource_type': 'pods'}, 'text': 'beta-456 1/1 Running'},
                {'object': 'app/gamma', 'tool': 'GetErrorLogs', 'arguments': {}, 'text': 'Pending request to alpha'}]
        self.assertEqual(unhealthy_pod_owners(rows), {'app/alpha'})

    def test_memory_probability_cannot_override_verified_candidate(self):
        search = object.__new__(ActiveSearch)
        search.types = {'secret_fault': {'description': 'missing binding'}, 'delay_fault': {'description': 'delay'}}
        search.ranker = SimpleNamespace(rank=lambda text, question, options: {key: 1 / len(options) for key in options})
        memory = SimpleNamespace(candidates=lambda rows, objects: [
            {'fault_object': 'app/beta', 'root_cause': 'delay_fault', 'probability': .99},
            {'fault_object': 'app/alpha', 'root_cause': 'secret_fault', 'probability': .01}])
        proof = [{'fault_object': 'app/alpha', 'root_cause': 'secret_fault'}]
        with patch('active_search.admissible', return_value=proof):
            result = search.decide({'query': 'q'}, [], {}, {'rules': []}, memory, {}, True)
        self.assertEqual(result['prediction'], {'fault_object': 'app/alpha', 'root_cause': 'secret_fault'})
        self.assertTrue(result['verified_candidate_constraint'])

    def test_public_asset_mutation_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'public').mkdir()
            (root / 'public/task.json').write_text('{}')
            (root / 'config.json').write_text(json.dumps({'project_root': str(root), 'benchmark_root': str(root / 'original')}))
            code = 'from pathlib import Path;from isolation import install;import sys;run=Path(sys.argv[1]);install(run,run/"audit.jsonl");(run/"public/task.json").write_text("changed")'
            result = subprocess.run([sys.executable, '-B', '-c', code, str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('PermissionError', result.stderr)
            self.assertEqual((root / 'public/task.json').read_text(), '{}')

    def test_learned_artifact_is_json_and_source_bound(self):
        try:
            import sklearn
        except ImportError:
            self.skipTest('scikit-learn is required for experience fitting')
        contract = SimpleNamespace(SYSTEM_VALID_SERVICES={'boutique': ['alpha', 'beta']}, VALID_NODES=['worker'])
        memory, labels, tasks = {}, {}, {}
        for i, cause in enumerate(['secret_fault', 'cpu_fault', 'secret_fault', 'cpu_fault']):
            case = str(i)
            phrase = 'secret missing binding not found' if cause == 'secret_fault' else 'cpu intensive busy loop throttled'
            memory[case] = {'evidence': [
                {'object': 'app/alpha', 'tool': 'GetErrorLogs', 'text': phrase, 'id': 's0l0'},
                {'object': 'app/beta', 'tool': 'GetErrorLogs', 'text': 'healthy successful normal service', 'id': 's1l0'}]}
            labels[case] = {'fault_object': 'app/alpha', 'root_cause': cause}
            tasks[case] = {'namespace': 'boutique'}
        artifact = json.loads(json.dumps(fit(memory, labels, tasks, contract)))
        types = {cause: {'target': 'app'} for cause in ('secret_fault', 'cpu_fault')}
        experience = Experience(artifact, types)
        objects = {'app/alpha': 'a', 'app/beta': 'b', 'node/worker': 'node', 'namespace/boutique': 'scope'}
        result = experience.candidates(memory['0']['evidence'], objects)
        self.assertEqual(result[0]['fault_object'], 'app/alpha')
        self.assertEqual(result[0]['root_cause'], 'secret_fault')
        self.assertEqual(result, experience.candidates(memory['0']['evidence'], objects))

    def test_binary_experience_has_one_logit_row_per_class(self):
        try:
            import sklearn
        except ImportError:
            self.skipTest('scikit-learn is required for experience fitting')
        contract = SimpleNamespace(SYSTEM_VALID_SERVICES={'boutique': ['alpha', 'beta']}, VALID_NODES=['worker'])
        memory = {str(i): {'evidence': [
            {'object': 'app/alpha', 'tool': 'GetErrorLogs', 'text': 'secret missing binding', 'id': 's0l0'},
            {'object': 'app/beta', 'tool': 'GetErrorLogs', 'text': 'healthy normal responses', 'id': 's1l0'}]} for i in range(4)}
        labels = {case: {'fault_object': 'app/alpha', 'root_cause': 'secret_fault'} for case in memory}
        tasks = {case: {'namespace': 'boutique'} for case in memory}
        artifact = fit(memory, labels, tasks, contract)
        self.assertEqual(len(artifact['coef']), 2)
        self.assertEqual(len(artifact['intercept']), 2)
        experience = Experience(artifact, {'secret_fault': {'target': 'app'}})
        result = experience.candidates(memory['0']['evidence'], {'app/alpha': '', 'app/beta': ''})
        self.assertGreater(result[0]['probability'], .5)


if __name__ == '__main__':
    unittest.main()
