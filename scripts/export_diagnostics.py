#!/usr/bin/env python3

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
from export_case_walkthroughs import committed_case, read

ROOT = Path(__file__).resolve().parents[1]


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', '<address>', value)
    prefix = '/' + r'(?:data/dds-data|Users|home|root|mnt)(?:/[^\s"\x27<>]*)?'
    value = re.sub(prefix, '<redacted-path>', value)
    return re.sub(r'sk-[A-Za-z0-9_-]{18,}', '<redacted-token>', value)


def excerpt(value, limit=1100):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    shown = text if len(text) <= limit else text[:limit - 250] + '\n[...]\n' + text[-250:]
    return {'text': redact(shown), 'original_characters': len(text), 'truncated': len(text) > limit}


def project(run, case):
    records = committed_case(run, case)
    first, feedback, update = (records[k] for k in ('first', 'feedback', 'updates'))
    trace = first['trace']
    before = records['dispatches']['payload']['harness']
    old_ids = {rule['id'] for rule in before['rules']}
    new_rules = [rule for rule in update['harness']['rules'] if rule['id'] not in old_ids]
    event = update['event']
    admission = event.get('admission', {})
    admitted = {k: v for k, v in admission.items() if k in event.get('accepted_rule_hashes', [])}
    proof = []
    for pair in trace.get('supported_pairs', [])[:16]:
        proof.append({**{k: pair.get(k) for k in ('fault_object', 'root_cause', 'rule')},
            'witnesses': [{**{k: w.get(k) for k in ('id', 'object', 'source_ids', 'tool')},
                           'excerpt': excerpt(w.get('text', ''), 1300)}
                          for w in pair.get('witnesses', [])[:3]]})
    return redact({'task': read(run / 'public/cases' / case / 'task.json'),
        'observations': [dict(index=i, excerpt=excerpt(s.get('output', '')))
                         for i, s in enumerate(trace.get('steps', []))],
        'object_scores': sorted(trace.get('component_scores', {}).items(), key=lambda v: -v[1])[:8],
        'candidates': trace.get('bank', []), 'supported_pairs': proof,
        'constraint_applied': trace.get('verified_candidate_constraint', False),
        'update': {'decision': event['decision'], 'version_before': before['version'],
            'version_after': update['harness']['version'], 'rules_before': len(before['rules']),
            'rules_after': len(update['harness']['rules']), 'proposal': records['proposals'],
            'new_rules': new_rules, 'admitted_checks': admitted,
            'predicates_checked': len(admission), 'checks_passed': sum(bool(v.get('passed')) for v in admission.values()),
            'experience': event.get('experience', {}), 'future_cases_only': event.get('future_cases_only', True)},
        'integrity': {'first_file_sha256': hashlib.sha256((run / 'online/first' / (case + '.json')).read_bytes()).hexdigest(),
            'first_committed_ns': first['committed_ns'], 'feedback_released_ns': feedback['released_ns'],
            'update_committed_ns': update['committed_ns'], 'new_inference_calls': 0},
        'display_scope': 'Recorded first-answer trace; excerpts may be truncated; addresses and host paths redacted.'})


def build(run):
    summary = read(run / 'online_summary.json')
    plan = read(run / 'online_plan.json')
    if not summary.get('audited') or summary.get('status') != 'complete' or summary.get('pending_updates') != 0:
        raise ValueError('An audited complete run is required')
    if len(plan['cases']) != 754 or len(set(plan['cases'])) != 754:
        raise ValueError('Exactly 754 unique cases required')
    cases = {case: project(run, case) for case in plan['cases']}
    return {'schema': 1, 'run_id': run.name, 'correct': summary['correct'], 'total': 754,
            'new_inference_calls': 0, 'cases': cases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    bundle = build(args.run.resolve())
    output = ROOT / 'web/diagnostics.json.gz'
    body = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode()
    temp = output.with_suffix('.tmp')
    temp.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    temp.replace(output)
    print(json.dumps({'cases': len(bundle['cases']), 'correct': bundle['correct'],
                      'new_inference_calls': 0, 'bytes': output.stat().st_size}))


if __name__ == '__main__':
    main()
