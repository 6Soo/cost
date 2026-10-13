import pytest

from app.google_tsv import expense_tsv
from app.receipt_candidates import Region, build_candidates, classify, to_expense_rows


def region(box, **over):
    base = {"page_id": "scan-1", "box": box, "merchant": "RAMEN-SYN", "date": "2027-08-03", "currency": "JPY",
            "total": 1234, "payment": "cash", "confidence": 0.95}
    base.update(over)
    return Region(**base)


PAGE = [region((0, 0, 100, 100)), region((110, 0, 210, 100), merchant="STATION-SYN", total=500, payment="private_card"),
        region((0, 110, 100, 210), merchant="CAFE-SYN", total=900, payment="corporate_card")]
CARD = [{"transaction_id": "card-9", "date": "2027-08-03", "merchant": "CAFE-SYN", "original_jpy": 900}]


def test_one_a4_page_becomes_one_candidate_per_receipt_with_ledger_rate():
    result = build_candidates(PAGE, CARD)
    by_merchant = {c.merchant: c for c in result["candidates"]}
    assert set(by_merchant) == {"RAMEN-SYN", "STATION-SYN", "CAFE-SYN"}
    assert by_merchant["CAFE-SYN"].card_transaction_id == "card-9" and by_merchant["CAFE-SYN"].amount_krw is None
    assert by_merchant["RAMEN-SYN"].amount_krw == 12340  # 1 JPY = 10 KRW, cash
    assert by_merchant["STATION-SYN"].amount_krw == 5000  # private card receipt, same simple rate
    assert by_merchant["RAMEN-SYN"].total_jpy == 1234  # original JPY kept


def test_unclear_regions_are_held_with_reasons_not_pasted():
    page = [region((0, 0, 100, 100), confidence=0.5),
            region((200, 0, 300, 100), total=None),
            region((400, 0, 500, 100), currency="USD"),
            region((600, 0, 700, 100), payment=None),
            region((0, 300, 100, 400)), region((50, 300, 150, 400), merchant="OVERLAP-SYN")]
    result = build_candidates(page, [])
    reasons = sorted(h["reason"] for h in result["holds"])
    assert reasons == ["CURRENCY_UNKNOWN", "LOW_CONFIDENCE", "OVERLAP", "OVERLAP", "PAYMENT_UNKNOWN", "TOTAL_UNCLEAR"]
    assert result["candidates"] == []


def test_corporate_receipt_needs_exactly_one_card_transaction():
    ambiguous = build_candidates([PAGE[2]], CARD + [dict(CARD[0], transaction_id="card-10")])
    assert ambiguous["holds"][0]["reason"] == "CARD_MATCH_AMBIGUOUS"
    missing = build_candidates([PAGE[2]], [])
    assert missing["holds"][0]["reason"] == "CARD_NOT_FOUND"


def test_rescanned_same_receipt_is_one_candidate():
    first = build_candidates([PAGE[0], PAGE[0]], [])
    assert len(first["candidates"]) == 1
    again = build_candidates([PAGE[0]], [], known={first["candidates"][0].identity})
    assert again["candidates"] == []


def test_machine_reading_has_no_payee_or_category_until_a_person_sets_them():
    candidate = build_candidates([PAGE[0]], [])["candidates"][0]
    assert candidate.payee is None and candidate.category is None
    rows = to_expense_rows([candidate])
    assert rows[0]["status"] == "not_ready"
    with pytest.raises(ValueError, match="FIELD_MISSING"):
        classify(candidate, payee="", category="식비")
    classify(candidate, payee="RAMEN-SYN", category="식비", note="현지 식사")
    assert candidate.history[0]["to"] == {"payee": "RAMEN-SYN", "category": "식비"}


def test_classified_receipts_paste_as_evidence_rows_and_card_match_is_not_doubled():
    candidates = build_candidates(PAGE, CARD)["candidates"]
    for c in candidates:
        classify(c, payee=c.merchant, category="식비" if c.merchant == "RAMEN-SYN" else "교통비")
    result = expense_tsv(to_expense_rows(candidates), layout="rev")
    assert result["row_count"] == 2 and result["total_krw"] == 17340
    assert "\t영수증\t12340" in result["tsv"]
    assert "CAFE-SYN" not in result["tsv"]  # the card transaction is the one expense
