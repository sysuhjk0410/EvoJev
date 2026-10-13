import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('publication', ROOT / 'scripts/publish_results.py')
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def gate(run):
    counts = [19, 20, 15, 10, 10, 20]
    save(run / 'development_summary.json', {'passed': True, 'metrics': {
        arm: {'correct': n, 'total': 36} for arm, n in zip(publication.ARMS, counts)}})


def fixture(run):
    gate(run)
    publication.select(run)
    ids = [f'case_{i:04d}' for i in range(754)]
    parts = {'historical': ids[:144], 'development': ids[144:599], 'frozen_evaluation': ids[599:]}
    save(run / 'protocol.json', {'test': ids, 'partitions': parts, 'historical_pool': ids[:144], 'rule_precision_min': .9})
    harness = {'rules': [{'id': 'inherited', 'cause': 'cpu', 'target': 'app', 'positive': ['cpu']}]}
    sha = publication.digest(harness)
    save(run / 'candidate_harness.json', harness)
    save(run / 'frozen_active.json', {'arms': publication.ARMS, 'code_hash': 'frozen', 'harness_hash': sha, 'budget_cap': 72})
    save(run / 'advisor_stopped.json', {'stopped_before_frozen_test': True})
    (run / 'worker_access.jsonl').write_text('')
    save(run / 'active_evolution.json', {'events': [], 'completed': [], 'memory': {i: {} for i in ids[:144]}, 'harness': harness})
    values = {'fault_object': 'app', 'root_cause': 'cpu'}
    labels, rows = {}, {}
    for case in ids:
        labels[case] = {'label': values}
        rows[case] = {}
        for arm in publication.ARMS:
            trace = {'case': case, 'code_hash': 'frozen', 'prediction': values, 'request_hash': case + arm,
                     'healthy': True, 'tool_calls': 1, 'wall_sec': 1.2,
                     'steps': [{'tool': 'Check', 'arguments': {}, 'elapsed_sec': .1, 'error': None, 'output': 'private'}]}
            rel = f'active_full_traces/{case}/{arm}.json'
            save(run / rel, trace)
            rows[case][arm] = {k: trace[k] for k in ('prediction', 'request_hash', 'healthy', 'tool_calls', 'wall_sec')}
            rows[case][arm]['trace_path'] = rel
    save(run / 'search_test_predictions.json', {'status': 'complete', 'cases': rows, 'code_hash': 'frozen', 'harness_hash': sha})
    save(run / 'sealed_evaluation/labels.json', {'cases': labels})
    metrics = {arm: {'correct': 754, 'total': 754} for arm in publication.ARMS}
    partitions = {name: {arm: {'correct': len(ids), 'total': len(ids)} for arm in publication.ARMS} for name, ids in parts.items()}
    save(run / 'active_summary.json', {'code_hash': 'frozen', 'harness_hash': sha, 'metrics': metrics, 'partitions': partitions,
         'worker_forbidden_attempts': 0, 'public_and_benchmark_hashes_unchanged': True,
         'all_tool_budgets': 72, 'advisor_stopped_before_test': True})


