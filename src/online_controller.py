import argparse
import copy
import fcntl
import json
from pathlib import Path
import time
from urllib.error import URLError

from cloudops_evolution import catalog
from contrastive_experience import fit
from controller import propose, rule_quality
from grounded import digest, write
from guard_process import available_gib
from online_protocol import Ledger, read, immutable
from semantic_rules import rejection
from worker import code_hash


def receive(run, ledger, case, harness):
    record = ledger.reserve(case, harness)
    key = record['request_hash']
    target = run / 'queue/outbox' / (key + '.json')
    if not target.exists():
        inbox = run / 'queue/inbox' / (key + '.json')
        if not inbox.exists() and not (run / 'online/started' / (case + '.json')).exists():
            immutable(inbox, record['payload'])
        start = time.monotonic()
        while not target.exists():
            if available_gib() < 50:
                raise RuntimeError('MemAvailable below 50 GiB safety floor')
            health = run / 'worker_health.json'
            if health.exists() and read(health).get('label_access'):
                raise RuntimeError('Worker label-access barrier violation')
            if time.monotonic() - start > 900:
                raise TimeoutError('Await the original dispatch; never submit a second diagnosis')
            time.sleep(.3)
    trace = read(target)
    if trace.get('blocked_retake'):
        raise RuntimeError('Ambiguous interrupted first dispatch; diagnosis retake is forbidden')
    if trace.get('request_hash') != key:
        raise ValueError('Outbox request mismatch')
    return trace


def signature(rule):
    return digest({key: rule.get(key) for key in ('cause', 'target', 'checks', 'positive', 'negative')})


def quality_gate(quality, memory, labels):
    supporting = sum(row['correct'] > 0 for row in quality['per_historical_case'].values())
    conflicts = [case for case, row in quality['per_historical_case'].items()
                 if row['wrong'] and memory[case].get('healthy') and memory[case].get('prediction') == labels[case]]
    return {'passed': quality['precision'] >= .95 and supporting >= 2 and not conflicts,
            'precision': quality['precision'], 'minimum_precision': .95, 'supporting_cases': supporting,
            'minimum_supporting_cases': 2, 'wrong_witnesses_on_originally_correct_cases': conflicts,
            'validation': 'pure cached predicate matching; zero JEV or tool re-execution',
            'prediction_nonregression_guaranteed': False}


def evolve(run, ledger, case, harness):
    memory, labels = ledger.memory()
    trace = memory[case]
    if not trace.get('healthy'):
        return harness, {'decision': 'unhealthy_diagnosis', 'reason': 'First failure remains scored wrong; no retake'}
    contract, types = catalog(run / 'public/repo')
    candidates = {}
    for prior in ledger.plan['cases'][:len(memory)]:
        file = run / 'online/proposals' / (prior + '.json')
        if file.exists() and read(file).get('rule'):
            rule = read(file)['rule']
            candidates[signature(rule)] = rule
    file = run / 'online/proposals' / (case + '.json')
    if not file.exists():
        try:
            rule = propose(run, case, trace, labels[case], types, 0,
                           {'protocol': 'First answer permanently committed. Update future cases only.',
                            'past_completed_cases': len(memory), 'current_harness_rules': harness['rules']})
            if rule and rejection(rule):
                immutable(file, {'rule': None, 'decision': 'rejected', 'reason': rejection(rule)})
            else:
                immutable(file, {'rule': rule, 'decision': 'proposed' if rule else 'no_update'})
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            immutable(file, {'rule': None, 'decision': 'rejected', 'reason': str(error)})
        except (URLError, TimeoutError) as error:
            immutable(file, {'rule': None, 'decision': 'advisor_unavailable', 'reason': str(error)})
    proposal = read(file)
    if proposal.get('rule'):
        candidates[signature(proposal['rule'])] = proposal['rule']
    candidate = copy.deepcopy(harness)
    existing = {signature(rule) for rule in candidate['rules']}
    audits, accepted = {}, []
    healthy_memory = {c: t for c, t in memory.items() if t.get('healthy')}
    label_rows = {c: {'label': labels[c]} for c in healthy_memory}
    for key, rule in candidates.items():
        if key in existing:
            continue
        quality = rule_quality(run, rule, healthy_memory, label_rows)
        audit = quality_gate(quality, healthy_memory, labels)
        audits[key] = audit
        if audit['passed']:
            candidate['rules'].append(dict(rule, id='online_' + key[:20]))
            existing.add(key)
            accepted.append(key)
    experience = {'decision': 'unchanged'}
    if len(healthy_memory) >= 8 and len(memory) % 8 == 0:
        tasks = {c: read(run / 'public/cases' / c / 'task.json') for c in healthy_memory}
        try:
            artifact = fit(healthy_memory, {c: labels[c] for c in healthy_memory}, tasks, contract)
            artifact['target_kind'] = {cause: types[cause]['target'] for cause in artifact['classes'] if cause in types}
            key = digest(artifact)
            immutable(run / 'experiences' / (key + '.json'), artifact)
            candidate['experience_sha'] = key
            experience = {'decision': 'updated', 'completed_cases_only': len(memory), 'artifact_hash': key}
        except ValueError as error:
            experience = {'decision': 'deferred', 'reason': str(error)}
    changed = digest(candidate) != digest(harness)
    if changed:
        candidate['version'] = harness['version'] + 1
    event = {'decision': 'accepted' if accepted else proposal['decision'] if proposal['decision'] != 'proposed' else 'rejected',
             'accepted_rule_hashes': accepted, 'admission': audits, 'experience': experience,
             'llm_proposal': proposal['decision'], 'future_cases_only': True, 'diagnosis_reruns': 0,
             'scored_prediction_replaced': False, 'completed_feedback_cases': len(memory)}
    return candidate, event


