
import json
from pathlib import Path

run = Path(__file__).resolve().parent
summary = json.loads((run / 'summary.json').read_text())
result = json.loads((run / 'test_predictions.json').read_text())
plan = json.loads((run / 'protocol.json').read_text())
assert result['status'] == 'complete' and len(result['cases']) == 754
assert set(result['cases']) == set(plan['test'])
assert (run / 'advisor_stopped.json').exists()
assert all(set(arms) == set(plan['arms']) for arms in result['cases'].values())
lines = ['# Complete Cloud-OpsBench Comparison', '',
         'Exact accuracy requires BOTH the fault object and root cause to match.', '',
         '| Method | Correct / 754 | Accuracy | Mean tool calls |',
         '| --- | ---: | ---: | ---: |']
for arm, metric in summary['metrics'].items():
    lines.append(f'| {arm} | {metric["correct"]}/{metric["total"]} | '
                 f'{100 * metric["correct"] / metric["total"]:.2f}% | '
                 f'{summary["tool_calls"][arm]["total"] / metric["total"]:.2f} |')
lines += ['', '## Separately Frozen Evaluation Partition', '',
          '| Method | Correct / 155 | Accuracy |', '| --- | ---: | ---: |']
for arm, metric in summary['partitions']['frozen_evaluation'].items():
    lines.append(f'| {arm} | {metric["correct"]}/{metric["total"]} | '
                 f'{100 * metric["correct"] / metric["total"]:.2f}% |')
lines += ['', '## Paired Comparisons', '',
          '| Comparator | Repairs | Regressions | Delta pp | Exact paired p |',
          '| --- | ---: | ---: | ---: | ---: |']
for arm, comparison in summary['comparisons'].items():
    lines.append(f'| {arm} | {comparison["repairs"]} | {comparison["regressions"]} | '
                 f'{comparison["delta_pp"]:.2f} | {comparison["paired_exact_p"]:.6g} |')
lines += ['', '## Interpretation', '',
          '- The full 754 includes historical learning and admission cases. It is frozen full-benchmark '
          're-evaluation, NOT held-out or prequential accuracy.',
          '- The 155-case evaluation partition was excluded from this run\'s historical feedback and gates. '
          'The public benchmark was previously used in the project, so this is not pristine external validation.',
          '- Qwen3.5-27B learns reusable predicates only from completed historical cases. Its service was '
          'stopped before final predictions; no current-case answers or online LLM diagnoses are used.',
          '- Static and evolved search share a 72-call maximum. The previous-v3 ablation has a 48-call maximum; '
          'plain JEV uses five initial calls. Additional search cost is reported, not hidden.',
          '- AgentJev weights remain frozen. This is transfer into executable diagnosis rules, '
          'not neural-weight distillation. Search is bounded evidence acquisition, not an MCTS claim.',
          f'- Historical evolution: {summary["evolution"]["accepted"]} accepted updates, '
          f'{summary["evolution"]["final_rules"]} final rules.',
          f'- Public/original benchmark content unchanged: {summary["public_and_benchmark_hashes_unchanged"]}. '
          f'Forbidden worker accesses: {summary["worker_forbidden_attempts"]}.',
          '- Earlier failed experiments and the 82-case confirmation remain preserved separately.',
          '', '## Outputs', '']
lines += [f'- `{run / name}`' for name in ('summary.json', 'scored_cases.json', 'test_predictions.json',
          'full_traces', 'protocol.json', 'frozen.json', 'state.json', 'actual_acquisition_gate.json',
          'worker_access.jsonl', 'controller.log')]
(run / 'REPORT.md').write_text('\n'.join(lines) + '\n')
print('\n'.join(lines[:32]))
