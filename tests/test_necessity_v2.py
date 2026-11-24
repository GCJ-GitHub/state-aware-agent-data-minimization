"""Prototype correctness and fault injection; no LLM/API is called."""
import copy
import itertools
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from necessity_v2.core import Authority, Denied, Policy, Registry, Verifier
from necessity_v2.scenarios import appointments, delivery, refund, scripted_complete, two_private_checks
from necessity_v2.acquire import Query, recommend


def best(verifier):
    plans = verifier.frontier()['accepted_plans']
    assert plans
    return plans[0]


class NecessityControls(unittest.TestCase):
    def test_query_order_oracle_uses_prior_for_order_not_permission(self):
        v = two_private_checks()
        queries = (Query('check_fee', 'wallet_fee_ok'), Query('check_speed', 'wallet_speed_ok'))
        result = recommend(v, queries, {'wallet_fee_ok': 0.1, 'wallet_speed_ok': 0.9})
        self.assertEqual(result['next_query'], 'check_fee')
        self.assertAlmostEqual(result['expected_remaining_query_cost'], 1.1)
        self.assertEqual(v.inspect()['status'], 'need_evidence')
        with self.assertRaises(Denied):
            v.propose({'wallet'})
        # A claimed probability of 1 is still not observed evidence.
        recommend(v, queries, {'wallet_fee_ok': 1.0, 'wallet_speed_ok': 1.0})
        with self.assertRaises(Denied):
            v.propose({'wallet'})

    def test_private_query_short_circuits_after_negative_result(self):
        v = two_private_checks(fee_ok=False)
        queries = (Query('check_fee', 'wallet_fee_ok'), Query('check_speed', 'wallet_speed_ok'))
        v.accept_evidence(v.authority.probe('check_fee'))
        result = recommend(v, queries)
        self.assertIsNone(result['next_query'])
        self.assertEqual(best(v).nodes, {'bank'})
        self.assertEqual(v.authority.metrics['private_probe_raw_reads'], 1)

    def test_conditional_dependencies_derived_from_same_contracts(self):
        low, high = refund(wallet=False, high=False), refund(wallet=False, high=True)
        self.assertEqual(low.registry.actions, high.registry.actions)
        self.assertEqual(best(low).fields, {'order.account_ref', 'customer.owner_ref'})
        self.assertEqual(best(high).fields, {'order.account_ref', 'customer.owner_ref', 'customer.identity_ref'})

    def test_multiple_legal_plans_not_labeled_illegal(self):
        v = refund(privacy_first=False)
        accepted = v.frontier()['accepted_plans']
        self.assertEqual(len(accepted), 2)
        self.assertEqual({len(p.fields) for p in accepted}, {1, 2})
        for p in accepted:
            self.assertEqual(p.fields, frozenset(f for n in p.nodes for f in v.registry.actions[n].fields))

    def test_explicit_privacy_preference_selects_smaller_set(self):
        v = refund()
        self.assertEqual(best(v).nodes, {'wallet'})
        with self.assertRaises(Denied):
            v.propose({'bank', 'bank_verify_low'})

    def test_user_utility_precedes_smaller_disclosure(self):
        v = refund(prefer_bank=True)
        self.assertEqual(best(v).nodes, {'bank', 'bank_verify_low'})
        self.assertEqual(len(best(v).fields), 2)

    def test_unknown_evidence_is_not_guessed_or_released(self):
        v = refund(private_wallet_check=True)
        self.assertEqual(v.inspect()['status'], 'need_evidence')
        self.assertEqual(v.inspect()['missing_evidence'], ['wallet_eligible'])
        self.assertEqual(v.disclosed, {})
        with self.assertRaises(Denied):
            v.propose({'wallet'})

    def test_private_predicate_reads_are_accounted_for(self):
        v = refund(private_wallet_check=True)
        receipt = v.authority.probe('check_wallet_constraints')
        v.accept_evidence(receipt)
        result = scripted_complete(v, best(v))
        self.assertEqual(result['disclosed_raw_fields'], ['order.wallet_ref'])
        self.assertEqual(result['connector_metrics']['private_probe_raw_reads'], 2)
        self.assertEqual(result['connector_metrics']['predicate_results_released'], 1)
        self.assertIs(receipt['value'], True)
        self.assertNotIn('private.wallet_fee', result['disclosed_raw_fields'])

    def test_unnecessary_probe_is_not_a_required_step(self):
        v = refund(private_wallet_check=True, prefer_bank=True)
        self.assertEqual(v.inspect()['status'], 'ready')
        scripted_complete(v, best(v))
        self.assertEqual(v.authority.metrics['private_probe_calls'], 0)

    def test_repeated_predicate_has_no_new_raw_reads(self):
        v = refund(private_wallet_check=True)
        a = v.authority.probe('check_wallet_constraints')
        b = v.authority.probe('check_wallet_constraints')
        self.assertEqual(a, b)
        self.assertEqual(v.authority.metrics['private_probe_raw_reads'], 2)
        with self.assertRaises(Denied):
            v.authority.probe('check_wallet_fee_at_arbitrary_threshold')

    def test_forged_evidence_cannot_expand_read_scope(self):
        v = refund()
        receipt = v.authority.public_receipt('wallet_available')
        forged = copy.deepcopy(receipt)
        forged['value'] = not forged['value']
        with self.assertRaises(Denied):
            v.accept_evidence(forged)

    def test_same_named_fact_from_another_order_is_rejected(self):
        a, b = refund(resource='order-a'), refund(resource='order-b')
        with self.assertRaises(Denied):
            b.accept_evidence(a.authority.public_receipt('wallet_available'))

    def test_unused_action_does_not_justify_extra_fields(self):
        v = refund()
        with self.assertRaises(Denied):
            v.propose({'wallet', 'quotes'})

    def test_raw_quote_values_are_allowed_when_user_really_requests_them(self):
        v = refund(exact_quotes=True)
        self.assertTrue({'private.wallet_fee', 'private.bank_fee'} <= best(v).fields)
        result = scripted_complete(v, best(v))
        self.assertTrue({'private.wallet_fee', 'private.bank_fee'} <= set(result['disclosed_raw_fields']))

    def test_grant_is_not_permission_to_read_backup_route(self):
        v = refund()
        sid = v.propose(best(v).nodes)
        g = v.issue(sid, 'wallet')
        with self.assertRaises(Denied):
            v.read(g['grant'], ['order.wallet_ref', 'order.account_ref'], v.authority.resource)
        self.assertEqual(v.disclosed, {})
        self.assertEqual(v.read(g['grant'], ['order.wallet_ref'], v.authority.resource), {'order.wallet_ref': 'SYN-WALLET'})

    def test_read_grant_is_single_use_and_resource_bound(self):
        v = refund()
        g = v.issue(v.propose(best(v).nodes), 'wallet')
        with self.assertRaises(Denied):
            v.read(g['grant'], g['fields'], 'another-order')
        v.read(g['grant'], g['fields'], v.authority.resource)
        with self.assertRaises(Denied):
            v.read(g['grant'], g['fields'], v.authority.resource)

    def test_next_action_not_entire_plan_is_released(self):
        v = refund(wallet=False, high=True)
        p = best(v)
        sid = v.propose(p.nodes)
        with self.assertRaises(Denied):
            v.issue(sid, 'bank')
        grant = v.issue(sid, 'identity')
        self.assertEqual(grant['fields'], ['customer.identity_ref'])
        self.assertNotIn('order.account_ref', grant['fields'])

    def test_negative_evidence_for_alternative_is_bound(self):
        v = refund(wallet=False)
        sid = v.propose(best(v).nodes)
        grant = v.issue(sid, 'bank_verify_low')
        self.assertIn('wallet_available', grant['evidence_versions'])
        v.authority.update_fact('wallet_available', True)
        with self.assertRaises(Denied):
            v.read(grant['grant'], grant['fields'], v.authority.resource)
        v.accept_evidence(v.authority.public_receipt('wallet_available'))
        self.assertEqual(best(v).nodes, {'wallet'})
        self.assertEqual(v.disclosed, {})

    def test_unrelated_state_change_does_not_invalidate_plan(self):
        v = refund()
        grant = v.issue(v.propose(best(v).nodes), 'wallet')
        self.assertNotIn('backend_help_banner_visible', grant['evidence_versions'])
        v.authority.update_fact('backend_help_banner_visible', False)
        self.assertTrue(v.read(grant['grant'], grant['fields'], v.authority.resource))

    def test_data_change_between_issue_and_read_is_detected(self):
        v = refund()
        grant = v.issue(v.propose(best(v).nodes), 'wallet')
        v.authority.update_value('order.wallet_ref', 'SYN-UPDATED-WALLET')
        with self.assertRaises(Denied):
            v.read(grant['grant'], grant['fields'], v.authority.resource)

    def test_data_change_between_read_and_execute_is_detected(self):
        v = refund()
        sid = v.propose(best(v).nodes)
        grant = v.issue(sid, 'wallet')
        values = v.read(grant['grant'], grant['fields'], v.authority.resource)
        v.authority.update_value('order.wallet_ref', 'SYN-UPDATED-WALLET')
        with self.assertRaises(Denied):
            v.execute(sid, 'wallet', values)

    def test_mutating_private_probe_input_invalidates_its_evidence(self):
        v = refund(private_wallet_check=True)
        receipt = v.authority.probe('check_wallet_constraints')
        v.accept_evidence(receipt)
        sid = v.propose(best(v).nodes)
        grant = v.issue(sid, 'wallet')
        v.authority.update_value('private.wallet_fee', 99)
        with self.assertRaises(Denied):
            v.read(grant['grant'], grant['fields'], v.authority.resource)
        v.accept_evidence(v.authority.probe('check_wallet_constraints'))
        self.assertEqual(best(v).nodes, {'bank', 'bank_verify_low'})

    def test_shared_dependency_is_not_duplicated(self):
        v = appointments()
        p = best(v)
        self.assertEqual(p.nodes, {'identity', 'session1.online', 'session2.online'})
        self.assertEqual(len(p.fields), 3)
        result = scripted_complete(v, p)
        self.assertEqual(result['monitor_metrics']['raw_disclosure_deliveries'], 3)

    def test_legitimate_actions_work_in_all_domains(self):
        for v in (refund(), refund(wallet=False), refund(wallet=False, high=True), appointments(), appointments(online=False)):
            result = scripted_complete(v, best(v))
            self.assertEqual(set(result['disclosed_raw_fields']), set(best(v).fields))
        for eligible in (False, True):
            v = delivery(within_radius=eligible)
            self.assertEqual(v.inspect()['missing_evidence'], ['pickup_within_radius'])
            v.accept_evidence(v.authority.probe('check_pickup_radius'))
            scripted_complete(v, best(v))

    def test_no_plan_when_all_routes_are_unavailable(self):
        v = refund(wallet=False, bank=False)
        self.assertEqual(v.inspect()['status'], 'no_permitted_plan')
        self.assertEqual(v.disclosed, {})

    def test_simulated_success_cannot_be_executed_twice(self):
        v = refund()
        p = best(v)
        scripted_complete(v, p)
        with self.assertRaises(Denied):
            v.propose(p.nodes)

    def test_exact_frontier_matches_independent_subset_enumerator(self):
        checked = 0
        for wallet, bank, high, eligible, prefer_bank, privacy in itertools.product((False, True), repeat=6):
            v = refund(wallet=wallet, bank=bank, high=high, prefer_bank=prefer_bank, privacy_first=privacy)
            v.authority.update_fact('wallet_eligible', eligible)
            v.accept_evidence(v.authority.public_receipt('wallet_eligible'))
            actions = list(v.registry.actions.values())
            valid = []
            truths = {'wallet_available': wallet, 'bank_available': bank, 'high_value': high, 'wallet_eligible': eligible}
            # Independent brute-force over ALL action subsets, not Registry.plans.
            for bits in itertools.product((False, True), repeat=len(actions)):
                subset = [a for a, use in zip(actions, bits) if use]
                producers = {a.produces: a for a in subset}
                if len(producers) != len(subset) or 'refund_done' not in producers:
                    continue
                if any(any(dep not in producers for dep in a.requires) for a in subset):
                    continue
                if any(truths.get(f) != expected for a in subset for f, expected in a.guards):
                    continue
                needed = set()
                def collect(output):
                    action = producers[output]
                    if action.id in needed:
                        return
                    needed.add(action.id)
                    for dep in action.requires:
                        collect(dep)
                collect('refund_done')
                if needed != {a.id for a in subset}:
                    continue
                fields = {f for a in subset for f in a.fields}
                rank = int(prefer_bank and producers['refund_done'].tool == 'wallet_refund')
                valid.append(((rank, len(fields) if privacy else 0), frozenset(needed)))
            optimum = min((score for score, _ in valid), default=None)
            expected = {nodes for score, nodes in valid if score == optimum}
            actual = {p.nodes for p in v.frontier()['accepted_plans']}
            self.assertEqual(actual, expected)
            checked += 1
        self.assertEqual(checked, 64)


if __name__ == '__main__':
    unittest.main()
