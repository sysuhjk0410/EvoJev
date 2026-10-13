import collections
import json
import math
import re

import numpy as np


FOCUS = re.compile(r'error|fail|denied|not found|cannot|unable|timeout|deadline|refused|backoff|pending|notready|unhealthy|oom|quota|limit|probe|secret|volume|mount|network|dns|sleep|while|loop|append|malloc|readfile|writefile|openfile|raise|panic|throw', re.I)
TOKEN = re.compile(r'(?u)\b[a-z_][a-z_0-9]+\b')


def normalize(text, objects):
    for name in sorted({o.split('/', 1)[1] for o in objects}, key=len, reverse=True):
        text = re.sub(r'(?<![\w])' + re.escape(name) + r'(?:-[a-z0-9]+){0,2}(?![\w])', ' subject ', text, flags=re.I)
    text = re.sub(r'\bcase_\d+\b|\b(?:boutique|train-ticket)\b', ' scope ', text, flags=re.I)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-f]{8,}\b', ' identifier ', text, flags=re.I)
    text = re.sub(r'\b\d[\w.:/-]*\b', ' number ', text)
    return text.casefold()


def document(rows, obj, objects):
    groups = collections.defaultdict(list)
    for row in rows:
        if row['object'] != obj:
            continue
        text = row['text'].strip()
        if row['tool'] == 'GetAlerts':
            try:
                alert = json.loads(text)
                text = json.dumps({'status': alert.get('status'), 'evidence': alert.get('evidence', [])})
            except (ValueError, AttributeError):
                continue
        if not text or text.startswith(('//', '#', '/*', '*')):
            continue
        groups[row['tool']].append(dict(row, text=text))
    parts = []
    for tool, members in sorted(groups.items()):
        if tool == 'GetSourceCode':
            indices = {j for i, row in enumerate(members) if FOCUS.search(row['text'])
                       for j in range(max(0, i - 3), min(len(members), i + 5))}
            members = [row for i, row in enumerate(members) if i in indices]
        members = sorted(members, key=lambda row: (not bool(FOCUS.search(row['text'])), row['id']))
        seen, used = set(), 0
        for row in members:
            text = normalize(row['text'], objects)
            if text in seen or used + len(text) > 6000:
                continue
            seen.add(text)
            used += len(text)
            words = TOKEN.findall(text)
            parts.append(' '.join(tool.lower() + '__' + word for word in words))
    return '\n'.join(parts)


def probe_model(texts, targets, vectorizer, classes, coefficients):
    bags = [set(TOKEN.findall(text)) for text in texts]
    tools = sorted({term.split('__', 1)[0] for term in vectorizer.vocabulary_ if '__' in term})
    background = classes.index('__background__')
    model = {}
    for tool in tools:
        features = [term for term in vectorizer.vocabulary_ if term.startswith(tool + '__')
                    and ' ' not in term and term.split('__', 1)[1] not in ('subject', 'number', 'scope', 'identifier')]
        features.sort(key=lambda term: (-float(np.max(coefficients[:, vectorizer.vocabulary_[term]] -
                                                    coefficients[background, vectorizer.vocabulary_[term]])), term))
        features = features[:16]
        if not features:
            continue
        observed = [i for i, bag in enumerate(bags) if any(word.startswith(tool + '__') for word in bag)]
        if not observed:
            continue
        pooled = [(1 + sum(feature in bags[i] for i in observed)) / (len(observed) + 2) for feature in features]
        rates, counts = {}, {}
        for cause in classes:
            indices = [i for i in observed if targets[i] == cause]
            rates[cause] = [(sum(feature in bags[i] for i in indices) + 5 * prior) / (len(indices) + 5)
                            for feature, prior in zip(features, pooled)]
            counts[cause] = len(indices)
        model[tool] = {'features': features, 'rates': rates, 'observed_documents': counts, 'pooled_rates': pooled}
    return model


def fit(memory, labels, tasks, contract):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from tree_skill_search import objects_for

    texts, targets = [], []
    for case in sorted(memory):
        objects = objects_for(contract, tasks[case]['namespace'])
        for obj in objects:
            text = document(memory[case]['evidence'], obj, objects)
            if not text:
                continue
            texts.append(text)
            targets.append(labels[case]['root_cause'] if obj == labels[case]['fault_object'] else '__background__')
    vectorizer = TfidfVectorizer(min_df=2, max_df=.98, max_features=16000,
                                 ngram_range=(1, 2), sublinear_tf=True, token_pattern=r'(?u)\b\w\w+\b')
    matrix = vectorizer.fit_transform(texts)
    classifier = LogisticRegression(C=4, class_weight='balanced', max_iter=500, random_state=20261006)
    classifier.fit(matrix, targets)
    classes = classifier.classes_.tolist()
    coefficients, intercept = classifier.coef_, classifier.intercept_
    if len(classes) == 2:
        coefficients = np.concatenate([-coefficients / 2, coefficients / 2])
        intercept = np.concatenate([-intercept / 2, intercept / 2])
    return {'schema': 'contrastive_source_bound_v1', 'vocabulary': {key: int(value) for key, value in vectorizer.vocabulary_.items()},
            'idf': vectorizer.idf_.tolist(), 'classes': classifier.classes_.tolist(),
            'coef': coefficients.tolist(), 'intercept': intercept.tolist(),
            'historical_cases': len(memory), 'subject_documents': len(texts),
            'tool_probe_model': probe_model(texts, targets, vectorizer, classes, coefficients),
            'probe_model_scope': 'Acquired historical subject observations only; unobserved checks are not negatives',
            'frozen_jev_weights': True, 'case_ids_in_runtime_artifact': False,
            'target_kind': {cause: ('app' if cause.startswith('code_') else None) for cause in classifier.classes_}}