def audit(run, ledger):
    from prepare import sha
    plan = ledger.plan
    if ledger.summary()['completed'] != len(plan['cases']):
        raise ValueError('Full single-pass stream is incomplete')
    ledger.validate()
    for case in plan['cases']:
        feedback = read(ledger.file('feedback', case))
        if feedback['label'] != read(run / 'sealed_evaluation/cases' / (case + '.json'))['label']:
            raise ValueError('Released feedback differs from its sealed source')
    dispatches = list((run / 'online/dispatches').glob('*.json'))
    starts = list((run / 'online/started').glob('*.json'))
    if len(dispatches) != len(plan['cases']) or len(starts) != len(plan['cases']):
        raise ValueError('Exactly one physical dispatch/start per case is required')
    violations = [json.loads(line) for line in (run / 'worker_access.jsonl').read_text().splitlines()
                  if line.strip() and json.loads(line).get('denied')]
    if violations:
        raise ValueError('Forbidden worker access detected')
    manifest = read(run / 'sealed_evaluation/public_hashes.json')
    if any(sha(run / 'public' / name) != key for name, key in manifest.items()):
        raise ValueError('Public observations changed during evaluation')
    manifest = read(run / 'sealed_evaluation/labels_manifest.json')
    if any(sha(run / 'sealed_evaluation/cases' / name) != key for name, key in manifest.items()):
        raise ValueError('Feedback source integrity failure')
    original = read(run / 'sealed_evaluation/original_hashes.json')
    if any(sha(name) != key for name, key in original.items()):
        raise ValueError('External benchmark files changed')
    result = dict(ledger.summary(), audited=True, unique_cases=len(plan['cases']),
                  label_release='only after immutable same-case first prediction',
                  zero_forbidden_worker_access=True, source_hashes_verified=True,
                  pending_updates=0, physical_diagnosis_starts=len(starts))
    write(run / 'online_summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    run = args.run.resolve()
    lock = (run / 'online_controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ledger = Ledger(run)
    if code_hash(run) != ledger.plan['code_hash']:
        raise ValueError('Freeze runtime code for the entire online experiment')
    while True:
        index, case, harness = ledger.current()
        if case is None or args.limit is not None and index >= args.limit:
            break
        if available_gib() < 50:
            raise RuntimeError('MemAvailable below 50 GiB safety floor')
        write(run / 'status.json', dict(ledger.summary(), current_case=case, stage='first_diagnosis'))
        if not ledger.file('first', case).exists():
            ledger.commit_first(case, receive(run, ledger, case, harness))
        ledger.release_feedback(case)
        write(run / 'status.json', dict(ledger.summary(), current_case=case, stage='post_case_llm_update'))
        updated, event = evolve(run, ledger, case, harness)
        ledger.commit_update(case, updated, event)
        immutable(run / 'online/versions' / (digest(updated) + '.json'), updated)
        write(run / 'live.json', updated)
        status = ledger.summary()
        write(run / 'status.json', status)
        print(json.dumps(status), flush=True)
    if ledger.current()[1] is None:
        result = audit(run, ledger)
        write(run / 'status.json', result)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
