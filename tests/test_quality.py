import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from controller import rule_quality, advisor_rows
from grounded import write


class QualityTests(unittest.TestCase):
    def test_source_statement_not_displaced_by_many_events(self):
        rows = [{'id':f's0l{i}','step':0,'tool':'DescribeResource','object':'app/alpha',
                 'arguments':{},'text':'Warning failure ' * 90} for i in range(100)]
        rows.append({'id':'s1l0','step':1,'tool':'GetSourceCode','object':'app/alpha',
                     'arguments':{},'text':'time.Sleep(5 * time.Second)'})
        result = advisor_rows({'evidence':rows}, {'fault_object':'app/alpha'})
        self.assertIn('s1l0', [r['id'] for r in result])

    def test_cause_and_subject_both_required_for_precision(self):
        rule = {'id': 'binding', 'cause': 'missing_secret_binding', 'target': 'app',
                'positive': [{'tool': 'DescribeResource', 'all': ['secret', 'not found']}], 'negative': []}
        memory = {'history_a': {'evidence': [{'id':'s0l0','step':0,'tool':'DescribeResource','arguments':{},
                                            'object':'app/alpha','text':'secret not found'}]}}
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write(run / 'public/cases/history_a/task.json', {'namespace':'sample'})
            with patch('controller.catalog', return_value=(object(), {})), patch('controller.objects_for', return_value={'app/alpha':'Alpha','app/beta':'Beta'}):
                exact = rule_quality(run, rule, memory, {'history_a': {'label': {'fault_object':'app/alpha','root_cause':'missing_secret_binding'}}})
                wrong_subject = rule_quality(run, rule, memory, {'history_a': {'label': {'fault_object':'app/beta','root_cause':'missing_secret_binding'}}})
        self.assertEqual(exact['precision'], 1)
        self.assertEqual(wrong_subject['precision'], 0)
        self.assertEqual(len(wrong_subject['historical_false_positive_examples']), 1)
        self.assertFalse(wrong_subject['final_test_feedback'])


if __name__ == '__main__':
    unittest.main()
