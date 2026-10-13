

from __future__ import annotations

import argparse

import contextlib

import copy

import hashlib

import importlib.util

import io

import json

import math

from pathlib import Path

import random

import re

import sys

import time

from urllib.request import Request, urlopen

from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

FEATURES = {
    'oom_killed': ('oomkilled', 'out of memory'),
    'image_pull': ('imagepullbackoff', 'errimagepull', 'failed to pull image'),
    'missing_secret': ('secret not found', 'failedmount'),
    'probe_failure': ('readiness probe failed', 'liveness probe failed'),
    'quota_exceeded': ('exceeded quota', 'resource quota'),
    'insufficient_cpu': ('insufficient cpu',),
    'insufficient_memory': ('insufficient memory',),
    'affinity_mismatch': ("didn't match pod", 'affinity', 'node selector'),
    'taint_mismatch': ('untolerated taint', 'had taints'),
    'volume_binding': ('unbound immediate persistentvolumeclaims', 'failedbinding'),
    'permission_denied': ('permission denied', 'forbidden'),
    'zero_replicas': ('replicas: 0', '0 desired'),
    'connection_refused': ('connection refused', 'actively refused', 'connection failed'),
    'dns_failure': ('no such host', 'name or service not known', 'nxdomain'),
    'timeout': ('deadline_exceeded', 'deadline exceeded', 'timed out', 'timeout'),
    'latency_degradation': ('latency_degradation', 'slow response', 'p50latency'),
    'db_credentials': ('access denied for user', 'authentication failed'),
    'db_readonly': ('read-only', 'read only'),
    'db_connections': ('too many connections', 'connection pool exhausted'),
    'empty_endpoints': ('endpoints: <none>', 'endpoints: none', 'no endpoints'),
    'cpu_saturation': ('throttling', 'cpu overload', 'cpu utilization'),
    'packet_loss': ('packet loss', 'retransmit'),
    'unavailable_node': ('status: notready', 'node status: notready', 'schedulingdisabled'),
    'invalid_address': ('invalid:', '-invalid', 'invalid address'),
    'crash_loop': ('crashloopbackoff', 'back-off restarting'),
    'pod_pending': (' pending ',),
    'node_cordoned': ('schedulingdisabled',),
    'pod_quota_full': (),
    'cpu_quota_full': (),
    'memory_quota_full': (),
    'service_quota_full': (),
    'storage_quota_full': (),
}

ALLOWED_TOOLS = {
    'GetResources', 'DescribeResource', 'GetAppYAML', 'GetServiceDependencies',
    'CheckServiceConnectivity', 'GetAlerts', 'GetRecentLogs', 'GetErrorLogs',
    'GetClusterConfiguration', 'CheckNodeServiceStatus', 'ListCodeFiles', 'GetSourceCode',
}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)

def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def catalog(repo):
    contract = module_at('cloudops_contract', repo / 'agents/cloudops_agent/runtime/contracts.py')
    types = {}
    for kind, target, description in re.findall(
        r'^- (\w+) \(Requires Target: (\w+)\): (.+)$',
        contract.root_cause_list_str, re.M,
    ):
        types[kind] = {'target': target.lower(), 'description': description}
    if not types:
        raise ValueError('Cannot parse upstream fault catalog')
    return contract, types

def features(text):
    lower = text.lower()
    found = {key for key, needles in FEATURES.items() if any(x in lower for x in needles)}
    quota_fields = {
        'pod_quota_full': 'pods',
        'cpu_quota_full': 'requests.cpu',
        'memory_quota_full': 'requests.memory',
        'service_quota_full': 'services',
        'storage_quota_full': 'requests.storage',
    }
    for feature, field in quota_fields.items():
        if re.search(rf'{re.escape(field)}:\s*([^\s/]+)\s*/\s*\1(?:\s|$)', lower):
            found.add(feature)
    return sorted(found)

