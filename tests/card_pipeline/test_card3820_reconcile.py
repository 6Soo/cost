"""3820 잔여 규칙과 환불의 원거래 연결 (사용자 규칙 2026-10-15)."""
import sqlite3

from app.classify import _card3820_residual, pair_refunds


def purchase(**changes):
    value = dict(card_tail="3820", transaction_direction="purchase", transaction_kind="일시불",
                 amount_krw=14280, approval_date="2026-09-29", posting_date="2026-09-29", foreign_currency="")
    value.update(changes)
    return value


def test_domestic_travel_hold_and_inference_without_trip_fall_to_the_quarter_residual():
    for source in ("travel_location_hold", "inference"):
        verdict = dict(classification_source=source, classification_state="needs_review", trip_id="",
                       display_tab_id="", item="", description="")
        result = _card3820_residual(purchase(), verdict)
        assert result["display_tab_id"] == "quarter:2026:3"
        assert result["classification_source"] == "owner_card_residual"


def test_foreign_travel_hold_waits_for_the_location_check():
    verdict = dict(classification_source="travel_location_hold", classification_state="needs_review",
                   trip_id="", display_tab_id="", item="", description="")
    result = _card3820_residual(purchase(foreign_currency="JPY"), verdict)
    assert result is verdict


def test_refund_takes_the_original_purchase_placement():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE transactions (transaction_id, card_tail, approval_number, original_approval_number,"
                 " transaction_direction, approval_date, classification_state, classification_source,"
                 " classification_basis, display_tab_id, trip_id, item, description)")
    conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("orig", "3820", "30058533", "", "purchase", "2026-05-29", "classified", "inference", "", "trip-x", "trip-x", "항공료", ""),
        ("refund", "3820", "30058999", "30058533", "cancellation", "2026-06-01", "classified", "", "", "", "", "", ""),
    ])
    assert pair_refunds(conn) == 1
    assert conn.execute("SELECT display_tab_id, trip_id, item, classification_source FROM transactions"
                        " WHERE transaction_id='refund'").fetchone() == ("trip-x", "trip-x", "항공료", "refund_original")
