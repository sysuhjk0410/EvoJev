#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import copy
import io
import inspect
import json
import math
from pathlib import Path
import re
import time

from cloudops_evolution import ALLOWED_TOOLS, catalog, digest, module_at, SnapshotSearch

SELECTORS = {'abnormal_apps', 'ranked_apps', 'not_ready_nodes', 'control_plane_nodes',
             'ranked_nodes', 'namespace'}
SKILL_TOOLS = {'DescribeResource', 'GetAppYAML', 'GetErrorLogs', 'GetServiceDependencies',
               'GetClusterConfiguration', 'CheckNodeServiceStatus', 'CheckServiceConnectivity',
               'ListCodeFiles', 'GetSourceCode', 'GetResources'}
HINT = re.compile(r'error|failed|exception|denied|refused|timeout|deadline|unbound|insufficient|'
                  r'untolerated|affinity|selector|probe|Active:|Events:|Warning|OOM|BackOff|'
                  r'replicas:|targetPort:|nodeName:|nodeSelector:|secret|Pending|NotReady', re.I)


def signature(tool, arguments):
    return tool + ':' + json.dumps(arguments, sort_keys=True, separators=(',', ':'))


def compatible_action(tools, tool, arguments):
    method = getattr(tools, tool, None)
    if not callable(method):
        return False
    try:
        inspect.signature(method).bind(**arguments)
    except (TypeError, ValueError):
        return False
    return True


def objects_for(contract, namespace):
    system = 'boutique' if namespace == 'boutique' else 'train-ticket'
    values = {f'app/{x}': f'Application {x}' for x in contract.SYSTEM_VALID_SERVICES[system]}
    values.update({f'node/{x}': f'Node {x}' for x in contract.VALID_NODES})
    values[f'namespace/{namespace}'] = 'Namespace quota'
    return values


def subject(arguments):
    return arguments.get('app_name') or arguments.get('node_name') or arguments.get('name') or ''


def observed_apps(steps, objects):
    names = [o[4:] for o in objects if o.startswith('app/')]
    found = set()
    for step in steps:
        if step['tool'] == 'GetResources' and step['arguments'].get('resource_type') == 'pods':
            for line in step['output'].splitlines():
                if not re.search(r'Pending|BackOff|Error|OOMKilled|Evicted|CrashLoop', line):
                    continue
                token = line.split()[0] if line.split() else ''
                matches = [name for name in names if token == name or token.startswith(name + '-')]
                if matches:
                    found.add(max(matches, key=len))
        target = subject(step['arguments'])
        if target in names and HINT.search(step['output']):
            found.add(target)
        if step['tool'] == 'GetAlerts':
            for name in names:
                if re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', step['output']):
                    found.add(name)
    return found


def node_roles(steps):
    ready, control = set(), set()
    for step in steps:
        if step['tool'] != 'GetResources' or step['arguments'].get('resource_type') != 'nodes':
            continue
        for line in step['output'].splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                if 'NotReady' in parts[1]:
                    ready.add(parts[0])
                if 'master' in parts[2] or 'control-plane' in parts[2]:
                    control.add(parts[0])
    return {'not_ready_nodes': sorted(ready), 'control_plane_nodes': sorted(control)}


def matches_skill(skill, steps):
    trigger = skill['trigger']
    for step in steps:
        if trigger['tool'] != 'any' and trigger['tool'] != step['tool']:
            continue
        if trigger['resource_type'] and step['tool'] in {'GetResources','DescribeResource'} and step['arguments'].get('resource_type') != trigger['resource_type']:
            continue
        tests = [cue.lower() in step['output'].lower() for cue in trigger['contains']]
        if (all(tests) if trigger['mode'] == 'all' else any(tests)):
            return True
    return False


def skill_targets(skill, steps, objects, components, namespace):
    selector = skill['selector']
    if selector == 'abnormal_apps':
        return sorted(observed_apps(steps, objects))
    if selector in {'not_ready_nodes', 'control_plane_nodes'}:
        return node_roles(steps)[selector]
    if selector == 'namespace':
        return [namespace]
    kind = 'app/' if selector == 'ranked_apps' else 'node/'
    return [o.split('/', 1)[1] for o in sorted(objects, key=lambda x: (-components.get(x, 0), x))
            if o.startswith(kind)][:3]


