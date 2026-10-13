#!/usr/bin/env python3

import argparse
import gzip
import json
from pathlib import Path
import re

from dashboard import ARMS, ROOT, Store


def export(path, output):
    store = Store(path)
    source = store.progress()
    entries = source.get('cases', [])
    ids = [row['case'] for row in entries]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('Unique scored cases required')
    summary = source.get('summary', {})
    arms = store.arms()
    if source.get('phase') != 'complete' or any(summary.get('metrics', {}).get(arm, {}).get('total') != len(ids) for arm in arms):
        raise ValueError('Complete frozen scoring required before export')
    cases, traces = [], {}
    for row in entries:
        name = row['case']
        if not re.fullmatch(r'case_\d{4}', name):
            raise ValueError('Invalid case identifier')
        values = {}
        for arm in arms:
            value = row['arms'][arm]
            if not isinstance(value.get('correct'), bool):
                raise ValueError('Scored correctness required')
            values[arm] = {key: value[key] for key in ('prediction', 'correct', 'healthy', 'tool_calls', 'wall_sec')}
        cases.append({'case': name, 'partition': row['partition'], 'arms': values})
        bundle = store.case(name)
        if set(bundle) != set(arms):
            raise ValueError('All case traces required')
        traces[name] = {arm: {
            **{key: bundle[arm][key] for key in ('prediction', 'healthy', 'tool_calls', 'wall_sec')},
            'steps': [{key: step.get(key) for key in ('tool', 'arguments', 'elapsed_sec', 'error')}
                      for step in bundle[arm]['steps']], 'search_tree': bundle[arm].get('search_tree', [])} for arm in arms}
    keys = ('metrics', 'comparisons', 'scope', 'harness_hash', 'code_hash', 'significant_gain_verified',
            'evaluation_labels_supplied_to_advisor', 'worker_forbidden_attempts',
            'public_and_benchmark_hashes_unchanged', 'partitions', 'tool_calls', 'evolution',
            'development_selection', 'observed_best_arm', 'selection_scope')
    progress = {
        'run_id': source['run_id'], 'phase': 'complete', 'planned': len(ids), 'completed': len(ids),
        'planned_arms': len(ids) * len(arms), 'completed_arms': len(ids) * len(arms),
        'source': 'Verified final frontend presentation; no original benchmark payload',
        'timeline': [{**{key: event.get(key) for key in ('case', 'accepted', 'status')},
                      'rule': {'id': event['rule']['id']} if event.get('rule') else None}
                     for event in source.get('timeline', [])],
        'rules': source.get('rules', []), 'cases': cases,
        'summary': {key: summary[key] for key in keys if key in summary}}
    progress.update({key: source[key] for key in ('arms', 'primary_arm', 'reference_arm', 'method_family') if key in source})
    body = json.dumps({'schema': 1, 'progress': progress, 'cases': traces}, ensure_ascii=False, separators=(',', ':')).encode()
    if re.search(rb'/(?:Users|home|data/dds-data|root|mnt)/|sk-[A-Za-z0-9_-]{18,}', body):
        raise ValueError('Private path or credential in presentation')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    return {'cases': len(ids), 'traces': len(ids) * len(arms), 'bytes': output.stat().st_size}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'web/presentation.json.gz')
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.output)))
