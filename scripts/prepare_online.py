#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grounded import write
from online_protocol import immutable
from prepare import prepare, sha
from worker import code_hash
from rca_bootstrap import initial_harness


def initialize(config, run, seed=20261007):
    result = prepare(config, run)
    sealed = json.loads((run / 'sealed_evaluation/labels.json').read_text())
    cases = sorted(sealed['cases'])
    random.Random(seed).shuffle(cases)
    for case, row in sealed['cases'].items():
        immutable(run / 'sealed_evaluation/cases' / (case + '.json'), row)
    immutable(run / 'sealed_evaluation/labels_manifest.json',
              {p.name: sha(p) for p in (run / 'sealed_evaluation/cases').glob('*.json')})
    immutable(run / 'sealed_evaluation/original_hashes.json', sealed['source_hashes'])
    (run / 'sealed_evaluation/labels.json').unlink()
    write(run / 'feedback_store/labels.json', {'cases': {}})
    manifest = json.loads((ROOT / 'configs/deepseek_rca_bootstrap.json').read_text())
    immutable(run / 'rca_bootstrap.json', manifest)
    harness = initial_harness(manifest)
    write(run / 'live.json', harness)
    write(run / 'versions/v0000.json', harness)
    write(run / 'protocol.json', {'historical_pool': [], 'gate': [], 'evaluation': cases,
                                 'rule_precision_min': .95, 'protocol': 'online_single_pass'})
    immutable(run / 'online_plan.json', {'schema': 'prequential_single_pass_v1', 'cases': cases,
              'order_seed': seed, 'initial_harness': harness, 'mode': 'puct', 'budget': 72,
              'code_hash': code_hash(run), 'advisor_after_every_case': True,
              'experience_refresh_completed_cases': 8, 'no_prior_case_feedback_in_initial_harness': True,
              'prior_public_benchmark_use': True, 'baseline_results_are_separate_experiments': True})
    write(run / 'status.json', {'phase': 'online_prepared', 'planned': len(cases), 'completed': 0})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--seed', type=int, default=20261007)
    args = parser.parse_args()
    from jev import location
    print(json.dumps(initialize(args.config, location(args.run), args.seed)))


if __name__ == '__main__':
    main()