def skill_actions(skills, steps, objects, components, namespace, actions):
    wanted = {}
    for skill in skills:
        if not matches_skill(skill, steps):
            continue
        for name in skill_targets(skill, steps, objects, components, namespace):
            pods = []
            for row in steps:
                if row['tool'] == 'GetResources' and row['arguments'].get('resource_type') == 'pods':
                    pods.extend(line.split()[0] for line in row['output'].splitlines()[1:]
                                if line.split() and (line.split()[0] == name or line.split()[0].startswith(name + '-')))
            for move in skill['steps']:
                for key, (tool, args) in actions.items():
                    if tool != move['tool']:
                        continue
                    expected = {k: v.replace('{entity}', name).replace('{namespace}', namespace)
                                if isinstance(v, str) else v for k, v in move['arguments'].items()}
                    if all(args.get(k) in pods if v == '{pod}' else
                           isinstance(args.get(k), int) and 0 < args[k] < 65536 if v == '{port}' else args.get(k) == v
                           for k, v in expected.items()):
                        wanted[key] = skill['id']
    return wanted


def validate_skill(raw, completed_trace, types, objects):
    fields = {'name', 'trigger', 'selector', 'steps', 'distinguish', 'evidence_quotes'}
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError('Invalid skill fields')
    if not isinstance(raw['name'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,64}', raw['name']):
        raise ValueError('Skill name must be a generic slug')
    trigger = raw['trigger']
    if not isinstance(trigger, dict) or set(trigger) != {'tool', 'resource_type', 'contains', 'mode'}:
        raise ValueError('Invalid trigger')
    if trigger['tool'] not in SKILL_TOOLS | {'any', 'GetAlerts'} or trigger['mode'] not in {'any', 'all'}:
        raise ValueError('Invalid trigger enums')
    if not isinstance(trigger['resource_type'], str) or len(trigger['resource_type']) > 32:
        raise ValueError('Invalid resource kind')
    cues = trigger['contains']
    if not isinstance(cues, list) or not 1 <= len(cues) <= 4:
        raise ValueError('One to four generic trigger cues required')
    if raw['selector'] not in SELECTORS:
        raise ValueError('Unsupported selector')
    if not isinstance(raw['steps'], list) or not 1 <= len(raw['steps']) <= 3:
        raise ValueError('One to three moves required')
    forbidden = [o.split('/', 1)[1] for o in objects if not o.startswith('namespace/')]
    texts = list(cues)
    for move in raw['steps']:
        if not isinstance(move, dict) or set(move) != {'tool', 'arguments'} or move['tool'] not in SKILL_TOOLS:
            raise ValueError('Invalid move')
        if not isinstance(move['arguments'], dict) or len(move['arguments']) > 6:
            raise ValueError('Invalid move arguments')
        for key, value in move['arguments'].items():
            if not isinstance(key, str) or not isinstance(value, (str, bool, int)):
                raise ValueError('Scalar tool arguments required')
            if isinstance(value, str):
                if len(value) > 120 or re.search(r'\{(?!entity\}|namespace\}|pod\}|port\})', value):
                    raise ValueError('Unsupported role binding')
                if '/' in value or '..' in value:
                    raise ValueError('No hardcoded paths in learned actions')
                if value:
                    texts.append(value)
            if key == 'port' and value != '{port}':
                raise ValueError('Service-specific ports must bind to observed {port}, not a constant')
    distinguish = raw['distinguish']
    if not isinstance(distinguish, dict) or set(distinguish) != {'faults', 'support', 'exclude', 'reason'}:
        raise ValueError('Invalid discriminator')
    if not isinstance(distinguish['faults'], list) or not 1 <= len(distinguish['faults']) <= 6:
        raise ValueError('One to six catalog hypotheses required')
    if any(f not in types for f in distinguish['faults']):
        raise ValueError('Unknown catalog fault')
    for channel in ('support', 'exclude'):
        items = distinguish[channel]
        if not isinstance(items, list) or len(items) > 4 or any(not isinstance(x, str) for x in items):
            raise ValueError('Invalid evidence cues')
        texts.extend(items)
    if not isinstance(distinguish['reason'], str) or len(distinguish['reason']) > 800:
        raise ValueError('Invalid explanation')
    
    for text in texts:
        if not isinstance(text, str) or not 2 <= len(text) <= 120:
            raise ValueError('Invalid cue length')
        if any(re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', text) for name in forbidden):
            raise ValueError('Hardcoded object in executable skill')
    quotes = raw['evidence_quotes']
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 3:
        raise ValueError('Grounded evidence references required')
    for quote in quotes:
        if not isinstance(quote, dict) or set(quote) != {'step', 'text'}:
            raise ValueError('Invalid evidence reference')
        index, text = quote['step'], quote['text']
        if type(index) is not int or not 0 <= index < len(completed_trace['steps']):
            raise ValueError('Unobserved step')
        if not isinstance(text, str) or len(text) < 8 or text not in completed_trace['steps'][index]['output']:
            raise ValueError('Unobserved quote')
    if not matches_skill(raw, completed_trace['steps']):
        raise ValueError('Seed observations do not activate this skill')
    clean = copy.deepcopy(raw)
    clean['id'] = digest({k: raw[k] for k in fields - {'name', 'evidence_quotes'}})[:16]
    return clean


def evidence_cards(query, steps, skills=(), limit=20000):
    cards = []
    per_step = max(500, (limit - 1000) // max(1, len(steps)))
    for index, step in enumerate(steps):
        lines = step['output'].splitlines()
        cues = [cue.lower() for skill in skills if matches_skill(skill, steps)
                for channel in ('support', 'exclude') for cue in skill['distinguish'][channel]]
        prioritized = sorted(range(len(lines)), key=lambda i: (
            -sum(cue in lines[i].lower() for cue in cues),
            -int(bool(HINT.search(lines[i]))), -i))
        selected, used = [], 0
        for i in prioritized:
            text = lines[i][:500]
            if used + len(text) + 12 > per_step:
                continue
            selected.append((i, text))
            used += len(text) + 12
            if len(selected) >= 24:
                break
        cards.append({'step': index, 'tool': step['tool'], 'subject': subject(step['arguments']),
                      'arguments': step['arguments'],
                      'evidence': [{'line': i + 1, 'quote': text} for i, text in sorted(selected)]})
    
    return query[:1000] + '\nObserved evidence cards:\n' + json.dumps(cards, ensure_ascii=False)


def raw_context(query, steps):
    quota = max(500, 15000 // max(1, len(steps)))
    return query + '\n' + '\n'.join(f"[{i}] {r['tool']} {json.dumps(r['arguments'])}\n{r['output'][:quota]}"
                                   for i, r in enumerate(steps))


class ToolSession:
    def __init__(self, snapshot, path, namespace, budget):
        system = 'boutique' if namespace == 'boutique' else 'train-ticket'
        self.tools = snapshot.KubernetesTools(str(path), system=system, namespace=namespace)
        self.budget, self.calls = budget, {}
        self.actions = {}
        
        for key in self.tools.tool_cache:
            tool, separator, arguments = key.partition(':')
            if not separator or tool not in SKILL_TOOLS or tool == 'GetSourceCode':
                continue
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                continue
            if isinstance(args, dict) and compatible_action(self.tools, tool, args):
                self.actions[signature(tool, args)] = (tool, args)

    def call(self, tool, arguments):
        key = signature(tool, arguments)
        if key in self.calls:
            return self.calls[key]
        if len(self.calls) >= self.budget:
            return None
        if tool not in ALLOWED_TOOLS:
            raise ValueError('Unsupported tool')
        started = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                result, error = getattr(self.tools, tool)(**arguments), None
            except (ValueError, KeyError, TypeError) as exc:
                result, error = str(exc), type(exc).__name__
        row = {'tool': tool, 'arguments': arguments,
               'output': result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
               'error': error, 'elapsed_sec': time.monotonic() - started}
        self.calls[key] = row
        if tool == 'ListCodeFiles':
            try:
                listing = json.loads(row['output'])
                for file in listing.get('files', []):
                    args = {'app_name': arguments['app_name'], 'file_path': file['path']}
                    self.actions[signature('GetSourceCode', args)] = ('GetSourceCode', args)
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                pass
        return row

    def initial(self, namespace):
        steps = []
        for tool, args in [('GetAlerts', {})] + [('GetResources', {
                'resource_type': kind, 'name': '', 'namespace': namespace})
                for kind in ('pods', 'nodes', 'resourcequotas')]:
            steps.append(self.call(tool, args))
        return steps


class SkillSearch:
    def __init__(self, repo, ranker, budget=16, width=2, depth=3):
        self.repo, self.ranker = repo, ranker
        self.contract, self.types = catalog(repo)
        self.snapshot = module_at('cloudops_snapshot_tree_skill_v3', repo / 'agents/cloudops_agent/tools/snapshot.py')
        self.budget, self.width, self.depth = budget, width, depth

    def run(self, path, public, skills=(), enhanced=True):
        if set(public) != {'query', 'namespace'}:
            raise ValueError('Solver accepts only the public task')
        if not enhanced and not skills:
            result = SnapshotSearch(self.repo, self.ranker, tool_budget=self.budget).run(path, public)
            winner = max(result['bank'], key=lambda x: x['base_score'])
            result['prediction'] = {k: winner[k] for k in ('fault_object', 'root_cause')}
            result['candidate_keys'] = [(r['fault_object'], r['root_cause']) for r in result['bank']]
            return result
        started = time.monotonic()
        session = ToolSession(self.snapshot, path, public['namespace'], self.budget)
        initial = session.initial(public['namespace'])
        objects = objects_for(self.contract, public['namespace'])
        def state(steps):
            return evidence_cards(public['query'], steps, skills) if enhanced else raw_context(public['query'], steps)
        def rank_objects(steps):
            return self.ranker.rank(state(steps), 'Locate the faulty object from observed evidence.', objects)
        initial_scores = rank_objects(initial)
        nodes = [{'id': 0, 'parent': None, 'depth': 0, 'steps': initial,
                  'components': initial_scores, 'action': None, 'skill_id': None}]
        frontier = [nodes[0]]
        max_depth = self.depth if enhanced else self.budget - 4
        for depth in range(max_depth):
            children = []
            for node in frontier:
                used = {signature(s['tool'], s['arguments']) for s in node['steps']}
                remaining = {k: v for k, v in session.actions.items() if k not in used}
                if not remaining or len(session.calls) >= self.budget:
                    continue
                learned = skill_actions(skills, node['steps'], objects, node['components'],
                                        public['namespace'], remaining)
                abnormal = observed_apps(node['steps'], objects)
                favored = {x.split('/', 1)[1] for x in sorted(objects, key=lambda x: -node['components'][x])[:16]}
                keys = sorted(remaining, key=lambda k: (
                    k not in learned,
                    not any(subject(remaining[k][1]) == name for name in abnormal),
                    not any(name in k for name in favored), k))[:40]
                options = {f'a{i}': key for i, key in enumerate(keys)}
                question = 'Choose the next tool to distinguish root cause from downstream effects.'
                if learned:
                    question += '\nApplicable generic investigation skills: ' + json.dumps([
                        {'name': s['name'], 'checks': s['steps'], 'discriminator': s['distinguish']}
                        for s in skills if matches_skill(s, node['steps'])])
                scores = self.ranker.rank(state(node['steps']), question, options)
                count = self.width if enhanced else 1
                chosen = sorted(scores, key=lambda k: (-scores[k], k))[:count]
                for option in chosen:
                    key = options[option]
                    tool, args = remaining[key]
                    step = session.call(tool, args)
                    if step is None:
                        continue
                    steps = node['steps'] + [step]
                    components = rank_objects(steps)
                    probabilities = sorted(components.values(), reverse=True)
                    child = {'id': len(nodes), 'parent': node['id'], 'depth': depth + 1,
                             'steps': steps, 'components': components,
                             'action': {'tool': tool, 'arguments': args},
                             'skill_id': learned.get(key), 'action_distribution': scores,
                             'value': math.log(max(probabilities[0], 1e-20) / max(probabilities[1], 1e-20))}
                    nodes.append(child)
                    children.append(child)
            if not children:
                break
            frontier = sorted(children, key=lambda n: (-n['value'], n['id']))[:self.width if enhanced else 1]
        steps = list(session.calls.values())
        components = rank_objects(steps)
        if enhanced:
            result = self.joint_rank(state(steps), steps, components, objects, skills)
        else:
            bank = []
            for obj in sorted(objects, key=lambda x: (-components[x], x))[:16]:
                options = {k: v['description'] for k, v in self.types.items() if v['target'] == obj.split('/')[0]}
                dist = self.ranker.rank(state(steps), f'For {obj}, rank direct root causes; reject downstream symptoms.', options)
                for fault, score in dist.items():
                    bank.append({'fault_object': obj, 'root_cause': fault,
                                 'score': .4 * components[obj] + .6 * score})
            bank.sort(key=lambda r: (-r['score'], r['fault_object'], r['root_cause']))
            result = {'prediction': {k: bank[0][k] for k in ('fault_object', 'root_cause')}, 'bank': bank,
                      'candidate_keys': [(r['fault_object'], r['root_cause']) for r in bank]}
        result.update(steps=steps, search_tree=[{k: v for k, v in node.items() if k != 'steps'} for node in nodes],
                      components=components, runtime={'llm_in_diagnosis': False, 'engine': 'AgentJev',
                          'unique_tool_calls': len(steps), 'tool_budget': self.budget,
                          'search_width': self.width if enhanced else 1,
                          'search_depth': max(n['depth'] for n in nodes),
                          'nodes': len(nodes), 'wall_sec': time.monotonic() - started,
                          'representation': 'source-grounded evidence cards' if enhanced else 'raw excerpts',
                          'ranking_bonus_used': False})
        return result

    def joint_rank(self, context, steps, components, objects, skills):
        by_kind = {}
        for kind in ('app', 'node', 'namespace'):
            options = {k: v['description'] for k, v in self.types.items() if v['target'] == kind}
            by_kind[kind] = self.ranker.rank(context, f'Rank direct {kind}-level faults using observed evidence.', options)
        
        candidates = set()
        for obj in objects:
            top = sorted(by_kind[obj.split('/')[0]], key=lambda f: (-by_kind[obj.split('/')[0]][f], f))[:2]
            candidates.update((obj, fault) for fault in top)
        ordered = sorted(objects, key=lambda o: (-components[o], o))
        for obj in ordered[:2]:
            candidates.update((obj, fault) for fault in by_kind[obj.split('/')[0]])
        for skill in skills:
            if matches_skill(skill, steps):
                for name in skill_targets(skill, steps, objects, components,
                                          next(o.split('/', 1)[1] for o in objects if o.startswith('namespace/'))):
                    for obj in objects:
                        if obj.split('/', 1)[1] == name:
                            candidates.update((obj, fault) for fault in skill['distinguish']['faults']
                                              if self.types[fault]['target'] == obj.split('/')[0])
        
        pairs = sorted(candidates, key=lambda pair: (
            -components[pair[0]] * by_kind[pair[0].split('/')[0]][pair[1]], pair))
        if len(pairs) > 255:
            mandatory = {(obj, max(by_kind[obj.split('/')[0]], key=by_kind[obj.split('/')[0]].get)) for obj in objects}
            pairs = sorted(mandatory) + [p for p in pairs if p not in mandatory][:255 - len(mandatory)]
        options = {f'h{i}': f'{obj} | {fault}: {self.types[fault]["description"]}'
                   for i, (obj, fault) in enumerate(pairs)}
        question = ('Select the single direct root-cause hypothesis. Match the exact subject of evidence; '
                    'reject downstream symptoms and distinguish competing explanations. '
                    'Do not favor a fault merely because its name occurs in an investigation guide.')
        active = [s['distinguish'] for s in skills if matches_skill(s, steps)]
        if active:
            question += '\nGeneric discriminator guides, not incident answers: ' + json.dumps(active)
        values = self.ranker.rank(context, question, options)
        bank = [{'fault_object': pairs[int(k[1:])][0], 'root_cause': pairs[int(k[1:])][1],
                 'score': values[k]} for k in options]
        bank.sort(key=lambda r: (-r['score'], r['fault_object'], r['root_cause']))
        return {'prediction': {k: bank[0][k] for k in ('fault_object', 'root_cause')},
                'bank': bank, 'candidate_keys': pairs,
                'top_3_predictions': [{k: r[k] for k in ('fault_object', 'root_cause')} for r in bank[:3]]}
