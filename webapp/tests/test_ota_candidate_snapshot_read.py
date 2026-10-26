"""Candidate GETs never reconcile original mail on the HTTP thread."""
from types import SimpleNamespace
from urllib.parse import urlsplit
import pytest
from webapp import ota_payment_review as review


def test_pending_card_candidates_use_snapshot_and_never_legacy_data():
    calls = []
    def pending():
        calls.append('snapshot')
        raise review.OtaSnapshotNotReady('refreshing')
    backend = SimpleNamespace(_action_data=pending, _data=lambda: pytest.fail('foreground mail parsing'))
    with pytest.raises(review.OtaSnapshotNotReady):
        review.CoreOtaPaymentBackend.cards_for_event(backend, 'synthetic')
    assert calls == ['snapshot']


@pytest.mark.parametrize('error', [review.OtaSnapshotNotReady('refreshing'), review.StalePreviewError()])
def test_pending_cards_route_returns_explicit_retry_without_source_details(error, monkeypatch):
    monkeypatch.setattr(review, 'enabled', lambda: True)
    replies = []
    handler = SimpleNamespace(current_user_id=lambda: 'synthetic-owner',
        _send_json=lambda payload, status=200: replies.append((status, payload)))
    def pending(_):
        raise error
    assert review.dispatch(handler, urlsplit('/api/imports/ota/cards/synthetic'),
        backend=SimpleNamespace(cards_for_event=pending), csrf='synthetic')
    status, payload = replies[0]
    assert status == 409 and payload['code'] == 'OTA_SNAPSHOT_NOT_READY'
    assert 'synthetic' not in str(payload)
