import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from online_protocol import Ledger, immutable, fingerprint
from rca_bootstrap import initial_harness


class OnlineProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.seed = {'version': 0, 'rules': []}
        self.gold = {'fault_object': 'app/subject', 'root_cause': 'code_busy_loop'}
        immutable(self.run / 'online_plan.json', {'cases': ['case_0000', 'case_0001'],
                  'initial_harness': self.seed, 'mode': 'puct', 'code_hash': 'frozen', 'budget': 72})
        for case in ('case_0000', 'case_0001'):
            immutable(self.run / 'sealed_evaluation/cases' / (case + '.json'), {'label': self.gold})
        self.ledger = Ledger(self.run)

    def prediction(self, case='case_0000', correct=False):
        _, _, harness = self.ledger.current()
        dispatch = self.ledger.reserve(case, harness)
        trace = {'case': case, 'code_hash': 'frozen', 'request_hash': dispatch['request_hash'],
                 'healthy': True, 'prediction': self.gold if correct else {}, 'tool_calls': 72,
                 'retrospective_replay': False}
        self.ledger.commit_first(case, trace)
        return trace

    def test_feedback_before_first_answer_is_forbidden(self):
        with self.assertRaises(ValueError):
            self.ledger.release_feedback('case_0000')

    def test_future_feedback_is_forbidden(self):
        self.prediction()
        with self.assertRaises(ValueError):
            self.ledger.release_feedback('case_0001')

    def test_first_answer_cannot_be_corrected(self):
        trace = self.prediction()
        with self.assertRaises(ValueError):
            self.ledger.commit_first('case_0000', dict(trace, prediction=self.gold))

    def test_duplicate_resume_does_not_create_another_dispatch(self):
        first = self.ledger.reserve('case_0000', self.seed)
        second = self.ledger.reserve('case_0000', self.seed)
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.run / 'online/dispatches').glob('*.json'))), 1)

    def test_cannot_skip_a_case(self):
        with self.assertRaises(ValueError):
            self.ledger.reserve('case_0001', self.seed)

    def test_update_requires_feedback(self):
        self.prediction()
        with self.assertRaises(ValueError):
            self.ledger.commit_update('case_0000', self.seed, {'decision': 'no_update'})

    def test_update_applies_only_to_future_case(self):
        self.prediction()
        self.ledger.release_feedback('case_0000')
        new = {'version': 1, 'rules': [{'id': 'generic_rule'}]}
        self.ledger.commit_update('case_0000', new, {'decision': 'accepted'})
        self.assertEqual(self.ledger.current(), (1, 'case_0001', new))
        self.assertEqual(self.ledger.summary()['correct'], 0)
        with self.assertRaises(ValueError):
            self.ledger.reserve('case_0000', new)

    def test_resume_checks_hash_chain(self):
        trace = self.prediction()
        self.ledger.release_feedback('case_0000')
        self.ledger.commit_update('case_0000', self.seed, {'decision': 'no_update'})
        path = self.ledger.file('first', 'case_0000')
        row = json.loads(path.read_text())
        row['trace']['prediction'] = self.gold
        path.write_text(json.dumps(row))
        with self.assertRaises(ValueError):
            Ledger(self.run)

    def test_complete_keeps_first_answer_score(self):
        self.prediction()
        self.ledger.release_feedback('case_0000')
        self.ledger.commit_update('case_0000', self.seed, {'decision': 'rejected'})
        self.prediction('case_0001', True)
        self.ledger.release_feedback('case_0001')
        self.ledger.commit_update('case_0001', self.seed, {'decision': 'no_update'})
        result = Ledger(self.run).summary()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['accuracy'], .5)
        self.assertEqual(result['completed'], 2)

    def test_retrospective_trace_is_forbidden(self):
        dispatch = self.ledger.reserve('case_0000', self.seed)
        with self.assertRaises(ValueError):
            self.ledger.commit_first('case_0000', {'request_hash': dispatch['request_hash'],
                                    'retrospective_replay': True})

    def test_budget_overrun_is_forbidden(self):
        dispatch = self.ledger.reserve('case_0000', self.seed)
        with self.assertRaises(ValueError):
            self.ledger.commit_first('case_0000', {'case': 'case_0000', 'code_hash': 'frozen',
                'request_hash': dispatch['request_hash'], 'healthy': True, 'tool_calls': 73})

    def test_prediction_after_completed_update_cannot_be_changed(self):
        trace = self.prediction()
        self.ledger.release_feedback('case_0000')
        self.ledger.commit_update('case_0000', self.seed, {'decision': 'no_update'})
        self.assertEqual(self.ledger.commit_first('case_0000', trace)['trace'], trace)
        with self.assertRaises(ValueError):
            self.ledger.commit_first('case_0000', dict(trace, prediction=self.gold))

    def test_immutable_commit_cannot_replace_records(self):
        path = self.run / 'record.json'
        immutable(path, {'answer': 1})
        with self.assertRaises(ValueError):
            immutable(path, {'answer': 2})

    def test_duplicate_plan_is_rejected(self):
        plan = json.loads((self.run / 'online_plan.json').read_text())
        plan['cases'] = ['case_0000', 'case_0000']
        (self.run / 'online_plan.json').write_text(json.dumps(plan))
        with self.assertRaises(ValueError):
            Ledger(self.run)

    def test_bootstrap_has_no_prior_case_feedback(self):
        manifest = json.loads((Path(__file__).resolve().parents[1] / 'configs/deepseek_rca_bootstrap.json').read_text())
        result = initial_harness(manifest)
        self.assertEqual(result['rules'], [])
        self.assertNotIn('experience_sha', result)
        self.assertIn('not stock dsh', result['bootstrap'])
        manifest['initial_rules'] = [{'cause': 'known_answer'}]
        with self.assertRaises(ValueError):
            initial_harness(manifest)
