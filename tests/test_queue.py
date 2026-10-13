import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controller import request_many, new_correct_proof_coverage, advisor_rows
from grounded import GroundedSearch, digest, write, source_preference, clause_matches
from semantic_rules import rejection


class QueueTest(unittest.TestCase):
    def test_extra_branch_counts_only_novel_calls_and_has_a_hard_cap(self):
        import infrastructure
        class Session:
            def __init__(self, *args):
                self.calls, self.actions = {}, {}
                for kind in ('events', 'services', 'statefulsets', 'persistentvolumes'):
                    args = {'resource_type': kind, 'name': '', 'namespace': 'space'}
                    self.actions[kind] = ('GetResources', args)
            def call(self, tool, args):
                row = {'tool': tool, 'arguments': args, 'output': '', 'error': None}
                self.calls[infrastructure.signature(tool, args)] = row
                return row
        search = object.__new__(GroundedSearch)
        search.contract, search.snapshot, search.budget = {}, None, 2
        search.rank = lambda *args: {}
        existing = {'tool': 'GetResources', 'arguments': {'resource_type': 'events', 'name': '',
                    'namespace': 'space'}, 'output': '', 'error': None}
        
        original = Session.__init__
        def initialize(session, *args):
            original(session, *args)
            session.actions = {infrastructure.signature(t, a): (t, a) for t, a in session.actions.values()}
        Session.__init__ = initialize
        with patch('infrastructure.ToolSession', Session), patch('infrastructure.objects_for', return_value={}):
            result = infrastructure.acquire(search, Path('/unused'), {'namespace': 'space'}, {'steps': [existing]})
        self.assertEqual(result['tool_calls'], 2)
        self.assertEqual(len(result['steps']), 2)
        self.assertNotIn('events', [s['arguments']['resource_type'] for s in result['steps']])

    def test_unverified_exploration_cannot_replace_reference(self):
        search = object.__new__(GroundedSearch)
        search.contract = {}
        search.budget = 24
        baseline = {'prediction': {'fault_object':'app/a', 'root_cause':'old'},
                    'steps': [], 'healthy': True, 'search_tree': [], 'tool_calls':24}
        exploration = dict(baseline, prediction={'fault_object':'app/b', 'root_cause':'new'})
        with patch('grounded.objects_for', return_value={}), patch('grounded.admissible', return_value=[]):
            result = search.combine(baseline, exploration, {'rules': []}, {'namespace':'test'}, 0)
        self.assertEqual(result['prediction'], baseline['prediction'])
        self.assertEqual(result['tool_calls'], 48)
        self.assertNotEqual(result['exploration_prediction'], result['prediction'])

    def test_source_window_equivalent_with_gaps_and_duplicate_lines(self):
        rows = [dict(id='s0l'+str(n), step=0, tool='GetSourceCode', object='app/sample',
                     arguments={'file_path':'main.go'}, text='loop' if n==3 else 'work' if n==14 else 'other')
                for n in (1, 3, 3, 5, 14, 17, 18, 24)]
        clause = {'tool':'GetSourceCode','all':['loop','work']}
        expected = []
        for anchor in rows:
            number = int(anchor['id'].split('l')[1])
            window = [r for r in rows if number <= int(r['id'].split('l')[1]) < number+12]
            text = '\n'.join(r['text'] for r in window)
            if 'loop' in text and 'work' in text:
                expected.append(dict(anchor, text=text, source_ids=[r['id'] for r in window]))
        self.assertEqual(clause_matches(clause, rows), expected)
    def test_entry_source_before_generated_helpers(self):
        self.assertLess(source_preference('main.go'), source_preference('genproto/demo.pb.go'))
        self.assertLess(source_preference('handlers.go'), source_preference('deployment_details.go'))
        self.assertLess(source_preference('product_catalog.go', 'gRPC business API for listing products'),
                        source_preference('server.go', 'process entrypoint and observability setup'))
    def test_cached_batch_preserves_ids_and_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            harness = {'version': 0, 'rules': []}
            for case in ('case_a', 'case_b'):
                payload = {'case': case, 'mode': 'tree', 'harness': harness,
                           'code_hash': 'fixed', 'replay_from': None}
                key = digest(payload)
                write(run / 'queue/outbox' / (key + '.json'),
                      {'healthy': True, 'request_hash': key, 'case': case})
            with patch('controller.code_hash', return_value='fixed'):
                result = request_many(run, ['case_a', 'case_b'], harness)
            self.assertEqual([r['case'] for r in result.values()], ['case_a', 'case_b'])
            self.assertEqual(len(list((run / 'queue/inbox').glob('*.json'))), 2)

    def test_batch_rejects_unhealthy_cached_result(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            payload = {'case': 'case_a', 'mode': 'tree', 'harness': {},
                       'code_hash': 'fixed', 'replay_from': None}
            key = digest(payload)
            write(run / 'queue/outbox' / (key + '.json'), {'healthy': False, 'request_hash': key})
            with patch('controller.code_hash', return_value='fixed'), self.assertRaises(AssertionError):
                request_many(run, ['case_a'], {})


class SemanticTest(unittest.TestCase):
    def check(self, cause, cues):
        return rejection({'cause': cause, 'positive': [{'all': cues}]})

    def test_dns_requires_resolution_failure(self):
        self.assertIsNotNone(self.check('service_dns_resolution_failure', ['total_errors', 'CrashLoopBackOff']))
        self.assertIsNone(self.check('service_dns_resolution_failure', ['no such host']))

    def test_secret_requires_missing_reference(self):
        self.assertIsNotNone(self.check('missing_secret_binding', ['CreateContainerConfigError', 'secretRef']))
        self.assertIsNone(self.check('missing_secret_binding', ['secret', 'not found']))

    def test_quota_requires_blocked_operation(self):
        self.assertIsNotNone(self.check('namespace_service_quota_exceeded', ['services:', '/11']))
        self.assertIsNone(self.check('namespace_service_quota_exceeded', ['exceeded quota', 'services']))

    def test_port_not_inferred_from_absence_of_dns_failure(self):
        self.assertIsNotNone(self.check('mysql_invalid_port', ['Communications link failure', 'JDBCConnectionException']))


class ProofCoverageTest(unittest.TestCase):
    def test_file_write_evidence_before_unrelated_counted_loops(self):
        rows = [dict(id='s1l'+str(n), step=1, tool='GetSourceCode', object='app/sample',
                     arguments={}, text='for i := 0; i < 10; i++ {' if n<120 else
                     'f.WriteString(payload)' if n==122 else 'other') for n in range(125)]
        selected = advisor_rows({'evidence': rows},
                                {'fault_object':'app/sample','root_cause':'code_excessive_file_writes'})
        self.assertIn('s1l122', [r['id'] for r in selected])
    def run_count(self, already_supported):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            gold = {'fault_object': 'app/sample', 'root_cause': 'fault'}
            memory = {c: {'evidence': []} for c in ('case_a', 'case_b')}
            for c in memory:
                write(run / 'public/cases' / c / 'task.json', {'namespace': 'space'})
            with patch('controller.catalog', return_value=({}, {})),\
                    patch('controller.objects_for', return_value=['app/sample']),\
                    patch('controller.witnesses', return_value=[gold]),\
                    patch('controller.admissible', return_value=[gold] if already_supported else []):
                return new_correct_proof_coverage(run, {}, {'rules': []}, memory,
                                                  {c: gold for c in memory})

    def test_new_proof_coverage_is_not_an_accuracy_delta(self):
        self.assertEqual(self.run_count(False), 2)

    def test_existing_proof_is_not_counted_twice(self):
        self.assertEqual(self.run_count(True), 0)


if __name__ == '__main__':
    unittest.main()
