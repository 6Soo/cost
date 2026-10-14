"""Synthetic coverage for the user-approved Trip.com vocabulary correction."""
from copy import deepcopy

import pytest

from app.ota_matching_defaults import load_defaults
from app.ota_payments import _descriptor_matches, match_ota_payment_events


EXACT_MERCHANT = "대표_카카오페이-트립닷컴"


def event(identity="event-a", **changes):
    value = dict(ota_event_id=identity, provider="trip", booking_ref="SYNTHETIC",
                 item="항공료", event_type="charge", paid_on="2026-09-04",
                 amount=30000, amount_krw=30000, currency="KRW", card_last4=None,
                 evidence_status="paid_verified", payment_status="paid",
                 source_digest=identity, source_ids=[f"synthetic:{identity}"])
    value.update(changes)
    return value


def card(identity="card-a", **changes):
    value = dict(transaction_id=identity, merchant=EXACT_MERCHANT,
                 merchant_normalized=EXACT_MERCHANT, issuer="Synthetic Bank",
                 card_tail="2042", approval_date="2026-09-04", amount_krw=26000,
                 transaction_direction="purchase", source_hash=identity)
    value.update(changes)
    return value


@pytest.mark.parametrize("item", ["항공", "항공권", "flight", "airfare", "항공료"])
def test_all_approved_flight_vocabulary_uses_the_existing_delta_rule(item):
    result = match_ota_payment_events([event(item=item)], [card()])[0]
    assert result["status"] == "MATCHED_AUTO"
    assert result["reason"] == "approved_trip_flight_delta"
    assert result["discount_cause_confirmed"] is False


def test_exact_descriptor_has_versioned_explicit_user_provenance():
    records = load_defaults()["provider_merchant_alias_records"]["trip"]
    approved = [record for record in records if record["status"] == "approved"]
    assert {"alias": EXACT_MERCHANT, "status": "approved", "version": 2,
            "source": "user-approved-trip-airfare-exact-descriptor-2026-10-09"} in approved
    assert {record["alias"] for record in records if record["status"] == "candidate"} == {
        "trip.com", "trip.com korea"}
    assert _descriptor_matches(event(), card())


def test_the_card_descriptor_approved_on_2026_10_14_is_exact_and_versioned():
    records = load_defaults()["provider_merchant_alias_records"]["trip"]
    assert {"alias": "트립닷컴(구)_NICE", "status": "approved", "version": 1,
            "source": "user-approved-trip-card-descriptor-2026-10-14"} in records
    assert _descriptor_matches(event(), card(merchant="트립닷컴(구)_NICE", merchant_normalized="트립닷컴(구)_nice"))
    assert not _descriptor_matches(event(), card(merchant="트립닷컴_이니시스", merchant_normalized="트립닷컴_이니시스"))


@pytest.mark.parametrize("merchant", ["트립닷컴", "TRIP.COM", "trip.com korea", "네이버페이-트립닷컴"])
def test_other_trip_descriptors_do_not_inherit_the_new_approval(merchant):
    transaction = card(merchant=merchant, merchant_normalized=merchant.casefold())
    assert not _descriptor_matches(event(), transaction)
    result = match_ota_payment_events([event()], [transaction])[0]
    assert result["status"].startswith("HOLD")


@pytest.mark.parametrize("delta", range(-10000, 0, 1000))
def test_existing_discount_range_and_thousand_won_steps_are_preserved(delta):
    result = match_ota_payment_events([event()], [card(amount_krw=30000 + delta)])[0]
    assert result["status"] == "MATCHED_AUTO"
    assert result["reason"] == "approved_trip_flight_delta"
    assert result["rule_delta_krw"] == delta


@pytest.mark.parametrize("delta", [-11000, -10500, -4500, -500, 1000])
def test_amounts_outside_the_approved_steps_remain_on_hold(delta):
    result = match_ota_payment_events([event()], [card(amount_krw=30000 + delta)])[0]
    assert result["status"] != "MATCHED_AUTO"


@pytest.mark.parametrize("changes,transaction_changes", [
    ({"item": "숙박비"}, {}),
    ({"event_type": "refund", "refund_status": "refunded"},
     {"transaction_direction": "refund", "amount_krw": -26000}),
    ({"provider": "agoda"}, {}),
])
def test_the_flight_discount_does_not_expand_to_lodging_refunds_or_other_providers(
        changes, transaction_changes):
    result = match_ota_payment_events([event(**changes)], [card(**transaction_changes)])[0]
    assert result["status"] != "MATCHED_AUTO"


def test_exact_amount_priority_is_preserved_in_a_complete_allocation():
    events = [event("first", booking_ref="SYNTHETIC-A", card_last4="2042"),
              event("second", booking_ref="SYNTHETIC-B", amount=34000,
                    amount_krw=34000, card_last4="2042")]
    results = {result["ota_event_id"]: result for result in match_ota_payment_events(
        events, [card("exact", amount_krw=30000), card("discount", amount_krw=26000)])}
    assert results["first"]["status"] == results["second"]["status"] == "MATCHED_AUTO"
    assert results["first"]["transaction_id"] == "exact"
    assert results["second"]["transaction_id"] == "discount"


def test_multiple_discount_candidates_remain_on_hold_without_an_arbitrary_choice():
    result = match_ota_payment_events([event()], [card("one"), card("two")])[0]
    assert result["status"].startswith("HOLD")
    assert result.get("transaction_id") is None
    assert set(result["candidates"]) == {"one", "two"}


def test_an_existing_exact_card_cannot_be_reused_by_the_new_descriptor():
    events = [event("existing"), event("new", booking_ref="SYNTHETIC-NEW")]
    results = {result["ota_event_id"]: result for result in match_ota_payment_events(
        events, [card("occupied")], existing_links={
            "existing": {"transaction_id": "occupied", "status": "MATCHED_AUTO"}})}
    assert results["existing"]["transaction_id"] == "occupied"
    assert results["new"]["status"].startswith("HOLD")
    assert results["new"].get("transaction_id") is None


def test_matching_never_invents_an_ota_card_tail_or_changes_source_facts():
    original = event()
    transaction = card()
    before = deepcopy((original, transaction))
    result = match_ota_payment_events([original], [transaction])[0]
    assert result["status"] == "MATCHED_AUTO"
    assert result["card_last4"] is None
    assert (original, transaction) == before
    assert result["amount_krw"] == 30000
    assert result["paid_on"] == "2026-09-04"


def test_known_ota_card_tail_is_still_a_strict_boundary():
    result = match_ota_payment_events([event(card_last4="9999")], [card()])[0]
    assert result["status"] != "MATCHED_AUTO"
