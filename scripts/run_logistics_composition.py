"""Compare frozen single-goal recipes and contracts on scripted logistics cases."""
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

STUDY = ROOT / 'logistics-composition-study'
CONFIG = STUDY / 'single-goal-config.json'
FREEZE = STUDY / 'freeze.json'
POINT = 'pickup_point_changed'
TIME = 'pickup_time_changed'
ARMS = ('route_table', 'contract')
INPUTS = ('single-goal-config.json', 'necessity_v2/core.py', 'necessity_v2/route_baseline.py',
          'necessity_v2/composable_routes.py')
FEEDBACK = 'Refresh trusted state and replan remaining goals within the original authorization.'


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def fingerprint():
    return {name: hashlib.sha256((CONFIG if name == CONFIG.name else ROOT / name).read_bytes()).hexdigest()
            for name in INPUTS}


def conditions(items):
    return tuple((name, value) for name, value in items)


class Workflow:
    def __init__(self, arm, case):
        config = json.loads(CONFIG.read_text())
        self.case, self.arm = case, arm
        actions = config['contracts']
        self.actions = [Action(row['id'], row['tool'], row['produces'], tuple(row.get('requires', ())),
                               tuple(row['fields']), conditions(row.get('guards', ()))) for row in actions]
        self.rows = [RouteRow(frozenset({row['goal']}), row['root'],
                              tuple((step, tuple(fields)) for step, fields in row['steps'].items()),
                              conditions(row['conditions'])) for row in config['route_recipes']]
        values = {field: 'SYN-' + hashlib.sha256(f'{case["id"]}:{field}'.encode()).hexdigest()[:12]
                  for field in config['allowed_fields'] + ['parcel.unrelated_private_note']}
        statuses = case['initial']
        self.authority = Authority(case['id'], values, statuses, public_facts=statuses)
        allowed = set(config['allowed_fields']) - set(case.get('withhold_fields', ()))
        self.policy = Policy(frozenset(action.tool for action in self.actions), frozenset(allowed),
                             utility_ranks=tuple(config['preference'].items()), minimize_disclosure=False)
        self.approval_tools = set(config['confirmation_required'])
        self.committed, self.values, self.events = set(), {}, []
        self.confirmed = set()
        self.verifier = None
        self.start_remaining()

    def log(self, action, **details):
        self.events.append({'action': action, **details})

    def start_remaining(self):
        remaining = tuple(goal for goal in self.case['goals'] if goal not in self.committed)
        previous = self.verifier
        if self.arm == 'route_table':
            verifier = ComposableRouteTable(self.authority, self.actions, self.policy, remaining, self.rows)
        else:
            verifier = LogisticsIdentityVerifier(self.authority, Registry(self.actions), self.policy, remaining)
        if previous:
            verifier.disclosed.update(previous.disclosed)
            verifier.identity_receipt = previous.identity_receipt
            self.log('recover', remaining=list(remaining), feedback=FEEDBACK)
        self.verifier = verifier
        refresh_public_state(verifier)
        self.sid = None

    def propose(self, nodes):
        self.sid = self.verifier.propose(nodes)
        self.log('propose', nodes=sorted(nodes),
                 reused=sorted(self.verifier.sessions[self.sid]['artifacts']))

    def prepare(self, step):
        if self.arm == 'contract':
            grant = self.verifier.issue(self.sid, step)
            self.log('issue', step=step)
            return grant['grant']
        return None

    def read(self, step, grant):
        action = self.verifier.registry.actions[step]
        fields = tuple(f for f in action.fields if
                       self.verifier.disclosed.get(f) != self.authority.value_version(f))
        try:
            if self.arm == 'route_table':
                self.log('read_refresh', step=step)
                values = self.verifier.read_step(self.sid, step, fields, self.authority.resource)
            else:
                values = self.verifier.read(grant, fields, self.authority.resource)
        except Denied:
            self.log('denied_read', step=step, delivered=[], feedback=FEEDBACK)
            return False
        self.values.update(values)
        self.log('read', step=step, delivered=sorted(values))
        return True

    def confirm(self, step):
        session = self.verifier._session(self.sid)
        self.verifier._enabled(session, step)
        self.confirmed.add((self.sid, step))
        self.log('confirm', step=step)

    def execute(self, step):
        action = self.verifier.registry.actions[step]
        if action.produces in self.committed:
            raise Denied('Business effect already committed.')
        if action.tool in self.approval_tools and (self.sid, step) not in self.confirmed:
            raise Denied('Current step requires approval.')
        self.verifier.execute(self.sid, step, {f: self.values[f] for f in action.fields})
        if action.produces in self.case['goals']:
            self.committed.add(action.produces)
        self.log('execute', step=step, produced=action.produces)

    def perform(self, step):
        assert self.read(step, self.prepare(step))
        if self.verifier.registry.actions[step].tool in self.approval_tools:
            self.confirm(step)
        self.execute(step)

    def exercise(self):
        case = self.case
        self.propose(case['initial_plan'])
        for step in case['before_event']:
            self.perform(step)
        drift = case.get('drift')
        if drift:
            pending = drift['pending']
            ticket = self.prepare(pending)
            # Trigger at the same business boundary in both arms.
            assert TIME in self.committed
            self.authority.update_fact(drift['fact'], drift['value'])
            self.log('state_event', after_goal=TIME, fact=drift['fact'], value=drift['value'])
            assert not self.read(pending, ticket)
            self.start_remaining()
            if drift['new_plan']:
                self.propose(drift['new_plan'])
                for step in drift['after_recovery']:
                    self.perform(step)
            else:
                assert self.verifier.inspect()['status'] == 'no_permitted_plan'
                self.log('stop', reason='No route within original authorization.')
        counts = Counter(event['action'] for event in self.events)
        effects = Counter(e['produced'] for e in self.events
                          if e['action'] == 'execute' and e['produced'] in case['goals'])
        assert self.committed == set(case['expected_goals'])
        assert set(self.values) == set(case['expected_fields'])
        assert all(count == 1 for count in effects.values())
        return {'case': case['id'], 'arm': self.arm, 'complete': self.committed == set(case['goals']),
                'goal_effects': dict(effects), 'fields': sorted(self.values),
                'confirmations': counts['confirm'], 'read_attempts': counts['read'] + counts['denied_read'],
                'denied_reads': counts['denied_read'], 'read_state_refreshes': counts['read_refresh'],
                'read_justifications': counts['issue'], 'recoveries': counts['recover'],
                'identity_executions': sum(e['action'] == 'execute' and e['step'] == 'identity'
                                           for e in self.events), 'events': self.events}


