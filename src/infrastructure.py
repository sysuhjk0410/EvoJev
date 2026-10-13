
import re
from tree_skill_search import ToolSession, objects_for, signature
from grounded import bound_subject, entity, scoped_rows


def acquire(search, path, public, prior):
    objects = objects_for(search.contract, public['namespace'])
    session = ToolSession(search.snapshot, path, public['namespace'], search.budget)
    
    session.calls.update({signature(s['tool'], s['arguments']): s for s in prior['steps']})
    reused = len(session.calls)
    session.budget = reused + search.budget
    steps, tree = [], []

    def call(tool, expected, reason):
        candidates = [(key, args) for key, (name, args) in session.actions.items()
                      if name == tool and key not in session.calls and
                      all(args.get(k) == v for k, v in expected.items())]
        if not candidates or len(session.calls) >= session.budget:
            return None
        key, args = min(candidates, key=lambda pair: (len(pair[1]), pair[0]))
        row = session.call(tool, args)
        if row:
            steps.append(row)
            tree.append({'depth': len(tree), 'action': {'tool': tool, 'arguments': args},
                         'selection': reason, 'new_evidence_step': len(steps) - 1})
        return row

    ns = public['namespace']
    for kind in ('events', 'persistentvolumeclaims', 'services', 'statefulsets', 'persistentvolumes'):
        call('GetResources', {'resource_type': kind, 'name': '', 'namespace': ns}, 'global_inventory')
    call('GetResources', {'resource_type': 'nodes', 'name': '', 'namespace': ns, 'output_wide': True},
         'node_inventory')
    for row in steps[:]:
        if row['tool'] == 'GetResources' and row['arguments'].get('resource_type') == 'persistentvolumeclaims':
            for line in row['output'].splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'Pending':
                    call('DescribeResource', {'resource_type': 'persistentvolumeclaims',
                         'name': parts[0], 'namespace': ns}, 'observed_pending_claim')
    node_rows = [r for r in scoped_rows(prior['steps'] + steps, objects)
                 if r['arguments'].get('resource_type') == 'nodes' and r['object']]
    observed_nodes = sorted({r['object'] for r in node_rows})
    for obj in observed_nodes:
        own = ' '.join(r['text'] for r in node_rows if r['object'] == obj)
        daemon = 'kube-scheduler' if re.search(r'control-plane|master', own) else 'kube-proxy'
        call('CheckNodeServiceStatus', {'node_name': obj.split('/', 1)[1], 'service_name': daemon},
             'observed_node_role')

    rows = scoped_rows(prior['steps'] + steps, objects)
    scores = search.rank(rows, 'Which owner needs a direct configuration or dependency check?', objects)
    abnormal = set()
    for row in rows:
        if row['object'] and row['tool'] == 'GetResources' and re.search(
                r'Warning|Pending|BackOff|Error|Init:|0/\d|NotReady', row['text']):
            abnormal.add(row['object'])
    apps = sorted((o for o in objects if o.startswith('app/')),
                  key=lambda o: (o not in abnormal, -scores[o], o))[:4]
    
    referenced = set()
    for row in rows:
        if row['tool'] in {'GetErrorLogs', 'GetServiceDependencies'}:
            for obj in objects:
                name = obj.split('/', 1)[1]
                if obj.startswith('app/') and re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', row['text']):
                    referenced.add(obj)
    apps = sorted(set(apps) | referenced, key=lambda o: (o not in abnormal, -scores[o], o))[:5]
    for tool, kind in [('DescribeResource', 'replicasets'), ('GetAppYAML', None),
                       ('GetErrorLogs', None), ('DescribeResource', 'services')]:
        for obj in apps:
            name = obj.split('/', 1)[1]
            candidates = [(key, args) for key, (t, args) in session.actions.items()
                          if t == tool and key not in session.calls and
                          entity(bound_subject(args), objects) == obj and
                          (kind is None or args.get('resource_type') == kind)]
            if candidates:
                _, args = min(candidates, key=lambda p: (len(p[1]), p[0]))
                call(tool, args, 'jev_ranked_abnormal_or_dependency_owner')
    return dict(prior, steps=steps, search_tree=tree, tool_calls=len(session.calls) - reused,
                max_tool_calls=search.budget, healthy=all(not s['error'] for s in steps))
