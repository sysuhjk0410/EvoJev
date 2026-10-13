#!/usr/bin/env python3

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cloudops_evolution import catalog, digest as ranking_digest
from grounded import digest, evidence_excerpt, scoped_rows, write
from tree_skill_search import objects_for, signature


def read(path):
    return json.loads(path.read_text())


def committed_case(run, case):
    paths = {name: run / 'online' / name / (case + '.json')
             for name in ('dispatches', 'first', 'feedback', 'updates', 'proposals')}
    if any(not path.exists() for path in paths.values()):
        raise ValueError('Export only cases with a committed first answer, feedback and completed update')
    records = {name: read(path) for name, path in paths.items()}
    first, feedback = records['first'], records['feedback']
    if first['request_hash'] != records['dispatches']['request_hash']:
        raise ValueError('First answer does not match its original dispatch')
    if not first['committed_ns'] < feedback['released_ns']:
        raise ValueError('Feedback was not released after the first answer')
    trace = first['trace']
    if first['trace_hash'] != digest(trace) or feedback['first_hash'] != digest(first):
        raise ValueError('First-answer or feedback hash mismatch')
    update = records['updates']
    before = records['dispatches']['payload']['harness']
    if (update['first_hash'] != digest(first) or update['before_hash'] != digest(before) or
            update['after_hash'] != digest(update['harness']) or trace['harness_hash'] != digest(before)):
        raise ValueError('Case version-chain mismatch')
    exact = bool(trace.get('healthy') and trace.get('prediction') == feedback['label'])
    if exact != feedback['correct']:
        raise ValueError('Stored feedback score differs from exact first-answer scoring')
    return records


def snapshot(run):
    plan = read(run / 'online_plan.json')
    count, correct, updates = 0, 0, 0
    decisions = {}
    for case in plan['cases']:
        first = run / 'online/first' / (case + '.json')
        if not first.exists():
            break
        feedback = run / 'online/feedback' / (case + '.json')
        for _ in range(20):
            if feedback.exists():
                break
            time.sleep(.1)
        if not feedback.exists():
            raise ValueError('Do not publish a snapshot with an unscored first answer')
        trace, scored = read(first)['trace'], read(feedback)
        exact = bool(trace.get('healthy') and trace.get('prediction') == scored['label'])
        if exact != scored['correct']:
            raise ValueError('First-answer score mismatch')
        count += 1
        correct += int(exact)
        update = run / 'online/updates' / (case + '.json')
        if update.exists():
            updates += 1
            decision = read(update)['event']['decision']
            decisions[decision] = decisions.get(decision, 0) + 1
    return {'as_of': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
            'status': 'complete' if count == len(plan['cases']) and updates == count else 'running',
            'audited': (run / 'online_summary.json').exists() and read(run / 'online_summary.json').get('audited', False),
            'planned': len(plan['cases']), 'first_answers': count, 'correct': correct,
            'wrong': count - correct, 'accuracy': correct / count if count else None,
            'completed_updates': updates, 'update_decisions': decisions,
            'metric': 'prequential first-answer exact fault_object AND root_cause',
            'denominator': 'All persisted first answers for an interim snapshot; all 754 cases at completion',
            'not_held_out': True, 'retrospective_answers_used': False}


def ranking(run, payload, recorded_distribution=None):
    options = payload['questions'][0]['options']
    key = ranking_digest(payload)
    cache = run / 'scores' / (key + '.json')
    distribution = read(cache) if cache.exists() else ({next(iter(options)): 1.0} if len(options) == 1 else None)
    if distribution is not None and recorded_distribution is not None:
        if set(distribution) != set(recorded_distribution) or any(
                not math.isclose(distribution[k], recorded_distribution[k], rel_tol=1e-9, abs_tol=1e-12)
                for k in distribution):
            raise ValueError('Ranking cache differs from the committed trace')
    serialization = ('original request serialization verified by its persisted cache key' if cache.exists() else
                     'single-candidate interface skips model serialization' if len(options) == 1 else
                     'semantically reconstructed input; exact original serialization was not verified')
    return {'input': payload, 'output': distribution,
            'provenance': 'persisted ranking cache' if cache.exists() else
                          'single-candidate identity; no neural call' if len(options) == 1 else 'not recorded',
            'input_serialization': serialization, 'reconstructed_request_sha256': key,
            'original_request_sha256': key if cache.exists() else None, 'new_model_inference': False}


