"""Verify station evidence is rechecked when its target station changes."""
import json
import unittest

from scripts.run_logistics_dependency import ARMS, POINT, STUDY, DependentWorkflow


class StationReceiptBoundary(unittest.TestCase):
    def test_changed_station_invalidates_reused_check_at_delivery(self):
        cases = json.loads((STUDY / 'cases.json').read_text())
        case = next(c for c in cases if c['id'] == 'enhanced_station_primary_only')
        for arm in ARMS:
            with self.subTest(arm=arm):
                run = DependentWorkflow(arm, case)
                run.start_remaining([POINT])
                run.propose_expected(['identity', 'move'])
                run.perform_step('identity')
                run.perform_step('move')
                run.apply_state(case['after_move'], 'station_changed')
                run.start_remaining()
                run.propose_expected(case['booking_plan'])
                run.perform_step('station_check')
                run.start_remaining()
                run.propose_expected(case['booking_plan'])
                self.assertIn('station_verified', run.verifier.sessions[run.sid]['artifacts'])
                grant = run.prepare('primary_checked')
                run.authority.update_value('parcel.station_ref', 'SYN-OTHER-STATION')
                self.assertFalse(run.read('primary_checked', grant))
                self.assertNotIn('parcel.primary_slot_ref', run.values)
                self.assertEqual(run.committed, {POINT})
