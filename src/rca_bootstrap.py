from online_protocol import fingerprint


def initial_harness(manifest):
    if manifest['schema'] != 'deepseek_design_rca_adapter_v1':
        raise ValueError('Unsupported initial Harness adapter')
    plugins = manifest['plugins']
    if set(plugins) != {'public_evidence', 'decision_model', 'evidence_planner', 'first_answer',
                        'post_case_advisor', 'experience_admission'}:
        raise ValueError('Unexpected RCA plugin composition')
    if manifest['initial_rules'] or manifest['initial_case_experience'] is not None:
        raise ValueError('Initial Harness cannot contain prior benchmark feedback')
    if not plugins['public_evidence']['read_only'] or not plugins['decision_model']['weights_frozen']:
        raise ValueError('Readonly evidence and frozen JEV are required')
    if plugins['evidence_planner'] != {'backend': 'OpenSpiel PUCT', 'actual_call_cap': 72}:
        raise ValueError('Freeze the JEV-guided PUCT search and actual budget')
    if plugins['first_answer'] != {'immutable': True, 'diagnoses_per_case': 1}:
        raise ValueError('One immutable first answer per case is required')
    if plugins['post_case_advisor']['before_first_answer']:
        raise ValueError('Advisor cannot diagnose the current case')
    admission = plugins['experience_admission']
    if admission['precision_min'] < .95 or admission['supporting_cases_min'] < 2 or admission['historical_diagnosis_reruns'] != 0:
        raise ValueError('Do not weaken evidence admission or rerun prior cases')
    return {'version': 0, 'rules': [], 'bootstrap_sha': fingerprint(manifest),
            'bootstrap': 'DeepSeek plugin-design RCA adaptation, not stock dsh runtime'}