def walkthrough(run, case, contract, types):
    records = committed_case(run, case)
    dispatch, first, feedback, update = (records[k] for k in ('dispatches', 'first', 'feedback', 'updates'))
    trace, before = first['trace'], dispatch['payload']['harness']
    public = read(run / 'public/cases' / case / 'task.json')
    if set(public) != {'query', 'namespace'}:
        raise ValueError('Document only the actual label-free solver input')
    objects = objects_for(contract, public['namespace'])
    steps, tree = trace['steps'], trace['search_tree']
    index_by_action = {signature(s['tool'], s['arguments']): i for i, s in enumerate(steps)}
    initial_count = index_by_action[signature(tree[0]['action']['tool'], tree[0]['action']['arguments'])] if tree else len(steps)
    ordered_steps = []
    for i, step in enumerate(steps):
        args = step['arguments']
        if 1 <= i <= 3 and step['tool'] == 'GetResources' and set(args) == {'resource_type', 'name', 'namespace'}:
            args = {key: args[key] for key in ('resource_type', 'name', 'namespace')}
        ordered_steps.append(dict(step, arguments=args))
    initial_rows = scoped_rows(ordered_steps[:initial_count], objects)
    state = public['query'] + '\n' + json.dumps(evidence_excerpt(initial_rows, 9000), ensure_ascii=False)
    owner_input = {'state': state, 'questions': [{'id': 'rank', 'type': 'choice',
                   'question': 'Rank the faulty owner, distinguish downstream symptoms.', 'options': objects}]}
    owner_ranking = ranking(run, owner_input)
    owner_ranking['output_after_alert_adjustment'] = trace['component_scores']
    owner_ranking['alert_adjustment'] = 'If ABNORMAL owners exist: 0.2 * JEV probability + 0.8 / number_of_alerted_owners for each alerted owner'
    if owner_ranking['output'] is not None:
        alerted = {row['object'] for row in initial_rows if row['object'] and row['tool'] == 'GetAlerts' and 'ABNORMAL' in row['text']}
        adjusted = {obj: .2 * score + (.8 / len(alerted) if obj in alerted else 0)
                    for obj, score in owner_ranking['output'].items()} if alerted else owner_ranking['output']
        if set(adjusted) != set(trace['component_scores']) or any(
                not math.isclose(adjusted[obj], trace['component_scores'][obj], abs_tol=1e-10) for obj in adjusted):
            raise ValueError('Reconstructed owner ranking differs from the original committed score')
    final_rows = scoped_rows(ordered_steps, objects)
    if digest(final_rows) != digest(trace['evidence']):
        raise ValueError('Evidence reconstruction differs from the original committed observations')
    final_state = public['query'] + '\n' + json.dumps(evidence_excerpt(final_rows, 9000), ensure_ascii=False)
    final_options = {str(i): c['fault_object'] + ' | ' + c['root_cause'] + ' | ' + types[c['root_cause']]['description']
                     for i, c in enumerate(trace['bank'])}
    final_input = {'state': final_state, 'questions': [{'id': 'rank', 'type': 'choice',
                   'question': 'Choose the best source-supported object AND cause. Reject cascading effects.',
                   'options': final_options}]}
    final_distribution = {str(i): c['jev_probability'] for i, c in enumerate(trace['bank'])}
    final_rank = ranking(run, final_input, final_distribution)
    for candidate in trace['bank']:
        expected = math.log(max(1e-9, candidate['probability'])) + .15 * math.log(max(1e-9, candidate['jev_probability'])) + (.5 if candidate['explicit_proof'] else 0)
        if not math.isclose(expected, candidate['joint_score'], abs_tol=1e-10):
            raise ValueError('Recorded joint score does not match the frozen selection rule')
    winner = max(trace['bank'], key=lambda c: c['joint_score'])
    if {k: winner[k] for k in ('fault_object', 'root_cause')} != trace['prediction']:
        raise ValueError('Winner differs from the immutable first prediction')
    experience = read(run / 'experiences' / (before['experience_sha'] + '.json')) if before.get('experience_sha') else None
    proofs = trace['supported_pairs']
    proof_ids = {p['rule'] for p in proofs}
    matched_rules = [rule for rule in before['rules'] if rule['id'] in proof_ids]
    plans = []
    for node in tree:
        action = node['action']
        executed = index_by_action[signature(action['tool'], action['arguments'])]
        plans.append({'input': {'observed_tool_steps_before': list(range(executed)),
                                'selected_action': action, 'remaining_call_budget_before': 72 - executed,
                                'candidate_action_labels_and_gain_matrix': 'not recorded in the original trace'},
                      'output': {'selected_tool_step': executed,
                                 'new_evidence_step': node['new_evidence_step'], 'planning': node['planning']},
                      'next_module_receives': 'The selected action arguments; after acquisition only its actual output joins the evidence prefix'})
    advisor_files = list((run / 'advisor').glob(case + '_0_*.json'))
    advisor = read(advisor_files[0]) if len(advisor_files) == 1 else None
    if advisor and not (advisor.get('first_prediction_committed_before_feedback') and not advisor.get('future_labels_supplied')):
        raise ValueError('Advisor record violates the post-case feedback boundary')
    accepted_ids = {'online_' + key[:20] for key in update['event'].get('accepted_rule_hashes', [])}
    new_rules = [rule for rule in update['harness']['rules'] if rule['id'] in accepted_ids]
    return {'case': case, 'stream_position': dispatch['index'] + 1,
            'selection_note': 'Curated completed example for mechanism explanation, not an unbiased accuracy sample',
            'original_public_task': public,
            'original_acquired_tool_outputs': [{'step': i, **s} for i, s in enumerate(steps)],
            'source_bound_evidence': trace['evidence'],
            'modules': [
                {'name': 'Immutable dispatch and public-input boundary',
                 'input': {'task': public, 'harness_version': before['version'], 'harness_sha256': trace['harness_hash'],
                           'experience_sha256': before.get('experience_sha'), 'ground_truth_available_to_solver': False},
                 'output': {'valid_objects': objects, 'request_sha256': first['request_hash']},
                 'next_module_receives': 'Public query, namespace, valid owner catalog, and already admitted Harness'},
                {'name': 'Read-only snapshot bootstrap and source ownership',
                 'input': {'tool_step_indices': list(range(initial_count)), 'task': public},
                 'output': {'owned_evidence': initial_rows, 'tool_output_reference': 'original_acquired_tool_outputs'},
                 'next_module_receives': 'Only the acquired, owner-bound evidence prefix'},
                {'name': 'Frozen JEV owner ranking', **owner_ranking,
                 'next_module_receives': 'Owner probabilities and alert-adjusted owner scores, not a generated diagnosis'},
                {'name': 'Historical experience and iterative PUCT acquisition',
                 'input': {'experience_historical_cases': experience.get('historical_cases') if experience else 0,
                           'experience_subject_documents': experience.get('subject_documents') if experience else 0,
                           'simulations_per_replan': 96, 'horizon_call_budget': 3, 'discount': .95,
                           'actual_snapshot_call_cap': trace['max_tool_calls'], 'past_only_experience': True},
                 'output': {'replanning_steps': plans, 'actual_tool_calls': trace['tool_calls']},
                 'next_module_receives': 'Saved actual tool observations, never simulated future observations'},
                {'name': 'Executable Harness witness validation',
                 'input': {'evidence_reference': 'source_bound_evidence', 'matched_pre_case_rules': matched_rules},
                 'output': {'supported_pairs': proofs, 'verified_candidate_constraint': trace['verified_candidate_constraint']},
                 'next_module_receives': 'Allowed object/cause pairs and their direct source witnesses'},
                {'name': 'Final candidates and frozen JEV pair ranking', **final_rank,
                 'output_candidate_bank': trace['bank'],
                 'unfiltered_historical_candidate_bank': 'not recorded; do not claim the displayed bank is the full pre-filter bank',
                 'joint_score_formula': 'log(experience_probability) + 0.15 * log(JEV_probability) + 0.5 * explicit_proof',
                 'next_module_receives': 'The maximum joint-score pair'},
                {'name': 'Immutable first prediction, then feedback release',
                 'input': {'winner': winner},
                 'output': {'first_prediction': trace['prediction'], 'healthy': trace['healthy'],
                            'first_committed_ns': first['committed_ns'], 'trace_sha256': first['trace_hash'],
                            'feedback_released_ns': feedback['released_ns'], 'confirmed_outcome_after_commit': feedback['label'],
                            'exact_correct': feedback['correct'], 'diagnosis_wall_seconds': trace['wall_sec']},
                 'next_module_receives': 'Only now may the completed trace and confirmed outcome reach the advisor'},
                {'name': 'Post-case Qwen3.5-27B rule proposal',
                 'input': advisor['request'] if advisor else 'No unique successful advisor response recorded',
                 'output': advisor['response'] if advisor else records['proposals'],
                 'compiled_proposal': records['proposals'], 'future_labels_supplied': False,
                 'next_module_receives': 'A proposed generic source-bound predicate, not a replacement answer'},
                {'name': 'Past-evidence admission and next-case-only evolution',
                 'input': {'completed_feedback_cases': update['event'].get('completed_feedback_cases'),
                           'proposal_reference': 'Post-case Qwen3.5-27B rule proposal'},
                 'output': {'event': update['event'], 'accepted_rules': new_rules,
                            'version_before': before['version'], 'version_after': update['harness']['version'],
                            'effective_from_index': update['effective_from_index']},
                 'next_module_receives': 'Updated Harness for subsequent cases only; this case is never re-diagnosed'}],
            'integrity': {'first_prediction_file_sha256': hashlib.sha256((run / 'online/first' / (case + '.json')).read_bytes()).hexdigest(),
                          'request_sha256': first['request_hash'], 'trace_sha256': first['trace_hash'],
                          'new_tool_calls': 0, 'new_JEV_calls': 0, 'new_advisor_calls': 0,
                          'scored_prediction_replaced': False}}


