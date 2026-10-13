import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from online_controller import evolve, quality_gate, receive
from online_protocol import Ledger, immutable, fingerprint


class OnlineExecutionTests(unittest.TestCase):
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
        dispatch = self.ledger.reserve('case_0000', self.seed)
        self.trace = {'case': 'case_0000', 'code_hash': 'frozen', 'request_hash': dispatch['request_hash'],
                      'healthy': True, 'prediction': self.gold, 'tool_calls': 10, 'evidence': []}

    def test_outbox_resume_never_requeues_completed_diagnosis(self):
        key = self.trace['request_hash']
        immutable(self.run / 'queue/outbox' / (key + '.json'), self.trace)
        self.assertEqual(receive(self.run, self.ledger, 'case_0000', self.seed), self.trace)
        self.assertFalse((self.run / 'queue/inbox' / (key + '.json')).exists())

    def test_ambiguous_interrupted_dispatch_stops_without_retake(self):
        key = self.trace['request_hash']
        immutable(self.run / 'queue/outbox' / (key + '.json'), dict(self.trace, healthy=False, blocked_retake=True))
        with self.assertRaises(RuntimeError):
            receive(self.run, self.ledger, 'case_0000', self.seed)
        self.assertFalse((self.run / 'queue/inbox' / (key + '.json')).exists())

    def test_one_case_support_does_not_admit_rule(self):
        quality = {'precision': 1, 'per_historical_case': {'case_0000': {'correct': 1, 'wrong': 0}}}
        gate = quality_gate(quality, {'case_0000': self.trace}, {'case_0000': self.gold})
        self.assertFalse(gate['passed'])

    def test_wrong_witness_on_correct_case_blocks_update(self):
        quality = {'precision': .97, 'per_historical_case': {
            'case_0000': {'correct': 1, 'wrong': 1}, 'case_0001': {'correct': 2, 'wrong': 0}}}
        gate = quality_gate(quality, {'case_0000': self.trace, 'case_0001': self.trace},
                            {'case_0000': self.gold, 'case_0001': self.gold})
        self.assertFalse(gate['passed'])

    def test_cached_predicate_gate_does_not_claim_accuracy_guarantee(self):
        quality = {'precision': 1, 'per_historical_case': {
            'case_0000': {'correct': 1, 'wrong': 0}, 'case_0001': {'correct': 1, 'wrong': 0}}}
        gate = quality_gate(quality, {'case_0000': self.trace, 'case_0001': self.trace},
                            {'case_0000': self.gold, 'case_0001': self.gold})
        self.assertTrue(gate['passed'])
        self.assertFalse(gate['prediction_nonregression_guaranteed'])

    def test_llm_no_update_is_saved_and_not_called_again_on_resume(self):
        self.ledger.commit_first('case_0000', self.trace)
        self.ledger.release_feedback('case_0000')
        with patch('online_controller.catalog', return_value=({}, {})), \
                patch('online_controller.propose', return_value=None) as advisor, \
                patch('controller.request', side_effect=AssertionError('No diagnosis replays')):
            harness, event = evolve(self.run, self.ledger, 'case_0000', self.seed)
            harness2, event2 = evolve(self.run, self.ledger, 'case_0000', self.seed)
        self.assertEqual(advisor.call_count, 1)
        self.assertEqual(harness, self.seed)
        self.assertEqual(harness2, harness)
        self.assertEqual(event2, event)
        self.assertEqual(event['decision'], 'no_update')


if __name__ == '__main__':
    unittest.main()
