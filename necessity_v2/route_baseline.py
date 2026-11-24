"""Offline comparison of refreshed route tables and versioned read justifications."""
from dataclasses import dataclass

from .core import Denied, Plan, Verifier


@dataclass(frozen=True)
class RouteRow:
    goals: frozenset
    root: str
    steps: tuple
    conditions: tuple

    @property
    def nodes(self):
        return frozenset(node for node, _ in self.steps)


def refresh_public_state(verifier):
    for name in sorted(verifier.authority.public):
        verifier.accept_evidence(verifier.authority.public_receipt(name))


class ReusableIdentityVerifier(Verifier):
    """Shared receipt reuse for the standalone identity step in this comparison."""

    def __init__(self, authority, registry, policy, goals):
        super().__init__(authority, registry, policy, goals)
        self.identity_receipt = None

    def identity_stamp(self):
        action = self.registry.actions['identity']
        if action.requires or action.produces != 'identity_verified':
            raise ValueError('Expected the standalone identity contract.')
        return (self.authority.resource, 'refund_identity', self.policy,
                tuple((field, self.authority.value_version(field)) for field in action.fields),
                tuple((name, self.authority.fact_version(name)) for name, _ in action.guards))

    def propose(self, nodes):
        sid = super().propose(nodes)
        session = self.sessions[sid]
        if ('identity' in session['plan'].nodes and self.identity_receipt is not None
                and self.identity_receipt == self.identity_stamp()):
            session['done'].add('identity')
            session['artifacts'].add('identity_verified')
        return sid

    def _enabled(self, session, node):
        action = super()._enabled(session, node)
        if 'identity_verified' in action.requires and self.identity_receipt != self.identity_stamp():
            raise Denied('Identity verification is stale.')
        return action

    def execute(self, sid, node, values):
        result = super().execute(sid, node, values)
        if node == 'identity':
            self.identity_receipt = self.identity_stamp()
        return result


class RefreshedRouteTable(ReusableIdentityVerifier):
    """Handwritten route eligibility and per-step read fields, refreshed on each read."""

    def __init__(self, authority, registry, policy, goals, rows):
        super().__init__(authority, registry, policy, goals)
        self.rows = {row.nodes: row for row in rows if row.goals == frozenset(goals)}
        self.read_refreshes = 0

    def frontier(self):
        possible, proven = [], []
        for row in self.rows.values():
            fields = frozenset(field for _, fields in row.steps for field in fields)
            if (not fields <= self.policy.allowed_fields or
                    any(self.registry.actions[node].tool not in self.policy.allowed_tools for node in row.nodes)):
                continue
            roots = {row.root}
            if 'quotes_reported' in self.goals:
                roots.add('quotes')
            plan = Plan(row.nodes, frozenset(roots), fields, frozenset(row.conditions))
            checks = [(name, self.fact(name), expected) for name, expected in row.conditions]
            if any(value is not None and value != expected for _, value, expected in checks):
                continue
            possible.append(plan)
            if all(value is not None for _, value, _ in checks):
                proven.append(plan)
        best = min((self.score(plan) for plan in proven), default=None)
        missing = {name for plan in possible if best is None or self.score(plan) < best
                   for name, _ in plan.guards if self.fact(name) is None}
        accepted = [] if missing else [plan for plan in proven if self.score(plan) == best]
        support = {name: self.receipts[name]['version'] for name in self.authority.public
                   if self.fact(name) is not None}
        return {'status': 'need_evidence' if missing else ('ready' if accepted else 'no_permitted_plan'),
                'missing_evidence': sorted(missing), 'accepted_plans': accepted,
                'possible_plans': possible, 'support_versions': support}

    def _session(self, sid):
        session = self.sessions.get(sid)
        if session is None:
            raise Denied('Unknown plan session.')
        if session['plan'].id not in {plan.id for plan in self.frontier()['accepted_plans']}:
            raise Denied('Current evidence no longer supports the plan.')
        return session

    def read_step(self, sid, node, fields, resource):
        self.read_refreshes += 1
        refresh_public_state(self)
        try:
            if resource != self.authority.resource:
                raise Denied('Cross-resource read.')
            session = self._session(sid)
            self._enabled(session, node)
            table_fields = dict(self.rows[session['plan'].nodes].steps)[node]
            missing = {field for field in table_fields
                       if self.disclosed.get(field) != self.authority.value_version(field)}
            if set(fields) != missing or len(fields) != len(missing):
                raise Denied('Requested fields differ from the table requirements.')
            values = self.authority.values_for_executor(missing)
            self.disclosed.update({field: self.authority.value_version(field) for field in values})
            self.metrics['raw_disclosure_deliveries'] += len(values)
            return values
        except Denied:
            self.metrics['rejected_reads'] += 1
            raise
