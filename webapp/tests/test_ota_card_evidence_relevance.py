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
            "rejected": [{"transaction_id": card["transaction_id"], "reason": "CURRENCY_MISMATCH"}],
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
