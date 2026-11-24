"""Verify mandatory, fresh signature evidence before high-value rebooking."""
import unittest

from necessity_v2.core import Denied
from scripts.run_logistics_dependency import POINT
from scripts.run_logistics_signature import ARMS, SIGNATURE_FIELD, SignatureWorkflow, read


class SignatureAuthorizationBoundary(unittest.TestCase):
    def prepare_booking(self, arm):
        case = next(row for row in read('cases.json') if row['id'] == 'signature_primary')
        workflow = SignatureWorkflow(arm, case, read('rule.json'))
        workflow.start_remaining([POINT])
        workflow.propose_expected(['identity', 'move'])
        workflow.perform_step('identity')
        workflow.perform_step('move')
        workflow.apply_state(case['after_move'], 'station_changed')
        workflow.start_remaining()
        return workflow, case

    def test_unsigned_route_and_missing_signature_are_rejected(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                workflow, case = self.prepare_booking(arm)
                with self.assertRaises(Denied):
                    workflow.propose(['identity', 'primary'])
                workflow.propose_expected(case['booking_plan'])
                if arm == 'contract':
                    with self.assertRaises(Denied):
                        workflow.prepare('primary_signed')
                else:
                    self.assertFalse(workflow.read('primary_signed', None))
                self.assertNotIn('parcel.primary_slot_ref', workflow.values)
                self.assertEqual(workflow.committed, {POINT})

    def test_stale_signature_receipt_blocks_read_after_reuse(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                workflow, case = self.prepare_booking(arm)
                workflow.propose_expected(case['booking_plan'])
                workflow.perform_step('signature_check')
                workflow.start_remaining()
                workflow.propose_expected(case['booking_plan'])
                self.assertIn('signature_verified', workflow.verifier.sessions[workflow.sid]['artifacts'])
                ticket = workflow.prepare('primary_signed')
                workflow.authority.update_value(SIGNATURE_FIELD, 'SYN-CHANGED-SIGNATURE-AUTHORIZATION')
                self.assertFalse(workflow.read('primary_signed', ticket))
                self.assertNotIn('parcel.primary_slot_ref', workflow.values)
                self.assertEqual(workflow.committed, {POINT})
