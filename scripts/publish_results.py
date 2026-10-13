import argparse
import fcntl
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grounded import digest, write
from worker import code_hash

ARMS = {
    'puct': {'label': 'Contrastive PUCT', 'color': '#167d73'},
    'greedy': {'label': 'Contrastive greedy', 'color': '#458044'},
    'without_jev': {'label': 'Without JEV', 'color': '#78878c'},
    'reference': {'label': 'Reference Harness', 'color': '#426fcc'},
    'seed_puct': {'label': 'Seed PUCT', 'color': '#b58127'},
    'coverage_puct': {'label': 'Evidence-coverage PUCT', 'color': '#b65463'},
}


def load(path):
    return json.loads(path.read_text())


def select(run):
    gate = load(run / 'development_summary.json')
    if not gate['passed'] or set(gate['metrics']) != set(ARMS):
        raise ValueError('Complete successful six-arm development gate required')
    if any(v['total'] != 36 for v in gate['metrics'].values()):
        raise ValueError('All 36 development cases are required')
    priority = ['coverage_puct', 'puct', 'greedy', 'without_jev', 'reference', 'seed_puct']
    primary = max(priority, key=lambda arm: gate['metrics'][arm]['correct'])
    record = {'development_selected_arm': primary, 'development_metrics': gate['metrics'],
              'gate_sha256': digest(gate), 'basis': 'Development accuracy; PUCT preference on ties',
              'selected_without_final_labels': True}
    file = run / 'publication_selection.json'
    if file.exists():
        if load(file) != record:
            raise ValueError('Preserve the recorded development selection')
    else:
        if (run / 'active_summary.json').exists():
            raise ValueError('Record development selection before final scoring')
        write(file, record)
    return record


def paired(cases, before, after):
    repairs = sum(not c['arms'][before]['correct'] and c['arms'][after]['correct'] for c in cases)
    regressions = sum(c['arms'][before]['correct'] and not c['arms'][after]['correct'] for c in cases)
    n = repairs + regressions
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(repairs, regressions) + 1)) / 2 ** n) if n else 1.0
    return {'repairs': repairs, 'regressions': regressions, 'delta_pp': 100 * (repairs - regressions) / len(cases),
            'paired_exact_p': p}


def display_tree(trace):
    result = []
    for row in trace.get('search_tree', []):
        plan = row.get('planning')
        if not plan:
            continue
        nodes = sorted(plan.get('nodes', []), key=lambda node: (-node['visits'], node['action']))
        item = {key: row.get(key) for key in ('depth', 'action', 'selection', 'new_evidence_step')}
        item['planning'] = {key: plan[key] for key in ('model', 'simulations', 'depth', 'acquisition_discount',
                            'observations_simulated', 'contrastive_objective', 'exploration_utility_scale') if key in plan}
        item['planning'].update(nodes=nodes[:4], total_children=len(nodes), displayed_children=min(4, len(nodes)))
        result.append(item)
    return result


