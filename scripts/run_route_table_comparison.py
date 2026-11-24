"""Drive matched synthetic scenarios and write exact observations with no model calls."""
import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from necessity_v2.core import Denied, Registry
from necessity_v2.route_baseline import RefreshedRouteTable, ReusableIdentityVerifier, RouteRow, refresh_public_state
from necessity_v2.scenarios import refund


REFUND = frozenset({'refund_done'})
REFUND_AND_QUOTES = REFUND | {'quotes_reported'}
WALLET = ('wallet', ('order.wallet_ref',))
IDENTITY = ('identity', ('customer.identity_ref',))
BANK = ('bank', ('order.account_ref',))
BANK_INPUTS = ('order.account_ref', 'customer.owner_ref')
QUOTES = ('quotes', ('private.wallet_fee', 'private.bank_fee'))
WALLET_CONDITIONS = (('wallet_available', True), ('wallet_eligible', True))
LOW_CONDITIONS = (('bank_available', True), ('high_value', False))
HIGH_CONDITIONS = (('bank_available', True), ('high_value', True))

# Authored independently of Registry.plans. Identity reuse uses a shared verified receipt.
REFUND_ROWS = (
    RouteRow(REFUND, 'wallet', (WALLET,), WALLET_CONDITIONS),
    RouteRow(REFUND, 'bank', (('bank_verify_low', BANK_INPUTS), BANK), LOW_CONDITIONS),
    RouteRow(REFUND, 'bank', (IDENTITY, ('bank_verify_high', BANK_INPUTS), BANK), HIGH_CONDITIONS),
    RouteRow(REFUND_AND_QUOTES, 'wallet', (WALLET, QUOTES), WALLET_CONDITIONS),
    RouteRow(REFUND_AND_QUOTES, 'bank', (('bank_verify_low', BANK_INPUTS), BANK, QUOTES), LOW_CONDITIONS),
    RouteRow(REFUND_AND_QUOTES, 'bank', (IDENTITY, ('bank_verify_high', BANK_INPUTS), BANK, QUOTES), HIGH_CONDITIONS),
)
SHARED_IDENTITY_ROWS = (
    replace(REFUND_ROWS[0], steps=(IDENTITY, WALLET)),
    REFUND_ROWS[1],
    REFUND_ROWS[2],
)
CASES = ('preferred_route_restored', 'reuse_identity_after_replan', 'exact_quotes_required')


class Walkthrough:
    def __init__(self, case, arm, *, combined_goals=False, rows=None):
        self.case, self.arm = case, arm
        exact = case == 'exact_quotes_required' or combined_goals
        shared = case == 'reuse_identity_after_replan'
        original = refund(wallet=exact, high=shared, exact_quotes=exact, resource=case, privacy_first=False)
        actions = list(original.registry.actions.values())
        if shared:
            actions = [replace(action, requires=('identity_verified',)) if action.id == 'wallet' else action
                       for action in actions]
        policy = replace(original.policy, utility_ranks=(('wallet_refund', 0), ('bank_refund', 1)),
                         allowed_fields=original.policy.allowed_fields - {'private.wallet_days'})
        args = (original.authority, Registry(actions), policy, original.goals)
        self.verifier = (RefreshedRouteTable(*args, rows if rows is not None else
                                             (SHARED_IDENTITY_ROWS if shared else REFUND_ROWS))
                         if arm == 'route_table' else ReusableIdentityVerifier(*args))
        self.events = []
        self.values = {}
        self.confirmed = set()
        refresh_public_state(self.verifier)

    def log(self, action, **details):
        self.events.append({'action': action, **details})

    def propose(self, nodes):
        self.sid = self.verifier.propose(nodes)
        self.log('propose', nodes=sorted(nodes),
                 reused=sorted(self.verifier.sessions[self.sid]['artifacts']))

    def prepare(self, node, fields):
        if self.arm == 'contract':
            grant = self.verifier.issue(self.sid, node)
            self.log('issue_read', step=node, fields=grant['fields'])
            return grant['grant']
        return None

    def read(self, node, fields, grant):
        try:
            verifier = self.verifier
            resource = verifier.authority.resource
            if self.arm == 'route_table':
                values = verifier.read_step(self.sid, node, fields, resource)
            else:
                values = verifier.read(grant, fields, resource)
        except Denied:
            self.log('read_denied', step=node, fields=list(fields), delivered={},
                     feedback='Refresh trusted state, then propose the currently preferred plan.')
            return False
        self.values.update(values)
        self.log('read', step=node, delivered=values)
        return True

    def confirm(self, node):
        session = self.verifier._session(self.sid)
        self.verifier._enabled(session, node)
        self.confirmed.add((self.sid, node))
        self.log('confirm', step=node, approved=True)

    def execute(self, node, fields):
        if node in ('wallet', 'bank') and (self.sid, node) not in self.confirmed:
            raise Denied('Simulated approval is required for refund execution.')
        result = self.verifier.execute(self.sid, node, {field: self.values[field] for field in fields})
        self.log('execute', step=node, **result)
        if node == 'quotes':
            self.log('authorized_report', values={field: self.values[field] for field in fields})

    def step(self, node, fields):
        grant = self.prepare(node, fields)
        assert self.read(node, fields, grant)
        if node in ('wallet', 'bank'):
            self.confirm(node)
        self.execute(node, fields)

    def run(self):
        if self.case == 'exact_quotes_required':
            self.propose(('wallet', 'quotes'))
            self.step(*QUOTES)
            self.step(*WALLET)
        else:
            shared = self.case == 'reuse_identity_after_replan'
            node = 'bank_verify_high' if shared else 'bank_verify_low'
            self.propose(('identity', node, 'bank') if shared else (node, 'bank'))
            if shared:
                self.step(*IDENTITY)
            grant = self.prepare(node, BANK_INPUTS)
            # A scheduled service event at a shared workflow boundary. No tool induces it.
            self.verifier.authority.update_fact('wallet_available', True)
            self.log('state_event', at='before_first_bank_account_delivery', wallet_available=True)
            assert not self.read(node, BANK_INPUTS, grant)
            refresh_public_state(self.verifier)
            self.log('recovery_refresh')
            self.propose(('identity', 'wallet') if shared else ('wallet',))
            self.step(*WALLET)
        complete = set(self.verifier.goals) == self.verifier.committed_goals
        counts = Counter(event['action'] for event in self.events)
        result = {'case': self.case, 'arm': self.arm, 'complete': complete,
                  'delivered_fields': sorted(self.values), 'confirmations': counts['confirm'],
                  'denied_reads': counts['read_denied'], 'read_attempts': counts['read'] + counts['read_denied'],
                  'read_justification_operations': counts['issue_read'],
                  'read_state_refreshes': getattr(self.verifier, 'read_refreshes', 0),
                  'recovery_refreshes': counts['recovery_refresh'],
                  'identity_executions': sum(e['action'] == 'execute' and e['step'] == 'identity' for e in self.events),
                  'events': self.events}
        assert complete and result['confirmations'] == 1
        return result


