import argparse
import fcntl
import json
from pathlib import Path
import time

from cloudops_evolution import catalog
from contrastive_experience import fit
from controller import delta, request, propose, rule_quality
from grounded import digest, write
from worker import code_hash
from semantic_rules import rejection


ARMS = {'puct': 'puct', 'greedy': 'coverage_greedy', 'without_jev': 'experience_only',
        'reference': 'tree', 'seed_puct': 'puct_collect', 'coverage_puct': 'coverage_puct'}


def cross_incident_quality(quality, proposal_case):
    counts = [row for case, row in quality['per_historical_case'].items() if case != proposal_case]
    correct = sum(row['correct'] for row in counts)
    wrong = sum(row['wrong'] for row in counts)
    return {'correct': correct, 'wrong': wrong, 'precision': correct / (correct + wrong) if correct + wrong else 0,
            'supporting_incidents': sum(row['correct'] > 0 for row in counts), 'proposal_incident_excluded': True}


def next_residual(pool, state, labels, source):
    attempted = set(state['completed'])
    candidates = [case for case in pool if case not in attempted and state['memory'][case]['prediction'] != labels[case]]
    cause_counts = {}
    for event in state['events']:
        cause = labels[event['case']]['root_cause']
        cause_counts[cause] = cause_counts.get(cause, 0) + 1
    def priority(case):
        label = labels[case]
        ready = not label['root_cause'].startswith('code_') or any(
            row['object'] == label['fault_object'] and row['tool'] == 'GetSourceCode' for row in source[case]['evidence'])
        scores = sorted([row.get('joint_score', 0) for row in state['memory'][case].get('bank', [])], reverse=True)
        margin = scores[0] - scores[1] if len(scores) > 1 else 0
        return (cause_counts.get(label['root_cause'], 0), not ready, -margin, pool.index(case))
    return min(candidates, key=priority) if candidates else None


def inputs(run):
    return json.loads((run / 'protocol.json').read_text())


def collect(run, limit=None):
    plan = inputs(run)
    cases = plan['historical_pool'][:limit] if limit else plan['historical_pool']
    memory_path = run / 'historical_memory.json'
    memory = json.loads(memory_path.read_text()) if memory_path.exists() else {}
    bootstrap_path = run / 'bootstrap_harness.json'
    bootstrap = json.loads(bootstrap_path.read_text()) if bootstrap_path.exists() else {'version': 0, 'rules': []}
    for case in cases:
        if case not in memory:
            memory[case] = request(run, case, bootstrap, mode='puct' if bootstrap_path.exists() else 'puct_collect')
            write(memory_path, memory)
        write(run / 'status.json', {'phase': 'puct_historical_collection', 'completed': len(memory),
                                   'planned': len(cases), 'last_case': case, 'final_labels_opened': False})
        print(json.dumps({'phase': 'collect', 'case': case, 'completed': len(memory)}), flush=True)


def learn(run):
    plan = inputs(run)
    memory = json.loads((run / 'historical_memory.json').read_text())
    if set(memory) != set(plan['historical_pool']):
        raise ValueError('Retain the complete historical pool before admission')
    learned = run / 'experience_learning.json'
    if learned.exists():
        record = json.loads(learned.read_text())
        candidate = json.loads((run / 'candidate_harness.json').read_text())
        artifact = json.loads((run / 'experiences' / (record['artifact_hash'] + '.json')).read_text())
        if record['code_hash'] != code_hash(run) or digest(artifact) != record['artifact_hash'] or candidate['experience_sha'] != record['artifact_hash']:
            raise ValueError('Resume only the unchanged learned method; use a new revision otherwise')
        print(json.dumps({'phase': 'learn', 'resumed': True, 'historical_cases': len(memory)}), flush=True)
        return
    historical = json.loads((run / 'feedback_store/labels.json').read_text())['cases']
    labels = {c: historical[c]['label'] for c in memory}
    tasks = {c: json.loads((run / 'public/cases' / c / 'task.json').read_text()) for c in memory}
    contract, types = catalog(run / 'public/repo')
    artifact = fit(memory, labels, tasks, contract)
    artifact['target_kind'] = {cause: types[cause]['target'] for cause in artifact['classes'] if cause in types}
    key = digest(artifact)
    write(run / 'experiences' / (key + '.json'), artifact)
    seed = json.loads((run / 'live.json').read_text())
    candidate = {'version': 1, 'rules': seed['rules'], 'experience_sha': key}
    write(run / 'candidate_harness.json', candidate)
    write(run / 'experience_learning.json', {'historical_cases': len(memory), 'artifact_hash': key,
                                             'code_hash': code_hash(run), 'test_feedback_used': False})
    print(json.dumps({'phase': 'learn', 'historical_cases': len(memory), 'classes': len(artifact['classes']),
                      'features': len(artifact['vocabulary'])}), flush=True)