def build(run):
    selection = select(run)
    result, summary, frozen, protocol = [load(run / name) for name in
        ('search_test_predictions.json', 'active_summary.json', 'frozen_active.json', 'protocol.json')]
    if result['status'] != 'complete' or len(result['cases']) != 754 or len(protocol['test']) != 754 or len(set(protocol['test'])) != 754 or set(result['cases']) != set(protocol['test']):
        raise ValueError('Exactly 754 unique completed cases required')
    if set(frozen['arms']) != set(ARMS) or any(set(arms) != set(ARMS) for arms in result['cases'].values()):
        raise ValueError('All 4524 actual predictions required')
    if result['code_hash'] != frozen['code_hash'] or summary['code_hash'] != frozen['code_hash'] or code_hash(run) != frozen['code_hash']:
        raise ValueError('Frozen runtime code changed')
    harness = load(run / 'candidate_harness.json')
    if digest(harness) != frozen['harness_hash'] or result['harness_hash'] != frozen['harness_hash'] or summary['harness_hash'] != frozen['harness_hash']:
        raise ValueError('Frozen Harness changed')
    if not summary['public_and_benchmark_hashes_unchanged'] or summary['worker_forbidden_attempts']:
        raise ValueError('Complete audit must pass before publication')
    if not load(run / 'advisor_stopped.json')['stopped_before_frozen_test']:
        raise ValueError('Advisor must be stopped')
    if frozen['budget_cap'] != 72 or summary['all_tool_budgets'] != 72 or not summary['advisor_stopped_before_test']:
        raise ValueError('Frozen resource and advisor protocol mismatch')
    partitions = protocol['partitions']
    members = [case for rows in partitions.values() for case in rows]
    if len(members) != 754 or len(set(members)) != 754 or set(members) != set(protocol['test']) or len(partitions['frozen_evaluation']) != 155:
        raise ValueError('Expected disjoint frozen partitions')
    if any('denied' in json.loads(line) for line in (run / 'worker_access.jsonl').read_text().splitlines()):
        raise ValueError('Forbidden worker access')
    labels = load(run / 'sealed_evaluation/labels.json')['cases']
    if set(labels) != set(protocol['test']):
        raise ValueError('Scoring label identity mismatch')
    cases, traces = [], {}
    for case in protocol['test']:
        if not re.fullmatch(r'case_\d{4}', case):
            raise ValueError('Invalid case identifier')
        values, bundle = {}, {}
        for arm, compact in result['cases'][case].items():
            file = (run / compact['trace_path']).resolve()
            if run.resolve() not in file.parents:
                raise ValueError('Trace path escapes the run')
            trace = load(file)
            if not trace['healthy'] or trace.get('retrospective_replay') or not 0 <= trace['tool_calls'] <= 72:
                raise ValueError('Healthy actual acquisition within budget required')
            if trace['case'] != case or trace['code_hash'] != frozen['code_hash'] or any(
                trace[k] != compact[k] for k in ('prediction', 'request_hash', 'tool_calls', 'healthy')):
                raise ValueError('Frozen trace mismatch')
            values[arm] = {key: compact[key] for key in ('prediction', 'healthy', 'tool_calls', 'wall_sec')}
            values[arm]['correct'] = trace['prediction'] == labels[case]['label']
            bundle[arm] = {key: trace[key] for key in ('prediction', 'healthy', 'tool_calls', 'wall_sec')}
            bundle[arm]['steps'] = [{key: step.get(key) for key in ('tool', 'arguments', 'elapsed_sec', 'error')}
                                     for step in trace['steps']]
            bundle[arm]['search_tree'] = display_tree(trace)
        partition = next((name for name, members in protocol['partitions'].items() if case in members), 'unassigned')
        cases.append({'case': case, 'partition': partition, 'arms': values})
        traces[case] = bundle
    def metrics(rows):
        return {arm: {'correct': sum(c['arms'][arm]['correct'] for c in rows), 'total': len(rows)} for arm in ARMS}
    measured = metrics(cases)
    if measured != summary['metrics']:
        raise ValueError('Published score differs from frozen scorer')
    partitions = {name: metrics([c for c in cases if c['partition'] == name]) for name in protocol['partitions']}
    if partitions != summary['partitions']:
        raise ValueError('Published partition scores differ from frozen scorer')
    preferred = [selection['development_selected_arm']] + [arm for arm in ARMS if arm != selection['development_selected_arm']]
    best = max(preferred, key=lambda arm: measured[arm]['correct'])
    evolution = load(run / 'active_evolution.json')
    events = evolution['events']
    completed = evolution['completed']
    if len(completed) != len(set(completed)) or completed != [e['case'] for e in events] or not set(completed).issubset(protocol['historical_pool']):
        raise ValueError('Pending or inconsistent evolution updates')
    if set(evolution['memory']) != set(protocol['historical_pool']) or len(evolution['memory']) != 144 or evolution['harness'] != harness:
        raise ValueError('Preserve complete historical memory and final Harness')
    for event in events:
        if event['accepted']:
            gate = event['attempts'][-1]
            admission = gate['historical_source_gate']
            if admission['repairs'] <= 0 or admission['regressions'] or gate['rule_quality']['precision'] < protocol['rule_precision_min'] or gate['cross_incident_quality']['precision'] < protocol['rule_precision_min'] or not gate['cross_incident_quality']['supporting_incidents']:
                raise ValueError('Admitted rule did not pass the historical and cross-incident gates')
    accepted = sum(event['accepted'] for event in events)
    no_update = sum(not event['accepted'] and any(a.get('reason') == 'no_update' for a in event['attempts']) for event in events)
    calls = {arm: {'total': sum(c['arms'][arm]['tool_calls'] for c in cases),
                   'max': max(c['arms'][arm]['tool_calls'] for c in cases), 'cap': 72} for arm in ARMS}
    metadata = {**summary, 'metrics': measured, 'comparisons': {arm: paired(cases, arm, best) for arm in ARMS if arm != best},
                'tool_calls': calls, 'development_selection': selection, 'observed_best_arm': best,
                'selection_scope': 'Highest observed full-benchmark score, a post-hoc method comparison, not a casewise oracle',
                'evolution': {'proposals': len(events), 'accepted': accepted, 'rejected': len(events) - accepted - no_update,
                              'no_update': no_update, 'final_rules': len(harness['rules']), 'pending_updates': 0}}
    timeline = [{'case': e['case'], 'accepted': e['accepted'],
                 'status': 'accepted' if e['accepted'] else 'no_update' if any(a.get('reason') == 'no_update' for a in e['attempts']) else 'rejected',
                 'rule': {'id': e['rule']['id']} if e.get('rule') else None} for e in events]
    progress = {'run_id': run.name, 'phase': 'complete', 'planned': 754, 'completed': 754,
                'planned_arms': 4524, 'completed_arms': 4524, 'method_family': 'active_search',
                'arms': ARMS, 'primary_arm': best, 'reference_arm': 'reference',
                'historical_cases': 144, 'proposal_limit': 24, 'cases': cases, 'timeline': timeline,
                'rules': harness['rules'], 'summary': metadata,
                'source': 'Verified frozen full comparison; tool outputs and original benchmark payload excluded'}
    return {'schema': 2, 'progress': progress, 'cases': traces}


