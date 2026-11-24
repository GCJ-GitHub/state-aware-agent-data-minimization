"""Derive disclosure requirements from alternative tool plans and trusted evidence.

The small exhaustive solver is a reference implementation, NOT a novel optimal
online acquisition algorithm or a hardened production reference monitor.
"""
from dataclasses import dataclass
from itertools import product
import hashlib
import hmac
import json
import secrets


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class Denied(Exception):
    pass


@dataclass(frozen=True)
class Action:
    id: str
    tool: str
    produces: str
    requires: tuple = ()
    fields: tuple = ()
    guards: tuple = ()


@dataclass(frozen=True)
class Plan:
    nodes: frozenset
    roots: frozenset
    fields: frozenset
    guards: frozenset

    @property
    def id(self):
        return hashlib.sha256(canonical(sorted(self.nodes)).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class Policy:
    allowed_tools: frozenset
    allowed_fields: frozenset
    # Rank is an explicit user utility ordering, not a privacy label.
    utility_ranks: tuple = ()
    minimize_disclosure: bool = True
    field_costs: tuple = ()


class Authority:
    """Trusted connector stand-in. The model must not have this Python object.

    Signing supports testable origin/freshness checks, not a novelty claim.
    Private probes expose only registered predicates, never arbitrary queries.
    """
    def __init__(self, resource, values, facts, public_facts=(), probes=None):
        self.resource = resource
        self._key = secrets.token_bytes(32)
        self._values = dict(values)
        self._versions = {f: 1 for f in values}
        self._facts = {f: (bool(v), 1) for f, v in facts.items()}
        self.public = frozenset(public_facts)
        # name -> (output fact, raw dependency fields, pure trusted function)
        self.probes = probes or {}
        self.probe_cache = {}
        self.metrics = {'private_probe_calls': 0, 'private_probe_raw_reads': 0,
                        'predicate_results_released': 0, 'public_receipts': 0}

    def fact_version(self, name):
        return self._facts[name][1] if name in self._facts else None

    def value_version(self, name):
        return self._versions[name]

    def _receipt(self, name):
        value, version = self._facts[name]
        payload = {'resource': self.resource, 'fact': name, 'value': value,
                   'version': version, 'issuer': 'trusted_connector'}
        payload['mac'] = hmac.new(self._key, canonical(payload).encode(), hashlib.sha256).hexdigest()
        return payload

    def verify(self, receipt):
        payload = {k: v for k, v in receipt.items() if k != 'mac'}
        if set(payload) != {'resource', 'fact', 'value', 'version', 'issuer'}:
            return False
        expected = hmac.new(self._key, canonical(payload).encode(), hashlib.sha256).hexdigest()
        return (hmac.compare_digest(expected, receipt.get('mac', ''))
                and payload['resource'] == self.resource
                and payload['issuer'] == 'trusted_connector'
                and type(payload['value']) is bool
                and self.fact_version(payload['fact']) == payload['version'])

    def public_receipt(self, name):
        if name not in self.public:
            raise Denied('Private fact requires its authorized predicate tool.')
        self.metrics['public_receipts'] += 1
        return self._receipt(name)

    def probe(self, name):
        if name not in self.probes:
            raise Denied('Only a registered fixed predicate is allowed.')
        fact, fields, function = self.probes[name]
        self.metrics['private_probe_calls'] += 1
        stamp = tuple((f, self.value_version(f)) for f in fields)
        key = name, stamp
        if key not in self.probe_cache:
            result = bool(function({f: self._values[f] for f in fields}))
            old = self._facts.get(fact)
            version = 1 if old is None else old[1] + 1
            self._facts[fact] = result, version
            self.metrics['private_probe_raw_reads'] += len(fields)
            self.metrics['predicate_results_released'] += 1
            self.probe_cache[key] = self._receipt(fact)
        # A repeated predicate cannot vary thresholds or read another resource.
        cached = self.probe_cache[key]
        if not self.verify(cached):
            raise Denied('Predicate evidence changed; refresh its trusted input.')
        return dict(cached)

    def update_fact(self, name, value):
        """Trusted service event, never an agent-facing tool."""
        _, version = self._facts[name]
        self._facts[name] = bool(value), version + 1

    def update_value(self, name, value):
        """Invalidate derived evidence whenever a raw dependency changes."""
        self._values[name] = value
        self._versions[name] += 1
        for fact, fields, _ in self.probes.values():
            if name in fields and fact in self._facts:
                current, version = self._facts[fact]
                self._facts[fact] = current, version + 1

    def values_for_executor(self, fields):
        return {f: self._values[f] for f in fields}


class Registry:
    def __init__(self, actions):
        self.actions = {a.id: a for a in actions}
        if len(self.actions) != len(actions):
            raise ValueError('Action identifiers must be unique.')
        self.producers = {}
        for action in actions:
            self.producers.setdefault(action.produces, []).append(action)

    def _plans_for(self, artifact, trail=()):
        if artifact in trail:
            raise ValueError('Cyclic contract dependencies are unsupported.')
        found = []
        for action in self.producers.get(artifact, []):
            dependencies = [self._plans_for(dep, trail + (artifact,)) for dep in action.requires]
            if any(not possibilities for possibilities in dependencies):
                continue
            for children in product(*dependencies):
                nodes = frozenset({action.id}).union(*(p.nodes for p in children))
                fields = frozenset(action.fields).union(*(p.fields for p in children))
                guards = frozenset(action.guards).union(*(p.guards for p in children))
                if any((name, not expected) in guards for name, expected in guards):
                    continue
                # One artifact may not have conflicting producers in a plan.
                outputs = [self.actions[n].produces for n in nodes]
                if len(outputs) != len(set(outputs)):
                    continue
                found.append(Plan(nodes, frozenset({action.id}), fields, guards))
        return list({p.id: p for p in found}.values())

    def plans(self, goals):
        choices = [self._plans_for(goal) for goal in goals]
        if any(not options for options in choices):
            return []
        result = {}
        for alternatives in product(*choices):
            nodes = frozenset().union(*(p.nodes for p in alternatives))
            outputs = [self.actions[n].produces for n in nodes]
            if len(outputs) != len(set(outputs)):
                continue
            guards = frozenset().union(*(p.guards for p in alternatives))
            if any((name, not expected) in guards for name, expected in guards):
                continue
            plan = Plan(nodes, frozenset().union(*(p.roots for p in alternatives)),
                        frozenset().union(*(p.fields for p in alternatives)), guards)
            result[plan.id] = plan
        return sorted(result.values(), key=lambda p: p.id)


class Verifier:
    def __init__(self, authority, registry, policy, goals):
        self.authority, self.registry, self.policy = authority, registry, policy
        self.goals = tuple(goals)
        self.receipts = {}
        self.grants = {}
        self.sessions = {}
        self.disclosed = {}
        self.events = []
        self.committed_goals = set()
        self.metrics = {'raw_disclosure_deliveries': 0, 'rejected_reads': 0,
                        'rejected_executions': 0}

    def accept_evidence(self, receipt):
        if not self.authority.verify(receipt):
            raise Denied('Untrusted, cross-resource or stale evidence.')
        self.receipts[receipt['fact']] = dict(receipt)

    def fact(self, name):
        receipt = self.receipts.get(name)
        return receipt['value'] if receipt and self.authority.verify(receipt) else None

    def score(self, plan):
        ranks = dict(self.policy.utility_ranks)
        weights = dict(self.policy.field_costs)
        utility_penalty = sum(ranks.get(self.registry.actions[n].tool, 0) for n in plan.roots)
        disclosure = sum(weights.get(f, 1) for f in plan.fields)
        return utility_penalty, disclosure if self.policy.minimize_disclosure else 0

    def frontier(self):
        structural = self.registry.plans(self.goals)
        permitted = [p for p in structural if p.fields <= self.policy.allowed_fields and
                     all(self.registry.actions[n].tool in self.policy.allowed_tools for n in p.nodes)]
        possible, proven = [], []
        for plan in permitted:
            states = [(self.fact(name), expected) for name, expected in plan.guards]
            if any(actual is not None and actual != expected for actual, expected in states):
                continue
            possible.append(plan)
            if all(actual is not None for actual, _ in states):
                proven.append(plan)
        best = min((self.score(p) for p in proven), default=None)
        blockers = [p for p in possible if (best is None or self.score(p) < best) and
                    any(self.fact(name) is None for name, _ in p.guards)]
        missing = sorted({name for p in blockers for name, _ in p.guards if self.fact(name) is None})
        accepted = [] if blockers else [p for p in proven if self.score(p) == best]
        # Include negative evidence excluding alternatives. Binding only the chosen
        # branch would miss a newly feasible higher-priority/lower-cost branch.
        relevant_facts = {name for p in permitted for name, _ in p.guards}
        support = {name: self.receipts[name]['version'] for name in relevant_facts
                   if self.fact(name) is not None}
        return {'status': 'need_evidence' if blockers else ('ready' if accepted else 'no_permitted_plan'),
                'missing_evidence': missing, 'accepted_plans': accepted,
                'possible_plans': possible, 'support_versions': support}

    def propose(self, nodes):
        """An agent proposes a plan; its own need/permission claims carry no authority."""
        if self.committed_goals:
            raise Denied('Successful effects already exist; cross-plan continuation is not implemented.')
        nodes = frozenset(nodes)
        front = self.frontier()
        matching = [p for p in front['accepted_plans'] if p.nodes == nodes]
        if not matching:
            raise Denied('Unproven, unauthorized, nonoptimal or extraneous plan; ' + front['status'])
        plan = matching[0]
        sid = 'session-' + secrets.token_hex(12)
        self.sessions[sid] = {'plan': plan, 'support': front['support_versions'],
                              'done': set(), 'artifacts': set()}
        return sid

    def _session(self, sid):
        if sid not in self.sessions:
            raise Denied('Unknown plan session.')
        session = self.sessions[sid]
        for fact, version in session['support'].items():
            if self.authority.fact_version(fact) != version:
                raise Denied('Supporting evidence changed; re-evaluate the plan.')
        # Completeness of support is checked again, including newly needed facts.
        if session['plan'].id not in {p.id for p in self.frontier()['accepted_plans']}:
            raise Denied('Current evidence no longer supports the plan.')
        return session

    def _enabled(self, session, node):
        if node not in session['plan'].nodes or node in session['done']:
            raise Denied('Action not pending in the verified plan.')
        action = self.registry.actions[node]
        if not set(action.requires) <= session['artifacts']:
            raise Denied('Action dependencies are not completed.')
        return action

    def issue(self, sid, node):
        session = self._session(sid)
        action = self._enabled(session, node)
        fields = frozenset(f for f in action.fields
                           if self.disclosed.get(f) != self.authority.value_version(f))
        gid = 'grant-' + secrets.token_hex(12)
        self.grants[gid] = {'session': sid, 'node': node, 'resource': self.authority.resource,
                            'fields': fields, 'versions': {f: self.authority.value_version(f) for f in fields},
                            'used': False}
        return {'grant': gid, 'fields': sorted(fields), 'action': node,
                'resource': self.authority.resource, 'evidence_versions': dict(session['support'])}

    def read(self, gid, fields, resource):
        try:
            grant = self.grants.get(gid)
            if not grant or grant['used'] or resource != grant['resource']:
                raise Denied('Unknown, consumed or cross-resource grant.')
            session = self._session(grant['session'])
            self._enabled(session, grant['node'])
            if frozenset(fields) != grant['fields'] or len(fields) != len(set(fields)):
                raise Denied('Requested fields differ from the next action requirements.')
            if any(self.authority.value_version(f) != v for f, v in grant['versions'].items()):
                raise Denied('Data changed after issuance; request a fresh grant.')
            grant['used'] = True
            self.disclosed.update(grant['versions'])
            values = self.authority.values_for_executor(grant['fields'])
            self.metrics['raw_disclosure_deliveries'] += len(values)
            self.events.append({'kind': 'read', 'node': grant['node'], 'fields': sorted(values)})
            return values
        except Denied:
            self.metrics['rejected_reads'] += 1
            raise

    def execute(self, sid, node, values):
        """Pure simulated execution. No real financial or service effects."""
        try:
            session = self._session(sid)
            action = self._enabled(session, node)
            if any(self.disclosed.get(f) != self.authority.value_version(f) for f in action.fields):
                raise Denied('Required current values have not been obtained.')
            if values != self.authority.values_for_executor(action.fields):
                raise Denied('Payload has extra, incorrect or stale values.')
            session['done'].add(node)
            session['artifacts'].add(action.produces)
            if action.produces in self.goals:
                self.committed_goals.add(action.produces)
            self.events.append({'kind': 'execute', 'node': node, 'fields': sorted(values)})
            return {'produced': action.produces, 'complete': set(self.goals) <= session['artifacts']}
        except Denied:
            self.metrics['rejected_executions'] += 1
            raise

    def inspect(self):
        """Agent-facing metadata; deliberately no hidden fact values or vault values."""
        front = self.frontier()
        return {'status': front['status'], 'missing_evidence': front['missing_evidence'],
                'plans': [{'id': p.id, 'nodes': sorted(p.nodes), 'fields': sorted(p.fields),
                           'utility_and_disclosure_cost': list(self.score(p))} for p in front['accepted_plans']]}
