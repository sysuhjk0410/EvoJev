#!/usr/bin/env python3

import argparse
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from online_protocol import Ledger, read, fingerprint
from grounded import write
from worker import code_hash
from publish_results import display_tree
from render_workflow import render
from package_audit import audit


def serving_changes(run):
    path = run / 'advisor_context_256k_transition.json'
    if not path.exists():
        return []
    transition = read(path)
    if (transition.get('phase') != 'ready_and_resumed' or
            not transition.get('first_answers_unchanged') or not transition.get('no_case_retake')):
        raise ValueError('Advisor serving change is not fully audited')
    return [{'role': 'post_case_advisor', 'old_context': transition['old_context'],
             'new_context': transition['new_context'],
             'first_answers_already_committed': transition['first_answers_before'],
             'effective_after_first_index': transition['effective_for_advisor_requests_after_first_index'],
             'prior_failed_updates_retried': False, 'first_answers_unchanged': True,
             'frozen_diagnosis_runtime_unchanged': True}]


def accuracy_section(summary):
    correct, total = summary['correct'], 754
    if not isinstance(correct, int) or isinstance(correct, bool) or not 0 <= correct <= total:
        raise ValueError('Invalid final accuracy count')
    decisions = summary['updates']
    counts = '、'.join(f'{key}={value}' for key, value in sorted(decisions.items()))
    target = '80% 目标已达到' if correct / total >= .8 else '80% 目标未达到'
    return '\n'.join([
        '## 总体准确率', '',
        f'本轮已完成全部 754 个唯一案例，最终正确 {correct} 题、错误 {total - correct} 题，'
        f'对象与原因联合准确率为 **{correct}/754 = {100 * correct / total:.2f}%**，{target}。'
        f'全部首答与 754 次题后更新已通过单遍、时序、版本链、哈希及访问审计。更新决策计数：{counts}。'
        '决策次数与最终规则条数不是同一个指标。前端已切换为本轮完整首答与逐题演进记录。', '',
        '准确率按 `sum(healthy_i AND predicted_fault_object_i == gold_fault_object_i AND predicted_root_cause_i == gold_root_cause_i) / 754` 计算。'
        '故障对象与原因必须同时精确一致，只有一个字段正确计错；无输出、异常和不健康诊断计错，不从分母删掉。'
        '每题只执行一次实际诊断，接受规则、更新失败或后来有更好的 Harness 均不能改写已保存首答或旧分数。', '',
        '这是先预测、保存，再释放本题反馈更新后续 Harness 的 prequential 首答准确率，'
        '不是用最终 Harness 重答旧题的回放准确率，也不是项目级未见 benchmark 的 held-out 成绩。'
        '公开 benchmark 此前已被本项目使用；总体数字也不能单独证明 PUCT、LLM 或历史经验模型各自的独立收益。', '',
    ])


def update_accuracy_readme(text, summary):
    pattern = r'(?ms)^## 总体准确率\n.*?(?=^## |\Z)'
    if len(re.findall(pattern, text)) != 1:
        raise ValueError('README must contain one dedicated accuracy section')
    return re.sub(pattern, lambda match: accuracy_section(summary), text)


def update_case_snapshot(run, summary):
    path = ROOT / 'docs/case_walkthroughs.json'
    if not path.exists():
        return
    bundle = read(path)
    examples = bundle.get('cases', [])
    if len(examples) != 3 or len({case['case'] for case in examples}) != 3:
        raise ValueError('Documentation must retain three unique completed cases')
    for case in examples:
        original = run / 'online/first' / (case['case'] + '.json')
        if hashlib.sha256(original.read_bytes()).hexdigest() != case['integrity']['first_prediction_file_sha256']:
            raise ValueError('Documented example differs from the original first answer')
    bundle['accuracy_snapshot'] = {'as_of': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'status': 'complete', 'audited': True, 'planned': 754, 'first_answers': 754,
        'correct': summary['correct'], 'wrong': 754 - summary['correct'], 'accuracy': summary['correct'] / 754,
        'completed_updates': 754, 'update_decisions': summary['updates'],
        'metric': summary['metric'], 'denominator': 'All 754 unique immutable first answers, including failed diagnoses',
        'not_held_out': True, 'retrospective_answers_used': False}
    write(path, bundle)