def readme(old, progress):
    s = progress['summary']
    methods = ('## 方法\n\nEvoJev 使用冻结 JEV 的分类排序先验，结合源绑定的可执行 Harness、历史证据经验模型和有预算的证据采集。'
               '本次对照包含蒙特卡洛树搜索 PUCT、一步贪心、去除 JEV、参考 Harness、初始 PUCT 和覆盖目标 PUCT。'
               'Qwen3.5-27B 只在历史案例完成后提议原子规则，经跨案例精度、完整历史零回退回放和独立实际采集门控后更新 Harness；'
               '评测前停止 advisor，冻结模型、经验、规则和代码。所有六组实际工具调用上限均为 72。\n\n'
               'Cloud-OpsBench 的故障对象与原因同时正确才计分。全量 754 题包含历史和开发案例，不是独立泛化或在线准确率；'
               '155 题冻结分区单独报告，公开 benchmark 此前已经被本项目使用。\n\n![方法流程](workflow.png)\n\n'
               '## 结果\n\n| 方法 | 全量正确 / 754 | 准确率 | 冻结分区正确 / 155 |\n| --- | ---: | ---: | ---: |\n')
    for arm, info in ARMS.items():
        m, f = s['metrics'][arm], s['partitions']['frozen_evaluation'][arm]
        methods += f'| {info["label"]} | {m["correct"]}/{m["total"]} | {100*m["correct"]/m["total"]:.2f}% | {f["correct"]}/{f["total"]} |\n'
    primary = s['development_selection']['development_selected_arm']
    best = s['observed_best_arm']
    methods += f'\n开发门控预选：{ARMS[primary]["label"]}；全量观察到的最高方法：{ARMS[best]["label"]}。后者是六组固定方法的事后比较，不是逐题挑答案，也不是未见任务上的最优性保证。\n\n'
    if '## 启动前端' not in old:
        methods = methods.replace('## 方法', '## 总体准确率', 1).replace('## 结果', '### 冻结对照结果', 1)
        methods += ('本节来自六组冻结对照的 4524 份预测，不是在线逐题首答实验。'
                    '复现冻结对照使用 `scripts/active_pipeline.py`，不能与下方在线流程混用。\n\n')
        pattern = r'(?ms)^## 总体准确率\n.*?(?=^## |\Z)'
        updated, count = re.subn(pattern, lambda match: methods, old, count=1)
        if count != 1:
            raise ValueError('README accuracy section is required')
        return updated
    a, b = old.index('## 方法'), old.index('## 启动前端')
    updated = old[:a] + methods + old[b:]
    starts = [updated.index(marker) for marker in ('在三个独立终端中', '准备完成后，启动任务自己的') if marker in updated]
    a, b = min(starts), updated.index('## 引用')
    updated = updated[:a] + (
        '准备完成后，启动任务自己的 worker、历史采集与协调流程：\n\n```bash\n'
        'tmux new-session -d -s jev-worker "python scripts/jev.py worker --run full754"\n'
        'tmux new-session -d -s jev-collect "python scripts/jev.py active-collect --run full754"\n'
        'python src/guard_process.py --record runs/full754/pipeline_resources.json -- python scripts/active_pipeline.py --run full754 --worker-session jev-worker --collector-session jev-collect\n```\n\n'
        '协调流程依次完成 144 题历史采集、经验拟合、规则演进、36 题实际门控、停止 advisor、冻结六组全量预测和评分。'
        '另开终端，评测完成前启动结果发布器：\n\n```bash\n'
        'python src/guard_process.py --record runs/full754/publication_resources.json -- python scripts/publish_results.py --run full754 --wait\n```\n\n'
        '发布器先记录开发门控选择，再等待完整评分，审核 4524 份轨迹，更新前端压缩资源、方法图与本 README。'
        '运行数据写入忽略版本管理的 `runs/`，不修改原模型或原 benchmark。门控失败时会停止，不会用最终答案继续训练。\n\n'
    ) + updated[b:]
    return updated


