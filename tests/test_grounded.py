import copy
import unittest
from grounded import scoped_rows, witnesses, compile_rule, clause_matches, admissible


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.objects = {'app/alpha': 'alpha', 'app/beta': 'beta', 'node/worker-01': 'node'}
        self.types = {'missing_secret_binding': {'target': 'app'}}
        self.steps = [{'tool': 'DescribeResource', 'arguments': {'name': 'alpha-xyz', 'resource_type': 'pods'},
                       'output': 'Warning secret x not found'},
                      {'tool': 'GetErrorLogs', 'arguments': {'app_name': 'beta'}, 'output': 'Healthy process'}]
        self.rows = scoped_rows(self.steps, self.objects)
        self.rule = {'id': 'missing_binding', 'cause': 'missing_secret_binding', 'target': 'app',
                     'checks': ['DescribeResource'], 'positive': [{'tool': 'DescribeResource', 'all': ['secret', 'not found']}],
                     'negative': [], 'evidence_ids': ['s0l0'], 'explanation': 'A named secret binding explicitly fails to resolve.'}

    def test_valid_source_id_compiles(self):
        compiled = compile_rule(self.rule, self.rows, self.types, self.objects)
        self.assertNotIn('evidence_ids', compiled)
        self.assertEqual(witnesses([compiled], self.rows, self.objects)[0]['fault_object'], 'app/alpha')

    def test_no_label_or_object_lookup(self):
        raw = copy.deepcopy(self.rule); raw['positive'][0]['all'] = ['alpha']
        with self.assertRaises(ValueError): compile_rule(raw, self.rows, self.types, self.objects)

    def test_invalid_evidence_id_rejected(self):
        raw = copy.deepcopy(self.rule); raw['evidence_ids'] = ['s99l0']
        with self.assertRaises(ValueError): compile_rule(raw, self.rows, self.types, self.objects)

    def test_hallucinated_condition_rejected(self):
        raw = copy.deepcopy(self.rule); raw['positive'][0]['all'] = ['password rejected']
        with self.assertRaises(ValueError): compile_rule(raw, self.rows, self.types, self.objects)

    def test_no_cross_object_join(self):
        raw = copy.deepcopy(self.rule)
        raw['positive'].append({'tool': 'GetErrorLogs', 'all': ['Healthy']})
        raw['evidence_ids'].append('s1l0')
        with self.assertRaises(ValueError): compile_rule(raw, self.rows, self.types, self.objects)

    def test_explicit_contradiction(self):
        raw = copy.deepcopy(self.rule); raw['negative'] = [{'tool': 'DescribeResource', 'all': ['not found']}]
        self.assertFalse(witnesses([raw], self.rows, self.objects))

    def test_transport_ids_do_not_bind_object(self):
        rows = scoped_rows([{'tool': 'GetErrorLogs', 'arguments': {'app_name': 'beta'}, 'output': 'Warning secret x not found'}], self.objects)
        self.assertEqual(witnesses([self.rule], rows, self.objects), [])

    def test_empty_positive_forbidden(self):
        raw = copy.deepcopy(self.rule); raw['positive'] = []
        with self.assertRaises(ValueError): compile_rule(raw, self.rows, self.types, self.objects)

    def test_snapshot_service_name_log_contract(self):
        rows = scoped_rows([{'tool': 'GetErrorLogs', 'arguments': {'namespace': 'boutique', 'service_name': 'alpha'},
                              'output': 'explicit failure'}], self.objects)
        self.assertEqual(rows[0]['object'], 'app/alpha')

    def test_structured_alerts_preserve_declared_subject(self):
        import json
        rows = scoped_rows([{'tool': 'GetAlerts', 'arguments': {}, 'output': json.dumps({'alerts': [
            {'name': 'alpha', 'evidence': ['cpu throttled']}, {'name': 'beta', 'evidence': ['latency']} ]})}], self.objects)
        self.assertEqual([r['object'] for r in rows], ['app/alpha', 'app/beta'])
        self.assertNotIn('latency', rows[0]['text'])

    def test_event_owner_is_object_column_not_mentioned_downstream(self):
        rows = scoped_rows([{'tool': 'GetResources', 'arguments': {'resource_type': 'events'},
              'output': '1m Warning FailedCreate replicaset/alpha-xyz beta dependency failed'}], self.objects)
        self.assertEqual(rows[0]['object'], 'app/alpha')

    def test_event_without_involved_owner_stays_unscoped(self):
        rows = scoped_rows([{'tool': 'GetResources', 'arguments': {'resource_type': 'events'},
              'output': '1m Warning FailedCreate replicaset/unknown beta dependency failed'}], self.objects)
        self.assertIsNone(rows[0]['object'])

    def test_storage_owner_comes_from_observed_workload_reference(self):
        steps = [{'tool': 'GetAppYAML', 'arguments': {'app_name': 'alpha'},
                  'output': 'spec:\n  template:\n    spec:\n      volumes:\n      - persistentVolumeClaim:\n          claimName: shared-data'},
                 {'tool': 'DescribeResource', 'arguments': {'resource_type': 'persistentvolumeclaims', 'name': 'shared-data'},
                  'output': 'Warning selector mismatch'}]
        rows = scoped_rows(steps, self.objects)
        self.assertEqual(rows[-1]['object'], 'app/alpha')

    def test_ambiguous_shared_storage_is_not_assigned_to_one_app(self):
        yaml = 'spec:\n  volumes:\n  - persistentVolumeClaim:\n      claimName: shared-data'
        steps = [{'tool': 'GetAppYAML', 'arguments': {'app_name': a}, 'output': yaml} for a in ('alpha', 'beta')]
        steps.append({'tool': 'DescribeResource', 'arguments': {'resource_type': 'persistentvolumeclaims', 'name': 'shared-data'},
                      'output': 'Warning selector mismatch'})
        self.assertIsNone(scoped_rows(steps, self.objects)[-1]['object'])

    def test_code_conjunction_can_span_short_same_file_window(self):
        steps = [{'tool':'GetSourceCode','arguments':{'app_name':'alpha','file_path':'main.go'},
                  'output':'for {\n  _, err := os.Open(path)\n  buf, err := io.ReadAll(file)\n}'}]
        rows = scoped_rows(steps, self.objects)
        matches = clause_matches({'tool':'GetSourceCode','all':['for {','os.Open','io.ReadAll']}, rows)
        self.assertTrue(matches)
        self.assertEqual(matches[0]['source_ids'], ['s0l0','s0l1','s0l2','s0l3'])

    def test_code_windows_do_not_join_files_or_distant_lines(self):
        steps = [{'tool':'GetSourceCode','arguments':{'app_name':'alpha','file_path':'one.go'},'output':'for {'},
                 {'tool':'GetSourceCode','arguments':{'app_name':'alpha','file_path':'two.go'},'output':'os.Open(path)'}]
        self.assertFalse(clause_matches({'tool':'GetSourceCode','all':['for {','os.Open']}, scoped_rows(steps, self.objects)))
        steps = [{'tool':'GetSourceCode','arguments':{'app_name':'alpha','file_path':'one.go'},
                  'output':'for {\n'+'x\n'*20+'os.Open(path)'}]
        self.assertFalse(clause_matches({'tool':'GetSourceCode','all':['for {','os.Open']}, scoped_rows(steps, self.objects)))

    def test_same_subject_mechanism_precedes_pressure_syndrome(self):
        steps = [{'tool':'GetSourceCode','arguments':{'app_name':'alpha','file_path':'one.go'},'output':'for {\n cpuSpin()\n}'},
                 {'tool':'GetAlerts','arguments':{},'output':'alpha throttled'}]
        rules = [{'id':'loop','cause':'code_busy_loop','target':'app','positive':[{'tool':'GetSourceCode','all':['for {','cpuSpin']}],'negative':[]},
                 {'id':'pressure','cause':'pod_cpu_overload','target':'app','positive':[{'tool':'GetAlerts','all':['throttled']}],'negative':[]}]
        rows = scoped_rows(steps, self.objects)
        self.assertEqual(len(witnesses(rules, rows, self.objects)), 2)
        self.assertEqual([v['root_cause'] for v in admissible(rules, rows, self.objects)], ['code_busy_loop'])

    def test_node_service_name_is_not_node_identity(self):
        rows = scoped_rows([{'tool': 'CheckNodeServiceStatus', 'arguments': {'node_name': 'worker-01', 'service_name': 'containerd'},
                             'output': 'Active: failed'}], self.objects)
        self.assertEqual(rows[0]['object'], 'node/worker-01')

    def test_status_alone_is_not_dns_evidence(self):
        raw = copy.deepcopy(self.rule); raw['positive'] = [{'tool': 'DescribeResource', 'all': ['ErrImagePull']}]
        with self.assertRaises(ValueError): compile_rule(raw, self.rows, self.types, self.objects)

    def test_oom_status_does_not_prove_code_leak(self):
        raw = copy.deepcopy(self.rule)
        raw['cause'] = 'code_memory_leak'
        raw['positive'] = [{'tool': 'DescribeResource', 'all': ['Reason:', 'OOMKilled']}]
        rows = scoped_rows([{'tool': 'DescribeResource', 'arguments': {'name': 'alpha'},
                            'output': 'Reason: OOMKilled'}], self.objects)
        with self.assertRaises(ValueError): compile_rule(raw, rows, {'code_memory_leak': {'target': 'app'}}, self.objects)

    def test_container_creating_not_memory_limit_evidence(self):
        raw = copy.deepcopy(self.rule)
        raw['positive'] = [{'tool': 'DescribeResource', 'all': ['ContainerCreating']}]
        rows = scoped_rows([{'tool': 'DescribeResource', 'arguments': {'name': 'alpha'},
                            'output': 'ContainerCreating'}], self.objects)
        with self.assertRaises(ValueError): compile_rule(raw, rows, self.types, self.objects)

    def test_node_daemons_do_not_cross_join(self):
        steps = [{'tool': 'CheckNodeServiceStatus', 'arguments': {'node_name': 'worker-01', 'service_name': 'containerd'},
                   'output': 'Service: containerd\nActive: active (running)'},
                 {'tool': 'CheckNodeServiceStatus', 'arguments': {'node_name': 'worker-01', 'service_name': 'kubelet'},
                   'output': 'Service: kubelet\nActive: failed'}]
        rule = {'id': 'runtime_failed', 'cause': 'containerd_unavailable', 'target': 'node',
                'positive': [{'tool': 'CheckNodeServiceStatus', 'all': ['Service: containerd']},
                             {'tool': 'CheckNodeServiceStatus', 'all': ['Active: failed']}], 'negative': []}
        self.assertFalse(witnesses([rule], scoped_rows(steps, self.objects), self.objects))

    def test_inactive_daemon_and_socket_error_corroborate(self):
        steps = [{'tool': 'CheckNodeServiceStatus', 'arguments': {'node_name': 'worker-01', 'service_name': 'containerd'},
                  'output': 'Active: inactive (dead)'},
                 {'tool': 'CheckNodeServiceStatus', 'arguments': {'node_name': 'worker-01', 'service_name': 'kubelet'},
                  'output': 'containerd.sock: no such file or directory'}]
        rule = {'id': 'runtime_failed', 'cause': 'containerd_unavailable', 'target': 'node',
                'positive': [{'tool': 'CheckNodeServiceStatus', 'arguments': {'service_name': 'containerd'}, 'all': ['containerd', 'inactive']},
                             {'tool': 'CheckNodeServiceStatus', 'arguments': {'service_name': 'kubelet'}, 'all': ['containerd.sock', 'no such file']}], 'negative': []}
        self.assertEqual(witnesses([rule], scoped_rows(steps, self.objects), self.objects)[0]['fault_object'], 'node/worker-01')


if __name__ == '__main__': unittest.main()