def build(run):
    ledger = Ledger(run)
    summary = read(run / 'online_summary.json')
    if (summary.get('status') != 'complete' or not summary.get('audited') or
            summary.get('unique_cases') != 754 or len(ledger.plan['cases']) != 754 or
            summary.get('physical_diagnosis_starts') != 754 or summary.get('pending_updates') != 0 or
            not summary.get('zero_forbidden_worker_access') or not summary.get('source_hashes_verified')):
        raise ValueError('Publish only audited complete 754-case single-pass experiments')
    if code_hash(run) != ledger.plan['code_hash'] or ledger.summary()['completed'] != 754:
        raise ValueError('Runtime or first-answer ledger changed')
    cases, traces, timeline = [], {}, []
    total_calls = 0
    for index, case in enumerate(ledger.plan['cases']):
        first = read(ledger.file('first', case))
        feedback = read(ledger.file('feedback', case))
        update = read(ledger.file('updates', case))
        before = read(ledger.file('dispatches', case))['payload']['harness']
        trace = first['trace']
        values = {'prediction': trace.get('prediction', {}), 'correct': feedback['correct'],
                  'healthy': trace.get('healthy', False), 'tool_calls': trace.get('tool_calls', 0),
                  'wall_sec': trace.get('wall_sec', 0)}
        total_calls += values['tool_calls']
        event = update['event']
        cases.append({'case': case, 'partition': 'online_stream', 'arms': {'online_puct': values},
                      'stream_index': index, 'harness_version': before['version'],
                      'update': {'decision': event['decision'], 'version_after': update['harness']['version'],
                                 'new_rules': len(event.get('accepted_rule_hashes', []))}})
        traces[case] = {'online_puct': dict(values, steps=[{key: step.get(key) for key in
                      ('tool', 'arguments', 'elapsed_sec', 'error')} for step in trace.get('steps', [])],
                      search_tree=display_tree(trace), update=cases[-1]['update'])}
        timeline.append({'case': case, 'accepted': event['decision'] == 'accepted',
                         'status': event['decision'], 'harness_version': update['harness']['version'],
                         'new_rule_hashes': event.get('accepted_rule_hashes', []), 'rule': None})
        timeline[-1]['accepted_rule_ids'] = ['online_' + key[:20] for key in event.get('accepted_rule_hashes', [])]
    harness = ledger.current()[2]
    progress = {'run_id': run.name, 'phase': 'complete', 'planned': 754, 'completed': 754,
                'planned_arms': 754, 'completed_arms': 754, 'method_family': 'online_single_pass',
                'arms': {'online_puct': {'label': 'Evolving JEV + PUCT', 'color': '#167d73'}},
                'primary_arm': 'online_puct', 'reference_arm': None, 'timeline': timeline,
                'rules': harness['rules'], 'cases': cases,
                'summary': {'metrics': {'online_puct': {'correct': summary['correct'], 'total': 754}},
                            'comparisons': {}, 'scope': summary['metric'], 'evolution': summary['updates'],
                            'tool_calls': {'online_puct': {'total': total_calls}},
                            'code_hash': ledger.plan['code_hash'], 'harness_hash': fingerprint(harness),
                            'worker_forbidden_attempts': 0, 'public_and_benchmark_hashes_unchanged': True,
                            'retrospective_predictions': 0, 'prior_public_benchmark_use': True,
                            'advisor_serving_changes': serving_changes(run)}}
    if sum(c['arms']['online_puct']['correct'] for c in cases) != summary['correct']:
        raise ValueError('First-answer score mismatch')
    return {'schema': 1, 'progress': progress, 'cases': traces}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    bundle = build(run)
    archive = run / 'publication_archive'
    archive.mkdir(exist_ok=True)
    for name in ('README.md', 'workflow.png', 'web/presentation.json.gz'):
        source = ROOT / name
        target = archive / Path(name).name
        if not target.exists():
            target.write_bytes(source.read_bytes())
    body = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode()
    if re.search(rb'/(?:Users|home|data/dds-data|root|mnt)/|sk-[A-Za-z0-9_-]{18,}', body):
        raise ValueError('Private path or credential in frontend presentation')
    output = ROOT / 'web/presentation.json.gz'
    temp = output.with_suffix('.tmp')
    temp.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    temp.replace(output)
    render(ROOT / 'workflow.png', online=True)
    readme = ROOT / 'README.md'
    text = readme.read_text()
    marker = '本轮在线实验尚未完成。前端暂保留上一次通过审计的冻结实验结果，不是本轮在线演进成绩。旧的六方法实验和已保存预测单独保留，不追认为逐题演进结果。'
    summary = bundle['progress']['summary']['metrics']['online_puct']
    text = text.replace(marker, f'本轮在线实验已完成：754 个唯一首答，{summary["correct"]}/754 = {100 * summary["correct"] / 754:.2f}% 的对象与原因联合准确率。每题只执行一次诊断，更新只影响后续题；前端展示逐题首答、累计准确率、Harness 演进与证据采集轨迹。它不是 held-out 成绩，旧的冻结实验单独保留。')
    full_summary = read(run / 'online_summary.json')
    readme.write_text(update_accuracy_readme(text, full_summary))
    update_case_snapshot(run, full_summary)
    record = {'published': True, 'cases': 754, 'presentation_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'prequential_accuracy': summary['correct'] / 754}
    write(run / 'publication.json', record)
    (ROOT / 'PACKAGE_MANIFEST.json').write_text(json.dumps(audit(), indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
