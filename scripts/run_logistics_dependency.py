"""Freeze known workflows, then compare interdependent synthetic logistics goals."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from necessity_v2.composable_routes import ComposableRouteTable, LogisticsIdentityVerifier
from necessity_v2.core import Action, Authority, Denied, Policy, Registry
from necessity_v2.route_baseline import RouteRow, refresh_public_state
from scripts.run_logistics_composition import ARMS, Workflow, dump

STUDY = ROOT / 'logistics-dependent-study'
CONFIG = STUDY / 'config.json'
POINT = 'pickup_point_changed'
BOOKING = 'appointment_resolved'
STATE_KEYS = ('assessment_ready', 'original_slot_valid', 'enhanced_check',
              'primary_available', 'backup_available')


def frozen_bytes():
    paths = [CONFIG, Path(__file__), ROOT / 'scripts/run_logistics_composition.py']
    paths.extend(ROOT / 'necessity_v2' / name
                 for name in ('core.py', 'route_baseline.py', 'composable_routes.py'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def compile_route(route, fragments):
    """Expand authored recipe fragments independently of the tool dependency registry."""
    steps, predicates = {}, {}

    def visit(item, ancestors):
        for name in item.get('include', ()):
            if name in ancestors:
                raise ValueError(f'Cyclic recipe fragment: {name}')
            visit(fragments[name], ancestors | {name})
        if 'step' in item:
            step, fields = item['step'], tuple(item['fields'])
            if step in steps and steps[step] != fields:
                raise ValueError(f'Conflicting fields for {step}')
            steps[step] = fields
        for key, value in item.get('when', {}).items():
            if key in predicates and predicates[key] != value:
                raise ValueError(f'Conflicting predicates for {key}')
            predicates[key] = value

    visit(route, set())
    return RouteRow(frozenset({route['goal']}), route['step'], tuple(steps.items()),
                    tuple(predicates.items()))


def state(*, ready=True, valid=False, enhanced=False, primary=True, backup=True):
    return dict(zip(STATE_KEYS, (ready, valid, enhanced, primary, backup)))


class StationReceiptReuse:
    """Reuse a station check only for the same station and verified inputs."""

    station_receipt = None

    def station_stamp(self):
        return (self.authority.resource, 'pickup_station_verification', self.policy,
                self.identity_stamp(),
                self.authority.value_version('parcel.station_ref'),
                self.authority.value_version('customer.station_access_ref'),
                self.authority.fact_version('assessment_ready'),
                self.authority.fact_version('enhanced_check'))

    def propose(self, nodes):
        sid = super().propose(nodes)
        session = self.sessions[sid]
        if ('station_check' in nodes and 'identity_verified' in session['artifacts']
                and self.station_receipt == self.station_stamp()):
            session['done'].add('station_check')
            session['artifacts'].add('station_verified')
        return sid

    def _enabled(self, session, node):
        action = super()._enabled(session, node)
        if 'station_verified' in action.requires and self.station_receipt != self.station_stamp():
            raise Denied('Station verification is stale.')
        return action

    def execute(self, sid, node, values):
        result = super().execute(sid, node, values)
        if node == 'station_check':
            self.station_receipt = self.station_stamp()
        return result


class StationContractVerifier(StationReceiptReuse, LogisticsIdentityVerifier):
    pass


class StationRouteTable(StationReceiptReuse, ComposableRouteTable):
    pass


class DependentWorkflow(Workflow):
    def __init__(self, arm, case):
        config = json.loads(CONFIG.read_text())
        self.case, self.arm = case, arm
        self.actions = [Action(row['id'], row['tool'], row['produces'], tuple(row.get('requires', ())),
                               tuple(row['fields']), tuple(tuple(g) for g in row.get('guards', ())))
                        for row in config['contracts']]
        self.rows = [compile_route(route, config['table_fragments']) for route in config['table_routes']]
        values = {field: f'SYN-{case["id"]}-{field}' for field in config['allowed_fields']}
        self.authority = Authority(case['id'], values, case['initial'], public_facts=STATE_KEYS)
        allowed = set(config['allowed_fields']) - set(case.get('withhold_fields', ()))
        self.policy = Policy(frozenset(action.tool for action in self.actions), frozenset(allowed),
                             utility_ranks=tuple(config['preferences'].items()), minimize_disclosure=False)
        self.approval_tools = set(config['confirmation_tools'])
        self.committed, self.values, self.events, self.confirmed = set(), {}, [], set()
        self.verifier = None
        self.start_remaining()

    def start_remaining(self, phase_goals=None):
        goals = self.case['goals'] if phase_goals is None else phase_goals
        remaining = tuple(goal for goal in goals if goal not in self.committed)
        previous = self.verifier
        if self.arm == 'route_table':
            verifier = StationRouteTable(self.authority, self.actions, self.policy, remaining, self.rows)
        else:
            verifier = StationContractVerifier(self.authority, Registry(self.actions), self.policy, remaining)
        if previous:
            verifier.disclosed.update(previous.disclosed)
            verifier.identity_receipt = previous.identity_receipt
            verifier.station_receipt = previous.station_receipt
            self.log('recover', remaining=list(remaining))
        self.verifier = verifier
        refresh_public_state(verifier)
        self.sid = None

    def apply_state(self, updates, cause):
        for name, value in updates.items():
            self.authority.update_fact(name, value)
        self.log('state_event', cause=cause, updates=updates)

    def propose_expected(self, nodes):
        actual = [plan['nodes'] for plan in self.verifier.inspect()['plans']]
        assert actual == [sorted(nodes)], (self.case['id'], self.arm, actual, nodes)
        self.propose(nodes)

    def perform_step(self, node):
        if node in self.verifier.sessions[self.sid]['done']:
            self.log('reuse_step', step=node)
            return
        if self.verifier.registry.actions[node].fields:
            self.perform(node)
        else:
            self.execute(node)

    def run(self):
        case = self.case
        if POINT in case['goals']:
            # Location changes the appointment evaluation. Before the move, only
            # the phase's point goal is actionable under the common phase rule.
            assert set(case['goals']) == {POINT} or not self.authority.public_receipt('assessment_ready')['value']
            if BOOKING in case['goals']:
                assert self.verifier.inspect()['status'] == 'no_permitted_plan'
                self.start_remaining([POINT])
            self.propose_expected(['identity', 'move'])
            self.perform_step('identity')
            self.perform_step('move')
            if BOOKING in case['goals']:
                self.apply_state(case['after_move'], 'station_changed')
                self.start_remaining()
        if BOOKING in case['goals']:
            for node in case.get('verify_before_drift', ()):
                # Execute the common verification in the initial chosen plan.
                assert node in case['booking_plan']
            plan = case['booking_plan']
            if plan:
                self.propose_expected(plan)
            else:
                assert self.verifier.inspect()['status'] == 'no_permitted_plan'
                self.log('stop', reason='No booking route within original authorization.')
            for node in case.get('verify_before_drift', ()):
                if node == 'identity' and POINT in self.committed:
                    continue
                self.perform_step(node)
            if 'drift' in case:
                drift = case['drift']
                grant = self.prepare(drift['old_step'])
                self.apply_state(drift['updates'], 'before_slot_delivery')
                assert not self.read(drift['old_step'], grant)
                self.start_remaining()
                self.propose_expected(drift['new_plan'])
            for node in case['finish']:
                self.perform_step(node)

        counts = Counter(event['action'] for event in self.events)
        executions = Counter(event['step'] for event in self.events if event['action'] == 'execute')
        assert self.committed == set(case['expected_goals'])
        assert set(self.values) == set(case['expected_fields'])
        assert executions == case['expected_executions'], (case['id'], self.arm, executions)
        assert counts['confirm'] == case['expected_confirmations']
        assert counts['denied_read'] == int('drift' in case)
        return {'case': case['id'], 'arm': self.arm, 'complete': self.committed == set(case['goals']),
                'goals': sorted(self.committed), 'fields': sorted(self.values),
                'read_attempts': counts['read'] + counts['denied_read'], 'denied_reads': counts['denied_read'],
                'confirmations': counts['confirm'], 'executions': dict(executions),
                'read_refreshes': counts['read_refresh'], 'justifications': counts['issue'],
                'events': self.events}


def known_cases():
    return [
        {'id': 'known_move', 'goals': [POINT], 'initial': state(), 'expected_goals': [POINT],
         'expected_fields': ['customer.identity_ref', 'parcel.station_ref'],
         'expected_executions': {'identity': 1, 'move': 1}, 'expected_confirmations': 1},
        {'id': 'known_retain', 'goals': [BOOKING], 'initial': state(valid=True),
         'booking_plan': ['retain'], 'finish': ['retain'], 'expected_goals': [BOOKING],
         'expected_fields': [], 'expected_executions': {'retain': 1}, 'expected_confirmations': 0},
        {'id': 'known_enhanced_backup', 'goals': [BOOKING], 'initial': state(enhanced=True, primary=False),
         'booking_plan': ['identity', 'station_check', 'backup_checked'],
         'finish': ['identity', 'station_check', 'backup_checked'], 'expected_goals': [BOOKING],
         'expected_fields': ['customer.identity_ref', 'customer.station_access_ref', 'parcel.backup_slot_ref'],
         'expected_executions': {'identity': 1, 'station_check': 1, 'backup_checked': 1},
         'expected_confirmations': 1},
    ]


def compare(cases):
    results = []
    for case in cases:
        pair = [DependentWorkflow(arm, case).run() for arm in ARMS]
        for key in ('complete', 'goals', 'fields', 'read_attempts', 'denied_reads', 'confirmations', 'executions'):
            assert pair[0][key] == pair[1][key], (case['id'], key)
        results.extend(pair)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'compare', 'develop'))
    args = parser.parse_args()
    if args.phase == 'develop':
        cases = json.loads((STUDY / 'development-cases.json').read_text())
        dump(STUDY / 'development-results.json', compare(cases))
        return
    freeze = STUDY / 'freeze.json'
    if args.phase == 'freeze':
        if freeze.exists() or (STUDY / 'cases.json').exists():
            parser.error('Freeze must precede new-case creation.')
        results = compare(known_cases())
        dump(STUDY / 'known-results.json', results)
        dump(freeze, {'sha256': frozen_bytes(), 'known_runs': len(results)})
        print(f'Froze configuration after {len(results)} passing known runs.')
        return

    assert json.loads(freeze.read_text())['sha256'] == frozen_bytes()
    path = STUDY / 'cases.json'
    results = compare(json.loads(path.read_text()))
    dump(STUDY / 'results.json', {'model_calls': 0, 'configuration_changes': dict.fromkeys(ARMS, 0),
                                 'case_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'frozen_inputs_verified': True, 'results': results})
    print(f'Checked {len(results)} new runs under frozen configuration.')


if __name__ == '__main__':
    main()