def check_configuration_reuse():
    """Apply an existing exact-quote goal to the workflow with shared identity."""
    case = 'reuse_identity_after_replan'
    baseline_before = Walkthrough(case, 'route_table', combined_goals=True)
    contract = Walkthrough(case, 'contract', combined_goals=True)
    plan = ('identity', 'wallet', 'quotes')
    before = baseline_before.verifier.inspect()['status']
    assert before == 'no_permitted_plan'
    contract.propose(plan)
    for node, fields in (IDENTITY, QUOTES, WALLET):
        contract.step(node, fields)
    assert set(contract.verifier.goals) == contract.verifier.committed_goals

    # Register every route in the composed workflow, including both fallbacks.
    additional_rows = tuple(replace(row, goals=REFUND_AND_QUOTES, steps=row.steps + (QUOTES,))
                            for row in SHARED_IDENTITY_ROWS)
    baseline = Walkthrough(case, 'route_table', combined_goals=True,
                           rows=SHARED_IDENTITY_ROWS + additional_rows)
    baseline.propose(plan)
    for node, fields in (IDENTITY, QUOTES, WALLET):
        baseline.step(node, fields)
    assert set(baseline.verifier.goals) == baseline.verifier.committed_goals
    assert baseline.events[-1] == contract.events[-1] and baseline.values == contract.values
    return {'before_table_registration': before, 'added_route_rows': len(additional_rows),
            'added_tool_contracts': 0, 'added_contract_arm_route_rows': 0,
            'business_goals_completed_by_both_after_registration': sorted(contract.verifier.committed_goals),
            'delivered_fields': sorted(contract.values),
            'scope': 'Configuration demonstration for this explicit table representation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    results = [Walkthrough(case, arm).run() for case in CASES for arm in ('route_table', 'contract')]
    for baseline, contract in zip(results[::2], results[1::2]):
        for key in ('complete', 'delivered_fields', 'confirmations', 'denied_reads', 'read_attempts',
                    'recovery_refreshes', 'identity_executions'):
            assert baseline[key] == contract[key], (baseline['case'], key)
        assert not set(BANK_INPUTS) & set(baseline['delivered_fields'])
        if baseline['case'] == 'reuse_identity_after_replan':
            for row in (baseline, contract):
                assert row['identity_executions'] == 1
                assert [e for e in row['events'] if e['action'] == 'propose'][-1]['reused'] == ['identity_verified']
        if baseline['case'] == 'exact_quotes_required':
            for row in (baseline, contract):
                assert [e['values'] for e in row['events'] if e['action'] == 'authorized_report'] == [
                    {'private.wallet_fee': 2, 'private.bank_fee': 4}]
    output = json.dumps({'mode': 'offline_scripted_walkthrough', 'model_calls': 0, 'results': results,
                         'configuration_check': check_configuration_reuse()}, indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output)
    else:
        print(output, end='')


if __name__ == '__main__':
    main()
