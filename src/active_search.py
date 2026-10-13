import collections
import json
import math
import re
import time

from cloudops_evolution import catalog, module_at
from contrastive_experience import Experience, document
from grounded import admissible, bound_subject, clause_matches, digest, entity, evidence_excerpt, scoped_rows, source_preference
from puct_planner import choose
from tree_skill_search import ToolSession, objects_for, signature


def unhealthy_pod_owners(rows):
    return {row['object'] for row in rows if row['object'] and row['object'].startswith('app/')
            and row['tool'] == 'GetResources' and row['arguments'].get('resource_type') == 'pods'
            and re.search(r'Pending|BackOff|Error|Init:|OOM|Evicted|\b0/\d+', row['text'])}


class ActiveSearch:
    def __init__(self, repo, ranker, budget=72):
        self.contract, self.types = catalog(repo)
        self.snapshot = module_at('active_snapshot', repo / 'agents/cloudops_agent/tools/snapshot.py')
        self.ranker, self.budget = ranker, budget

    def run(self, path, public, harness, experience_data=None, planner=True, jev=True, contrastive=True):
        if set(public) != {'query', 'namespace'}:
            raise ValueError('Only label-free public task is accepted')
        started = time.monotonic()
        objects = objects_for(self.contract, public['namespace'])
        session = ToolSession(self.snapshot, path, public['namespace'], self.budget)
        steps = [row for row in session.initial(public['namespace']) if row]
        tree = []
        experience = Experience(experience_data, self.types) if experience_data else None
        global_kinds = ('deployments', 'events', 'persistentvolumeclaims', 'services')
        for kind in global_kinds:
            actions = [(key, args) for key, (tool, args) in session.actions.items() if tool == 'GetResources'
                       and args.get('resource_type') == kind and args.get('name') == ''
                       and key not in session.calls]
            if actions:
                _, args = min(actions, key=lambda row: (len(row[1]), row[0]))
                row = session.call('GetResources', args)
                if row:
                    steps.append(row)
        rows = scoped_rows(steps, objects)
        for obj in sorted(unhealthy_pod_owners(rows))[:8]:
            actions = [(key, args) for key, (tool, args) in session.actions.items()
                       if tool == 'DescribeResource' and args.get('resource_type') == 'pods'
                       and entity(bound_subject(args), objects) == obj and key not in session.calls]
            if actions:
                _, args = min(actions, key=lambda pair: (len(pair[1]), pair[0]))
                row = session.call('DescribeResource', args)
                if row:
                    steps.append(row)
        rows = scoped_rows(steps, objects)
        context = lambda: public['query'] + '\n' + json.dumps(evidence_excerpt(rows, 9000), ensure_ascii=False)
        component_scores = self.ranker.rank(context(), 'Rank the faulty owner, distinguish downstream symptoms.', objects) if jev else {obj: 1 / len(objects) for obj in objects}
        alerted = {row['object'] for row in rows if row['object'] and row['tool'] == 'GetAlerts' and 'ABNORMAL' in row['text']}
        if alerted:
            component_scores = {obj: .2 * score + (.8 / len(alerted) if obj in alerted else 0)
                                for obj, score in component_scores.items()}
        action_scores = {}
        bank = []
        while len(session.calls) < self.budget:
            rows = scoped_rows(steps, objects)
            bank = experience.candidates(rows, objects) if experience else []
            partial_rules = []
            for rule in harness.get('rules', []):
                matched = {row['object'] for clause in rule['positive'] for row in clause_matches(clause, rows)
                           if row['object'] and row['object'].startswith(rule['target'] + '/')}
                partial_rules.extend((obj, rule) for obj in matched)
            options, seen = [], set()
            used_families = set()
            for row in steps:
                args = row['arguments']
                owner = entity(bound_subject(args), objects)
                used_families.add((row['tool'], owner or bound_subject(args), args.get('resource_type', ''),
                                   args.get('service_name') if owner and owner.startswith('node/') else None,
                                   args.get('file_path')))
            for key, (tool, args) in sorted(session.actions.items(), key=lambda row: (len(row[1][1]), row[0])):
                if key in session.calls:
                    continue
                obj = entity(bound_subject(args), objects)
                kind = args.get('resource_type', '')
                family = (tool, obj or bound_subject(args), kind,
                          args.get('service_name') if obj and obj.startswith('node/') else None, args.get('file_path'))
                if family in seen or family in used_families or tool == 'GetResources' and not kind:
                    continue
                if obj is None and tool not in ('GetResources', 'GetClusterConfiguration'):
                    continue
                seen.add(family)
                options.append((key, tool, args, obj))
            if not options:
                break
            counts = collections.Counter(entity(bound_subject(s['arguments']), objects) for s in steps)
            logs_seen = {entity(bound_subject(s['arguments']), objects) for s in steps if s['tool'] == 'GetErrorLogs'}
            abnormal = {row['object'] for row in rows if row['object'] and re.search(r'Warning|Pending|BackOff|Error|NotReady|0/\d', row['text'])}
            if not alerted and len(logs_seen) < sum(o.startswith('app/') for o in objects):
                broad_logs = [o for o in options if o[1] == 'GetErrorLogs' and o[3] not in logs_seen]
                if broad_logs:
                    options = broad_logs
            def priority(option):
                _, tool, args, obj = option
                order = {'GetErrorLogs': 0, 'DescribeResource': 1, 'GetAppYAML': 2,
                         'CheckNodeServiceStatus': 2, 'GetClusterConfiguration': 3,
                         'GetServiceDependencies': 4, 'GetResources': 4,
                         'ListCodeFiles': 2, 'GetSourceCode': 3, 'CheckServiceConnectivity': 4}
                quality = {'pods': 0, 'deployments': 1, 'replicasets': 2, 'services': 3,
                           'endpoints': 4}.get(args.get('resource_type'), 5) if tool == 'DescribeResource' else 0
                return (counts[obj] * 2 + order.get(tool, 8) + quality - (2 if obj in abnormal else 0),
                        -component_scores.get(obj, 0), option[0])
            focused = sorted(options, key=lambda o: (o[3] not in alerted, priority(o)))[:12]
            wide = sorted(options, key=priority)[:16]
            options = list({o[0]: o for o in focused + wide}.values())
            source_choices = sorted([o for o in session.actions.items() if o[1][0] == 'ListCodeFiles'
                                     and o[0] not in session.calls], key=lambda o: (len(o[1][1]), o[0]))
            subjects = sorted({h['fault_object'] for h in bank[:12]} | alerted | abnormal,
                              key=lambda obj: (-component_scores.get(obj, 0), obj))[:8]
            for key, (tool, args) in source_choices:
                obj = entity(bound_subject(args), objects)
                family = (tool, obj or bound_subject(args), '', None, None)
                if obj in subjects and family not in used_families and not any(o[1] == tool and o[3] == obj for o in options):
                    options.append((key, tool, args, obj))
            options = [o for o in options if o[1] != 'ListCodeFiles' or self.budget - len(session.calls) >= 2]
            if not options:
                break
            if jev and (len(tree) % 8 == 0 or not action_scores):
                choices = {str(i): tool + ' ' + json.dumps(args, sort_keys=True) for i, (_, tool, args, _) in enumerate(options)}
                scores = self.ranker.rank(context(), 'Choose the check that best discriminates the fault from confounders.', choices)
                action_scores = {options[int(i)][0]: value for i, value in scores.items()}
            hypotheses = bank[:12] if bank else []
            for obj, rule in partial_rules:
                if not any(h['fault_object'] == obj and h['root_cause'] == rule['cause'] for h in hypotheses):
                    hypotheses.append({'fault_object': obj, 'root_cause': rule['cause'], 'probability': .1})
            if not hypotheses:
                hypotheses = [{'fault_object': obj, 'root_cause': None, 'probability': component_scores[obj]} for obj in objects]
            covered_objects = {h['fault_object'] for h in hypotheses}
            hypotheses += [{'fault_object': obj, 'root_cause': None, 'probability': .015}
                           for obj in objects if obj not in covered_objects]
            weights = [max(.001, h['probability']) for h in hypotheses]
            gains, priors = [], []
            for key, tool, args, obj in options:
                gain = []
                for h in hypotheses:
                    if obj is not None and obj != h['fault_object']:
                        gain.append(.005)
                        continue
                    profile = experience.tool_profile(h['root_cause']) if experience and h['root_cause'] else {}
                    learned = profile.get(tool.lower(), 0)
                    if any(owner == h['fault_object'] and rule['cause'] == h['root_cause'] and tool in rule['checks']
                           for owner, rule in partial_rules):
                        learned = max(learned, .9)
                    breadth = {'GetErrorLogs': .60, 'DescribeResource': .40, 'GetAppYAML': .65,
                               'CheckNodeServiceStatus': .55, 'GetSourceCode': .95,
                               'ListCodeFiles': .95, 'GetResources': .30}.get(tool, .20)
                    gain.append(min(.95, max(.1, .60 * learned + .40 * breadth) / (1 + .12 * counts[obj])))
                gains.append(gain)
                priors.append(.05 + .40 * action_scores.get(key, 0) + .12 / (1 + counts[obj]))
            discriminative = False
            if experience and contrastive:
                gains, weights, discriminative = experience.separation(
                    [{'tool': o[1], 'object': o[3]} for o in options], hypotheses, gains)
            objective = 'historical_pairwise_evidence_separation' if discriminative else 'historical_expected_evidence_coverage'
            if planner:
                selected, trace = choose(gains, weights, priors, seed=20261006 + len(tree), simulations=96,
                                         depth=min(3, self.budget - len(session.calls)),
                                         costs=[2 if o[1] == 'ListCodeFiles' else 1 for o in options], objective=objective)
            else:
                total = sum(weights)
                values = [(sum(w * g for w, g in zip(weights, gain)) / total + prior) / (2 if option[1] == 'ListCodeFiles' else 1)
                          for gain, prior, option in zip(gains, priors, options)]
                selected = max(range(len(values)), key=lambda i: values[i])
                trace = {'model': 'greedy_' + objective, 'simulations': 0}
            trace.update(actual_future_observations_used=False, contrastive_objective=discriminative,
                         utility_model_is_empirical_surrogate=True)
            key, tool, args, obj = options[selected]
            row = session.call(tool, args)
            if row is None:
                break
            steps.append(row)
            if tool == 'ListCodeFiles':
                files = [(source_key, file_args) for source_key, (source_tool, file_args) in session.actions.items()
                         if source_tool == 'GetSourceCode' and file_args.get('app_name') == args.get('app_name')
                         and source_key not in session.calls]
                descriptions = {}
                try:
                    descriptions = {file['path']: file.get('description', '') for file in json.loads(row['output']).get('files', [])}
                except (ValueError, AttributeError, KeyError, TypeError):
                    pass
                files.sort(key=lambda pair: (source_preference(pair[1]['file_path'], descriptions.get(pair[1]['file_path'], '')), pair[0]))
                if files:
                    extra = session.call('GetSourceCode', files[0][1])
                    if extra:
                        steps.append(extra)
                        trace['executed_prerequisite_macro'] = {'tool': 'GetSourceCode', 'arguments': files[0][1], 'charged': True}
            tree.append({'depth': len(tree), 'action': {'tool': tool, 'arguments': args},
                         'selection': 'jev_prior_puct' if planner else 'greedy',
                         'planning': trace, 'new_evidence_step': len(steps) - 1})
        rows = scoped_rows(steps, objects)
        decision = self.decide(public, rows, objects, harness, experience, component_scores, jev)
        return dict(decision, steps=steps, evidence=rows, component_scores=component_scores,
                    search_tree=tree, tool_calls=len(session.calls), max_tool_calls=self.budget,
                    healthy=all(not row['error'] for row in steps), wall_sec=time.monotonic() - started,
                    harness_hash=digest(harness), actual_tool_budget_shared=True,
                    retrospective_replay=False, experience_is_probabilistic_not_proof=True)

    def replay(self, trace, public, harness, experience_data):
        if set(public) != {'query', 'namespace'}:
            raise ValueError('Only label-free public task is accepted')
        objects = objects_for(self.contract, public['namespace'])
        rows = scoped_rows(trace['steps'], objects)
        experience = Experience(experience_data, self.types)
        scores = trace.get('component_scores', {obj: 1 / len(objects) for obj in objects})
        decision = self.decide(public, rows, objects, harness, experience, scores, True)
        return dict(trace, **decision, harness_hash=digest(harness), retrospective_replay=True,
                    cached_acquisition_code_hash=trace['code_hash'], replay_original_tool_calls=trace['tool_calls'],
                    tool_calls=0, wall_sec=0)

    def decide(self, public, rows, objects, harness, experience, component_scores, jev):
        context = lambda: public['query'] + '\n' + json.dumps(evidence_excerpt(rows, 9000), ensure_ascii=False)
        bank = experience.candidates(rows, objects) if experience else []
        proofs = admissible(harness.get('rules', []), rows, objects)
        proof_pairs = {(r['fault_object'], r['root_cause']) for r in proofs}
        candidates = [row for row in bank if (row['fault_object'], row['root_cause']) in proof_pairs] if proof_pairs else bank[:12]
        for obj, cause in proof_pairs:
            if not any(r['fault_object'] == obj and r['root_cause'] == cause for r in candidates):
                candidates.append({'fault_object': obj, 'root_cause': cause, 'probability': .2, 'background': 0})
        if not candidates:
            subjects = sorted(objects, key=lambda o: (-component_scores[o], o))[:4]
            for obj in subjects:
                causes = {cause: value['description'] for cause, value in self.types.items() if value['target'] == obj.split('/')[0]}
                distribution = self.ranker.rank(context(), 'Select the direct root cause for ' + obj, causes) if jev else {cause: 1 / len(causes) for cause in causes}
                for cause in sorted(distribution, key=distribution.get, reverse=True)[:3]:
                    candidates.append({'fault_object': obj, 'root_cause': cause,
                                       'probability': component_scores[obj] * distribution[cause], 'background': 0})
        candidates = sorted(candidates, key=lambda r: (-r['probability'], r['fault_object'], r['root_cause']))
        options = {str(i): r['fault_object'] + ' | ' + r['root_cause'] + ' | ' + self.types[r['root_cause']]['description']
                   for i, r in enumerate(candidates)}
        decision_scores = self.ranker.rank(context(), 'Choose the best source-supported object AND cause. Reject cascading effects.', options) if jev else {str(i): 1 / len(candidates) for i in range(len(candidates))}
        for i, row in enumerate(candidates):
            row['jev_probability'] = decision_scores[str(i)]
            row['explicit_proof'] = (row['fault_object'], row['root_cause']) in proof_pairs
            row['joint_score'] = math.log(max(1e-9, row['probability'])) + .15 * math.log(max(1e-9, row['jev_probability'])) + (.5 if row['explicit_proof'] else 0)
        winner = max(candidates, key=lambda row: row['joint_score'])
        return {'prediction': {key: winner[key] for key in ('fault_object', 'root_cause')},
                'bank': candidates, 'supported_pairs': proofs, 'verified_candidate_constraint': bool(proof_pairs)}
