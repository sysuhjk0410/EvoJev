
import argparse
import copy
import fcntl
import hashlib
import json
import math
import re
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from grounded import compile_rule, digest, evidence_excerpt, write, TOOLS, witnesses, admissible
from worker import code_hash
from tree_skill_search import objects_for
from cloudops_evolution import catalog
from semantic_rules import rejection
from settings import load


def request(run, case, harness, mode='tree', replay=None):
    payload = {'case': case, 'mode': mode, 'harness': harness, 'code_hash': code_hash(run),
               'replay_from': replay['request_hash'] if replay else None}
    key = digest(payload)
    target = run / 'queue/outbox' / (key + '.json')
    write(run / 'queue/inbox' / (key + '.json'), payload)
    start = time.monotonic()
    while not target.exists():
        if time.monotonic() - start > 600:
            raise TimeoutError('Diagnosis worker did not respond')
        time.sleep(.3)
    result = json.loads(target.read_text())
    if not result['healthy']:
        raise ValueError('Unhealthy diagnosis: ' + json.dumps(result))
    assert result['request_hash'] == key
    return result


def request_many(run, cases, harness, replay=None):
    pending = {}
    for case in cases:
        payload = {'case': case, 'mode': 'tree', 'harness': harness, 'code_hash': code_hash(run),
                   'replay_from': replay[case]['request_hash'] if replay else None}
        key = digest(payload)
        pending[case] = (key, run / 'queue/outbox' / (key + '.json'))
        write(run / 'queue/inbox' / (key + '.json'), payload)
    start = time.monotonic()
    while any(not path.exists() for _, path in pending.values()):
        if time.monotonic() - start > 1800:
            raise TimeoutError('Batch diagnosis worker did not respond')
        time.sleep(.3)
    result = {}
    for case, (key, path) in pending.items():
        row = json.loads(path.read_text())
        assert row['healthy'] and row['request_hash'] == key
        result[case] = row
    return result


def schema(rows, types):
    def obj(fields):
        return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
    def arr(item, lo=0, hi=3):
        return {'type': 'array', 'items': item, 'minItems': lo, 'maxItems': hi}
    clause = obj({'tool': {'type': 'string', 'enum': TOOLS + ['GetAlerts', 'any']},
                  'arguments': {'type': 'object', 'properties': {'service_name': {'type': 'string', 'maxLength': 80},
                                'resource_type': {'type': 'string', 'maxLength': 80}}, 'additionalProperties': False},
                  'all': arr({'type': 'string', 'minLength': 3, 'maxLength': 100}, 1, 4)})
    rule = obj({'id': {'type': 'string', 'pattern': '^[a-z][a-z0-9_]{2,64}$'},
                'cause': {'type': 'string', 'enum': sorted(types)},
                'target': {'type': 'string', 'enum': ['app', 'node', 'namespace']},
                'checks': arr({'type': 'string', 'enum': TOOLS}, 1, 4),
                'positive': arr(clause, 1, 3), 'negative': arr(clause),
                'evidence_ids': arr({'type': 'string', 'enum': [row['id'] for row in rows]}, 1, 6),
                'explanation': {'type': 'string', 'minLength': 10, 'maxLength': 1000}})
    return {'anyOf': [obj({'no_update': {'const': True}}), obj({'rule': rule})]}