def singles():
    initial = {'locker_available': True, 'desk_available': True}
    results = []
    for goal, step, field in ((POINT, 'locker', 'parcel.locker_ref'),
                              (TIME, 'slot', 'parcel.slot_ref')):
        case = {'id': goal, 'goals': [goal], 'initial': initial, 'initial_plan': ['identity', step],
                'before_event': ['identity', step], 'expected_goals': [goal],
                'expected_fields': ['customer.identity_ref', field]}
        results.extend(Workflow(arm, case).exercise() for arm in ARMS)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'compare'))
    args = parser.parse_args()
    if args.phase == 'freeze':
        if FREEZE.exists():
            raise SystemExit('Configuration is already frozen.')
        results = singles()
        dump(STUDY / 'single-goal-results.json', results)
        dump(FREEZE, {'sha256': fingerprint(), 'single_goal_passes': len(results)})
        print('Froze single-goal configuration after four passing runs.')
        return
    frozen = json.loads(FREEZE.read_text())
    assert frozen['sha256'] == fingerprint()
    cases = json.loads((STUDY / 'combination-cases.json').read_text())
    results = []
    for case in cases:
        rows = [Workflow(arm, case).exercise() for arm in ARMS]
        for key in ('complete', 'fields', 'confirmations', 'read_attempts', 'denied_reads',
                    'recoveries', 'goal_effects', 'identity_executions'):
            assert rows[0][key] == rows[1][key], (case['id'], key)
        results.extend(rows)
    dump(STUDY / 'results.json', {'model_calls': 0, 'frozen_config_verified': True,
                                 'configuration_changes': {arm: 0 for arm in ARMS},
                                 'case_file_sha256': hashlib.sha256((STUDY / 'combination-cases.json').read_bytes()).hexdigest(),
                                 'results': results})
    print(f'Checked {len(results)} scripted combined runs with zero configuration changes.')


if __name__ == '__main__':
    main()
