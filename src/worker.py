import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import time
import traceback
from grounded import GroundedSearch, digest, write
from isolation import install
from tree_skill_search import objects_for
from settings import load


def code_hash(run):
    names = ['grounded.py', 'infrastructure.py', 'reference_v3.py', 'retention_search.py', 'worker.py', 'tree_skill_search.py', 'blind_search.py', 'cloudops_evolution.py', 'settings.py', 'isolation.py', 'controller.py', 'semantic_rules.py', 'config.json', 'model_identity.json']
    names += [name for name in ('active_search.py', 'puct_planner.py', 'contrastive_experience.py', 'search_experiment.py', 'search_pipeline.py', 'active_full.py', 'online_protocol.py', 'online_controller.py', 'rca_bootstrap.py', 'rca_bootstrap.json') if (run / name).exists()]
    return digest({name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in names})


def serve(run):
    barrier = install(run, run / 'worker_access.jsonl')
    from cloudops_evolution import JevRanker
    lock = (run / 'worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ranker = JevRanker(load(run / 'config.json'), run / 'scores')
    ranker.engine.max_tokens = 8192
    search = GroundedSearch(run / 'public/repo', ranker, budget=24)
    experience_cache = {}
    def experience_data(harness):
        key = harness.get('experience_sha')
        if not key:
            return None
        assert len(key) == 64 and all(c in '0123456789abcdef' for c in key)
        if key not in experience_cache:
            data = json.loads((run / 'experiences' / (key + '.json')).read_text())
            assert digest(data) == key
            experience_cache[key] = data
        return experience_cache[key]
    version = code_hash(run)
    for name in ('processed', 'retired'):
        (run / 'queue' / name).mkdir(exist_ok=True)
    write(run / 'worker_health.json', {'ready': True, 'code_hash': version, 'label_access': False})
    while not (run / 'STOP_WORKER').exists():
        for file in sorted((run / 'queue/inbox').glob('*.json')):
            destination = run / 'queue/outbox' / file.name
            if destination.exists():
                file.rename(run / 'queue/processed' / file.name)
                continue
            request = json.loads(file.read_text())
            if request['code_hash'] != version:
                file.rename(run / 'queue/retired' / file.name)
                continue
            assert set(request) == {'case', 'mode', 'harness', 'code_hash', 'replay_from'} and digest(request) == file.stem
            assert '/' not in request['case'] and '..' not in request['case']
            path = run / 'public/cases' / request['case']
            blocked_retake = False
            try:
                if (run / 'online_plan.json').exists():
                    plan = json.loads((run / 'online_plan.json').read_text())
                    from rca_bootstrap import initial_harness
                    if initial_harness(json.loads((run / 'rca_bootstrap.json').read_text())) != plan['initial_harness']:
                        raise ValueError('Initial DeepSeek-design RCA plugin composition changed')
                    dispatch = json.loads((run / 'online/dispatches' / (request['case'] + '.json')).read_text())
                    index = dispatch['index']
                    expected = plan['cases'][index]
                    harness = plan['initial_harness'] if index == 0 else json.loads(
                        (run / 'online/updates' / (plan['cases'][index - 1] + '.json')).read_text())['harness']
                    payload = {'case': expected, 'mode': plan['mode'], 'harness': harness,
                               'code_hash': plan['code_hash'], 'replay_from': None}
                    if request != payload:
                        raise ValueError('Online worker accepts only the next immutable first dispatch')
                    if dispatch['payload'] != payload or dispatch['request_hash'] != file.stem:
                        raise ValueError('Dispatch reservation mismatch')
                    if (run / 'online/first' / (expected + '.json')).exists():
                        raise ValueError('A committed first answer cannot be diagnosed again')
                    claim = run / 'online/started' / (expected + '.json')
                    claim.parent.mkdir(parents=True, exist_ok=True)
                    if claim.exists():
                        blocked_retake = True
                        raise ValueError('Previous dispatch started without an outbox result; fail closed, never re-diagnose')
                    with claim.open('x') as stream:
                        json.dump({'case': expected, 'request_hash': file.stem, 'started_ns': time.time_ns()}, stream)
                        stream.flush()
                        import os
                        os.fsync(stream.fileno())
                public = json.loads((path / 'task.json').read_text())
                if request['replay_from']:
                    key = request['replay_from']
                    assert len(key) == 64 and all(c in '0123456789abcdef' for c in key)
                    previous = json.loads((run / 'queue/outbox' / (key + '.json')).read_text())
                    assert previous['case'] == request['case'] and previous['healthy']
                    if request['mode'] == 'puct':
                        from active_search import ActiveSearch
                        plan = json.loads((run / 'protocol.json').read_text())
                        if request['case'] not in plan['historical_pool']:
                            raise ValueError('Cached admission is historical-only, never final evaluation')
                        result = ActiveSearch(run / 'public/repo', ranker, budget=72).replay(
                            previous, public, request['harness'], experience_data(request['harness']))
                    else:
                        assert previous['code_hash'] == version
                        search.current_objects = objects_for(search.contract, public['namespace'])
                        result = search.replay(previous, request['harness'])
                else:
                    if request['mode'] in ('puct', 'puct_collect', 'coverage_greedy', 'experience_only', 'coverage_puct'):
                        from active_search import ActiveSearch
                        result = ActiveSearch(run / 'public/repo', ranker, budget=72).run(
                            path, public, request['harness'], experience_data(request['harness']),
                            planner=request['mode'] != 'coverage_greedy', jev=request['mode'] != 'experience_only',
                            contrastive=request['mode'] != 'coverage_puct')
                    elif request['mode'] == 'previous_v3':
                        from reference_v3 import GroundedSearch as PreviousSearch
                        previous_search = PreviousSearch(run / 'public/repo', ranker, budget=24)
                        result = previous_search.run(path, public, request['harness'])
                    else:
                        result = search.run(path, public, request['harness'], request['mode'])
                result.update(case=request['case'], code_hash=version, request_hash=file.stem)
            except Exception as exc:
                result = {'healthy': False, 'error': str(exc), 'traceback': traceback.format_exc(),
                          'case': request['case'], 'code_hash': version, 'request_hash': file.stem,
                          'blocked_retake': blocked_retake}
            write(destination, result)
            file.rename(run / 'queue/processed' / file.name)
            write(run / 'worker_health.json', {'ready': True, 'last_case': request['case'],
                  'healthy': result['healthy'], 'label_access': bool(barrier['denied'])})
        time.sleep(.3)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--run', type=Path, required=True)
    serve(p.parse_args().run.resolve())
