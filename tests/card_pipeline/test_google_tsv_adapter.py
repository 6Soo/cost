import pytest

from app.google_tsv_adapter import tsv_for_tab


def prow(tx, **overrides):
    base = {"transaction_id": tx, "display_tab_id": "trip-A", "occurred_on": "2027-08-02",
            "merchant": "SHOP-A", "item": "식비", "amount_krw": 12000, "blocked": None,
            "already_booked": False, "service_period": "", "booking_ref": ""}
    base.update(overrides)
    return base


def test_maps_merchant_to_payee_and_item_to_category_one_row_each():
    rows = [prow("t1", booking_ref="RES-1", service_period="2027-08-01~02"), prow("t2", amount_krw=-3000)]
    result = tsv_for_tab(rows, "trip-A")
    assert result["row_count"] == 2 and result["total_krw"] == 9000
    assert result["tsv"].splitlines()[0] == "2027-08-02\tSHOP-A\t식비\t2027-08-01~02\tRES-1\t카드\t12000"


def test_already_booked_rows_are_still_pasted_because_the_target_is_google():
    result = tsv_for_tab([prow("t1", already_booked=True)], "trip-A")
    assert result["row_count"] == 1 and result["held"] == []


def test_blocked_rows_are_listed_with_preview_reason_and_not_pasted():
    result = tsv_for_tab([prow("t1", blocked="item_missing"), prow("t2")], "trip-A")
    assert result["row_count"] == 1
    assert {"transaction_id": "t1", "reason": "item_missing"} in result["held"]


def test_blocked_duplicate_identity_cannot_disappear_before_export_validation():
    rows = [prow('conflict'), prow('conflict', blocked='duplicate_conflict'), prow('unrelated', amount_krw=3000)]
    result = tsv_for_tab(rows, 'trip-A')
    assert result['row_count'] == 1 and result['total_krw'] == 3000
    assert {'transaction_id': 'conflict', 'reason': 'duplicate_conflict'} in result['held']
    assert {'transaction_id': 'conflict', 'reason': 'DUPLICATE_ID'} in result['held']


def test_other_trips_are_excluded_not_held():
    result = tsv_for_tab([prow("t1", display_tab_id="trip-B"), prow("t2")], "trip-A")
    assert result["row_count"] == 1 and result["held"] == []


def test_missing_merchant_or_category_is_held_not_guessed():
    result = tsv_for_tab([prow("t1", merchant=""), prow("t2", item="")], "trip-A")
    assert result["row_count"] == 0
    assert {h["transaction_id"]: h["reason"] for h in result["held"]} == {"t1": "FIELD_MISSING", "t2": "FIELD_MISSING"}


def test_tab_is_required():
    with pytest.raises(ValueError, match="TAB_REQUIRED"):
        tsv_for_tab([prow("t1")], "")