class PublicationTests(unittest.TestCase):
    def test_development_selection_recorded_before_final_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            gate(run)
            selected = publication.select(run)
            self.assertEqual(selected['development_selected_arm'], 'coverage_puct')
            self.assertTrue(selected['selected_without_final_labels'])
            save(run / 'active_summary.json', {'metrics': 'unused'})
            self.assertEqual(publication.select(run), selected)
            (run / 'publication_selection.json').unlink()
            with self.assertRaisesRegex(ValueError, 'before final scoring'):
                publication.select(run)

    def test_failed_or_partial_development_gate_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            gate(run)
            value = publication.load(run / 'development_summary.json')
            value['metrics']['puct']['total'] = 35
            save(run / 'development_summary.json', value)
            with self.assertRaises(ValueError):
                publication.select(run)

    def test_complete_publication_preserves_all_methods_and_removes_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            fixture(run)
            with patch.object(publication, 'code_hash', return_value='frozen'):
                bundle = publication.build(run)
            p = bundle['progress']
            self.assertEqual(p['completed_arms'], 4524)
            self.assertEqual(p['primary_arm'], 'coverage_puct')
            self.assertIn('post-hoc', p['summary']['selection_scope'])
            for case in p['cases']:
                self.assertEqual(set(case['arms']), set(publication.ARMS))
                self.assertNotIn('gold', case)
            for methods in bundle['cases'].values():
                for trace in methods.values():
                    self.assertNotIn('output', trace['steps'][0])
            old = (ROOT / 'README.md').read_text()
            text = publication.readme(old, p)
            self.assertEqual(publication.readme(text, p), text)
            self.assertNotIn('frontend.gif', text)
            self.assertIn('workflow.png', text)
            self.assertIn('4524', text)
            self.assertIn('155', text)
            self.assertIn('## 运行方法', text)
            self.assertNotIn('methodology.gif', text)
            self.assertIn('post-hoc', publication.report(p))
            self.assertNotIn(str(ROOT), text)

    def test_partial_predictions_rejected_before_label_access(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            gate(run)
            publication.select(run)
            for name, value in [('search_test_predictions.json', {'status': 'running', 'cases': {}}),
                                ('active_summary.json', {}), ('frozen_active.json', {}), ('protocol.json', {'test': []})]:
                save(run / name, value)
            with self.assertRaisesRegex(ValueError, '754'):
                publication.build(run)
            self.assertFalse((run / 'sealed_evaluation').exists())

    def test_wrong_score_and_hash_are_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            fixture(run)
            summary = publication.load(run / 'active_summary.json')
            bad = copy.deepcopy(summary)
            bad['metrics']['puct']['correct'] = 753
            save(run / 'active_summary.json', bad)
            with patch.object(publication, 'code_hash', return_value='frozen'):
                with self.assertRaisesRegex(ValueError, 'frozen scorer'):
                    publication.build(run)
            save(run / 'active_summary.json', summary)
            with patch.object(publication, 'code_hash', return_value='changed'):
                with self.assertRaisesRegex(ValueError, 'code changed'):
                    publication.build(run)

    def test_tree_compaction_does_not_invent_or_hide_omission(self):
        row = {'planning': {'simulations': 96, 'nodes': [{'visits': i, 'action': i} for i in range(8)]}}
        plan = publication.display_tree({'search_tree': [row]})[0]['planning']
        self.assertEqual(plan['total_children'], 8)
        self.assertEqual(plan['displayed_children'], 4)
        self.assertEqual([n['action'] for n in plan['nodes']], [7, 6, 5, 4])

    def test_pending_evolution_update_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            fixture(run)
            evolution = publication.load(run / 'active_evolution.json')
            evolution['completed'] = ['case_0000']
            save(run / 'active_evolution.json', evolution)
            with patch.object(publication, 'code_hash', return_value='frozen'):
                with self.assertRaisesRegex(ValueError, 'Pending'):
                    publication.build(run)

    def test_admission_regression_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            fixture(run)
            evolution = publication.load(run / 'active_evolution.json')
            evolution['completed'] = ['case_0000']
            evolution['events'] = [{'case': 'case_0000', 'accepted': True, 'attempts': [{
                'historical_source_gate': {'repairs': 1, 'regressions': 1}, 'rule_quality': {'precision': 1},
                'cross_incident_quality': {'precision': 1, 'supporting_incidents': ['case_0001']}}]}]
            save(run / 'active_evolution.json', evolution)
            with patch.object(publication, 'code_hash', return_value='frozen'):
                with self.assertRaisesRegex(ValueError, 'did not pass'):
                    publication.build(run)

    def test_dynamic_six_method_disk_and_presentation(self):
        import dashboard
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            save(run / 'dashboard.json', {'phase': 'complete', 'arms': publication.ARMS})
            save(run / 'active_summary.json', {})
            for arm in publication.ARMS:
                save(run / f'active_full_traces/case_0000/{arm}.json', {'steps': [], 'search_tree': []})
            store = dashboard.Store(run)
            self.assertEqual(set(store.arms()), set(publication.ARMS))
            self.assertEqual(set(store.case('case_0000')), set(publication.ARMS))


if __name__ == '__main__':
    unittest.main()
