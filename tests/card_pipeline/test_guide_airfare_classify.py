"""The guide-airfare rule is a distinct, evidence-based classification source."""
from app.classify import classify_transaction

MERCHANT = "대표_카카오페이-트립닷컴"


def card(**changes):
    value = {"transaction_id": "card-1", "source_hash": "hash-1", "merchant": MERCHANT,
             "merchant_normalized": MERCHANT, "card_kind": "credit", "transaction_direction": "purchase",
             "approval_date": "2026-05-18", "amount_krw": 1081000, "parse_error": ""}
    value.update(changes)
    return value


def guide_rule(trip_id="trip-1"):
    return {"conditions": {"merchant_normalized": MERCHANT, "card_kind": "credit",
                           "transaction_direction": "purchase"},
            "optional": {"source_hash": "hash-1",
                         "inferred_assignment": {"trip_id": trip_id, "confidence": "높음",
                                                 "basis": "여행 시작 전 출국 · 탑승자 대장 확인 · 여행 0801_북해도 · 근거 aaaaaaaaaaaa"}},
            "effects": {"item": "항공료", "description": "예약 REF1"},
            "origin": "guide-airfare-live", "rule_id": "guide-airfare-hash-1"}


def resolver(valid):
    return lambda transaction, target: target["inferred_trip_id"] if target["inferred_trip_id"] in valid else ""


def test_a_guide_rule_classifies_with_its_own_source_and_readable_basis():
    verdict = classify_transaction(card(), rules=[guide_rule()], trip_resolver=resolver({"trip-1"}))
    assert verdict["classification_source"] == "guide_airfare_evidence"
    assert (verdict["item"], verdict["trip_id"], verdict["display_tab_id"]) == ("항공료", "trip-1", "trip-1")
    assert verdict["classification_basis"].startswith("대장·가이드 항공권 근거 · ")
    assert "탑승자 대장 확인" in verdict["classification_basis"]
    assert verdict["description"] == "예약 REF1"


def test_a_trip_that_stopped_being_authoritative_returns_to_review():
    verdict = classify_transaction(card(), rules=[guide_rule()], trip_resolver=resolver(set()))
    assert verdict["classification_state"] == "needs_review"
    assert verdict["trip_id"] == ""


def test_a_user_decision_is_never_overwritten():
    prior = {"item": "교통비", "description": "직접 입력", "display_tab_id": "trip-9", "trip_id": "trip-9"}
    verdict = classify_transaction(card(), rules=[guide_rule()], prior_decision=prior,
                                   trip_resolver=resolver({"trip-1"}))
    assert verdict["classification_source"] == "previous_decision"
    assert verdict["trip_id"] == "trip-9"


def test_a_refund_row_does_not_match_a_purchase_guide_rule():
    refund = card(transaction_direction="refund", amount_krw=-760200)
    verdict = classify_transaction(refund, rules=[guide_rule()], trip_resolver=resolver({"trip-1"}))
    assert verdict["classification_source"] != "guide_airfare_evidence"
    assert verdict["trip_id"] == ""


def test_a_different_card_row_does_not_receive_the_rule():
    verdict = classify_transaction(card(source_hash="other"), rules=[guide_rule()],
                                   trip_resolver=resolver({"trip-1"}))
    assert verdict["classification_source"] != "guide_airfare_evidence"


def test_two_disagreeing_assignments_stay_in_review():
    verdict = classify_transaction(card(), rules=[guide_rule("trip-1"), guide_rule("trip-2")],
                                   trip_resolver=resolver({"trip-1", "trip-2"}))
    assert verdict["classification_source"] == "inference_conflict"
    assert verdict["classification_state"] == "needs_review"
