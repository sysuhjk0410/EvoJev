
import copy
import hashlib
import json
import re
import time

from tree_skill_search import ToolSession, objects_for, signature

TOOLS = ['DescribeResource', 'GetAppYAML', 'GetErrorLogs', 'CheckNodeServiceStatus',
         'GetResources', 'GetServiceDependencies', 'GetClusterConfiguration',
         'CheckServiceConnectivity', 'ListCodeFiles', 'GetSourceCode']
WEAK_CUES = {'error', 'running', 'pending', 'errimagepull', 'imagepullbackoff', 'crashloopbackoff',
             'http-get', 'grpc', 'liveness:', 'readiness:', 'serviceaccountname:', 'kind: serviceaccount',
             'cpu_cfs', 'throttled', 'http 503', '503', 'httperror', 'availability_missing',
             'failed', 'false', 'true', 'unhealthy', 'notready', 'memory', 'cpu', 'latency',
             'containercreating', 'createcontainerconfigerror', 'reason:', 'oomkilled'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def entity(text, objects):
    names = [obj for obj in objects if text == obj.split('/', 1)[1] or
             (obj.startswith('app/') and text.startswith(obj[4:] + '-'))]
    return max(names, key=len) if names else None


def bound_subject(args):
    return str(args.get('app_name') or args.get('node_name') or args.get('name') or args.get('service_name') or '')


def scoped_rows(steps, objects):
    rows = []
    for si, step in enumerate(steps):
        args = step['arguments']
        obj = entity(bound_subject(args), objects)
        declared = {}
        lines = step['output'].splitlines()
        if step['tool'] == 'GetAlerts':
            try:
                alerts = json.loads(step['output']).get('alerts')
                if isinstance(alerts, list) and all(isinstance(alert, dict) for alert in alerts):
                    lines = [json.dumps(alert, ensure_ascii=False) for alert in alerts]
                    declared = {i: entity(str(alert.get('name', '')), objects) for i, alert in enumerate(alerts)}
            except (json.JSONDecodeError, AttributeError):
                pass
        for li, line in enumerate(lines):
            scoped = declared.get(li) or obj
            if not scoped and step['tool'] == 'GetResources' and line.split():
                scoped = entity(line.split()[0], objects)
            if not scoped and step['tool'] == 'GetAlerts':
                matches = [key for key in objects if re.search(r'(?<![\w-])' + re.escape(key.split('/', 1)[1]) + r'(?![\w-])', line)]
                if len(matches) == 1:
                    scoped = matches[0]
            if not scoped and args.get('resource_type') in {'resourcequotas', 'namespaces'}:
                scoped = next((o for o in objects if o.startswith('namespace/')), None)
            rows.append({'id': f's{si}l{li}', 'step': si, 'tool': step['tool'],
                         'object': scoped, 'arguments': args, 'text': line[:1800]})
    return rows


def clause_matches(clause, rows):
    candidates = [row for row in rows if (clause['tool'] == 'any' or row['tool'] == clause['tool']) and
            all(row['arguments'].get(k) == v for k, v in clause.get('arguments', {}).items()) and
            row['tool'] != 'GetSourceCode']
    if clause['tool'] == 'GetSourceCode':
        groups = {}
        for row in rows:
            if row['tool'] == 'GetSourceCode' and all(row['arguments'].get(k) == v for k, v in clause.get('arguments', {}).items()):
                groups.setdefault((row['step'], row['object'], digest(row['arguments'])), []).append(row)
        for group in groups.values():
            line = lambda r: int(r['id'].rsplit('l', 1)[1])
            group.sort(key=line)
            for anchor in group:
                window = [r for r in group if line(anchor) <= line(r) < line(anchor) + 12]
                text = '\n'.join(r['text'] for r in window)
                if all(cue.casefold() in text.casefold() for cue in clause['all']):
                    candidates.append(dict(anchor, text=text, source_ids=[r['id'] for r in window]))
    return [row for row in candidates if all(cue.casefold() in (row['text'] + ' ' + json.dumps(row['arguments'])).casefold() for cue in clause['all'])]


def witnesses(rules, rows, objects):
    supported = []
    for rule in rules:
        for obj in objects:
            if not obj.startswith(rule['target'] + '/'):
                continue
            scoped = [row for row in rows if row['object'] == obj or
                      (obj.startswith('namespace/') and row['arguments'].get('namespace') == obj.split('/', 1)[1])]
            matches = [clause_matches(clause, scoped) for clause in rule['positive']]
            source_consistent = True
            for key in {(clause['tool'], digest(clause.get('arguments', {}))) for clause in rule['positive']}:
                groups = [found for clause, found in zip(rule['positive'], matches)
                          if (clause['tool'], digest(clause.get('arguments', {}))) == key]
                if len(groups) > 1 and not set.intersection(*[{row['step'] for row in found} for found in groups]):
                    source_consistent = False
            if all(matches) and source_consistent and not any(clause_matches(clause, scoped) for clause in rule['negative']):
                supported.append({'fault_object': obj, 'root_cause': rule['cause'], 'rule': rule['id'],
                    'witnesses': [{'id': row['id'], 'tool': row['tool'], 'object': row['object'], 'text': row['text'],
                                   'source_ids': row.get('source_ids', [row['id']])}
                                  for found in matches for row in found[:2]]})
    return supported


def admissible(rules, rows, objects):
    supported = witnesses(rules, rows, objects)
    
    mechanisms = {row['fault_object'] for row in supported if row['root_cause'].startswith('code_') and
                  any(w['tool'] == 'GetSourceCode' for w in row['witnesses'])}
    return [row for row in supported if not (row['fault_object'] in mechanisms and
            row['root_cause'] in {'pod_cpu_overload', 'pod_memory_overload', 'pod_io_overload'})]


def compile_rule(raw, rows, types, objects):
    if set(raw) != {'id', 'cause', 'target', 'checks', 'positive', 'negative', 'evidence_ids', 'explanation'}:
        raise ValueError('Exact executable-rule fields required')
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,64}', raw['id']):
        raise ValueError('Generic rule ID required')
    if raw['cause'] not in types or types[raw['cause']]['target'] != raw['target']:
        raise ValueError('Fault and object kind mismatch')
    if not 1 <= len(raw['checks']) <= 4 or any(tool not in TOOLS for tool in raw['checks']):
        raise ValueError('Unsupported executable check')
    if not 1 <= len(raw['positive']) <= 3 or len(raw['negative']) > 3:
        raise ValueError('One to three positive clauses required')
    lookup = {row['id']: row for row in rows}
    if not raw['evidence_ids'] or any(key not in lookup for key in raw['evidence_ids']):
        raise ValueError('Grounded evidence IDs required')
    quoted = [lookup[key] for key in raw['evidence_ids']]
    forbidden = [obj.split('/', 1)[1] for obj in objects if not obj.startswith('namespace/')]
    cues = [cue.casefold().strip() for clause in raw['positive'] for cue in clause['all']]
    if raw['cause'] == 'code_memory_leak' and not any(clause['tool'] == 'GetSourceCode' for clause in raw['positive']):
        raise ValueError('Memory exhaustion is not proof of code leakage; require direct source-code corroboration')
    if all(cue in WEAK_CUES for cue in cues):
        raise ValueError('Generic status/probe/saturation cues alone cannot identify the fault; acquire direct diagnostic evidence')
    for clause in raw['positive'] + raw['negative']:
        if not {'tool', 'all'} <= set(clause) <= {'tool', 'all', 'arguments'} or clause['tool'] not in TOOLS + ['GetAlerts', 'any']:
            raise ValueError('Invalid predicate')
        if not isinstance(clause.get('arguments', {}), dict) or any(k not in {'service_name', 'resource_type'} for k in clause.get('arguments', {})):
            raise ValueError('Only generic tool argument filters are allowed')
        if not 1 <= len(clause['all']) <= 4:
            raise ValueError('Bounded literal conjunction required')
        for cue in clause['all'] + list(clause.get('arguments', {}).values()):
            if not isinstance(cue, str) or not 3 <= len(cue) <= 100:
                raise ValueError('Invalid generic cue')
            if re.search(r'case_\d+|benchmark/|\d{1,3}(?:\.\d{1,3}){3}', cue):
                raise ValueError('No case/address memorization')
            if any(re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', cue) for name in forbidden):
                raise ValueError('No object-name memorization')
        if clause in raw['positive'] and not clause_matches(clause, quoted):
            raise ValueError('Positive predicate must match ONE cited line (or a 12-line same-file GetSourceCode window); cite each cue source. '
                             + json.dumps(clause)[:500])
    if not witnesses([raw], rows, objects):
        raise ValueError('No subject-consistent positive witness')
    clean = copy.deepcopy(raw)
    clean.pop('evidence_ids')
    return clean


def evidence_excerpt(rows, maximum=14500):
    interesting = re.compile(r'error|fail|denied|not found|notready|pending|backoff|exception|refused|timeout|'
                             r'thrott|latency|killed|replica|probe|secret|account|active:|nodeName|quota|limit|unsched', re.I)
    chosen = sorted(rows, key=lambda row: (not bool(interesting.search(row['text'])), row['step'], row['id']))
    output, used = [], 0
    for row in chosen:
        text = json.dumps(row, ensure_ascii=False)
        if used + len(text) > maximum:
            continue
        output.append(row)
        used += len(text)
    return output


class RetentionSearch:
    def __init__(self, repo, ranker, budget=16):
        from cloudops_evolution import catalog, module_at
        self.contract, self.types = catalog(repo)
        self.snapshot = module_at('grounded_snapshot', repo / 'agents/cloudops_agent/tools/snapshot.py')
        self.ranker, self.budget = ranker, budget

    def rank(self, rows, question, options):
        if len(options) == 1:
            return {next(iter(options)): 1.0}
        if len(options) > 255:
            raise ValueError('Bounded candidate set required')
        state = '\n'.join(f"{r['object'] or 'unscoped'} {r['tool']}: {r['text']}" for r in evidence_excerpt(rows, 6000))
        return self.ranker.rank(state or 'No positive observation yet.', question, options)

    def replay(self, trace, harness):
        supported = admissible(harness['rules'], trace['evidence'], self.current_objects)
        pairs = sorted({(row['fault_object'], row['root_cause']) for row in supported})
        result = copy.deepcopy(trace)
        if pairs:
            options = {f'h{i}': f'{obj} | {cause}: {self.types[cause]["description"]}' for i, (obj, cause) in enumerate(pairs)}
            values = self.rank(trace['evidence'], 'Choose the root cause with subject-consistent direct evidence; reject downstream symptoms.', options)
            selected = max(values, key=values.get)
            result['prediction'] = dict(zip(('fault_object', 'root_cause'), pairs[int(selected[1:])]))
        result.update(verified_candidates=supported, harness_hash=digest(harness), harness_version=harness['version'],
                      validation_mode='cached-evidence provisional gate, not live acquisition or held-out performance')
        return result

    def run(self, path, public, harness, mode='tree'):
        start = time.monotonic()
        objects = objects_for(self.contract, public['namespace'])
        session = ToolSession(self.snapshot, path, public['namespace'], self.budget)
        steps = session.initial(public['namespace'])
        steps.append(session.call('GetResources', {'resource_type':'deployments', 'name':'', 'namespace':public['namespace']}))
        rows = scoped_rows(steps, objects)
        scores = self.rank(rows, 'Identify the directly faulty object, not an affected downstream service.', objects)
        ordered = sorted(objects, key=lambda obj: (-scores[obj], obj))
        prior = {obj: i + 10 for i, obj in enumerate(ordered)}
        for row in rows:
            if not row['object']:
                continue
            text = row['text']
            if row['tool'] == 'GetAlerts':
                prior[row['object']] = 1
                if row['object'].startswith('app/') and re.search(r'cpu_cfs|memory|working.set|rss', text, re.I):
                    prior[row['object']] = -.5
            if row['tool'] == 'GetResources':
                parts = text.split()
                resource = row['arguments'].get('resource_type')
                if resource == 'nodes' and 'NotReady' in text:
                    prior[row['object']] = -2
                if resource == 'deployments' and len(parts) > 1 and parts[1] == '0/0':
                    prior[row['object']] = min(prior[row['object']], 0)
                if resource == 'pods' and (re.search(r'Pending|BackOff|Error|Init:|OOM|Evicted', text) or
                        len(parts) > 3 and parts[3].isdigit() and int(parts[3]) > 0):
                    prior[row['object']] = -1
        
        seen = {row['object'] for row in rows if row['arguments'].get('resource_type') == 'pods'}
        for obj in objects:
            if obj.startswith('app/') and obj not in seen:
                prior[obj] = min(prior[obj], 2)
        subjects = sorted(objects, key=lambda obj: (prior[obj], -scores[obj], obj))[:4]
        tree = []
        if mode != 'initial':
            for depth in range(10):
                actions = []
                for obj in subjects:
                    name = obj.split('/', 1)[1]
                    learned = [tool for rule in harness['rules'] if rule['target'] == obj.split('/')[0] for tool in rule['checks']]
                    default = (['CheckNodeServiceStatus', 'GetResources'] if obj.startswith('node/') else
                               ['DescribeResource', 'GetErrorLogs', 'GetAppYAML', 'GetServiceDependencies', 'ListCodeFiles', 'GetSourceCode'])
                    first = default[depth % len(default)]
                    preferred = list(dict.fromkeys([first] + learned + default))
                    unique = set()
                    for key, (tool, args) in session.actions.items():
                        if key in session.calls or tool not in preferred:
                            continue
                        bound = entity(bound_subject(args), objects)
                        if bound != obj:
                            continue
                        resource = args.get('resource_type', '')
                        family = (tool, resource, args.get('service_name'))
                        if family in unique:
                            continue
                        unique.add(family)
                        kinds = ['pods', 'replicasets', 'deployments', 'services'] if obj in seen else ['replicasets', 'deployments', 'pods', 'services']
                        quality = kinds.index(resource) if resource in kinds else len(kinds)
                        actions.append((subjects.index(obj), preferred.index(tool), quality, key, obj))
                if not actions or len(session.calls) >= self.budget:
                    break
                
                actions.sort(key=lambda a: (a[1], a[0], a[2], a[3]))
                pool = actions[:8]
                values = self.rank(rows, 'Choose a read-only check that can expose direct fault evidence.',
                                   {f'a{i}': action[3] for i, action in enumerate(pool)})
                chosen = sorted(values, key=lambda key: -values[key])[:2 if mode == 'tree' else 1]
                
                indices = list(dict.fromkeys([0] + [int(key[1:]) for key in chosen]))[:2 if mode == 'tree' else 1]
                for index in indices:
                    action = pool[index]
                    tool, args = session.actions[action[3]]
                    step = session.call(tool, args)
                    if step:
                        steps.append(step)
                        tree.append({'depth': depth, 'object': action[4], 'action': {'tool': tool, 'arguments': args},
                                     'selection': 'executable_primary_check' if index == 0 else 'jev_branch',
                                     'new_evidence_step': len(steps) - 1})
                rows = scoped_rows(steps, objects)
                
                referenced = []
                for row in rows:
                    if row['tool'] not in {'GetServiceDependencies', 'GetErrorLogs'}:
                        continue
                    for obj in objects:
                        name = obj.split('/', 1)[1]
                        if obj.startswith('app/') and obj != row['object'] and obj not in subjects and re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', row['text']):
                            referenced.append(obj)
                for obj in dict.fromkeys(referenced):
                    subjects = [subjects[0], obj] + [old for old in subjects[1:] if old != obj]
                    subjects = subjects[:4]
        supported = admissible(harness['rules'], rows, objects)
        pairs = {(row['fault_object'], row['root_cause']) for row in supported}
        verified = bool(pairs)
        if not verified:
            selected = subjects if mode != 'initial' else ordered[:3]
            for obj in selected:
                allowed = {cause: value['description'] for cause, value in self.types.items() if value['target'] == obj.split('/')[0]}
                own_rows = [r for r in rows if r['object'] in {obj, None}]
                fault_scores = self.rank(own_rows, f'Identify a direct fault in {obj} using positive evidence.', allowed)
                pairs.update((obj, cause) for cause in sorted(fault_scores, key=lambda c: -fault_scores[c])[:2])
        pairs = sorted(pairs)
        options = {f'h{i}': f'{obj} | {cause}: {self.types[cause]["description"]}' for i, (obj, cause) in enumerate(pairs)}
        values = self.rank(rows, 'Choose the root cause with subject-consistent direct evidence; reject downstream symptoms.', options)
        winner = max(values, key=values.get)
        pred = dict(zip(('fault_object', 'root_cause'), pairs[int(winner[1:])]))
        return {'prediction': pred, 'healthy': all(not r['error'] for r in steps),
                'steps': steps, 'evidence': rows, 'verified_candidates': supported,
                'admissibility': 'positive-witness constraints then JEV ranking' if verified else 'no proof; JEV fallback',
                'search_tree': tree, 'harness_version': harness['version'], 'harness_hash': digest(harness),
                'mode': mode, 'tool_calls': len(session.calls), 'wall_sec': time.monotonic() - start,
                'llm_in_diagnosis': False, 'ranking_bonus_used': False}