def scoped_lines(steps, obj):
    kind, name = obj.split('/', 1)
    excerpts = []
    for step in steps:
        args = step['arguments']
        text = step['output']
        scoped = any(str(args.get(k, '')) == name for k in ('app_name', 'service_name', 'node_name'))
        resource_name = str(args.get('name', ''))
        scoped = scoped or resource_name == name or resource_name.startswith(name + '-')
        if scoped or kind == 'namespace' and 'quota' in text.lower():
            excerpts.append(text[:5000])
        elif step['tool'] == 'CheckServiceConnectivity' and kind == 'node':
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if name not in line:
                    continue
                block = [line]
                for part in lines[index + 1:index + 5]:
                    if part.startswith('Debug Pod test results deployed on '):
                        break
                    block.append(part)
                excerpts.extend(part[:600] for part in block)
        else:
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if name in line:
                    excerpts.append(line[:600])
    local = '\n'.join(excerpts)
    if kind == 'app' and ' pending ' in f' {local.lower()} ':
        local += '\n' + '\n'.join(
            step['output'] for step in steps
            if step['tool'] == 'GetResources'
            and step['arguments'].get('resource_type') == 'nodes'
            and 'schedulingdisabled' in step['output'].lower()
        )
    return local[:16000]

def scored(bank, rules):
    output = []
    for leaf in bank:
        applied = [r for r in rules if r['feature'] in leaf['features'] and r['root_cause'] == leaf['root_cause']]
        row = {**leaf, 'score': leaf['base_score'] + sum(r['delta'] for r in applied),
               'rule_ids': [r['id'] for r in applied]}
        output.append(row)
    return sorted(output, key=lambda r: (-r['score'], r['fault_object'], r['root_cause']))

def prediction(row):
    return {key: row[key] for key in ('fault_object', 'root_cause')}

def matches(pred, gold):
    return all(pred.get(key) == gold.get(key) for key in ('fault_object', 'root_cause'))

def replay_gate(history, rules, proposal):
    regressions, repairs = [], []
    comparisons = []
    for case in history:
        before = prediction(scored(case['bank'], rules)[0])
        after = prediction(scored(case['bank'], rules + [proposal])[0])
        was, now = matches(before, case['gold']), matches(after, case['gold'])
        comparisons.append({'id': case['id'], 'before': before, 'after': after, 'was_correct': was, 'is_correct': now})
        if was and not now:
            regressions.append(case['id'])
        if not was and now:
            repairs.append(case['id'])
    accepted = bool(repairs) and not regressions
    return {'accepted': accepted, 'mode': 'cached_leaf_rescore', 'checked': len(history),
            'repairs': repairs, 'regressions': regressions, 'comparisons': comparisons,
            'reason': 'net gain with zero replay regressions' if accepted else
                      'replay regression' if regressions else 'no verified improvement'}

def validate_proposal(raw, case, types):
    if not isinstance(raw, dict):
        raise ValueError('Advisor response must be a JSON object')
    expected = {'feature', 'root_cause', 'delta', 'rationale', 'evidence_step', 'evidence_quote'}
    if set(raw) != expected:
        raise ValueError('Unexpected proposal fields')
    if raw['feature'] not in FEATURES or raw['root_cause'] not in types:
        raise ValueError('Unknown feature or fault type')
    delta = float(raw['delta'])
    if not math.isfinite(delta) or not 0 < abs(delta) <= .5:
        raise ValueError('Rule delta must be nonzero and within [-0.5, 0.5]')
    step = raw['evidence_step']
    if type(step) is not int or not 0 <= step < len(case['steps']):
        raise ValueError('Invalid evidence step')
    quote = str(raw['evidence_quote'])
    if len(quote) < 8 or quote not in case['steps'][step]['output']:
        raise ValueError('Evidence quote is not in an observed tool response')
    if raw['feature'] not in features(quote):
        raise ValueError('Quoted evidence does not support the proposed feature')
    if not any(raw['feature'] in row['features'] and raw['root_cause'] == row['root_cause'] for row in case['bank']):
        raise ValueError('Rule has no target in the scored leaf bank')
    rule = {**raw, 'delta': delta}
    rule['id'] = digest({k: rule[k] for k in ('feature', 'root_cause', 'delta')})[:12]
    return rule