def gate(run):
    plan = inputs(run)
    candidate = json.loads((run / 'candidate_harness.json').read_text())
    seed = json.loads((run / 'previous_v3_harness.json').read_text())
    file = run / 'development_predictions.json'
    result = json.loads(file.read_text()) if file.exists() else {'cases': {}, 'code_hash': code_hash(run), 'harness_hash': digest(candidate)}
    if result['code_hash'] != code_hash(run) or result['harness_hash'] != digest(candidate):
        raise ValueError('Use a new revision rather than overwriting predictions')
    for case in plan['gate']:
        arms = result['cases'].setdefault(case, {})
        for name, mode in ARMS.items():
            if name not in arms:
                arms[name] = request(run, case, seed if name in ('reference', 'seed_puct') else candidate, mode=mode)
                write(file, result)
        write(run / 'status.json', {'phase': 'puct_development_gate', 'completed': len(result['cases']),
                                   'planned': len(plan['gate']), 'completed_arms': sum(len(a) for a in result['cases'].values()),
                                   'final_labels_opened': False})
        print(json.dumps({'phase': 'gate', 'case': case, 'completed': len(result['cases'])}), flush=True)
    gold = json.loads((run / 'feedback_store/labels.json').read_text())['cases']
    labels = {c: gold[c]['label'] for c in plan['gate']}
    metrics = {arm: {'correct': sum(result['cases'][c][arm]['prediction'] == labels[c] for c in labels),
                     'total': len(labels)} for arm in ARMS}
    comparison = delta({c: result['cases'][c]['reference'] for c in labels},
                       {c: result['cases'][c]['puct'] for c in labels}, labels)
    outcome = {'metrics': metrics, 'comparison': comparison,
               'passed': comparison['repairs'] > 0 and comparison['regressions'] == 0,
               'current_test_labels_used': False, 'scope': '36-case development gate only',
               'budget_cap': {arm: 72 for arm in ARMS}}
    write(run / 'development_summary.json', outcome)
    write(run / 'status.json', {'phase': 'development_gate_passed' if outcome['passed'] else 'development_gate_failed',
                               'completed': len(labels), 'planned': len(labels), 'summary': outcome})
    print(json.dumps(outcome), flush=True)


def evolve(run, limit=24):
    plan = inputs(run)
    source = json.loads((run / 'historical_memory.json').read_text())
    if set(source) != set(plan['historical_pool']):
        raise ValueError('The full historical pool is required')
    label_rows = json.loads((run / 'feedback_store/labels.json').read_text())['cases']
    labels = {c: label_rows[c]['label'] for c in source}
    _, types = catalog(run / 'public/repo')
    harness = json.loads((run / 'candidate_harness.json').read_text())
    file = run / 'active_evolution.json'
    state = json.loads(file.read_text()) if file.exists() else {'events': [], 'memory': {}, 'completed': [], 'code_hash': code_hash(run), 'harness': harness}
    if state['code_hash'] != code_hash(run):
        raise ValueError('Preserve evolved state and use a new code revision')
    harness = state['harness']
    write(run / 'candidate_harness.json', harness)
    for case in source:
        if case not in state['memory']:
            state['memory'][case] = request(run, case, harness, mode='puct', replay=source[case])
            write(file, state)
    while len(state['completed']) < limit:
        case = next_residual(plan['historical_pool'], state, labels, source)
        if case is None:
            break
        event = {'case': case, 'accepted': False, 'attempts': []}
        feedback = None
        for attempt in range(2):
            try:
                rule = propose(run, case, source[case], labels[case], types, attempt, feedback)
                if rule is None:
                    event['attempts'].append({'reason': 'no_update'})
                    break
                reason = rejection(rule)
                if reason:
                    raise ValueError(reason)
                quality = rule_quality(run, rule, source, label_rows)
                generalization = cross_incident_quality(quality, case)
                if quality['precision'] < plan['rule_precision_min'] or generalization['precision'] < plan['rule_precision_min'] or not generalization['supporting_incidents']:
                    feedback = {'rule_quality': quality, 'cross_incident_quality': generalization,
                                'protocol_error': 'Require direct evidence that generalizes to another completed incident, excluding the proposal case; keep the unchanged precision floor.'}
                    event['attempts'].append(feedback)
                    continue
                candidate = dict(harness, version=harness['version'] + 1,
                                 rules=[r for r in harness['rules'] if r['id'] != rule['id']] + [rule])
                after = {c: request(run, c, candidate, mode='puct', replay=source[c]) for c in source}
                metrics = delta(state['memory'], after, labels)
                feedback = {'historical_source_gate': metrics, 'rule_quality': quality,
                            'cross_incident_quality': generalization,
                            'stage': 'provisional cached historical admission; actual acquisition gate remains mandatory'}
                event['attempts'].append(feedback)
                if metrics['repairs'] > 0 and metrics['regressions'] == 0:
                    harness = candidate
                    state['memory'] = after
                    state['harness'] = harness
                    write(file, state)
                    write(run / 'candidate_harness.json', harness)
                    write(run / 'active_versions' / (digest(harness) + '.json'), harness)
                    event.update(accepted=True, rule=rule)
                    break
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                feedback = {'protocol_error': str(error)}
                event['attempts'].append(feedback)
        state['completed'].append(case)
        state['events'].append(event)
        write(file, state)
        write(run / 'status.json', {'phase': 'post_case_contrastive_evolution', 'completed': len(state['completed']),
                                   'planned_max': limit, 'accepted': sum(e['accepted'] for e in state['events']),
                                   'final_labels_opened': False})
        print(json.dumps({'phase': 'evolve', 'case': case, 'accepted': event['accepted']}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--phase', choices=['collect', 'learn', 'evolve', 'gate'], required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    run = args.run.resolve()
    lock = (run / 'search_controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (run / 'test_predictions.json').exists() or (run / 'search_test_predictions.json').exists():
        raise ValueError('Frozen tests started; no development changes are permitted')
    if args.phase == 'collect':
        collect(run, args.limit)
    elif args.phase == 'learn':
        learn(run)
    elif args.phase == 'evolve':
        evolve(run, args.limit or 24)
    else:
        gate(run)


if __name__ == '__main__':
    main()
