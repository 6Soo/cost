"""Pure helper tests for ota_core_projection projection functions."""
import unittest
from app.ota_core_projection import project_card_ota_statuses, project_card_ota_candidate_notes


class OtaCoreProjectionTests(unittest.TestCase):
    def test_project_card_ota_statuses_none_returns_empty(self):
        statuses, generation, reconciliation = project_card_ota_statuses(None)
        self.assertEqual(statuses, {})
        self.assertIsNone(generation)
        self.assertEqual(reconciliation, {'enabled': True, 'fresh': False, 'status': 'stale', 'generation': None})

    def test_project_card_ota_statuses_fresh_snapshot(self):
        current = {'generation': 9, 'results': [
            {'transaction_id': 'exact', 'status': 'MATCHED_AUTO'},
            {'transaction_id': 'inferred', 'status': 'MATCHED_AUTO', 'inferred_link': True},
            {'transaction_id': 'manual', 'status': 'MATCHED_USER'},
            {'reserved_card_ids': ['contested'], 'status': 'HOLD_PARTIAL_GROUP'},
            {'transaction_id': 'grouped', 'status': 'MATCHED_AUTO', 'allocation_basis': 'auto_stable_order',
             'individual_payment_evidence': False},
        ]}
        statuses, generation, reconciliation = project_card_ota_statuses(current)
        self.assertEqual(generation, 9)
        self.assertEqual(reconciliation, {'enabled': True, 'fresh': True, 'status': 'ready', 'generation': 9})
        self.assertEqual(statuses, {'exact': 'EXACT', 'inferred': 'INFERRED',
                                    'manual': 'USER_CONFIRMED', 'contested': 'REVIEW_REQUIRED',
                                    'grouped': 'GROUP_RECONCILED'})

    def test_project_card_ota_statuses_input_immutability(self):
        current = {'generation': 9, 'results': [
            {'transaction_id': 'exact', 'status': 'MATCHED_AUTO'},
        ]}
        original = current.copy()
        project_card_ota_statuses(current)
        self.assertEqual(current, original)

    def test_toyoko_reservation_axis_is_separate_and_notes_payment_is_unverified(self):
        current = {'generation': 3, 'results': [
            {'status': 'RESERVATION_ONLY', 'reservation_link': {
                'status': 'INFERRED', 'transaction_id': 'toyoko-card', 'amount_status': 'UNKNOWN',
                'payment_verified': False}}],
            'data': {'events': [{'ota_event_id': 'toyoko-event', 'provider': 'toyoko',
                                 'booking_ref': 'SYNTHETIC-1234567'}],
                     'results': [{'ota_event_id': 'toyoko-event', 'status': 'RESERVATION_ONLY',
                         'reservation_link': {'status': 'INFERRED', 'transaction_id': 'toyoko-card',
                                              'amount_status': 'UNKNOWN', 'payment_verified': False}}]}}
        statuses, _, _ = project_card_ota_statuses(current)
        notes = project_card_ota_candidate_notes(current, {'toyoko-card'})
        self.assertEqual(statuses['toyoko-card'], 'RESERVATION_INFERRED')
        self.assertTrue(any('예약 추론' in note and '원문 금액' in note and 'SYNTHETIC-1234567' in note
                            for note in notes['toyoko-card']))

    def test_project_card_ota_candidate_notes_none_returns_empty(self):
        notes = project_card_ota_candidate_notes(None, {'txn1'})
        self.assertEqual(notes, {})

    def test_project_card_ota_candidate_notes_unlinked_card(self):
        # Snapshot format: data.results is what the helper iterates
        current = {'generation': 18, 'results': [], 'data': {
            'events': [{'ota_event_id': 'candidate-event', 'provider': 'Agoda',
                        'booking_ref': 'SYNTHETIC-REF', 'paid_on': '2026-10-01',
                        'amount_krw': 39000, 'event_type': 'charge'}],
            'transactions': [], 'links': {},
            'results': [{'ota_event_id': 'candidate-event', 'status': 'HOLD_AMOUNT_MISMATCH',
                         'transaction_id': None, 'candidates': ['txn1'], 'reason': 'amount_differs'}]
        }}
        notes = project_card_ota_candidate_notes(current, {'txn1'})
        self.assertIn('txn1', notes)
        self.assertTrue(any('OTA 후보(미확정): Agoda SYNTHETIC-REF' in note
                            and 'amount_differs' not in note
                            for note in notes['txn1']))

    def test_project_card_ota_candidate_notes_deduplication_and_top2(self):
        current = {'generation': 1, 'results': [], 'data': {
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
        }}
        notes = project_card_ota_candidate_notes(current, {'txn1'})
        self.assertEqual(len(notes['txn1']), 2)  # Limited to top 2
        self.assertEqual(notes['txn1'], sorted(notes['txn1']))  # Sorted

    def test_project_card_ota_candidate_notes_group_only(self):
        current = {'generation': 1, 'results': [], 'data': {
            'events': [{'ota_event_id': 'group-evt', 'provider': 'Agoda', 'booking_ref': 'GROUP-REF'}],
            'transactions': [], 'links': {},
            'results': [{'ota_event_id': 'group-evt', 'status': 'MATCHED_AUTO',
                         'allocation_basis': 'auto_stable_order', 'individual_payment_evidence': False,
                         'transaction_id': 'txn1', 'reserved_card_ids': ['txn2']}]
        }}
        notes = project_card_ota_candidate_notes(current, {'txn1', 'txn2'})
        self.assertIn('txn1', notes)
        self.assertTrue(any('OTA 반복 결제 그룹은 대응됐지만' in note for note in notes['txn1']))

    def test_project_card_ota_candidate_notes_rejected_candidates(self):
        current = {'generation': 1, 'results': [], 'data': {
            'events': [{'ota_event_id': 'evt1', 'provider': 'Agoda', 'booking_ref': 'REF1'}],
            'transactions': [], 'links': {},
            'results': [{'ota_event_id': 'evt1', 'status': 'HOLD_AMOUNT_MISMATCH',
                         'candidate_search': {
                             'candidates': [{'transaction_id': 'txn1'}],
                             'rejected': [{'transaction_id': 'txn2', 'reason': 'AMOUNT_MISMATCH'}]
                         }}]
        }}
        notes = project_card_ota_candidate_notes(current, {'txn1', 'txn2'})
        self.assertIn('txn1', notes)
        self.assertIn('txn2', notes)
        self.assertTrue(any('OTA 후보 제외 사유:' in note for note in notes['txn2']))

    def test_project_card_ota_candidate_notes_input_immutability(self):
        current = {'generation': 1, 'results': [], 'data': {
            'events': [{'ota_event_id': 'evt1', 'provider': 'Agoda', 'booking_ref': 'REF1'}],
            'transactions': [], 'links': {},
            'results': [{'ota_event_id': 'evt1', 'status': 'HOLD_AMOUNT_MISMATCH', 'candidates': ['txn1']}]
        }}
        import copy
        original = copy.deepcopy(current)
        project_card_ota_candidate_notes(current, {'txn1'})
        self.assertEqual(current, original)


if __name__ == '__main__':
    unittest.main()