class JevRanker:
    def __init__(self, config, cache):
        sys.path.insert(0, str(Path(config['project_root']) / 'vendor/agent-jev'))
        from jev_service.engine import DecisionEngine
        self.engine = DecisionEngine(config['jev_checkpoint'], config['jev_backbone'],
                                     device=config.get('jev_device', 'cuda:0'), max_tokens=8192,
                                     path_batch=8, encoder='auto', temperatures=None)
        self.cache = cache

    def rank(self, state, question, options):
        if not options:
            raise ValueError('Empty JEV candidate set')
        if len(options) == 1:
            return {next(iter(options)): 1.0}
        payload = {'state': state, 'questions': [{'id': 'rank', 'type': 'choice',
                    'question': question, 'options': options}]}
        key = digest(payload)
        path = self.cache / (key + '.json')
        if path.exists():
            return json.loads(path.read_text())
        result = self.engine.evaluate({'id': key, **payload})
        distribution = result['results'][0]['answers'][0]['distribution']
        values = {k: float(distribution[k]) for k in options}
        if any(not math.isfinite(v) for v in values.values()):
            raise ValueError('Nonfinite JEV score')
        dump(path, values)
        return values

class SnapshotSearch:
    def __init__(self, repo, ranker, tool_budget=10, beam=16):
        self.repo, self.ranker = repo, ranker
        self.contract, self.types = catalog(repo)
        self.snap = module_at('cloudops_snapshot', repo / 'agents/cloudops_agent/tools/snapshot.py')
        self.tool_budget, self.beam = tool_budget, beam

    def run(self, path, public):
        
        
        system = 'boutique' if public['namespace'] == 'boutique' else 'train-ticket'
        tools = self.snap.KubernetesTools(str(path), system=system, namespace=public['namespace'])
        steps = []

        def call(name, args):
            if name not in ALLOWED_TOOLS:
                raise ValueError('Unsupported snapshot tool')
            started = time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    result = getattr(tools, name)(**args)
                    error = None
                except (ValueError, KeyError, TypeError) as exc:
                    result, error = str(exc), type(exc).__name__
            output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            steps.append({'tool': name, 'arguments': args, 'output': output,
                          'elapsed_sec': time.monotonic() - started, 'error': error})

        def state():
            
            quota = max(500, 15000 // max(1, len(steps)))
            return public['query'] + '\n' + '\n'.join(
                f"[{i}] {r['tool']} {json.dumps(r['arguments'])}\n{r['output'][:quota]}"
                for i, r in enumerate(steps))

        call('GetAlerts', {})
        call('GetResources', {'resource_type': 'pods', 'name': '', 'namespace': public['namespace']})
        call('GetResources', {'resource_type': 'nodes', 'name': '', 'namespace': public['namespace']})
        call('GetResources', {'resource_type': 'resourcequotas', 'name': '', 'namespace': public['namespace']})
        initial_state = state()
        objects = {f'app/{x}': f'Application {x}' for x in self.contract.SYSTEM_VALID_SERVICES[system]}
        objects.update({f'node/{x}': f'Node {x}' for x in self.contract.VALID_NODES})
        objects[f"namespace/{public['namespace']}"] = 'Namespace scope resource quota'
        components = self.ranker.rank(initial_state, 'Locate the faulty object from observed evidence.', objects)
        base_obj = max(components, key=components.get)
        base_types = {k: v['description'] for k, v in self.types.items() if v['target'] == base_obj.split('/')[0]}
        base_scores = self.ranker.rank(initial_state, f'Choose the fault for {base_obj}.', base_types)
        baseline = {'fault_object': base_obj, 'root_cause': max(base_scores, key=base_scores.get)}

        
        
        actions = {}
        for cache_key in tools.tool_cache:
            name, sep, argument_text = cache_key.partition(':')
            if not sep or name not in ALLOWED_TOOLS:
                continue
            try:
                args = json.loads(argument_text)
            except json.JSONDecodeError:
                continue
            if name in ('GetAppYAML', 'GetErrorLogs', 'GetServiceDependencies', 'GetClusterConfiguration',
                        'CheckNodeServiceStatus', 'DescribeResource', 'CheckServiceConnectivity', 'ListCodeFiles'):
                actions[cache_key] = (name, args)
        trace_tree = []
        for turn in range(max(0, self.tool_budget - len(steps))):
            remaining = {k: v for k, v in actions.items()
                         if not any(s['tool'] == v[0] and s['arguments'] == v[1] for s in steps)}
            if not remaining:
                break
            ordered = sorted(objects, key=lambda x: -components[x])
            favored = {obj.split('/')[1] for obj in ordered[:self.beam]}
            keys = sorted(remaining, key=lambda k: (not any(x in k for x in favored), k))[:40]
            options = {f'a{i}': k for i, k in enumerate(keys)}
            action_scores = self.ranker.rank(state(), 'Choose the next tool to distinguish root cause from downstream effects.', options)
            selected = max(action_scores, key=action_scores.get)
            key = options[selected]
            trace_tree.append({'stage': 'tool', 'choices': [{'label': options[k], 'score': v} for k, v in action_scores.items()], 'selected': key})
            tool_name, tool_args = remaining[key]
            call(tool_name, tool_args)
            if tool_name == 'ListCodeFiles':
                try:
                    listing = json.loads(steps[-1]['output'])
                    for file in listing.get('files', []):
                        args = {'app_name': tool_args['app_name'], 'file_path': file['path']}
                        actions['GetSourceCode:' + json.dumps(args, sort_keys=True)] = ('GetSourceCode', args)
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            components = self.ranker.rank(state(), 'Locate the faulty object using the acquired evidence.', objects)
        ordered = sorted(objects, key=lambda x: (-components[x], x))[:self.beam]
        bank = []
        for obj in ordered:
            available = {k: v['description'] for k, v in self.types.items() if v['target'] == obj.split('/')[0]}
            dist = self.ranker.rank(state(), f'For {obj}, rank direct root causes; reject downstream symptoms.', available)
            local = scoped_lines(steps, obj)
            for fault, value in dist.items():
                bank.append({'fault_object': obj, 'root_cause': fault,
                             'component_score': components[obj], 'type_score': value,
                             'base_score': .4 * components[obj] + .6 * value,
                             'features': features(local)})
        return {'baseline': baseline, 'steps': steps, 'search_tree': trace_tree,
                'component_scores': components, 'bank': bank,
                'runtime': {'engine': 'AgentJev', 'llm_in_diagnosis': False,
                            'context_policy': 'bounded tool excerpts', 'tool_budget': self.tool_budget}}

class Advisor:
    def __init__(self, url, model):
        if urlparse(url).hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('The offline advisor must use a local model endpoint')
        self.url, self.model = url.rstrip('/') + '/chat/completions', model

    def propose(self, case, rules):
        valid_pairs = sorted({
            (feature, row['root_cause'])
            for row in case['bank']
            if row['fault_object'] == case['gold']['fault_object']
            and row['root_cause'] == case['gold']['root_cause']
            for feature in row['features']
        })
        if not valid_pairs:
            return {'no_update': True}, json.dumps(
                {'no_update': True, 'reason': 'No validated feature is scoped to the reference leaf'},
                ensure_ascii=False,
            )
        prompt = {
            'task': 'After this completed RCA case, propose one generic evidence-to-fault ranking rule. Return JSON only, or {"no_update": true}. The feature and root_cause MUST be copied as one exact pair from valid_rule_pairs_for_reference_object. Do not add code, object names, case IDs, or exact answers as matching conditions.',
            'schema': {'feature': 'one allowed feature', 'root_cause': 'one observed candidate root cause',
                       'delta': 'nonzero number from -0.5 to 0.5; use 0.5 for a direct signal that must repair current rank-1', 'rationale': 'brief causal explanation',
                       'evidence_step': 'zero-based index', 'evidence_quote': 'verbatim supporting quote from that tool output'},
            'allowed_features': FEATURES,
            'valid_rule_pairs_for_reference_object': [
                {'feature': feature, 'root_cause': root_cause} for feature, root_cause in valid_pairs
            ],
            'prediction': case['prediction'], 'reference_after_diagnosis': case['gold'],
            'steps': [{**r, 'features': features(r['output']), 'output': r['output'][:1800]} for r in case['steps']],
            'top_leaves': scored(case['bank'], rules)[:12], 'active_rules': rules,
        }
        body = {'model': self.model, 'messages': [{'role': 'user', 'content': json.dumps(prompt, ensure_ascii=False)}],
                'temperature': 0, 'max_tokens': 2048, 'chat_template_kwargs': {'enable_thinking': False}}
        request = Request(self.url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=180) as response:
            text = json.load(response)['choices'][0]['message']['content']
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
        return json.loads(cleaned), text