def report(progress):
    s = progress['summary']
    text = '# EvoJev Frozen Full Comparison\n\n754 unique cases; six fixed methods; 4524 healthy actual-acquisition predictions.\n\n'
    text += '| Method | Full correct | Full accuracy | Frozen 155 correct | Mean calls |\n| --- | ---: | ---: | ---: | ---: |\n'
    for arm, info in ARMS.items():
        m, p, calls = s['metrics'][arm], s['partitions']['frozen_evaluation'][arm], s['tool_calls'][arm]
        text += f'| {info["label"]} | {m["correct"]}/{m["total"]} | {100*m["correct"]/m["total"]:.2f}% | {p["correct"]}/{p["total"]} | {calls["total"]/m["total"]:.2f} |\n'
    selected = s['development_selection']['development_selected_arm']
    text += f'\nDevelopment-selected: {ARMS[selected]["label"]}. Highest observed full method: {ARMS[progress["primary_arm"]]["label"]}.\n\n'
    text += 'The full set includes historical and development cases. The frozen 155 partition is reported separately; this public benchmark was already used by the project. Best full-method selection is post-hoc, not a per-case oracle or independent generalization claim. All caps are 72 calls.\n\n'
    e = s['evolution']
    text += f'Current revision: {e["proposals"]} proposals, {e["accepted"]} accepted, {e["rejected"]} rejected, {e["no_update"]} no-update; {e["final_rules"]} final rules including inherited rules.\n\n'
    text += 'Frozen code and Harness hashes match; benchmark/public hashes unchanged; zero forbidden worker accesses; advisor stopped before testing.\n'
    return text


