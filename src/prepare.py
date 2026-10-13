
import hashlib
import json
from pathlib import Path
import shutil

from grounded import write
from settings import PROJECT, load


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def enumerate_cases(repo):
    groups = {}
    for path in sorted(repo.glob('benchmark/*/*/*/metadata.json')):
        group = '/'.join(path.parent.relative_to(repo / 'benchmark').parts[:2])
        groups.setdefault(group, []).append(path)
    ordered = []
    for _, members in sorted(groups.items()):
        ordered.extend(sorted(members, key=lambda p: (int(p.parent.name) if p.parent.name.isdigit() else 10**12, p.parent.name)))
    return {f'case_{i:04d}': path for i, path in enumerate(ordered)}


def prepare(config_file, run, single=None):
    config = load(config_file)
    repo, run = Path(config['benchmark_root']), Path(run).resolve()
    if run.exists():
        raise ValueError('Run exists: choose a new name; use resume for interrupted runs')
    checkpoint = Path(config['jev_checkpoint'])
    if not checkpoint.is_file() or not Path(config['jev_backbone']).is_dir():
        raise FileNotFoundError('Configure external JEV checkpoint and backbone first')
    cases = enumerate_cases(repo)
    plan = json.loads((PROJECT / 'configs/protocol_full754.json').read_text())
    if len(cases) != 754:
        raise ValueError(f'Expected pinned 754-case benchmark; found {len(cases)}')
    if single is not None and single not in cases:
        raise ValueError('Unknown case id')
    selected = {single: cases[single]} if single else cases
    run.mkdir(parents=True)
    write(run / 'config.json', config)
    write(run / 'model_identity.json', {'checkpoint_sha256': sha(checkpoint),
        'backbone_config_sha256': sha(Path(config['jev_backbone']) / 'config.json'),
        'checkpoint_is_external': True})
    labels, originals = {}, {}
    for case, path in selected.items():
        meta = json.loads(path.read_text())
        destination = run / 'public/cases' / case
        write(destination / 'task.json', {k: meta[k] for k in ('query', 'namespace')})
        labels[case] = {'source': str(path.parent.relative_to(repo / 'benchmark')),
                        'label': {k: meta['result'][k] for k in ('fault_object', 'root_cause')}}
        originals[str(path)] = sha(path)
        for name in ('tool_cache.json', 'raw_data/logs.json'):
            source = path.parent / name
            if source.exists():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                originals[str(source)] = sha(source)
        code = path.parent / 'code'
        if code.exists():
            shutil.copytree(code, destination / 'code')
            originals.update({str(p): sha(p) for p in code.rglob('*') if p.is_file()})
    for name in ('agents/cloudops_agent/runtime/contracts.py', 'agents/cloudops_agent/tools/snapshot.py'):
        target = run / 'public/repo' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
        originals[str(repo / name)] = sha(repo / name)
    hashes = {str(p.relative_to(run / 'public')): sha(p) for p in (run / 'public').rglob('*') if p.is_file()}
    write(run / 'sealed_evaluation/labels.json', {'cases': labels, 'source_hashes': originals})
    write(run / 'sealed_evaluation/public_hashes.json', hashes)
    feedback = {c: labels[c] for c in plan['historical_pool'] + plan['gate'] if c in labels}
    write(run / 'feedback_store/labels.json', {'cases': feedback})
    write(run / 'protocol.json', plan)
    seed = json.loads((PROJECT / 'configs/seed_v3.json').read_text())
    write(run / 'previous_v3_harness.json', seed)
    seed['version'] = 0
    write(run / 'live.json', seed)
    write(run / 'versions/v0000.json', seed)
    for path in (PROJECT / 'src').glob('*.py'):
        shutil.copyfile(path, run / path.name)
    for name in ('queue/inbox', 'queue/outbox', 'scores', 'cache/hf', 'cache/torch',
                 'cache/vllm', 'cache/triton', 'cache/cuda', 'tmp', 'advisor', 'full_traces'):
        (run / name).mkdir(parents=True, exist_ok=True)
    write(run / 'status.json', {'phase': 'prepared', 'planned': len(selected), 'completed': 0})
    return {'run': str(run), 'cases': len(selected), 'source_read_only': True}
