"""Check policy boundaries shared by both walkthrough arms."""
import unittest

from necessity_v2.core import Denied
from necessity_v2.route_baseline import refresh_public_state
from scripts.run_route_table_comparison import IDENTITY, WALLET, Walkthrough


class ComparisonBoundaries(unittest.TestCase):
    def test_refund_needs_confirmation_and_reads_are_exact(self):
        for arm in ('route_table', 'contract'):
            with self.subTest(arm=arm):
                run = Walkthrough('exact_quotes_required', arm)
                run.propose(('wallet', 'quotes'))
                node, fields = WALLET
                grant = run.prepare(node, fields)
                self.assertFalse(run.read(node, fields + ('order.account_ref',), grant))
                self.assertEqual(run.values, {})
                self.assertTrue(run.read(node, fields, grant))
                with self.assertRaisesRegex(Denied, 'approval is required'):
                    run.execute(node, fields)
                self.assertFalse(run.verifier.committed_goals)

    def test_identity_receipt_with_changed_value_is_not_reused(self):
        for arm in ('route_table', 'contract'):
            with self.subTest(arm=arm):
                run = Walkthrough('reuse_identity_after_replan', arm)
                run.propose(('identity', 'bank_verify_high', 'bank'))
                run.step(*IDENTITY)
                authority = run.verifier.authority
                authority.update_fact('wallet_available', True)
                refresh_public_state(run.verifier)
                run.propose(('identity', 'wallet'))
                self.assertIn('identity_verified', run.verifier.sessions[run.sid]['artifacts'])
                authority.update_value('customer.identity_ref', 'SYN-UPDATED-IDENTITY')
                if arm == 'contract':
                    with self.assertRaisesRegex(Denied, 'Identity verification is stale'):
                        run.prepare(*WALLET)
                else:
                    self.assertFalse(run.read(*WALLET, None))
                run.propose(('identity', 'wallet'))
                self.assertEqual(run.verifier.sessions[run.sid]['artifacts'], set())
                run.step(*IDENTITY)
                run.step(*WALLET)
                self.assertEqual(run.verifier.committed_goals, {'refund_done'})
