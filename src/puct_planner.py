import copy
from types import SimpleNamespace

import numpy as np


class CoverageState:
    def __init__(self, gains, weights, depth, costs=None, discount=1):
        self.gains, self.weights, self.depth = gains, weights, depth
        raw = np.ones(len(gains)) if costs is None else np.asarray(costs, dtype=float)
        if raw.shape != (len(gains),) or not np.isfinite(raw).all() or (raw < 1).any() or (raw != np.floor(raw)).any():
            raise ValueError('Planning costs must be positive integer call counts')
        self.costs = raw.astype(int)
        if not 0 < discount <= 1:
            raise ValueError('Invalid acquisition discount')
        self.discount = discount
        self.selected = []

    def clone(self):
        state = copy.copy(self)
        state.selected = self.selected[:]
        return state

    def current_player(self):
        return 0

    def is_chance_node(self):
        return False

    def is_terminal(self):
        return not self.legal_actions()

    def legal_actions(self):
        remaining = self.depth - sum(self.costs[i] for i in self.selected)
        return [i for i in range(len(self.gains)) if i not in self.selected and self.costs[i] <= remaining]

    def apply_action(self, action):
        if action not in self.legal_actions():
            raise ValueError('Repeated or invalid planned action')
        self.selected.append(action)

    def coverage(self):
        return 1 - np.prod(1 - self.gains[self.selected], axis=0) if self.selected else np.zeros(len(self.weights))

    def returns(self):
        remaining = np.ones(len(self.weights))
        score, elapsed = 0.0, 0
        for action in self.selected:
            elapsed += self.costs[action]
            score += self.discount ** (elapsed - 1) * float(self.weights @ (remaining * self.gains[action]))
            remaining *= 1 - self.gains[action]
        return [score]


class CoverageGame:
    def get_type(self):
        import pyspiel
        return SimpleNamespace(reward_model=pyspiel.GameType.RewardModel.TERMINAL,
                               dynamics=pyspiel.GameType.Dynamics.SEQUENTIAL)

    def max_utility(self):
        return 1


class CoverageEvaluator:
    def __init__(self, priors, random):
        self.priors, self.random = priors, random

    def prior(self, state):
        actions = state.legal_actions()
        coverage = state.coverage()
        values = np.asarray([self.priors[i] + float(state.weights @ (state.gains[i] * (1 - coverage)))
                             for i in actions]) + .001
        values /= values.sum()
        return list(zip(actions, values.tolist()))

    def evaluate(self, state):
        scores = []
        for _ in range(4):
            rollout = state.clone()
            while not rollout.is_terminal():
                actions, probabilities = zip(*self.prior(rollout))
                rollout.apply_action(int(self.random.choice(actions, p=probabilities)))
            scores.append(rollout.returns()[0])
        return [float(np.mean(scores))]


def choose(gains, weights, priors, seed=20261006, simulations=96, depth=3, costs=None,
           objective='historical_expected_evidence_coverage'):
    gains, weights, priors = np.asarray(gains, dtype=float), np.asarray(weights, dtype=float), np.asarray(priors, dtype=float)
    if gains.ndim != 2 or gains.shape != (len(priors), len(weights)) or not len(priors) or not len(weights):
        raise ValueError('Invalid action model dimensions')
    if not all(np.isfinite(a).all() for a in (gains, weights, priors)) or (gains < 0).any() or (gains > 1).any() or (weights < 0).any() or (priors < 0).any():
        raise ValueError('Invalid probability model')
    costs = np.ones(len(priors)) if costs is None else np.asarray(costs, dtype=float)
    if costs.shape != priors.shape or not np.isfinite(costs).all() or (costs < 1).any() or (costs != np.floor(costs)).any() or not (costs <= depth).any() or depth < 1 or simulations < 2:
        raise ValueError('Invalid planning costs or budget')
    from open_spiel.python.algorithms import mcts
    weights = weights / weights.sum() if weights.sum() else np.full(len(weights), 1 / len(weights))
    upper = 1 - np.prod(1 - np.sort(gains, axis=0)[-min(depth, len(gains)):], axis=0)
    utility_scale = max(1e-6, float(weights @ upper))
    random = np.random.RandomState(seed)
    state = CoverageState(gains, weights, depth, costs, discount=.95)
    evaluator = CoverageEvaluator(priors, random)
    bot = mcts.MCTSBot(CoverageGame(), 1.25 * utility_scale, simulations, evaluator, solve=False,
                       random_state=random, child_selection_fn=mcts.SearchNode.puct_value)
    root = bot.mcts_search(state)
    winner = root.best_child()
    return winner.action, {'simulations': root.explore_count, 'model': objective,
                          'observations_simulated': False, 'depth': state.depth,
                          'acquisition_discount': state.discount,
                          'exploration_utility_scale': utility_scale,
                          'ucb_coefficient': 1.25 * utility_scale,
                          'nodes': [{'action': child.action, 'visits': child.explore_count,
                                     'prior': child.prior, 'mean_value': child.total_reward / max(1, child.explore_count)}
                                    for child in root.children]}