def advisor_rows(trace, label):
    source = [r for r in trace['evidence'] if r['tool'] == 'GetSourceCode' and r['object'] == label['fault_object']]
    focus = re.compile(r'\bsleep\b|time\.Sleep|Thread\.Sleep|\bfor\b|\bwhile\s*\(|ReadFile|ReadAll|WriteFile|WriteString|OpenFile|open\(|append\(|malloc\(|make\(|panic\(|throw\b|raise\b', re.I)
    selected, seen = [], set()
    preferred = {
        'code_artificial_delay': r'\bsleep\b|time\.Sleep|Thread\.Sleep',
        'code_busy_loop': r'\bfor\b|\bwhile\b|time\.Now|math\.',
        'code_memory_leak': r'append\(|malloc\(|make\(|alloc',
        'code_excessive_file_reads': r'ReadFile|ReadAll|os\.Open|readfile',
        'code_excessive_file_writes': r'WriteFile|WriteString|OpenFile|writefile|fstream',
    }
    strong = re.compile(preferred.get(label.get('root_cause'), focus.pattern), re.I)
    centers = sorted([i for i, row in enumerate(source) if focus.search(row['text'])], key=lambda i: (not bool(strong.search(source[i]['text'])), i))
    for i in centers:
        for j in range(max(0, i-3), min(len(source), i+4)):
            if j not in seen:
                seen.add(j); selected.append(j)
    code = [source[i] for i in selected if not source[i]['text'].lstrip().startswith(('//','#','/*','*'))]
    rows, used = [], 0
    for row in code:
        size = len(json.dumps(row))
        if used + size > 7500:
            continue
        rows.append(row); used += size
    ids = {r['id'] for r in rows}
    owned = [r for r in trace['evidence'] if r['object'] == label['fault_object'] and
             r['tool'] != 'GetSourceCode']
    rows.extend(r for r in evidence_excerpt(owned, 6500) if r['id'] not in ids)
    ids = {r['id'] for r in rows}
    rows.extend(r for r in evidence_excerpt(trace['evidence'], 2000) if r['id'] not in ids)
    return rows