def build(run, cases):
    if len(cases) != 3 or len(set(cases)) != 3:
        raise ValueError('Exactly three unique completed examples are required')
    plan = read(run / 'online_plan.json')
    if any(case not in plan['cases'] for case in cases):
        raise ValueError('Example is not part of this experiment')
    contract, types = catalog(run / 'public/repo')
    examples = [walkthrough(run, case, contract, types) for case in cases]
    return {'schema': 'evojev_module_io_walkthrough_v1', 'accuracy_snapshot': snapshot(run),
            'benchmark_source': 'https://github.com/LLM4Ops/Cloud-OpsBench',
            'data_scope': 'Three requested explanatory cases; acquired observations only, no unobserved snapshot outputs',
            'recording_limits': 'Tool inputs/outputs, owner scores, selected PUCT actions and root statistics, final scores and advisor exchanges are persisted. Some exact JEV inputs are reconstructed without inference. Unlogged action-candidate order, gain matrices and pre-filter candidate banks are explicitly not supplied.',
            'observation_provenance': 'Original acquired public benchmark snapshots. Their cluster addresses and configured storage hostPath belong to benchmark observations, not the machine running this experiment.',
            'cases': examples}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--cases', nargs=3, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/case_walkthroughs.json')
    args = parser.parse_args()
    run = args.run.resolve()
    if ROOT not in run.parents or ROOT not in args.output.resolve().parents:
        raise ValueError('Keep documentation exports inside the project')
    bundle = build(run, args.cases)
    write(args.output, bundle)
    print(json.dumps({'cases': [c['case'] for c in bundle['cases']], 'accuracy_snapshot': bundle['accuracy_snapshot'],
                      'bytes': args.output.stat().st_size, 'new_diagnoses': 0}))


if __name__ == '__main__':
    main()
