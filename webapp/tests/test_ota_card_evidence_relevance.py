"""Card-side OTA evidence must not list unrelated same-provider booking rejections."""
from webapp.card_flow import _index_ota_display_candidates


def _snapshot(*, paid_on, approval_date="2026-09-22"):
    event = {
        "ota_event_id": "synthetic-agoda-event",
        "provider": "agoda",
        "booking_ref": "SYNTHETIC-AGODA-BOOKING",
        "event_type": "charge",
        "paid_on": paid_on,
        "amount": 20532,
        "amount_krw": 20532,
        "currency": "JPY",
        "service_period": {"starts_on": "2026-03-10", "ends_on": "2026-03-11"},
    }
    card = {
        "transaction_id": "synthetic-card-625280",
        "merchant": "AGODA NICE-Agoda",
        "merchant_normalized": "AGODA NICE-Agoda",
        "amount_krw": 625280,
        "approval_date": approval_date,
        "transaction_direction": "purchase",
        "currency": "KRW",
        "foreign_currency": None,
        "foreign_amount": None,
        "card_tail": "2042",
        "issuer": "Synthetic Bank",
    }
    result = {
        "ota_event_id": event["ota_event_id"],
        "status": "HOLD_DATE_UNKNOWN" if not paid_on else "HOLD_AMOUNT_MISMATCH",
        "reason": "payment_date_not_in_source" if not paid_on else "amount_differs",
        "candidates": [],
        "candidate_search": {
            "status": "NO_CANDIDATE",
            "candidates": [],
            "rejected": [{"transaction_id": card["transaction_id"], "reason": "CURRENCY_MISMATCH",
                          "display_relevant": bool(paid_on and paid_on == card["approval_date"])}],
        },
    }
    return {
        "results": [],
        "data": {"events": [event], "transactions": [card], "rules": [], "results": [result]},
    }


def test_unknown_booking_payment_date_does_not_attach_every_agoda_rejection_to_card():
    indexed = _index_ota_display_candidates(_snapshot(paid_on=None))
    assert "synthetic-card-625280" not in indexed


def test_rejected_agoda_candidate_on_unrelated_payment_date_is_hidden():
    indexed = _index_ota_display_candidates(_snapshot(paid_on="2026-03-10"))
    assert "synthetic-card-625280" not in indexed


def test_rejected_candidate_on_same_payment_date_remains_visible_for_review():
    indexed = _index_ota_display_candidates(_snapshot(paid_on="2026-09-22"))
    notes = indexed["synthetic-card-625280"]
    assert len(notes) == 1
    assert "SYNTHETIC-AGODA-BOOKING" in notes[0]
    assert "제외" in notes[0]
    assert "625,280원" in notes[0]


def test_page_filter_projects_core_trace_without_rechecking_provider_or_hidden_cards(monkeypatch):
    from copy import deepcopy
    from webapp import card_flow
    snapshot = _snapshot(paid_on="2026-09-22")
    visible = snapshot['data']['transactions'][0]['transaction_id']
    hidden = dict(snapshot['data']['transactions'][0], transaction_id='synthetic-hidden')
    snapshot['data']['transactions'].append(hidden)
    result = snapshot['data']['results'][0]
    result['candidate_search']['rejected'].append({'transaction_id': hidden['transaction_id'],
                                                    'display_relevant': True})
    result['reserved_card_ids'] = [visible, hidden['transaction_id']]
    before = deepcopy(snapshot)
    expected = _index_ota_display_candidates(snapshot)[visible]
    calls = []
    def forbidden(*_args, **_kwargs):
        calls.append('rechecked')
        raise AssertionError('projection must consume core candidate trace')
    monkeypatch.setattr('app.ota_payments.provider_compatible', forbidden)
    assert _index_ota_display_candidates(snapshot, transaction_ids=[visible]) == {visible: expected}
    assert calls == []
    calls.clear()
    assert _index_ota_display_candidates(snapshot, transaction_ids=[]) == {}
    assert not calls
    assert snapshot == before


def test_core_rejection_visibility_marker_avoids_projection_date_recalculation(monkeypatch):
    snapshot = _snapshot(paid_on='2026-03-10')
    rejected = snapshot['data']['results'][0]['candidate_search']['rejected'][0]
    rejected['display_relevant'] = True

    def forbidden(*_args, **_kwargs):
        raise AssertionError('core visibility metadata must be projected as-is')

    monkeypatch.setattr('app.ota_payments._approved_lag_match', forbidden)
    monkeypatch.setattr('app.ota_payments._foreign_day_lag_match', forbidden)
    indexed = _index_ota_display_candidates(snapshot)
    assert 'synthetic-card-625280' in indexed
    assert '제외' in indexed['synthetic-card-625280'][0]