def propose(run, case, trace, label, types, attempt, feedback):
    config = load(run / 'config.json')
    rows = advisor_rows(trace, label)
    content = {'observations': rows, 'completed_historical_prediction': trace['prediction'],
               'confirmed_historical_outcome': label, 'catalog': types, 'repair_feedback': feedback}
    prompt = ('Learn one reusable executable diagnostic rule AFTER this completed historical incident. '
              'The final test answers are not available. Return no_update if no direct distinguishing evidence exists. '
              'Choose exact evidence_ids from observations; do not rewrite source quotes. '
              'positive clauses are literal case-insensitive substrings that ALL occur within one source line; '
              'GetSourceCode is the exception: its conjunction may span at most 12 adjacent lines of ONE file '
              'on ONE application. Cite the individual line IDs containing each cue. This allows a loop and '
              'its body to be described without inventing a merged source quote. '
              'all positive clauses must be witnessed for the SAME object. A clause has tool, arguments and all. '
              'Application ownership is ALREADY provided by each observation object; never put its literal '
              'service name in arguments or cues. Application log/code clauses use arguments={}. '
              'Only node daemon clauses may specify service_name. Code causes require direct GetSourceCode '
              'corroboration, not merely latency/throttling or "No error logs found". '
              'arguments is normally {}; for node daemon checks it must specify the generic service_name '
              '(e.g. containerd vs kubelet) so evidence is not joined across different daemons. '
              'all matches one cited line plus its actual tool arguments, so a containerd service_name '
              'can accompany an inactive-status line. Different argument-filtered checks may corroborate one node. '
              'For example a generic missing binding rule can require ["secret", "not found"] in DescribeResource. '
              'Use direct root-cause evidence, not only general symptoms such as HTTP 503, Pending, or high latency. '
              'Differentiate close alternatives with corroborating evidence. No absence-as-proof. '
              'ErrImagePull does NOT imply DNS: require a pull-event name-resolution error. HTTP 503, '
              'CrashLoopBackOff, HTTP-vs-gRPC probe labels, CPU saturation and generic errors are not '
              'unique fault explanations. Seek the actual event/log error before assigning a cause. '
              'OOMKilled alone does not prove a code memory leak; it also occurs with insufficient limits. '
              'ContainerCreating does not prove a low memory limit. For a memory limit rule require '
              'explicit limit-exceeded evidence and corroborating resource configuration. '
              'If cues occupy separate lines, use separate clauses, not an impossible single-line conjunction. '
              'Historical false-positive examples in repair_feedback are completed prior incidents, not test answers. '
              'Use their observations to add generic explicit negative predicates or more discriminative checks. '
              'Old ReplicaSet failure events may coexist with currently created pods; distinguish a current creation '
              'blockage from stale history. Do not treat a symptom or an old event as proof of the current cause. '
              'negative clauses are explicit contradictions, not missing observations. checks are tool names '
              'that future JEV tree searches should actually execute. Never put app/node identities, specific '
              'addresses, case IDs, numeric scores, or incident answer lookups into predicates. '
              'A hypothesis is allowed only when predicates produce cited positive witnesses; JEV ranks survivors. '
              'The historical label is feedback, not a runtime input. Return only JSON.\n' + json.dumps(content))
    payload = {'model': config.get('advisor_name', 'Qwen3.5-27B'), 'temperature': 0, 'max_tokens': 900,
               'chat_template_kwargs': {'enable_thinking': False}, 'messages': [{'role': 'user', 'content': prompt}],
               'response_format': {'type': 'json_schema', 'json_schema': {'name': 'grounded_experience',
                                   'strict': True, 'schema': schema(rows, types)}}}
    req = Request(config['advisor_url'].rstrip('/') + '/v1/chat/completions', json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json'})
    for retry_number in range(6):
        try:
            with urlopen(req, timeout=180) as stream:
                response = json.load(stream)
            break
        except HTTPError:
            raise
        except (URLError, TimeoutError):
            if retry_number == 5:
                raise
            time.sleep(min(30, 5 * (retry_number + 1)))
    online = (run / 'online_plan.json').exists()
    write(run / 'advisor' / f'{case}_{attempt}_{time.time_ns()}.json', {'request': payload, 'response': response,
          'evaluation_labels_supplied': online, 'future_labels_supplied': False,
          'first_prediction_committed_before_feedback': online,
          'role': 'online completed-case feedback' if online else 'post-case historical feedback'})
    result = json.loads(response['choices'][0]['message']['content'])
    if 'rule' not in result:
        return None
    if result['rule']['cause'] != label['root_cause']:
        raise ValueError('Historical feedback confirms a different cause; seek evidence for that cause or return no_update')
    if result['rule']['cause'].startswith('code_') and not any(c['tool'] == 'GetSourceCode' for c in result['rule']['positive']):
        raise ValueError('Code cause requires a positive GetSourceCode clause from the provided exact source lines; symptoms or missing logs alone are insufficient')
    task = json.loads((run / 'public/cases' / case / 'task.json').read_text())
    contract, _ = catalog(run / 'public/repo')
    return compile_rule(result['rule'], trace['evidence'], types, objects_for(contract, task['namespace']))


def delta(before, after, labels):
    repairs = sum(before[c]['prediction'] != labels[c] and after[c]['prediction'] == labels[c] for c in before)
    regressions = sum(before[c]['prediction'] == labels[c] and after[c]['prediction'] != labels[c] for c in before)
    return {'repairs': repairs, 'regressions': regressions, 'correct_before': sum(before[c]['prediction'] == labels[c] for c in before),
            'correct_after': sum(after[c]['prediction'] == labels[c] for c in before), 'total': len(before)}


def rule_quality(run, rule, memory, labels):
    contract, _ = catalog(run / 'public/repo')
    correct, wrong, case_counts = 0, [], {}
    for c, trace in memory.items():
        task = json.loads((run / 'public/cases' / c / 'task.json').read_text())
        matches = witnesses([rule], trace['evidence'], objects_for(contract, task['namespace']))
        counts = {'correct': 0, 'wrong': 0}
        for match in matches:
            prediction = {k: match[k] for k in ('fault_object', 'root_cause')}
            if prediction == labels[c]['label']:
                correct += 1
                counts['correct'] += 1
            else:
                wrong.append((c, trace, match))
                counts['wrong'] += 1
        case_counts[c] = counts
    examples = []
    chosen, seen_status = [], set()
    for c, trace, match in wrong:
        inventory = [r for r in trace['evidence'] if r['object'] == match['fault_object'] and r['tool'] == 'GetResources']
        statuses = tuple(sorted(set(re.findall(r'Running|Pending|ContainerCreating|CrashLoopBackOff|Error', ' '.join(r['text'] for r in inventory)))))
        if statuses not in seen_status:
            chosen.append((c, trace, match)); seen_status.add(statuses)
        if len(chosen) == 3:
            break
    for c, trace, match in chosen:
        rows = [r for r in trace['evidence'] if r['object'] == match['fault_object']]
        inventory = [r for r in rows if r['tool'] == 'GetResources'][:4]
        witness_ids = {r['id'] for r in match['witnesses']}
        direct = [r for r in rows if r['id'] in witness_ids][:4]
        examples.append({'completed_historical_case': c, 'false_hypothesis': {k: match[k] for k in ('fault_object','root_cause')},
                         'confirmed_historical_outcome': labels[c]['label'], 'observations': inventory + direct})
    return {'matching_hypotheses': correct + len(wrong), 'correct_matches': correct,
            'precision': correct / (correct + len(wrong)) if correct + len(wrong) else 0,
            'per_historical_case': case_counts,
            'historical_false_positive_examples': examples, 'final_test_feedback': False}


def new_correct_proof_coverage(run, rule, live, memory, labels):
    contract, _ = catalog(run / 'public/repo')
    count = 0
    for case, trace in memory.items():
        task = json.loads((run / 'public/cases' / case / 'task.json').read_text())
        objects = objects_for(contract, task['namespace'])
        gold = labels[case]
        def contains(rows):
            return any({k: r[k] for k in ('fault_object', 'root_cause')} == gold for r in rows)
        if contains(witnesses([rule], trace['evidence'], objects)) and not contains(
                admissible(live['rules'], trace['evidence'], objects)):
            count += 1
    return count


def prime(run):
    plan = json.loads((run / 'protocol.json').read_text())
    labels = json.loads((run / 'feedback_store/labels.json').read_text())['cases']
    path = run / 'priming.json'
    live = json.loads((run / 'live.json').read_text())
    memory = json.loads(path.read_text()) if path.exists() else {}
    for c in plan['historical_pool']:
        if c not in memory:
            memory[c] = request(run, c, live)
            write(path, memory)
        write(run / 'status.json', {'phase': 'historical_memory_collection', 'completed': len(memory), 'planned': len(plan['historical_pool'])})
    audit = {rule['id']: rule_quality(run, rule, memory, labels) for rule in live['rules']}
    live['rules'] = [rule for rule in live['rules'] if audit[rule['id']]['precision'] >= plan['rule_precision_min']]
    live['version'] += 1
    write(run / 'seed_quality_audit.json', audit)
    write(run / 'live.json', live); write(run / 'versions' / f'v{live["version"]:04d}.json', live)
    memory = {c: request(run, c, live) for c in plan['historical_pool']}
    gate_memory = {c: request(run, c, live) for c in plan['gate']}
    state = {'status': 'training', 'completed': [], 'events': [], 'memory': memory, 'gate_memory': gate_memory,
             'code_hash': code_hash(run), 'all_historical_memory_protected': len(memory)}
    write(run / 'gate_start.json', gate_memory)
    write(run / 'state.json', state)
    print(json.dumps({'historical_memory_completed': len(memory), 'retained_seed_rules': len(live['rules'])}), flush=True)
    train(run)


def dashboard_events(run, state):
    write(run / 'dashboard_events.json', {'timeline': [
        {'case': e['case'], 'accepted': e['accepted'], 'rule': e.get('rule'),
         'status': 'accepted' if e['accepted'] else 'covered' if e.get('redundant_existing_proof') else 'rejected',
         'attempts': len(e['attempts']), 'gate': e['attempts'][-1].get('historical_source_gate', {}) if e['attempts'] else {},
         'retention': e['attempts'][-1].get('separate_gate_aggregate_only', {}) if e['attempts'] else {},
         'precision': e['attempts'][-1].get('rule_quality', {}).get('precision') if e['attempts'] else None,
         'reason': e['attempts'][-1].get('protocol_error') if e['attempts'] else None}
        for e in state['events']]})


def train(run):
    plan = json.loads((run / 'protocol.json').read_text())
    labels = json.loads((run / 'feedback_store/labels.json').read_text())['cases']
    _, types = catalog(run / 'public/repo')
    file = run / 'state.json'
    state = json.loads(file.read_text()) if file.exists() else {'status': 'training', 'completed': [], 'events': [], 'memory': {}, 'gate_memory': {}}
    live = json.loads((run / 'live.json').read_text())
    cold = {'version': 0, 'rules': []}
    if state.get('code_hash') != code_hash(run):
        state['memory'] = {c: request(run, c, live) for c in state['memory']}
        state['gate_memory'] = {c: request(run, c, live) for c in plan['gate']}
        state['code_hash'] = code_hash(run)
        write(file, state)
        dashboard_events(run, state)
    for c in plan['gate']:
        if c not in state['gate_memory']:
            state['gate_memory'][c] = request(run, c, cold)
            write(file, state)
    gate_labels = {c: labels[c]['label'] for c in plan['gate']}
    training_cases = state.get('retry_cases', plan['train'])
    for case in training_cases:
        if case in state['completed']:
            continue
        trace = request(run, case, live)
        state['memory'][case] = trace
        event = {'case': case, 'before': trace['prediction'], 'accepted': False, 'attempts': []}
        feedback = None
        memory_labels = {c: labels[c]['label'] for c in state['memory']}
        for attempt in range(2):
            try:
                rule = propose(run, case, trace, labels[case]['label'], types, attempt, feedback)
                if not rule:
                    event['attempts'].append({'reason': 'no_update'}); break
                reason = rejection(rule)
                if reason:
                    raise ValueError(reason)
                quality = rule_quality(run, rule, state['memory'], labels)
                if quality['precision'] < plan['rule_precision_min']:
                    feedback = {'rule_quality': quality, 'protocol_error': 'Too many historical false positives; strengthen conditions or add explicit contradictions.'}
                    event['attempts'].append(feedback)
                    continue
                stage = copy.deepcopy(live)
                stage['rules'] = [r for r in stage['rules'] if r['id'] != rule['id']] + [rule]
                stage['version'] += 1
                after = request_many(run, state['memory'], stage, replay=state['memory'])
                gate_after = request_many(run, state['gate_memory'], stage, replay=state['gate_memory'])
                inner = delta(state['memory'], after, memory_labels)
                outer = delta(state['gate_memory'], gate_after, gate_labels)
                proof_gain = new_correct_proof_coverage(run, rule, live, state['memory'], memory_labels)
                feedback = {'historical_source_gate': inner, 'separate_gate_aggregate_only': outer,
                            'rule_quality': quality,
                            'new_correct_historical_proof_coverage': proof_gain,
                            'stage': 'cached-evidence provisional; actual acquisition gate required before test'}
                event['attempts'].append(feedback)
                learned = inner['repairs'] > 0 or proof_gain >= 2
                if learned and inner['regressions'] == 0 and outer['regressions'] == 0:
                    write(run / 'versions' / f'v{stage["version"]:04d}.json', stage)
                    write(run / 'live.json', stage)
                    live = stage
                    state['memory'], state['gate_memory'] = after, gate_after
                    event['accepted'] = True
                    event['rule'] = rule
                    break
                if inner['repairs'] == 0 and proof_gain == 0 and inner['regressions'] == 0 and outer['regressions'] == 0:
                    event['redundant_existing_proof'] = True
                    break
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                feedback = {'protocol_error': str(exc)}
                event['attempts'].append(feedback)
        state['completed'].append(case)
        state['events'].append(event)
        write(file, state)
        dashboard_events(run, state)
        write(run / 'status.json', {'phase': 'historical_evolution', 'completed': len(state['completed']),
              'planned': len(training_cases), 'version': live['version'], 'accepted': sum(e['accepted'] for e in state['events'])})
        print(json.dumps({'case': case, 'completed': len(state['completed']), 'accepted': event['accepted'], 'version': live['version']}), flush=True)
    actual = {}
    for case in plan['gate']:
        actual[case] = request(run, case, live)
    cold_gate = {c: request(run, c, cold) for c in plan['gate']}
    gate = delta(cold_gate, actual, gate_labels)
    initial_gate = json.loads((run / 'gate_start.json').read_text())
    rolling = delta(initial_gate, actual, gate_labels)
    passed = gate['repairs'] > 0 and gate['regressions'] == 0 and rolling['regressions'] == 0
    write(run / 'actual_acquisition_gate.json', {'metrics': gate, 'before': cold_gate, 'after': actual,
          'rolling_retention': rolling, 'passed': passed, 'harness_hash': digest(live), 'code_hash': code_hash(run)})
    state['status'] = 'actual_gate_passed' if passed else 'actual_gate_failed'
    write(file, state)
    print(json.dumps({'status': state['status'], 'actual_gate': gate}), flush=True)


def retry(run):
    assert not (run / 'test_predictions.json').exists()
    plan = json.loads((run / 'protocol.json').read_text())
    labels = json.loads((run / 'feedback_store/labels.json').read_text())['cases']
    live = json.loads((run / 'live.json').read_text())
    old = json.loads((run / 'state.json').read_text())
    memory = {c: request(run, c, live) for c in plan['train']}
    remaining = [c for c, t in memory.items() if t['prediction'] != labels[c]['label']]
    archive = run / 'historical_rounds' / str(time.time_ns())
    write(archive / 'state.json', old)
    state = {'status': 'training', 'completed': [], 'events': [], 'memory': memory,
             'gate_memory': {c: request(run, c, live) for c in plan['gate']},
             'code_hash': code_hash(run), 'retry_cases': remaining, 'history': str(archive)}
    write(run / 'state.json', state)
    write(run / 'status.json', {'phase': 'historical_residual_retry', 'completed': 0, 'planned': len(remaining),
          'all_historical_memory_protected': len(memory), 'version': live['version']})
    print(json.dumps({'historical_retry_cases': len(remaining), 'test_labels_opened': False}), flush=True)
    train(run)


def test(run):
    if not (run / 'advisor_stopped.json').exists():
        raise ValueError('Stop the task-owned advisor before frozen evaluation')
    state = json.loads((run / 'state.json').read_text())
    if state['status'] != 'actual_gate_passed':
        raise ValueError('Fix historical method before opening frozen evaluation')
    live = json.loads((run / 'live.json').read_text())
    frozen = run / 'frozen.json'
    if frozen.exists() and json.loads(frozen.read_text()) != live:
        raise ValueError('Frozen Harness cannot change')
    write(frozen, live)
    plan = json.loads((run / 'protocol.json').read_text())
    path = run / 'test_predictions.json'
    result = json.loads(path.read_text()) if path.exists() else {'status': 'running', 'cases': {}, 'code_hash': code_hash(run), 'harness_hash': digest(live)}
    assert result['code_hash'] == code_hash(run) and result['harness_hash'] == digest(live)
    cold = {'version': 0, 'rules': []}
    previous = json.loads((run / 'previous_v3_harness.json').read_text())
    for case in plan['test']:
        arms = result['cases'].setdefault(case, {})
        for arm, model, mode in [('plain_jev', cold, 'initial'), ('static_tree', cold, 'tree'),
                                 ('previous_v3', previous, 'previous_v3'), ('evolved_tree', live, 'tree')]:
            if arm not in arms:
                trace = request(run, case, model, mode)
                target = run / 'full_traces' / case / (arm + '.json')
                write(target, trace)
                arms[arm] = {k: trace[k] for k in ('prediction', 'healthy', 'request_hash', 'tool_calls', 'wall_sec')}
                arms[arm]['trace_path'] = str(target.relative_to(run))
                write(path, result)
        completed = sum(set(arms) == set(plan['arms']) for arms in result['cases'].values())
        write(run / 'status.json', {'phase': 'frozen_evaluation', 'completed': completed, 'planned': len(plan['test']),
              'completed_arms': sum(len(arms) for arms in result['cases'].values()), 'planned_arms': 4 * len(plan['test'])})
        print(json.dumps({'test_case': case, 'completed': len(result['cases'])}), flush=True)
    result['status'] = 'complete'; write(path, result)


def score(run):
    result = json.loads((run / 'test_predictions.json').read_text())
    plan = json.loads((run / 'protocol.json').read_text())
    assert result['status'] == 'complete' and set(result['cases']) == set(plan['test'])
    assert result['code_hash'] == code_hash(run) and result['harness_hash'] == digest(json.loads((run / 'frozen.json').read_text()))
    assert all(set(arms) == set(plan['arms']) and all(t['healthy'] for t in arms.values()) for arms in result['cases'].values())
    audit = [json.loads(l) for l in (run / 'worker_access.jsonl').read_text().splitlines()]
    assert not any('denied' in row for row in audit)
    private = json.loads((run / 'sealed_evaluation/labels.json').read_text())
    labels = private['cases']
    def file_hash(path):
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                h.update(block)
        return h.hexdigest()
    hashes = json.loads((run / 'sealed_evaluation/public_hashes.json').read_text())
    public_unchanged = all(file_hash(run / 'public' / name) == expected for name, expected in hashes.items())
    source_unchanged = all(file_hash(Path(name)) == expected for name, expected in private['source_hashes'].items())
    if (run / 'sealed_evaluation/code_public_hashes.json').exists():
        code_public = json.loads((run / 'sealed_evaluation/code_public_hashes.json').read_text())
        code_source = json.loads((run / 'sealed_evaluation/code_source_hashes.json').read_text())
        public_unchanged = public_unchanged and all(file_hash(run / 'public' / n) == h for n, h in code_public.items())
        source_unchanged = source_unchanged and all(file_hash(Path(n)) == h for n, h in code_source.items())
    assert public_unchanged and source_unchanged
    gold = {c: labels[c]['label'] for c in plan['test']}
    metrics = {arm: {'correct': sum(result['cases'][c][arm]['prediction'] == gold[c] for c in gold), 'total': len(gold)}
               for arm in plan['arms']}
    comparisons = {}
    for base in ['plain_jev', 'static_tree', 'previous_v3']:
        before = {c: result['cases'][c][base] for c in gold}
        after = {c: result['cases'][c]['evolved_tree'] for c in gold}
        diff = delta(before, after, gold)
        n = diff['repairs'] + diff['regressions']
        diff['paired_exact_p'] = min(1, 2 * sum(math.comb(n, k) for k in range(min(diff['repairs'], diff['regressions']) + 1)) / 2**n) if n else 1
        diff['delta_pp'] = 100 * (diff['correct_after'] - diff['correct_before']) / len(gold)
        diff['criterion_passed'] = diff['repairs'] - diff['regressions'] >= 6 and diff['delta_pp'] >= 10 and diff['paired_exact_p'] < .05
        comparisons[base] = diff
    summary = {'metrics': metrics, 'comparisons': comparisons, 'scope': plan['scope'],
               'harness_hash': result['harness_hash'], 'code_hash': result['code_hash'],
               'significant_gain_verified': all(d['criterion_passed'] for d in comparisons.values()),
               'evaluation_labels_supplied_to_advisor': False, 'worker_forbidden_attempts': 0,
               'public_and_benchmark_hashes_unchanged': public_unchanged and source_unchanged}
    summary['partitions'] = {name: {arm: {'correct': sum(result['cases'][c][arm]['prediction'] == gold[c] for c in cases),
                            'total': len(cases)} for arm in plan['arms']}
                            for name, cases in plan['partitions'].items()}
    summary['tool_calls'] = {arm: {'total': sum(result['cases'][c][arm]['tool_calls'] for c in gold),
                            'maximum': max(result['cases'][c][arm]['tool_calls'] for c in gold)} for arm in plan['arms']}
    state = json.loads((run / 'state.json').read_text())
    summary['evolution'] = {'accepted': sum(e['accepted'] for e in state['events']),
                            'completed_historical_updates': len(state['completed']),
                            'final_rules': len(json.loads((run / 'frozen.json').read_text())['rules'])}
    write(run / 'summary.json', summary)
    write(run / 'scored_cases.json', [{'case': c, 'gold': gold[c], 'answers': {arm: row['prediction'] for arm, row in result['cases'][c].items()}} for c in gold])
    write(run / 'status.json', {'phase': 'complete', 'completed': len(gold), 'planned': len(gold),
                              'completed_arms': len(gold) * len(plan['arms']), 'pending_updates': 0})
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--run', type=Path, required=True); p.add_argument('--phase', choices=['prime', 'train', 'retry', 'test', 'score'], required=True)
    a = p.parse_args()
    with (a.run / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        {'prime': prime, 'train': train, 'retry': retry, 'test': test, 'score': score}[a.phase](a.run.resolve())
