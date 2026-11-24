"""Small exact query-order oracle under an explicit independent Bernoulli prior.

This is standard finite-state dynamic programming, supplied as an evaluation
reference. It is exponential, prior-dependent, and not a novelty claim. Query
recommendations never substitute for trusted receipts in the Verifier.
"""
from dataclasses import dataclass
from functools import lru_cache
from math import inf


@dataclass(frozen=True)
class Query:
    name: str
    fact: str
    cost: float = 1.0


def recommend(verifier, queries, probabilities=None):
    """Minimize expected query cost to certify the current plan objective.

    The objective in core is lexicographic user utility, then raw field cost if
    explicitly requested. This module does not jointly optimize raw privacy,
    predicate information, latency and monetary cost.
    """
    probabilities = probabilities or {}
    if any(q.cost <= 0 for q in queries):
        raise ValueError('Query costs must be strictly positive.')
    if any(not 0 <= p <= 1 for p in probabilities.values()):
        raise ValueError('Prior probabilities must lie in [0,1].')
    plans = [p for p in verifier.registry.plans(verifier.goals)
             if p.fields <= verifier.policy.allowed_fields and all(
                 verifier.registry.actions[n].tool in verifier.policy.allowed_tools for n in p.nodes)]
    facts = sorted({f for p in plans for f, _ in p.guards})
    known = tuple(sorted((f, verifier.fact(f)) for f in facts if verifier.fact(f) is not None))
    visits = 0

    def terminal(evidence):
        possible = [p for p in plans if all(f not in evidence or evidence[f] == value for f, value in p.guards)]
        if not possible:
            return True
        proven = [p for p in possible if all(f in evidence for f, _ in p.guards)]
        if not proven:
            return False
        optimum = min(verifier.score(p) for p in proven)
        return not any(verifier.score(p) < optimum for p in possible)

    @lru_cache(None)
    def value(state):
        nonlocal visits
        visits += 1
        evidence = dict(state)
        if terminal(evidence):
            return 0.0, None
        best = (inf, None)
        for query in sorted(queries, key=lambda q: q.name):
            if query.fact in evidence or query.fact not in facts:
                continue
            p = probabilities.get(query.fact, 0.5)
            yes = value(tuple(sorted({**evidence, query.fact: True}.items())))[0]
            no = value(tuple(sorted({**evidence, query.fact: False}.items())))[0]
            # Even a zero-prior outcome must admit a safe completion/failure
            # certificate; the prior is never a permission to assume a fact.
            if yes == inf or no == inf:
                cost = inf
            else:
                cost = query.cost + p * yes + (1 - p) * no
            if cost < best[0]:
                best = cost, query.name
        return best

    cost, query = value(known)
    return {'next_query': query, 'expected_remaining_query_cost': cost,
            'dp_states': visits, 'objective': 'cost to certify current lexicographic plan objective',
            'prior_is_authority': False}