class Experience:
    def __init__(self, data, types):
        if data.get('schema') != 'contrastive_source_bound_v1':
            raise ValueError('Unsupported experience artifact')
        self.data, self.types = data, types
        self.classes = data['classes']
        self.vocabulary = data['vocabulary']
        self.idf = np.asarray(data['idf'])
        self.coef = np.asarray(data['coef'])
        self.intercept = np.asarray(data['intercept'])
        self.subject_cache, self.profile_cache = {}, {}
        if self.coef.shape != (len(self.classes), len(self.vocabulary)):
            raise ValueError('Experience dimensions mismatch')
        if not all(np.isfinite(a).all() for a in (self.idf, self.coef, self.intercept)):
            raise ValueError('Nonfinite experience')
        for model in data.get('tool_probe_model', {}).values():
            width = len(model['features'])
            rates = [model['pooled_rates']] + list(model['rates'].values())
            if not width or any(len(rate) != width or not np.isfinite(rate).all() or
                                (np.asarray(rate) < 0).any() or (np.asarray(rate) > 1).any() for rate in rates):
                raise ValueError('Invalid historical probe probabilities')
            if any(not isinstance(count, int) or count < 0 for count in model['observed_documents'].values()):
                raise ValueError('Invalid historical probe support')

    def vector(self, text):
        words = re.findall(r'(?u)\b\w\w+\b', text)
        grams = words + [' '.join(words[i:i + 2]) for i in range(len(words) - 1)]
        counts = collections.Counter(self.vocabulary[g] for g in grams if g in self.vocabulary)
        indices = np.fromiter(counts, dtype=int)
        values = np.asarray([1 + math.log(counts[i]) for i in indices]) * self.idf[indices]
        norm = np.linalg.norm(values)
        if norm:
            values /= norm
        return indices, values

    def candidates(self, rows, objects):
        result = []
        grouped = collections.defaultdict(list)
        for row in rows:
            grouped[row['object']].append(row)
        for obj in objects:
            owned = grouped[obj]
            fingerprint = tuple((row['tool'], row['text']) for row in owned)
            previous = self.subject_cache.get(obj)
            if previous and previous[0] == fingerprint:
                result.extend(dict(row) for row in previous[1])
                continue
            text = document(owned, obj, objects)
            if not text:
                continue
            indices, values = self.vector(text)
            logits = self.intercept + self.coef[:, indices] @ values
            probabilities = np.exp(logits - logits.max())
            probabilities /= probabilities.sum()
            background = float(probabilities[self.classes.index('__background__')])
            candidates = []
            for i, cause in enumerate(self.classes):
                if cause not in self.types or self.types[cause]['target'] != obj.split('/', 1)[0]:
                    continue
                support = self.coef[i, indices] * values
                candidates.append({'fault_object': obj, 'root_cause': cause,
                               'probability': float(probabilities[i]), 'background': background,
                               'positive_feature_count': int((support > .03).sum()),
                               'experience_logit': float(logits[i])})
            self.subject_cache[obj] = (fingerprint, candidates)
            result.extend(dict(row) for row in candidates)
        return sorted(result, key=lambda r: (-r['probability'], r['fault_object'], r['root_cause']))

    def tool_profile(self, cause):
        if cause not in self.classes:
            return {}
        if cause in self.profile_cache:
            return self.profile_cache[cause]
        weights = self.coef[self.classes.index(cause)]
        totals = collections.defaultdict(float)
        for term, i in self.vocabulary.items():
            if weights[i] > .15:
                totals[term.split('__', 1)[0]] += float(weights[i])
        maximum = max(totals.values(), default=1)
        self.profile_cache[cause] = {key: value / maximum for key, value in totals.items()}
        return self.profile_cache[cause]

    def separation(self, actions, hypotheses, gains):
        models = self.data.get('tool_probe_model', {})
        if not models or len(hypotheses) < 2:
            return gains, [max(.001, h['probability']) for h in hypotheses], False
        pairs = [(i, j) for i in range(len(hypotheses)) for j in range(i + 1, len(hypotheses))]
        weights = [max(1e-9, hypotheses[i]['probability'] * hypotheses[j]['probability']) for i, j in pairs]
        result = []
        for action, coverage in zip(actions, gains):
            tool, owner = action['tool'], action['object']
            model = models.get(('GetSourceCode' if tool == 'ListCodeFiles' else tool).lower())
            distributions, confidence = [], []
            for hypothesis in hypotheses:
                cause = hypothesis['root_cause'] if owner == hypothesis['fault_object'] else '__background__'
                rate = model['rates'].get(cause, model['pooled_rates']) if model else [.5]
                count = model['observed_documents'].get(cause, 0) if model else 0
                distributions.append(np.clip(np.asarray(rate), 1e-6, 1 - 1e-6))
                confidence.append(count / (count + 5))
            separation = []
            for i, j in pairs:
                p, q = distributions[i], distributions[j]
                middle = (p + q) / 2
                divergence = (p * np.log(p / middle) + (1 - p) * np.log((1 - p) / (1 - middle)) +
                              q * np.log(q / middle) + (1 - q) * np.log((1 - q) / (1 - middle))) / (2 * math.log(2))
                supported = float(np.sort(divergence)[-min(4, len(divergence)):].mean()) * min(confidence[i], confidence[j])
                separation.append(min(.95, .8 * supported + .2 * abs(coverage[i] - coverage[j])))
            result.append(separation)
        return result, weights, True
