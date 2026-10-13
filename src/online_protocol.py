import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def immutable(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read(path) != value:
            raise ValueError('Immutable record mismatch: ' + str(path))
        return value
    fd, name = tempfile.mkstemp(prefix='.commit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if read(path) != value:
                raise ValueError('Concurrent immutable record mismatch')
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(name)
    return value


class Ledger:
    def __init__(self, run):
        self.run = Path(run)
        self.plan = read(self.run / 'online_plan.json')
        cases = self.plan['cases']
        if not cases or len(cases) != len(set(cases)) or any('/' in c or '..' in c for c in cases):
            raise ValueError('Online plan must contain unique safe case IDs')
        self._cursor = None
        self._memory = {}
        self._labels = {}
        self._updates = {}
        self.validate()

    def file(self, section, case):
        return self.run / 'online' / section / (case + '.json')

    def validate(self):
        allowed = set(self.plan['cases'])
        for section in ('dispatches', 'first', 'feedback', 'updates'):
            actual = {p.stem for p in (self.run / 'online' / section).glob('*.json')}
            if not actual <= allowed:
                raise ValueError('Unknown case in online ledger')
        harness = self.plan['initial_harness']
        incomplete = False
        for index, case in enumerate(self.plan['cases']):
            paths = [self.file(s, case) for s in ('dispatches', 'first', 'feedback', 'updates')]
            if incomplete and any(p.exists() for p in paths):
                raise ValueError('Online records must form an ordered completed prefix')
            if not paths[0].exists():
                if any(p.exists() for p in paths[1:]):
                    raise ValueError('Prediction without dispatch')
                incomplete = True
                continue
            dispatch = read(paths[0])
            payload = dispatch['payload']
            if dispatch['index'] != index or payload != self.payload(case, harness):
                raise ValueError('Dispatch does not use the prior admitted Harness')
            if dispatch['request_hash'] != fingerprint(payload):
                raise ValueError('Dispatch hash mismatch')
            if not paths[1].exists():
                if paths[2].exists() or paths[3].exists():
                    raise ValueError('Feedback or update precedes the first answer')
                incomplete = True
                continue
            first = read(paths[1])
            if first['trace_hash'] != fingerprint(first['trace']) or first['request_hash'] != dispatch['request_hash']:
                raise ValueError('First-answer integrity failure')
            if not paths[2].exists():
                if paths[3].exists():
                    raise ValueError('Update without released feedback')
                incomplete = True
                continue
            feedback = read(paths[2])
            if feedback['first_hash'] != fingerprint(first) or feedback['released_ns'] < first['committed_ns']:
                raise ValueError('Feedback not bound to the immutable first answer')
            correct = bool(first['trace'].get('healthy') and first['trace'].get('prediction') == feedback['label'])
            if feedback['correct'] != correct:
                raise ValueError('Feedback score does not match the immutable first prediction')
            if not paths[3].exists():
                incomplete = True
                continue
            update = read(paths[3])
            if update['before_hash'] != fingerprint(harness) or update['first_hash'] != fingerprint(first):
                raise ValueError('Broken Harness update chain')
            if (update['after_hash'] != fingerprint(update['harness']) or
                    update['effective_from_index'] != index + 1 or update['committed_ns'] < feedback['released_ns']):
                raise ValueError('Update must apply only to subsequent cases')
            harness = update['harness']
        return harness

    def current(self):
        if self._cursor is not None:
            return self._cursor
        harness = self.plan['initial_harness']
        for index, case in enumerate(self.plan['cases']):
            update = self.file('updates', case)
            if not update.exists():
                self._cursor = (index, case, harness)
                return self._cursor
            harness = read(update)['harness']
        self._cursor = (len(self.plan['cases']), None, harness)
        return self._cursor

    def payload(self, case, harness):
        return {'case': case, 'mode': self.plan['mode'], 'harness': harness,
                'code_hash': self.plan['code_hash'], 'replay_from': None}

    def reserve(self, case, harness):
        index, expected, current = self.current()
        if case != expected or harness != current:
            raise ValueError('Only the next case may be dispatched')
        path = self.file('dispatches', case)
        if path.exists():
            return read(path)
        payload = self.payload(case, harness)
        return immutable(path, {'index': index, 'payload': payload,
                               'request_hash': fingerprint(payload), 'created_ns': time.time_ns()})

    def commit_first(self, case, trace):
        path = self.file('first', case)
        if path.exists():
            saved = read(path)
            if saved['trace'] != trace:
                raise ValueError('First answer cannot be replaced')
            return saved
        _, expected, _ = self.current()
        if expected != case:
            raise ValueError('Cannot commit a future or completed case')
        dispatch = read(self.file('dispatches', case))
        if trace.get('request_hash') != dispatch['request_hash']:
            raise ValueError('Prediction request mismatch')
        if trace.get('retrospective_replay'):
            raise ValueError('Retrospective diagnoses are forbidden')
        if trace.get('healthy') and (trace.get('case') != case or
                                    trace.get('code_hash') != self.plan['code_hash'] or
                                    trace.get('tool_calls', 0) > self.plan['budget']):
            raise ValueError('Trace violates the frozen runtime or tool budget')
        return immutable(path, {'case': case, 'request_hash': dispatch['request_hash'],
                                'trace': trace, 'trace_hash': fingerprint(trace), 'committed_ns': time.time_ns()})

    def release_feedback(self, case):
        _, expected, _ = self.current()
        if expected != case or not self.file('first', case).exists():
            raise ValueError('Feedback is available only after the current first answer')
        path = self.file('feedback', case)
        if path.exists():
            return read(path)
        first = read(self.file('first', case))
        label = read(self.run / 'sealed_evaluation/cases' / (case + '.json'))['label']
        correct = first['trace'].get('healthy', False) and first['trace'].get('prediction') == label
        return immutable(path, {'case': case, 'label': label, 'correct': bool(correct),
                                'first_hash': fingerprint(first), 'released_ns': time.time_ns()})

    def commit_update(self, case, harness, event):
        index, expected, before = self.current()
        path = self.file('updates', case)
        if path.exists():
            saved = read(path)
            if saved['harness'] != harness or saved['event'] != event:
                raise ValueError('Committed Harness transition cannot be replaced')
            return saved
        if expected != case or not self.file('feedback', case).exists():
            raise ValueError('Harness updates require a committed answer and released feedback')
        first = read(self.file('first', case))
        result = immutable(path, {'case': case, 'before_hash': fingerprint(before),
                                 'after_hash': fingerprint(harness), 'harness': harness, 'event': event,
                                 'first_hash': fingerprint(first), 'effective_from_index': index + 1,
                                 'committed_ns': time.time_ns()})
        next_case = self.plan['cases'][index + 1] if index + 1 < len(self.plan['cases']) else None
        self._cursor = (index + 1, next_case, harness)
        self._updates[case] = result
        return result

    def memory(self):
        traces, labels = self._memory, self._labels
        for case in self.plan['cases'][len(traces):]:
            path = self.file('feedback', case)
            if not path.exists():
                break
            labels[case] = read(path)['label']
            traces[case] = read(self.file('first', case))['trace']
        return traces, labels

    def summary(self):
        traces, labels = self.memory()
        correct = sum(t.get('healthy', False) and t.get('prediction') == labels[c] for c, t in traces.items())
        for case in traces:
            if case not in self._updates and self.file('updates', case).exists():
                self._updates[case] = read(self.file('updates', case))
        updates = list(self._updates.values())
        _, current, harness = self.current()
        totals = {kind: sum(u['event']['decision'] == kind for u in updates)
                  for kind in ('accepted', 'rejected', 'no_update', 'advisor_unavailable', 'unhealthy_diagnosis')}
        return {'status': 'complete' if current is None else 'running', 'phase': 'online_single_pass',
                'planned': len(self.plan['cases']), 'completed': len(updates), 'first_answers': len(traces),
                'correct': correct, 'accuracy': correct / len(traces) if traces else 0,
                'metric': 'prequential first-answer exact object AND cause accuracy',
                'updates': totals, 'harness_version': harness['version'], 'rules': len(harness['rules']),
                'next_case': current, 'retrospective_predictions': 0, 'prior_public_benchmark_use': True,
                'admission_guarantee': 'past cached evidence predicates only; not a guarantee of future accuracy'}
