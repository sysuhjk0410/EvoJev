import argparse
import hashlib
import json
from pathlib import Path

from controller import delta, request
from grounded import digest, write
from worker import code_hash


ARMS = {'puct': 'puct', 'greedy': 'coverage_greedy', 'without_jev': 'experience_only', 'reference': 'tree', 'seed_puct': 'puct_collect', 'coverage_puct': 'coverage_puct'}


def predict(run):
    gate = json.loads((run / 'development_summary.json').read_text())
    if not gate['passed'] or not (run / 'advisor_stopped.json').exists():
        raise ValueError('Actual gate and stopped advisor are required')
    candidate = json.loads((run / 'candidate_harness.json').read_text())
    plan = json.loads((run / 'protocol.json').read_text())
    if len(plan['test']) != 754 or len(set(plan['test'])) != 754:
        raise ValueError('Exactly 754 unique planned cases are required')
    frozen = run / 'frozen_active.json'
    record = {'harness': candidate, 'harness_hash': digest(candidate), 'code_hash': code_hash(run),
              'arms': ARMS, 'budget_cap': 72, 'scope': plan['scope']}
    if frozen.exists() and json.loads(frozen.read_text()) != record:
        raise ValueError('Frozen method cannot change')
    write(frozen, record)
    path = run / 'search_test_predictions.json'
    result = json.loads(path.read_text()) if path.exists() else {'cases': {}, 'code_hash': record['code_hash'], 'harness_hash': record['harness_hash'], 'status': 'running'}
    if result['code_hash'] != code_hash(run) or result['harness_hash'] != digest(candidate):
        raise ValueError('Resume only the exact frozen method')
    if not set(result['cases']).issubset(plan['test']) or any(not set(arms).issubset(ARMS) for arms in result['cases'].values()):
        raise ValueError('Unexpected cases or arms in saved predictions')
    seed = json.loads((run / 'previous_v3_harness.json').read_text())
    for case in plan['test']:
        arms = result['cases'].setdefault(case, {})
        for arm, mode in ARMS.items():
            if arm in arms:
                continue
            trace = request(run, case, seed if arm in ('reference', 'seed_puct') else candidate, mode=mode)
            if not trace['healthy'] or trace.get('retrospective_replay') or trace['tool_calls'] > 72:
                raise ValueError('Frozen test requires healthy actual-acquisition traces')
            target = run / 'active_full_traces' / case / (arm + '.json')
            write(target, trace)
            arms[arm] = {key: trace[key] for key in ('prediction', 'healthy', 'request_hash', 'tool_calls', 'wall_sec')}
            arms[arm]['trace_path'] = str(target.relative_to(run))
            write(path, result)
        write(run / 'status.json', {'phase': 'frozen_active_full_test', 'completed': len(result['cases']),
                                   'planned': 754, 'completed_arms': sum(len(a) for a in result['cases'].values()),
                                   'planned_arms': len(ARMS) * 754, 'final_labels_opened': False})
        print(json.dumps({'phase': 'full', 'case': case, 'completed': len(result['cases'])}), flush=True)
    result['status'] = 'complete'
    write(path, result)


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def score(run):
    result = json.loads((run / 'search_test_predictions.json').read_text())
    plan = json.loads((run / 'protocol.json').read_text())
    frozen = json.loads((run / 'frozen_active.json').read_text())
    if result['status'] != 'complete' or len(result['cases']) != 754 or set(result['cases']) != set(plan['test']):
        raise ValueError('All 754 unique cases must be complete before opening final labels')
    if result['code_hash'] != code_hash(run) or result['harness_hash'] != frozen['harness_hash']:
        raise ValueError('Frozen hash mismatch')
    if any(set(arms) != set(ARMS) or any(not row['healthy'] or row['tool_calls'] > 72 for row in arms.values()) for arms in result['cases'].values()):
        raise ValueError('All predeclared actual prediction arms are required')
    for case, arms in result['cases'].items():
        for arm, compact in arms.items():
            trace = json.loads((run / compact['trace_path']).read_text())
            if trace['case'] != case or trace['code_hash'] != result['code_hash'] or trace['prediction'] != compact['prediction'] or trace['request_hash'] != compact['request_hash'] or trace.get('retrospective_replay') or trace['tool_calls'] != compact['tool_calls']:
                raise ValueError('Actual trace audit mismatch')
    audit = [json.loads(line) for line in (run / 'worker_access.jsonl').read_text().splitlines()]
    if any('denied' in row for row in audit):
        raise ValueError('Worker access audit contains a forbidden attempt')
    private = json.loads((run / 'sealed_evaluation/labels.json').read_text())
    hashes = json.loads((run / 'sealed_evaluation/public_hashes.json').read_text())
    if not all(sha(run / 'public' / name) == expected for name, expected in hashes.items()):
        raise ValueError('Public observations changed')
    if not all(sha(Path(name)) == expected for name, expected in private['source_hashes'].items()):
        raise ValueError('External benchmark source changed')
    gold = {case: value['label'] for case, value in private['cases'].items()}
    def metrics(cases):
        return {arm: {'correct': sum(result['cases'][c][arm]['prediction'] == gold[c] for c in cases),
                      'total': len(cases)} for arm in ARMS}
    summary = {'metrics': metrics(plan['test']), 'partitions': {name: metrics(cases) for name, cases in plan['partitions'].items()},
               'scope': plan['scope'], 'code_hash': code_hash(run), 'harness_hash': frozen['harness_hash'],
               'worker_forbidden_attempts': 0, 'public_and_benchmark_hashes_unchanged': True,
               'all_tool_budgets': 72, 'advisor_stopped_before_test': True,
               'comparisons': {arm: delta({c: result['cases'][c][arm] for c in gold},
                                           {c: result['cases'][c]['puct'] for c in gold}, gold)
                               for arm in ARMS if arm != 'puct'}}
    summary['target_met'] = summary['metrics']['puct']['correct'] >= 604
    write(run / 'active_summary.json', summary)
    write(run / 'status.json', {'phase': 'target_met_pending_presentation_sync' if summary['target_met'] else 'full_evaluated_below_target',
                               'completed': 754, 'planned': 754, 'summary': summary})
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--phase', choices=['predict', 'score'], required=True)
    args = parser.parse_args()
    (predict if args.phase == 'predict' else score)(args.run.resolve())
