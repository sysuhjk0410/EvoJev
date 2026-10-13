import argparse
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grounded import digest, write


def revise(source_name, name):
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (source_name, name)):
        raise ValueError('Use simple run names')
    source = ROOT / 'runs' / source_name
    run = ROOT / 'runs' / name
    if run.exists():
        raise ValueError('Preserve existing revisions; choose a new name')
    plan = json.loads((source / 'protocol.json').read_text())
    memory = json.loads((source / 'historical_memory.json').read_text())
    if set(memory) != set(plan['historical_pool']):
        raise ValueError('Only completed historical experience may be transferred')
    if (source / 'search_test_predictions.json').exists():
        raise ValueError('Revise from historical/development runs, never final-test feedback')
    harness = json.loads((source / 'candidate_harness.json').read_text())
    learned = json.loads((source / 'experience_learning.json').read_text())
    if harness['experience_sha'] != learned['artifact_hash']:
        raise ValueError('Historical artifact provenance mismatch')
    public = (source / 'public').resolve()
    if ROOT not in public.parents:
        raise ValueError('Prepared observations must remain inside this project')
    run.mkdir(parents=True)
    for file in ('config.json', 'model_identity.json', 'protocol.json', 'previous_v3_harness.json'):
        shutil.copyfile(source / file, run / file)
    for directory in ('sealed_evaluation', 'feedback_store'):
        shutil.copytree(source / directory, run / directory)
    (run / 'public').symlink_to(public, target_is_directory=True)
    for directory in ('queue/inbox', 'queue/outbox', 'scores', 'cache/hf', 'cache/torch',
                      'cache/vllm', 'cache/triton', 'cache/cuda', 'tmp', 'advisor', 'full_traces', 'experiences'):
        (run / directory).mkdir(parents=True, exist_ok=True)
    key = learned['artifact_hash']
    artifact = json.loads((source / 'experiences' / (key + '.json')).read_text())
    if digest(artifact) != key:
        raise ValueError('Historical artifact hash mismatch')
    write(run / 'experiences' / (key + '.json'), artifact)
    write(run / 'bootstrap_harness.json', harness)
    write(run / 'live.json', {'version': 0, 'rules': harness['rules']})
    shutil.copyfile(source / 'historical_memory.json', run / 'prior_historical_memory.json')
    write(run / 'bootstrap_provenance.json', {'source_revision': source_name, 'historical_cases': len(memory),
          'artifact_hash': key, 'completed_historical_experience_only': True,
          'new_revision_requires_actual_acquisition': True, 'final_test_labels_used': False})
    for file in (ROOT / 'src').glob('*.py'):
        shutil.copyfile(file, run / file.name)
    write(run / 'status.json', {'phase': 'prepared_historical_revision', 'planned': 144, 'completed': 0})
    return {'run': name, 'preserved_source': source_name, 'historical_cases': len(memory)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    print(json.dumps(revise(args.source, args.run)))
