"""Financial-output regression coverage for the OTA matcher decomposition."""

from tests.card_pipeline.test_ota_payments import card, event
from app.ota_payments import match_ota_payment_events


def test_prepared_edges_keep_exact_repeated_payment_group_allocations():
    bookings = [
        event("prepared-a", booking_ref="BOOK-A"),
        event("prepared-b", booking_ref="BOOK-B", amount="30000.00", amount_krw="30000.00"),
    ]
    cards = [card("prepared-card-a", approval_number="1001"),
             card("prepared-card-b", approval_number="1002")]

    results = match_ota_payment_events(bookings, cards)

    assert {(row["ota_event_id"], row["transaction_id"], row["status"]) for row in results} == {
        ("prepared-a", "prepared-card-a", "MATCHED_AUTO"),
        ("prepared-b", "prepared-card-b", "MATCHED_AUTO"),
    }
    assert all(row["individual_payment_evidence"] is False for row in results)
    assert all(row["group_count"] == {"ota": 2, "cards": 2} for row in results)


def test_prepared_edges_respect_frozen_group_mapping_and_manual_links():
    bookings = [event("frozen-a", booking_ref="BOOK-A"),
                event("frozen-b", booking_ref="BOOK-B")]
    cards = [card("frozen-card-a", approval_number="1001"),
             card("frozen-card-b", approval_number="1002")]
    frozen = {"event_ids": ["frozen-a", "frozen-b"],
              "card_ids": ["frozen-card-a", "frozen-card-b"],
              "mapping": {"frozen-a": "frozen-card-b", "frozen-b": "frozen-card-a"}}

    results = match_ota_payment_events(
        bookings, cards, frozen_groups=[frozen])

    by_id = {row["ota_event_id"]: row for row in results}
    assert (by_id["frozen-a"]["status"], by_id["frozen-a"]["transaction_id"]) == (
        "MATCHED_AUTO", "frozen-card-b")
    assert (by_id["frozen-b"]["status"], by_id["frozen-b"]["transaction_id"]) == (
        "MATCHED_AUTO", "frozen-card-a")
    assert by_id["frozen-b"]["allocation_basis"] == "frozen_user_confirmed_order"


def test_prepared_edges_preserve_manual_link_identity():
    booking = event("manual-event")
    manual = {"manual-event": {"transaction_id": "manual-card", "status": "MATCHED_USER"}}

    result = match_ota_payment_events([booking], [card("manual-card")], existing_links=manual)[0]

    assert (result["status"], result["transaction_id"]) == ("MATCHED_USER", "manual-card")
    assert result["reason"] == "pinned_existing_link"
