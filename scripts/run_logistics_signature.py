"""Check a new signature-authorization rule in both logistics planners."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from necessity_v2.core import Action, Authority, Policy, Registry
from necessity_v2.route_baseline import refresh_public_state
from necessity_v2.signature_rule import SignedContractVerifier, SignedRouteTable, migrate_contracts, migrate_routes
from scripts.run_logistics_composition import ARMS, dump
from scripts.run_logistics_dependency import (
    BOOKING, CONFIG, STATE_KEYS, STUDY as OLD_STUDY, DependentWorkflow,
    compile_route, frozen_bytes, known_cases,
)

STUDY = ROOT / 'logistics-signature-study'
SIGNATURE_FIELD = 'customer.signature_authorization_ref'
CONDITION = 'signature_required'


def read(name):
    return json.loads((STUDY / name).read_text())


def configured(rule):
    config = json.loads(CONFIG.read_text())
    original = [Action(row['id'], row['tool'], row['produces'], tuple(row.get('requires', ())),
                       tuple(row['fields']), tuple(tuple(g) for g in row.get('guards', ())))
                for row in config['contracts']]
    actions = migrate_contracts(original, rule)
    routes, fragments = migrate_routes(config['table_routes'], config['table_fragments'], rule)
    rows = [compile_route(route, fragments) for route in routes]
    return config, original, actions, routes, fragments, rows


class SignatureWorkflow(DependentWorkflow):
    def __init__(self, arm, case, rule):
        config, _, self.actions, _, _, self.rows = configured(rule)
        self.arm, self.case = arm, case
        fields = [*config['allowed_fields'], *rule['shared']['step']['fields']]
        values = {field: f'SYN-{case["id"]}-{field}' for field in fields}
        self.authority = Authority(case['id'], values, {CONDITION: False, **case['initial']},
                                   public_facts=(*STATE_KEYS, CONDITION))
        allowed = set(config['allowed_fields']) - set(case.get('withhold_fields', ()))
        if case.get('signature_authorized', False) and SIGNATURE_FIELD not in case.get('withhold_fields', ()):
            allowed.add(SIGNATURE_FIELD)
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
            verifier = SignedRouteTable(self.authority, self.actions, self.policy, remaining, self.rows)
        else:
            verifier = SignedContractVerifier(self.authority, Registry(self.actions), self.policy, remaining)
        if previous:
            verifier.disclosed.update(previous.disclosed)
            verifier.identity_receipt = previous.identity_receipt
            verifier.station_receipt = previous.station_receipt
            verifier.signature_receipt = previous.signature_receipt
            self.log('recover', remaining=list(remaining))
        self.verifier = verifier
        refresh_public_state(verifier)
        self.sid = None


def check_pair(case, rule):
    rows = [SignatureWorkflow(arm, case, rule).run() for arm in ARMS]
    for key in ('complete', 'goals', 'fields', 'read_attempts', 'denied_reads', 'confirmations', 'executions'):
        assert rows[0][key] == rows[1][key], (case['id'], key)
    return rows


def migrated_counts(before, after, key):
    old = {key(record): record for record in before}
    new = {key(record): record for record in after}
    return {'before': len(old), 'after': len(new), 'added': len(new.keys() - old.keys()),
            'removed': len(old.keys() - new.keys()),
            'modified': sum(new[name] != value for name, value in old.items() if name in new)}


def measurement(rule):
    config, original, actions, routes, fragments, _ = configured(rule)
    return {
        'shared_authored_records': len(rule['shared']),
        'contract_authored_selectors': len(rule['contract']),
        'route_table_authored_selectors': len(rule['route_table']),
        'contract_compiled_operations': migrated_counts(original, actions, lambda record: record.id),
        'route_table_compiled_rows': migrated_counts(config['table_routes'], routes, lambda record: record['step']),
        'route_table_compiled_fragments': migrated_counts(config['table_fragments'].items(),
                                                           fragments.items(), lambda record: record[0]),
        'migration_adapters': ['migrate_contracts', 'migrate_routes'],
        'shared_recovery_adapter': 'SignatureReceiptReuse',
    }


def verify_prior_freeze():
    assert json.loads((OLD_STUDY / 'freeze.json').read_text())['sha256'] == frozen_bytes()


def fingerprints(names):
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__), ROOT / 'necessity_v2/signature_rule.py',
                         *(STUDY / name for name in names)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'run'))
    args = parser.parse_args()
    verify_prior_freeze()
    rule = read('rule.json')
    names = ('rule.json', 'cases.json')
    freeze = STUDY / 'freeze.json'
    if args.phase == 'freeze':
        if freeze.exists():
            parser.error('Rule and cases already frozen.')
        dump(freeze, {'sha256': fingerprints(names), 'prior_experiment_frozen': True})
        return

    assert read('freeze.json')['sha256'] == fingerprints(names)
    old_cases = known_cases()
    for name in ('development-cases.json', 'cases.json'):
        old_cases.extend(json.loads((OLD_STUDY / name).read_text()))
    regression = []
    for case in old_cases:
        rows = check_pair(case, rule)
        for row in rows:
            assert SIGNATURE_FIELD not in row['fields']
        regression.extend(rows)
    results = [row for case in read('cases.json') for row in check_pair(case, rule)]
    dump(STUDY / 'results.json', {'model_calls': 0, 'configuration': measurement(rule),
                                 'regression': regression, 'new_cases': results})
    print(f'Passed {len(regression)} old regression runs and {len(results)} new runs.')


if __name__ == '__main__':
    main()
