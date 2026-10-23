"""Golden regression tests comparing BASE frozen fixture with current CardFlow wrapper output.

These tests ensure the refactored pure helpers in ota_core_projection, called via
CardFlow._ota_card_statuses and _ota_candidate_notes, produce exactly the same
output as the original inline methods in CardFlow from BASE
fe340481ed5783d23f678d6a3df542ae8e6ce437.

The frozen fixture contains the original methods extracted via AST, preserving
exact behavior including all edge cases, Korean labels, and input immutability.
"""

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from webapp.card_flow import CardFlow
from tests.fixtures.original_card_flow_methods import _OriginalCardFlowMethods


class OtaCoreProjectionGoldenTests(unittest.TestCase):
    """Golden regression tests: current CardFlow wrapper vs frozen BASE fixture."""

    def setUp(self):
        """Set up synthetic test snapshots matching BASE test cases."""
        # Common snapshot structures used in BASE tests
        self.fresh_snapshot = {
            'generation': 9,
            'results': [
                {'transaction_id': 'exact', 'status': 'MATCHED_AUTO'},
                {'transaction_id': 'inferred', 'status': 'MATCHED_AUTO', 'inferred_link': True},
                {'transaction_id': 'manual', 'status': 'MATCHED_USER'},
                {'reserved_card_ids': ['contested'], 'status': 'HOLD_PARTIAL_GROUP'},
                {'transaction_id': 'grouped', 'status': 'MATCHED_AUTO',
                 'allocation_basis': 'auto_stable_order', 'individual_payment_evidence': False},
            ],
        }
        self.stale_snapshot = {
            'generation': 8,
            'results': [{'transaction_id': 'old-card', 'status': 'MATCHED_AUTO'}],
        }
        self.candidate_snapshot = {
            'generation': 18,
            'results': [
                {'ota_event_id': 'candidate-event', 'status': 'HOLD_AMOUNT_MISMATCH',
                 'transaction_id': None, 'candidates': ['txn1'], 'reason': 'amount_differs'},
            ],
            'data': {
                'events': [{'ota_event_id': 'candidate-event', 'provider': 'Agoda',
                           'booking_ref': 'SYNTHETIC-REF', 'paid_on': '2026-10-01',
                           'amount_krw': 39000, 'event_type': 'charge'}],
                'transactions': [], 'links': {},
                'results': [
                    {'ota_event_id': 'candidate-event', 'status': 'HOLD_AMOUNT_MISMATCH',
                     'transaction_id': None, 'candidates': ['txn1'], 'reason': 'amount_differs'},
                ]
            }
        }
        self.group_only_snapshot = {
            'generation': 1,
            'results': [],
            'data': {
                'events': [{'ota_event_id': 'group-evt', 'provider': 'Agoda', 'booking_ref': 'GROUP-REF'}],
                'transactions': [], 'links': {},
                'results': [{'ota_event_id': 'group-evt', 'status': 'MATCHED_AUTO',
                             'allocation_basis': 'auto_stable_order', 'individual_payment_evidence': False,
                             'transaction_id': 'txn1', 'reserved_card_ids': ['txn2']}]
            }
        }
        self.multiple_candidates_snapshot = {
            'generation': 1,
            'results': [],
            'data': {
                'events': [
                    {'ota_event_id': 'evt1', 'provider': 'Agoda', 'booking_ref': 'REF1'},
                    {'ota_event_id': 'evt2', 'provider': 'Trip.com', 'booking_ref': 'REF2'},
                    {'ota_event_id': 'evt3', 'provider': 'Booking.com', 'booking_ref': 'REF3'},
                ],
                'transactions': [], 'links': {},
                'results': [
                    {'ota_event_id': 'evt1', 'status': 'HOLD_AMOUNT_MISMATCH', 'transaction_id': None,
                     'candidates': ['txn1'], 'reason': 'amount_differs'},
                    {'ota_event_id': 'evt2', 'status': 'HOLD_DATE_UNKNOWN', 'transaction_id': None,
                     'candidates': ['txn1'], 'reason': 'payment_date_not_in_source'},
                    {'ota_event_id': 'evt3', 'status': 'HOLD_AMBIGUOUS', 'transaction_id': None,
                     'candidates': ['txn1'], 'reason': 'no_exact_amount_date_direction_card'},
                ]
            }
        }
        self.rejected_snapshot = {
            'generation': 1,
            'results': [],
            'data': {
                'events': [{'ota_event_id': 'evt1', 'provider': 'Agoda', 'booking_ref': 'REF1'}],
                'transactions': [], 'links': {},
                'results': [{'ota_event_id': 'evt1', 'status': 'HOLD_AMOUNT_MISMATCH',
                             'candidate_search': {
                                 'candidates': [{'transaction_id': 'txn1'}],
                                 'rejected': [{'transaction_id': 'txn2', 'reason': 'AMOUNT_MISMATCH'}]
                             }}]
            }
        }
        self.disabled_snapshot = None

    def _create_original_flow(self, snapshot, fresh=True, enabled=True):
        """Create a CardFlow-like object with frozen original methods."""
        # Create a minimal object with the original methods
        obj = _OriginalCardFlowMethods()
        
        def mock_held_ota_snapshot():
            return snapshot, fresh if snapshot is not None else False
        obj._held_ota_snapshot = mock_held_ota_snapshot
        
        # Patch enabled globally for this object
        self._enabled_patch = patch('webapp.ota_payment_review.enabled', return_value=enabled)
        self._enabled_patch.start()
        
        return obj

    def _create_current_flow(self, snapshot, fresh=True, enabled=True):
        """Create a CardFlow object with current wrapper methods."""
        # Create a mock CardFlow with minimal dependencies
        flow = MagicMock(spec=CardFlow)
        flow._held_ota_snapshot = MagicMock(return_value=(snapshot, fresh if snapshot is not None else False))
        
        # Patch enabled globally
        self._enabled_patch2 = patch('webapp.ota_payment_review.enabled', return_value=enabled)
        self._enabled_patch2.start()
        
        return flow

    def _cleanup_patches(self):
        """Stop all active patches."""
        for attr in dir(self):
            if attr.startswith('_enabled_patch'):
                getattr(self, attr).stop()

    def _run_original_statuses(self, snapshot, fresh=True, enabled=True, rows=None):
        """Run original _ota_card_statuses."""
        obj = self._create_original_flow(snapshot, fresh, enabled)
        try:
            if rows is None:
                rows = []
            return obj._ota_card_statuses(rows)
        finally:
            self._cleanup_patches()

    def _run_current_statuses(self, snapshot, fresh=True, enabled=True, rows=None):
        """Run current CardFlow._ota_card_statuses wrapper."""
        flow = self._create_current_flow(snapshot, fresh, enabled)
        # Bind the actual wrapper method
        flow._ota_card_statuses = CardFlow._ota_card_statuses.__get__(flow, CardFlow)
        try:
            if rows is None:
                rows = []
            return flow._ota_card_statuses(rows)
        finally:
            self._cleanup_patches()

    def _run_original_notes(self, snapshot, wanted_transaction_ids, fresh=True, enabled=True):
        """Run original _ota_candidate_notes with proper rows."""
        obj = self._create_original_flow(snapshot, fresh, enabled)
        try:
            rows = [{'transaction_id': tid} for tid in wanted_transaction_ids]
            return obj._ota_candidate_notes(rows)
        finally:
            self._cleanup_patches()

    def _run_current_notes(self, snapshot, wanted_transaction_ids, fresh=True, enabled=True):
        """Run current CardFlow._ota_candidate_notes wrapper with proper rows."""
        flow = self._create_current_flow(snapshot, fresh, enabled)
        flow._ota_candidate_notes = CardFlow._ota_candidate_notes.__get__(flow, CardFlow)
        try:
            rows = [{'transaction_id': tid} for tid in wanted_transaction_ids]
            return flow._ota_candidate_notes(rows)
        finally:
            self._cleanup_patches()

    # ==================== Status Tests ====================

    def test_fresh_snapshot_statuses_match(self):
        """Fresh snapshot produces identical statuses tuple."""
        orig_statuses, orig_gen, orig_recon = self._run_original_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        curr_statuses, curr_gen, curr_recon = self._run_current_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        
        self.assertEqual(curr_statuses, orig_statuses, 'Status mapping differs from BASE')
        self.assertEqual(curr_gen, orig_gen)
        self.assertEqual(curr_recon, orig_recon)

    def test_stale_snapshot_statuses_match(self):
        """Stale snapshot produces identical statuses tuple."""
        orig_statuses, orig_gen, orig_recon = self._run_original_statuses(self.stale_snapshot, fresh=False, enabled=True)
        curr_statuses, curr_gen, curr_recon = self._run_current_statuses(self.stale_snapshot, fresh=False, enabled=True)
        
        self.assertEqual(curr_statuses, orig_statuses)
        self.assertEqual(curr_gen, orig_gen)
        self.assertEqual(curr_recon, orig_recon)
        self.assertEqual(curr_recon['status'], 'stale')

    def test_disabled_snapshot_statuses_match(self):
        """Disabled (enabled=False) snapshot produces identical disabled statuses."""
        orig_statuses, orig_gen, orig_recon = self._run_original_statuses(None, fresh=False, enabled=False)
        curr_statuses, curr_gen, curr_recon = self._run_current_statuses(None, fresh=False, enabled=False)
        
        self.assertEqual(curr_statuses, orig_statuses)
        self.assertIsNone(curr_gen)
        self.assertIsNone(orig_gen)
        self.assertEqual(curr_recon, orig_recon)
        self.assertEqual(curr_recon['enabled'], False)
        self.assertEqual(curr_recon['status'], 'disabled')

    def test_enabled_but_none_snapshot_statuses_match(self):
        """Enabled but no snapshot (current=None) produces loading statuses."""
        orig_statuses, orig_gen, orig_recon = self._run_original_statuses(None, fresh=False, enabled=True)
        curr_statuses, curr_gen, curr_recon = self._run_current_statuses(None, fresh=False, enabled=True)
        
        self.assertEqual(curr_statuses, orig_statuses)
        self.assertEqual(curr_recon, orig_recon)
        self.assertEqual(curr_recon['status'], 'loading')

    # ==================== Notes Tests ====================

    def test_unlinked_candidate_notes_match(self):
        """Unlinked card candidate notes match BASE."""
        wanted = {'txn1'}
        orig_notes = self._run_original_notes(self.candidate_snapshot, wanted, fresh=True, enabled=True)
        curr_notes = self._run_current_notes(self.candidate_snapshot, wanted, fresh=True, enabled=True)
        
        self.assertEqual(curr_notes, orig_notes)
        notes = curr_notes.get('txn1', [])
        self.assertTrue(any('OTA 후보(미확정): Agoda SYNTHETIC-REF' in n for n in notes),
                        'Missing candidate note with provider/booking_ref')
        self.assertTrue(not any('amount_differs' in n for n in notes),
                        'Internal reason code should not appear in user note')

    def test_group_only_notes_match(self):
        """Group-only (ordered group) notes match BASE."""
        wanted = {'txn1', 'txn2'}
        orig_notes = self._run_original_notes(self.group_only_snapshot, wanted, fresh=True, enabled=True)
        curr_notes = self._run_current_notes(self.group_only_snapshot, wanted, fresh=True, enabled=True)
        
        self.assertEqual(curr_notes, orig_notes)
        notes = curr_notes.get('txn1', [])
        self.assertTrue(any('OTA 반복 결제 그룹은 대응됐지만' in n for n in notes),
                        'Missing group-only note')

    def test_multiple_candidates_deduplication_and_top2(self):
        """Multiple candidates deduplicated and limited to top 2."""
        wanted = {'txn1'}
        orig_notes = self._run_original_notes(self.multiple_candidates_snapshot, wanted, fresh=True, enabled=True)
        curr_notes = self._run_current_notes(self.multiple_candidates_snapshot, wanted, fresh=True, enabled=True)
        
        self.assertEqual(curr_notes, orig_notes)
        notes = curr_notes.get('txn1', [])
        self.assertEqual(len(notes), 2, 'Should be limited to top 2')
        self.assertEqual(notes, sorted(notes), 'Notes should be sorted for determinism')

    def test_rejected_candidates_match(self):
        """Rejected candidate notes match BASE."""
        wanted = {'txn1', 'txn2'}
        orig_notes = self._run_original_notes(self.rejected_snapshot, wanted, fresh=True, enabled=True)
        curr_notes = self._run_current_notes(self.rejected_snapshot, wanted, fresh=True, enabled=True)
        
        self.assertEqual(curr_notes, orig_notes)
        notes_t2 = curr_notes.get('txn2', [])
        self.assertTrue(any('OTA 후보 제외 사유:' in n for n in notes_t2),
                        'Missing rejection reason note')

    def test_stale_notes_return_empty(self):
        """Stale snapshot returns empty notes."""
        wanted = {'txn1'}
        orig_notes = self._run_original_notes(self.fresh_snapshot, wanted, fresh=False, enabled=True)
        curr_notes = self._run_current_notes(self.fresh_snapshot, wanted, fresh=False, enabled=True)
        
        self.assertEqual(curr_notes, orig_notes)
        self.assertEqual(curr_notes, {})

    def test_disabled_notes_return_empty(self):
        """Disabled (enabled=False) returns empty notes."""
        wanted = {'txn1'}
        orig_notes = self._run_original_notes(self.fresh_snapshot, wanted, fresh=True, enabled=False)
        curr_notes = self._run_current_notes(self.fresh_snapshot, wanted, fresh=True, enabled=False)
        
        self.assertEqual(curr_notes, orig_notes)
        self.assertEqual(curr_notes, {})

    # ==================== Invariants ====================

    def test_input_immutability_statuses(self):
        """Original snapshot dict is not mutated."""
        snapshot = copy.deepcopy(self.fresh_snapshot)
        self._run_current_statuses(snapshot, fresh=True, enabled=True)
        self.assertEqual(snapshot, self.fresh_snapshot,
                         'Input snapshot must not be mutated (deep equality)')

    def test_input_immutability_notes(self):
        """Original snapshot dict is not mutated."""
        snapshot = copy.deepcopy(self.candidate_snapshot)
        self._run_current_notes(snapshot, {'txn1'}, fresh=True, enabled=True)
        self.assertEqual(snapshot, self.candidate_snapshot,
                         'Input snapshot must not be mutated (deep equality)')

    def test_all_status_values_covered(self):
        """All expected status values appear in outputs."""
        _, _, _ = self._run_original_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        curr_statuses, _, _ = self._run_current_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        expected_statuses = {'EXACT', 'INFERRED', 'USER_CONFIRMED', 'GROUP_RECONCILED', 'REVIEW_REQUIRED'}
        actual_statuses = set(curr_statuses.values())
        self.assertEqual(actual_statuses, expected_statuses,
                         f'Missing statuses: {expected_statuses - actual_statuses}')

    def test_korean_labels_preserved(self):
        """Korean label strings are preserved exactly."""
        wanted = {'txn1'}
        curr_notes = self._run_current_notes(self.candidate_snapshot, wanted, fresh=True, enabled=True)
        notes = curr_notes.get('txn1', [])
        self.assertTrue(any('OTA 후보(미확정):' in n for n in notes),
                        'Korean label prefix missing')
        self.assertTrue(any('금액이 다른 카드 거래만 있음' in n for n in notes),
                        'Korean status label missing')

    def test_reconciliation_keys_identical(self):
        """Reconciliation dict has identical keys and structure."""
        _, _, orig_recon = self._run_original_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        _, _, curr_recon = self._run_current_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        self.assertEqual(set(curr_recon.keys()), set(orig_recon.keys()))

    def test_empty_wanted_returns_empty_notes(self):
        """Empty wanted set returns empty notes dict."""
        curr_notes = self._run_current_notes(self.candidate_snapshot, set(), fresh=True, enabled=True)
        orig_notes = self._run_original_notes(self.candidate_snapshot, set(), fresh=True, enabled=True)
        self.assertEqual(curr_notes, {})
        self.assertEqual(orig_notes, {})

    def test_fixture_validity_check(self):
        """Verify the frozen fixture itself matches BASE test expectations."""
        # This test confirms the fixture matches BASE test expectations
        orig_statuses, generation, reconciliation = self._run_original_statuses(self.fresh_snapshot, fresh=True, enabled=True)
        
        self.assertEqual(generation, 9)
        self.assertEqual(reconciliation, {'enabled': True, 'fresh': True,
                                          'status': 'ready', 'generation': 9})
        self.assertEqual(orig_statuses, {'exact': 'EXACT', 'inferred': 'INFERRED',
                                    'manual': 'USER_CONFIRMED', 'contested': 'REVIEW_REQUIRED',
                                    'grouped': 'GROUP_RECONCILED'})


if __name__ == '__main__':
    unittest.main()