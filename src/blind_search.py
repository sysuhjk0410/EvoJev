
import math
import time

from tree_skill_search import (SkillSearch, ToolSession, evidence_cards, objects_for,
    observed_apps, matches_skill, skill_actions, signature)


class BlindSearch(SkillSearch):
    def run(self, path, public, skills=(), mode='tree', actions=True, guides=True):
        if set(public) != {'query','namespace'}:
            raise ValueError('Only public query/namespace accepted')
        if mode not in {'initial','greedy','tree'}:
            raise ValueError('Unknown search mode')
        started = time.monotonic()
        session = ToolSession(self.snapshot, path, public['namespace'], self.budget)
        objects = objects_for(self.contract, public['namespace'])
        guidance = list(skills) if guides else []
        policies = list(skills) if actions else []

        def context(steps):
            return evidence_cards(public['query'], steps, guidance)

        def rank_objects(steps):
            return self.ranker.rank(context(steps), 'Locate the faulty object from observed evidence.', objects)

        initial = session.initial(public['namespace'])
        scores = rank_objects(initial)
        nodes = [{'id':0, 'parent':None, 'depth':0, 'steps':initial,
                  'components':scores, 'action':None, 'skill_id':None}]
        frontier = [nodes[0]]
        width = 2 if mode == 'tree' else 1
        depth_limit = self.budget if mode != 'initial' else 0
        for depth in range(depth_limit):
            children = []
            for node in frontier:
                used = {signature(s['tool'],s['arguments']) for s in node['steps']}
                remaining = {k:v for k,v in session.actions.items() if k not in used}
                if not remaining or len(session.calls) >= self.budget:
                    continue
                learned = skill_actions(policies,node['steps'],objects,node['components'],
                                        public['namespace'],remaining)
                abnormal = observed_apps(node['steps'],objects)
                favored = {o.split('/',1)[1] for o in sorted(objects,key=lambda o:-node['components'][o])[:16]}
                keys = sorted(remaining,key=lambda key:(key not in learned,
                    subject_name(remaining[key][1]) not in abnormal,
                    subject_name(remaining[key][1]) not in favored,key))[:40]
                options = {f'a{i}':key for i,key in enumerate(keys)}
                probabilities = self.ranker.rank(context(node['steps']),
                    'Choose the next tool to distinguish competing root causes using direct evidence.',options)
                ranked = sorted(probabilities,key=lambda k:(-probabilities[k],k))
                chosen = []
                
                if learned:
                    chosen = [next(k for k in ranked if options[k] in learned)]
                chosen.extend(k for k in ranked if k not in chosen)
                for option in chosen[:width]:
                    key = options[option]
                    tool,args = remaining[key]
                    step = session.call(tool,args)
                    if step is None:
                        continue
                    steps = node['steps']+[step]
                    dist = rank_objects(steps)
                    ordered = sorted(dist.values(),reverse=True)
                    child = {'id':len(nodes),'parent':node['id'],'depth':depth+1,
                        'steps':steps,'components':dist,'action':{'tool':tool,'arguments':args},
                        'skill_id':learned.get(key),'forced_policy_branch':option in chosen[:1] and bool(learned),
                        'value':math.log(max(ordered[0],1e-20)/max(ordered[1],1e-20))}
                    nodes.append(child)
                    children.append(child)
            if not children:
                break
            frontier = sorted(children,key=lambda n:(-n['value'],n['id']))[:width]
        steps = list(session.calls.values())
        components = rank_objects(steps)
        result = self.joint_rank(context(steps),steps,components,objects,guidance)
        result.update(steps=steps, search_tree=[{k:v for k,v in n.items() if k!='steps'} for n in nodes],
            components=components, active_skill_ids=[s['id'] for s in skills if matches_skill(s,steps)],
            runtime={'llm_in_diagnosis':False,'engine':'AgentJev','mode':mode,
                'actions':actions,'guides':guides,'unique_tool_calls':len(steps),
                'tool_budget':self.budget,'search_width':width,'nodes':len(nodes),
                'wall_sec':time.monotonic()-started,'ranking_bonus_used':False,
                'value_scope':'Uncalibrated classifier margin heuristic, not a correctness probability'})
        return result


def subject_name(args):
    return args.get('app_name') or args.get('node_name') or args.get('name') or ''
