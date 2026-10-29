from types import SimpleNamespace
from unittest.mock import patch

from webapp import ota_payment_review


TRIP = {'trip_id': 'trip-synthetic', 'display_key': 'Synthetic trip',
        'starts_on': '2026-10-01', 'ends_on': '2026-10-05'}
EVENT = {'ota_event_id': 'ota-synthetic', 'verified_portal_snapshot': True,
         'reservation_status': 'confirmed', 'event_type': 'charge',
         'service_period': {'starts_on': '2026-10-02', 'ends_on': '2026-10-03'}}


def _project(row):
    backend = SimpleNamespace(board=SimpleNamespace(list_trips=lambda: [TRIP]))
    result = {'status': 'MATCHED_USER', 'transaction_id': 'card-synthetic',
              'ota_event_id': EVENT['ota_event_id']}
    fake_flow = SimpleNamespace(board=backend.board, trip_valid=lambda identity: identity == TRIP['trip_id'])
    with patch('webapp.card_flow.CardFlow', return_value=fake_flow), \
            patch('webapp.provisional_trip_review.authoritative_trips', return_value=[TRIP]):
        return ota_payment_review._provisional_trip_decisions(
            backend, [EVENT], [row], [result])['ota-synthetic']


def test_empty_manual_history_allows_ota_candidate_evaluation():
    decision = _project({'transaction_id': 'card-synthetic',
                         'classification_source': 'user_decision', 'trip_id': ''})

    assert decision['status'] == 'CLASSIFIED'
    assert decision['trip_id'] == 'trip-synthetic'
    assert decision['assignment_source'] == 'automatic'


def test_real_manual_trip_assignment_remains_user_confirmed():
    decision = _project({'transaction_id': 'card-synthetic',
                         'classification_source': 'user_decision',
                         'trip_id': 'trip-synthetic'})

    assert decision['status'] == 'CLASSIFIED'
    assert decision['trip_id'] == 'trip-synthetic'


def test_auto_inferred_basis_is_never_projected_as_manual():
    decision = _project({'transaction_id': 'card-synthetic',
                         'classification_source': 'user_decision',
                         'classification_basis': 'AUTO_TRIP_INFERRED · synthetic',
                         'trip_id': 'trip-synthetic'})

    assert decision['status'] == 'CLASSIFIED'
    assert decision['assignment_source'] == 'automatic'