def publish(run):
    if (run / 'publication_state.json').exists():
        record = load(run / 'publication_state.json')
        if record.get('status') == 'complete':
            for name, key in [('web/presentation.json.gz', 'presentation_sha256'), ('README.md', 'readme_sha256'), ('workflow.png', 'workflow_sha256')]:
                if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != record[key]:
                    raise ValueError('Published artifact changed; do not overwrite it blindly')
            print(json.dumps({'status': 'already_published', 'cases': record['cases']}), flush=True)
            return
    bundle = build(run)
    progress = bundle['progress']
    body = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode()
    if re.search(rb'/(?:Users|home|data/dds-data|root|mnt)/|sk-[A-Za-z0-9_-]{18,}', body):
        raise ValueError('Private path or credential in frontend resource')
    text = readme((ROOT / 'README.md').read_text(), progress)
    if re.search(r'/(?:Users|home|data/dds-data|root|mnt)/', text):
        raise ValueError('Private path in README')
    archive = run / 'publication_archive'
    archive.mkdir(exist_ok=True)
    for name in ('README.md', 'workflow.png'):
        if not (archive / name).exists():
            shutil.copyfile(ROOT / name, archive / name)
    stage = run / 'publication_staging'
    stage.mkdir(exist_ok=True)
    from render_workflow import render
    render(stage / 'workflow.png')
    write(archive / 'presentation_metadata.json', {'previous_readme_sha256': hashlib.sha256((archive / 'README.md').read_bytes()).hexdigest(),
                                                  'previous_workflow_sha256': hashlib.sha256((archive / 'workflow.png').read_bytes()).hexdigest()})
    output = ROOT / 'web/presentation.json.gz'
    pending = output.with_suffix('.pending')
    pending.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    if gzip.decompress(pending.read_bytes()) != body:
        raise ValueError('Compressed presentation validation failed')
    workflow_pending = ROOT / 'workflow.pending.png'
    shutil.copyfile(stage / 'workflow.png', workflow_pending)
    workflow_pending.replace(ROOT / 'workflow.png')
    pending.replace(output)
    readme_pending = stage / 'README.md'
    readme_pending.write_text(text, encoding='utf-8')
    readme_pending.replace(ROOT / 'README.md')
    write(run / 'dashboard.json', progress)
    (run / 'REPORT.md').write_text(report(progress), encoding='utf-8')
    from package_audit import audit
    manifest = audit()
    write(ROOT / 'PACKAGE_MANIFEST.json', manifest)
    record = {'status': 'complete', 'cases': 754, 'predictions': 4524, 'primary_arm': progress['primary_arm'],
              'metrics': progress['summary']['metrics'], 'partitions': progress['summary']['partitions'],
              'presentation_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'presentation_bytes': output.stat().st_size,
              'readme_sha256': hashlib.sha256((ROOT / 'README.md').read_bytes()).hexdigest(),
              'workflow_sha256': hashlib.sha256((ROOT / 'workflow.png').read_bytes()).hexdigest(),
              'package_audit': 'passed',
              'code_hash': progress['summary']['code_hash'], 'harness_hash': progress['summary']['harness_hash']}
    write(run / 'publication_state.json', record)
    print(json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--select-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run):
        raise ValueError('Use a simple run name')
    run = ROOT / 'runs' / args.run
    lock = (run / 'publication.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        while not (run / 'development_summary.json').exists():
            if not args.wait:
                raise FileNotFoundError('Development gate not complete')
            if (run / 'pipeline_failure.json').exists():
                raise RuntimeError('Pipeline stopped before gate')
            time.sleep(15)
        select(run)
        if args.select_only:
            print(json.dumps(load(run / 'publication_selection.json')))
            return
        while not (run / 'active_summary.json').exists():
            if not args.wait:
                raise FileNotFoundError('Complete frozen scoring not ready')
            if (run / 'pipeline_failure.json').exists():
                raise RuntimeError('Pipeline stopped; preserve traces and repair before publication')
            time.sleep(15)
        publish(run)
    except Exception as error:
        write(run / 'publication_failure.json', {'status': 'failed', 'error': str(error)})
        raise


if __name__ == '__main__':
    main()
