from app.ota_payments import (_merge_proven_duplicate_payments, match_ota_payment_events,
                              same_date_cards)


def event(identity="evt-1", **changes):
    row = {
        "ota_event_id": identity, "provider": "trip", "booking_ref": "BOOK-1",
        "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000",
        "currency": "KRW", "amount_krw": 30000, "card_last4": "2042",
        "item": "항공권", "evidence_status": "paid_verified", "payment_status": "paid",
        "source_digest": identity, "source_ids": [f"mail:{identity}"],
        "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
    }
    row.update(changes)
    return row


def card(identity="card-1", **changes):
    row = {
        "transaction_id": identity, "merchant": "TRIP.COM", "merchant_normalized": "trip.com",
        "issuer": "Bank A", "card_tail": "2042", "approval_date": "2026-09-04",
        "amount_krw": 30000, "transaction_direction": "purchase",
    }
    row.update(changes)
    return row


def match(events, cards, **kwargs):
    return match_ota_payment_events(events, cards, **kwargs)


def test_missing_payment_date_never_exposes_card_candidates():
    result = match([event(paid_on=None)], [card()])[0]
    assert result["status"] == "HOLD_DATE_UNKNOWN"
    assert result["candidates"] == []


def test_provider_alias_covers_products_without_becoming_an_item_rule():
    result = match([event(item="숙박")], [card()])[0]
    assert result["status"] == "MATCHED_AUTO"


def test_provider_alias_requires_a_complete_merchant_token():
    result = match([event(card_last4=None)],
                   [card(merchant="nottrip.commercial", merchant_normalized="nottrip.commercial")])[0]
    assert result["status"] == "HOLD_NO_CARD"


def test_card_tail_and_issuer_must_both_match_ota_card_facts():
    result = match([event(card_last4="2042", card_issuer="Bank A")],
                   [card(issuer="Bank B")])[0]
    assert result["status"] == "HOLD_NO_CARD"


def test_comparable_authorization_numbers_are_strict():
    result = match([event(authorization_number="AUTH-01", authorization_scheme="scheme-a")],
                   [card(authorization_number="AUTH-02", authorization_scheme="scheme-a")])[0]
    assert result["status"] == "HOLD_NO_CARD"


def test_trip_flight_approved_discount_has_exact_steps_and_never_claims_cause():
    row = card(amount_krw=22000)
    result = match([event(amount_krw=30000, amount="30000")], [row])[0]
    assert result["status"] == "MATCHED_AUTO"
    assert result["reason"] == "approved_trip_flight_delta"
    assert result["discount_cause_confirmed"] is False
    assert result["rule_delta_krw"] == -8000


def test_trip_discount_is_rejected_for_non_step_or_non_flight():
    non_step = match([event(amount_krw=30000, amount="30000")], [card(amount_krw=23500)])[0]
    lodging = match([event(item="숙박", amount_krw=30000, amount="30000")],
                    [card(amount_krw=22000)])[0]
    assert non_step["status"] != "MATCHED_AUTO"
    assert lodging["status"] != "MATCHED_AUTO"


def test_percent_discount_requires_a_fully_scoped_approved_rule_and_minor_unit_rounding():
    from app.ota_payments import _rule_scope_valid
    from app.ota_matching_defaults import load_defaults
    conditions = {"provider":"trip", "item":"airfare", "merchant_normalized":"trip.com",
        "payment_method":"credit", "valid_from":"2026-09-01", "valid_to":"2026-09-30",
        "minimum_amount_krw":10000, "discount_rate_bps":1000, "discount_cap_krw":5000,
        "rounding_mode":"half_up"}
    rule = {"active":True, "approved_by":"synthetic-owner", "conditions":conditions}
    sample = event(item="airfare", amount="27999", amount_krw=27999, card_last4=None)
    exact_card = card(amount_krw=25199, payment_method="credit")
    assert load_defaults()["trip_flight_charge_delta"]["enabled"] is True
    assert _rule_scope_valid(conditions)
    assert match([sample], [exact_card], rules=[rule])[0]["status"] == "MATCHED_AUTO"
    assert match([sample], [exact_card], rules=[])[0]["status"] != "MATCHED_AUTO"
    capped = {**conditions, "discount_cap_krw":1000}
    assert match([sample], [card(amount_krw=26999, payment_method="credit")],
                 rules=[{**rule, "conditions":capped}])[0]["status"] == "MATCHED_AUTO"
    assert match([event(item="airfare", amount="9999", amount_krw=9999,
                        card_last4=None)], [card(amount_krw=8999, payment_method="credit")],
                 rules=[rule])[0]["status"] != "MATCHED_AUTO"
    assert match([event(item="airfare", paid_on="2026-10-01", card_last4=None)],
                 [card(amount_krw=27000, payment_method="credit")], rules=[rule])[0]["status"] != "MATCHED_AUTO"
    assert match([sample], [card(amount_krw=25199, payment_method="debit")],
                 rules=[rule])[0]["status"] != "MATCHED_AUTO"
    incomplete = dict(conditions)
    incomplete.pop("rounding_mode")
    assert not _rule_scope_valid(incomplete)
    malformed = {**conditions, "valid_from":"not-a-date"}
    assert not _rule_scope_valid(malformed)


def test_percent_discount_rounding_modes_use_exact_krw_minor_units():
    rule_base = {"provider":"trip", "item":"airfare", "merchant_normalized":"trip.com",
        "payment_method":"credit", "valid_from":"2026-09-01", "valid_to":"2026-09-30",
        "minimum_amount_krw":10000, "discount_rate_bps":500, "discount_cap_krw":5000}
    for amount, expected in ((10001, {"floor":500, "half_up":500, "ceiling":501}),
                             (10010, {"floor":500, "half_up":501, "ceiling":501})):
        for mode, discount in expected.items():
            rule = {"active":True, "approved_by":"synthetic-owner",
                    "conditions":{**rule_base, "rounding_mode":mode}}
            sample = event(item="airfare", amount=str(amount), amount_krw=amount, card_last4=None)
            transaction = card(amount_krw=amount-discount, payment_method="credit")
            assert match([sample], [transaction], rules=[rule])[0]["status"] == "MATCHED_AUTO"


def test_agoda_dot_com_alias_has_an_explicit_versioned_source_record():
    from app.ota_matching_defaults import load_defaults
    record = load_defaults()["provider_merchant_alias_records"]["agoda"][0]
    assert record == {"alias":"AGODA.COM", "status":"approved", "version":1,
                      "source":"user-selected-default-2026-10-08"}
    trip_records = load_defaults()["provider_merchant_alias_records"]["trip"]
    assert {item["alias"] for item in trip_records if item["status"] == "approved"} == {
        "대표_카카오페이-트립닷컴", "트립닷컴(구)_NICE"}
    assert all(item["status"] == "candidate" for item in trip_records
               if item["alias"] in {"trip.com", "trip.com korea"})
    result = match([event(provider="agoda", card_last4=None)],
                   [card(merchant="AGODA.COM", merchant_normalized="agoda.com")])[0]
    assert result["status"] == "MATCHED_AUTO"


def test_event_issuer_alias_requires_its_own_user_approved_versioned_rule():
    sample = event(card_issuer="Synthetic Issuer Alias")
    transaction = card(issuer="Bank A")
    assert match([sample], [transaction])[0]["status"] == "HOLD_NO_CARD"
    issuer_rule = {"active":True, "approved_by":"synthetic-owner", "conditions":{
        "rule_kind":"issuer_alias", "provider":"trip", "event_issuer_alias":"Synthetic Issuer Alias",
        "issuer":"Bank A", "approval_source":"synthetic-card-statement", "alias_version":1}}
    revoked = {**issuer_rule, "active":False}
    assert match([sample], [transaction], rules=[revoked])[0]["status"] == "HOLD_NO_CARD"
    assert match([sample], [transaction], rules=[issuer_rule])[0]["status"] == "MATCHED_AUTO"


def test_inactive_dynamic_provider_alias_does_not_corroborate_a_candidate():
    sample = event(card_last4=None)
    transaction = card(merchant="SYNTHETIC TRAVEL DESK", merchant_normalized="synthetic travel desk")
    rule = {"active":True, "approved_by":"synthetic-owner", "conditions":{
        "rule_kind":"provider_alias", "provider":"trip", "alias":"synthetic travel desk",
        "approval_source":"synthetic-source", "alias_version":1}}
    assert match([sample], [transaction], rules=[{**rule, "status":"revoked"}])[0]["status"] == "HOLD_NO_CARD"
    assert match([sample], [transaction], rules=[rule])[0]["status"] == "MATCHED_AUTO"


def test_approved_event_issuer_alias_survives_repeated_group_validation():
    events = [event(f"evt-alias-{index}", booking_ref=f"BOOK-ALIAS-{index}",
                    card_issuer="Synthetic issuer name") for index in range(2)]
    cards = [card(f"card-alias-{index}", authorization_number=f"AUTH-{index}", issuer="Bank A")
             for index in range(2)]
    rule = {"active":True, "approved_by":"synthetic-owner", "conditions":{
        "rule_kind":"issuer_alias", "provider":"trip", "event_issuer_alias":"Synthetic issuer name",
        "issuer":"Bank A", "approval_source":"synthetic-statement", "alias_version":1}}
    result = match(events, cards, rules=[rule])
    assert {row["status"] for row in result} == {"MATCHED_AUTO"}
    assert all(row["group_count"] == {"ota":2, "cards":2} for row in result)


def test_signed_date_lag_rule_preserves_direction():
    rules = [{"active": True, "approved_by": "owner", "conditions": {
        "provider": "trip", "item": "항공권", "merchant_normalized": "trip.com",
        "date_lag_days": -2,
    }}]
    earlier = match([event(paid_on="2026-09-04")],
                    [card(approval_date="2026-09-02")], rules=rules)[0]
    later = match([event(paid_on="2026-09-04")],
                  [card(approval_date="2026-09-06")], rules=rules)[0]
    assert earlier["status"] == "MATCHED_AUTO"
    assert later["status"] != "MATCHED_AUTO"


def test_same_date_cards_lists_every_day_inside_signed_lag_range():
    rules = [{"active": True, "approved_by": "owner", "conditions": {
        "provider": "trip", "item": "항공권", "merchant_normalized": "trip.com",
        "date_lag_days": 2,
    }}]
    rows = [card(f"d{i}", approval_date=f"2026-09-0{i}") for i in range(2, 7)]
    assert {r["transaction_id"] for r in same_date_cards(event(), rows, rules=rules)} == {
        "d4", "d5", "d6"}
    rules[0]["conditions"]["date_lag_days"] = -2
    assert {r["transaction_id"] for r in same_date_cards(event(), rows, rules=rules)} == {
        "d2", "d3", "d4"}


def test_exact_edges_do_not_remove_approved_discount_edges_from_repeated_group():
    events = [event(f"evt-{i}", booking_ref=f"BOOK-{i}") for i in range(3)]
    cards = [card("exact-a"), card("discount", amount_krw=28000), card("exact-b")]
    result = match(events, cards)
    assert {row["status"] for row in result} == {"MATCHED_AUTO"}
    assert sum(row["rule_delta_krw"] == -2000 for row in result) == 1


def test_exact_edges_are_assigned_before_delta_edges_for_unequal_repeated_amounts():
    events = [event("exact", booking_ref="BOOK-A", card_last4="2042"),
              event("higher", booking_ref="BOOK-B", amount="34000", amount_krw=34000,
                    card_last4=None, card_issuer=None)]
    cards = [card("card-a", card_tail="2042"), card("card-b", card_tail="9999")]
    alias_rule = {"active":True, "approved_by":"synthetic-owner", "conditions":{
        "rule_kind":"provider_alias", "provider":"trip", "alias":"trip.com",
        "approval_source":"synthetic-approved", "alias_version":1}}
    results = match(events, cards, rules=[alias_rule])
    by_id = {row["ota_event_id"]: row for row in results}
    assert by_id["exact"]["transaction_id"] == "card-a"
    assert by_id["higher"]["transaction_id"] == "card-b"


def test_partial_group_reserves_every_card_against_an_overlapping_group():
    first = [event(f"a{i}", booking_ref=f"A-{i}") for i in range(3)]
    second = [event(f"b{i}", booking_ref=f"B-{i}", item="숙박") for i in range(2)]
    cards = [card("shared-a"), card("shared-b")]
    results = match(first + second, cards)
    assert {row["status"] for row in results} == {"HOLD_AMBIGUOUS"}
    assert all(row.get("transaction_id") is None for row in results)
    reversed_results = match(list(reversed(first + second)), list(reversed(cards)))
    assert {row["ota_event_id"]:row["status"] for row in reversed_results} == {
        row["ota_event_id"]:row["status"] for row in results}
    assert all(row.get("transaction_id") is None for row in reversed_results)


def test_group_signature_ignores_missing_ota_card_facts_but_requires_one_card_identity():
    events = [event("known-a", booking_ref="BOOK-A", card_last4="2042", card_issuer="Bank A"),
              event("known-b", booking_ref="BOOK-B", card_last4="2042", card_issuer="Bank A"),
              event("missing", booking_ref="BOOK-C", card_last4=None, card_issuer=None)]
    alias_rule = {"active":True, "approved_by":"synthetic-owner", "conditions":{
        "rule_kind":"provider_alias", "provider":"trip", "alias":"trip.com",
        "approval_source":"synthetic-approved", "alias_version":1}}
    results = match(events, [card("c-a", authorization_number="AUTH-A"),
                             card("c-b", authorization_number="AUTH-B"),
                             card("c-c", authorization_number="AUTH-C")], rules=[alias_rule])
    assert {row["status"] for row in results} == {"HOLD_GROUP_CONFIRMATION_REQUIRED"}
    assert all(row["allocation_basis"] == "user_confirmed_group_required" for row in results)
    assert all(row["group_count"] == {"ota":3, "cards":3} for row in results)


def test_missing_issuer_with_same_tail_across_issuers_is_ambiguous():
    result = match([event(card_issuer=None)], [card("a", issuer="Bank A"),
                                               card("b", issuer="Bank B")])[0]
    assert result["status"] == "HOLD_AMBIGUOUS"


def test_one_ota_with_two_same_card_candidates_is_a_reserved_partial_group():
    result = match([event()], [card("a"), card("b")])[0]
    assert result["status"] == "HOLD_PARTIAL_GROUP"
    assert result["group_count"] == {"ota": 1, "cards": 2}
    assert result["card_group_ids"] == ["a", "b"]
    assert result["reserved_card_ids"] == ["a", "b"]


def test_same_comparable_ota_payment_id_is_strong_corroboration():
    row = card(payment_id="PAY-123", payment_id_scheme="trip-payment-v1")
    result = match([event(card_last4=None, payment_id="PAY-123",
                         payment_id_scheme="trip-payment-v1")], [row])[0]
    assert result["status"] == "MATCHED_AUTO"


def test_same_explicit_payment_id_conflicting_source_facts_fail_closed():
    left = event("mail-event", payment_id="PAYMENT-1", source_ids=["mail:1"])
    right = event("portal-event", payment_id="PAYMENT-1", amount_krw=31000,
                  amount="31000", source_ids=["portal:1"])
    merged = _merge_proven_duplicate_payments([left, right])
    assert len(merged) == 1
    assert merged[0]["evidence_status"] == "evidence_conflict"
    assert set(merged[0]["source_ids"]) == {"mail:1", "portal:1"}


def test_explicit_source_binding_with_conflicting_facts_fails_closed():
    left = event("mail-event", source_ids=["mail:1"], source_binding_ids=["portal:record:1"])
    right = event("portal-event", amount_krw=31000, amount="31000",
                  source_ids=["portal:record:1"])
    merged = _merge_proven_duplicate_payments([left, right])
    assert len(merged) == 1
    assert merged[0]["evidence_status"] == "evidence_conflict"


def test_partial_repeated_group_preserves_all_ids_and_blocks_individual_posting():
    events = [event(f"evt-{i}", booking_ref=f"BOOK-{i}") for i in range(3)]
    cards = [card(f"card-{i}") for i in range(2)]
    results = match(events, cards)
    assert all(row["status"] == "HOLD_PARTIAL_GROUP" for row in results)
    assert all(row["matched_count"] == 2 for row in results)
    assert all(row["ota_group_ids"] == ["evt-0", "evt-1", "evt-2"] for row in results)
    assert all(row["card_group_ids"] == ["card-0", "card-1"] for row in results)
    assert all(row.get("transaction_id") is None for row in results)


def test_two_ota_one_card_keeps_ambiguous_status_with_exact_partial_counts_and_reservation():
    events = [event("one-card-a", booking_ref="A"), event("one-card-b", booking_ref="B")]
    results = match(events, [card("only-card")])
    assert {row["status"] for row in results} == {"HOLD_AMBIGUOUS"}
    assert all(row["group_count"] == {"ota":2, "cards":1} for row in results)
    assert all(row["matched_count"] == 1 for row in results)
    assert all(row["unmatched_ota_count"] == 1 and row["unmatched_card_count"] == 0 for row in results)
    assert all(row["ota_group_ids"] == ["one-card-a", "one-card-b"] for row in results)
    assert all(row["card_group_ids"] == ["only-card"] for row in results)
    assert all(row["reserved_card_ids"] == ["only-card"] for row in results)


def test_complete_group_uses_stable_user_approved_order_and_preserves_periods():
    events = [event("evt-z", booking_ref="BOOK-Z", service_period={"starts_on": "2026-10-10", "ends_on": "2026-10-12"}),
              event("evt-a", booking_ref="BOOK-A", service_period={"starts_on": "2026-10-01", "ends_on": "2026-10-03"})]
    cards = [card("card-z", authorization_number="AUTH-Z"),
             card("card-a", authorization_number="AUTH-A")]
    results = match(events, cards)
    by_id = {row["ota_event_id"]: row for row in results}
    assert by_id["evt-a"]["transaction_id"] == "card-a"
    assert by_id["evt-a"]["allocation_basis"] == "user_approved_stable_order"
    assert by_id["evt-a"]["individual_payment_evidence"] is False
    assert by_id["evt-a"]["service_period"] == {"starts_on": "2026-10-01", "ends_on": "2026-10-03"}


def test_stable_group_tiebreak_uses_approval_order_after_booking_order():
    events = [event("e1", booking_ref="A"), event("e2", booking_ref="B")]
    cards = [card("a", approval_number="Z"), card("z", approval_number="A")]
    by_id = {row["ota_event_id"]:row["transaction_id"] for row in match(events, cards)}
    assert by_id == {"e1":"z", "e2":"a"}


def test_repeated_group_never_crosses_issuer_or_card_tail():
    events = [event("evt-a", booking_ref="BOOK-A"), event("evt-b", booking_ref="BOOK-B")]
    cards = [card("card-a", issuer="Bank A"), card("card-b", issuer="Bank B")]
    results = match(events, cards)
    assert all(row["status"] == "HOLD_AMBIGUOUS" for row in results)
    assert all(row.get("allocation_basis") != "user_approved_stable_order" for row in results)


def test_globally_pinned_links_keep_exact_allocation():
    events = [event("evt-pinned"), event("evt-new", source_ids=["mail:new"], amount_krw=25000, amount="25000")]
    cards = [card("card-pinned"), card("card-free", amount_krw=25000)]
    results = match(events, cards, existing_links={"evt-pinned": {"transaction_id": "card-pinned", "status": "MATCHED_USER"}})
    assert next(row for row in results if row["ota_event_id"] == "evt-pinned")["transaction_id"] == "card-pinned"
    assert next(row for row in results if row["ota_event_id"] == "evt-new")["transaction_id"] == "card-free"


def test_card_claimed_by_an_absent_linked_event_is_excluded_from_repeated_group():
    events = [event("e1", booking_ref="A"), event("e2", booking_ref="B")]
    cards = [card("a"), card("b")]
    results = match(events, cards, existing_links={
        "absent-event": {"transaction_id":"a", "status":"MATCHED_USER"}})
    assert {row["status"] for row in results} == {"HOLD_AMBIGUOUS"}
    assert all(row.get("transaction_id") is None for row in results)
    assert all(row["group_count"] == {"ota":2, "cards":1} for row in results)
    assert all(row["matched_count"] == 1 for row in results)
    assert all("a" not in row.get("reserved_card_ids", []) for row in results)


def test_repeated_events_with_distinct_known_cards_form_separate_groups():
    events = [event("e1", booking_ref="A", card_last4="2042"),
              event("e2", booking_ref="B", card_last4="9999")]
    cards = [card("a", card_tail="2042"), card("b", card_tail="9999")]
    by_id = {row["ota_event_id"]:row for row in match(events, cards)}
    assert by_id["e1"]["status"] == "MATCHED_AUTO"
    assert by_id["e1"]["transaction_id"] == "a"
    assert by_id["e2"]["status"] == "MATCHED_AUTO"
    assert by_id["e2"]["transaction_id"] == "b"


def test_frozen_group_cards_stay_reserved_when_the_source_events_are_missing():
    pin = {"event_ids":["old-1", "old-2"], "card_ids":["p-a", "p-b"],
           "mapping":{"old-1":"p-a", "old-2":"p-b"}, "order_snapshot":{}}
    results = match([event("new-event")], [card("p-a"), card("p-b"), card("free")],
                    frozen_groups=[pin])
    assert results[0]["status"] == "MATCHED_AUTO"
    assert results[0]["transaction_id"] == "free"


def test_frozen_group_signature_change_holds_members_and_keeps_cards_reserved():
    pin = {"event_ids":["e1", "e2"], "card_ids":["a", "b"],
           "mapping":{"e1":"a", "e2":"b"}, "order_snapshot":{}}
    events = [event("e1", item="숙박비"), event("e2"), event("new")]
    results = match(events, [card("a"), card("b"), card("free")], frozen_groups=[pin])
    by_id = {row["ota_event_id"]:row for row in results}
    assert by_id["e1"]["status"] == "HOLD_GROUP_CHANGED"
    assert by_id["e2"]["status"] == "HOLD_GROUP_CHANGED"
    assert {"a", "b"} <= set(by_id["e1"]["reserved_card_ids"])
    assert by_id["new"]["status"].startswith("HOLD")
    assert by_id["new"].get("transaction_id") is None


def test_equal_optimum_singleton_candidates_across_signatures_hold_as_a_component():
    events = [event("e1", booking_ref="A", item="항공권", card_last4=None, card_issuer=None),
              event("e2", booking_ref="B", item="숙박비", card_last4=None, card_issuer=None)]
    cards = [card("a", issuer="Bank A", card_tail="2042"),
             card("b", issuer="Bank B", card_tail="9999")]
    alias_rule = {"active":True, "approved_by":"synthetic-owner", "conditions":{
        "rule_kind":"provider_alias", "provider":"trip", "alias":"trip.com",
        "approval_source":"synthetic-approved", "alias_version":1}}
    results = match(events, cards, rules=[alias_rule])
    assert {row["status"] for row in results} == {"HOLD_AMBIGUOUS"}
    assert all(row.get("transaction_id") is None for row in results)
    assert all(set(row["reserved_card_ids"]) == {"a", "b"} for row in results)


def test_new_card_completes_partial_group_without_replacing_any_event_facts():
    events = [event(f"evt-{i}", booking_ref=f"BOOK-{i}") for i in range(3)]
    partial = match(events, [card("card-0"), card("card-1")])
    assert {row["status"] for row in partial} == {"HOLD_PARTIAL_GROUP"}
    completed = match(events, [card("card-0"), card("card-1"), card("card-2")])
    assert {row["status"] for row in completed} == {"MATCHED_AUTO"}
    assert {row["ota_event_id"] for row in completed} == {row["ota_event_id"] for row in events}
    assert {row["booking_ref"] for row in completed} == {row["booking_ref"] for row in events}


def _assert_synthetic_pin_count(count):
    events = [event(f"evt-{i}", booking_ref=f"BOOK-{i}", amount_krw=10000+i, amount=str(10000+i))
              for i in range(count)]
    cards = [card(f"card-{i}", amount_krw=10000+i) for i in range(count)]
    links = {f"evt-{i}": {"transaction_id": f"card-{i}",
             "status": "MATCHED_AUTO" if i % 2 == 0 else "MATCHED_USER"}
             for i in range(count)}
    result = match(events, cards, existing_links=links)
    assert len(result) == count
    assert {row["ota_event_id"]: row["transaction_id"] for row in result} == {
        identity: value["transaction_id"] for identity, value in links.items()}
    assert all(result[i]["amount_krw"] == 10000+i for i in range(count))


import pytest


@pytest.mark.parametrize("count", [200, 734], ids=["synthetic-exact-pin-invariant", "synthetic-ledger-pin-invariant"])
def test_synthetic_pin_invariants(count):
    _assert_synthetic_pin_count(count)


def test_acceptance_04_signed_lag_range_matches_candidates_and_rejects_outside_days():
    from datetime import date, timedelta

    ota = event(card_last4="2042")
    rule = {"approved_by":"synthetic-owner", "active":True, "conditions":{
        "provider":"trip", "item":ota["item"], "issuer":"Bank A", "card_last4":"2042",
        "merchant_normalized":"trip.com", "currency":"KRW", "event_type":"charge",
        "amount_delta_krw":0, "date_lag_min_days":-1, "date_lag_max_days":2}}
    rows = [card(f"lag-{offset}", approval_date=(date.fromisoformat(ota["paid_on"]) + timedelta(days=offset)).isoformat())
            for offset in (-2, -1, 0, 1, 2, 3)]
    assert {row["transaction_id"] for row in same_date_cards(ota, rows, rules=[rule])} == {
        "lag--1", "lag-0", "lag-1", "lag-2"}
    matched = match([ota], rows, rules=[rule])
    assert len(matched) == 1
    assert matched[0]["status"] == "HOLD_PARTIAL_GROUP"
    assert set(matched[0]["candidates"]) == {"lag--1", "lag-0", "lag-1", "lag-2"}


def test_acceptance_06_blank_card_hint_requires_confirmation_then_stores_actual_group():
    from app.ota_review import OtaReviewStore
    from pathlib import Path
    from tempfile import TemporaryDirectory

    events = [event(f"no-hint-{index}", booking_ref=f"BOOK-{index}", card_last4=None) for index in range(2)]
    cards = [card("no-hint-card-a"), card("no-hint-card-b", approval_number="B")]
    alias_rule = {"approved_by":"synthetic-owner", "active":True, "conditions":{
        "rule_kind":"provider_alias", "provider":"trip", "alias":"trip.com",
        "approval_source":"synthetic-review", "alias_version":1}}
    automatic = match(events, cards, rules=[alias_rule])
    assert {row["status"] for row in automatic} == {"HOLD_GROUP_CONFIRMATION_REQUIRED"}
    assert all(row.get("transaction_id") is None for row in automatic)
    with TemporaryDirectory() as directory:
        store = OtaReviewStore(Path(directory) / "synthetic-review.sqlite")
        try:
            mapping = {events[0]["ota_event_id"]:"no-hint-card-a",
                       events[1]["ota_event_id"]:"no-hint-card-b"}
            store.confirm_group_order(mapping, mapping.values(), mapping,
                user="synthetic-owner", order_snapshot=automatic[0]["group_order_snapshot"], request_id="manual-group")
            confirmed = match(events, cards, rules=[alias_rule], frozen_groups=store.group_pins())
            assert {row["status"] for row in confirmed} == {"MATCHED_AUTO"}
            assert all(row["group_order_frozen"] is True for row in confirmed)
        finally:
            store.close()


def test_acceptance_07_approved_delta_is_limited_to_its_full_edge_scope():
    base = event(provider="agoda", card_last4="2042", amount_krw=100000, amount="100000")
    rule = {"approved_by":"synthetic-owner", "active":True, "conditions":{
        "provider":"agoda", "item":base["item"], "merchant_normalized":"trip.com",
        "issuer":"Bank A", "card_last4":"2042", "currency":"KRW", "event_type":"charge",
        "amount_delta_krw":-4000, "valid_from":"2026-09-01", "valid_to":"2026-09-30"}}
    allowed = match([base], [card("delta-allowed", amount_krw=96000)], rules=[rule])[0]
    assert allowed["status"] == "MATCHED_AUTO"
    cases = [
        (event("wrong-provider", provider="booking", amount_krw=100000, amount="100000"), card("c1", amount_krw=96000, merchant="AGODA.COM", merchant_normalized="agoda.com")),
        (event("wrong-item", provider="agoda", item="hotel", amount_krw=100000, amount="100000"), card("c2", merchant="AGODA.COM", merchant_normalized="agoda.com", amount_krw=96000)),
        (event("wrong-merchant", provider="agoda", amount_krw=100000, amount="100000"), card("c3", merchant="other", merchant_normalized="other", amount_krw=96000)),
        (event("wrong-card", provider="agoda", card_last4="9999", amount_krw=100000, amount="100000"), card("c4", merchant="AGODA.COM", merchant_normalized="agoda.com", card_tail="9999", amount_krw=96000)),
        (event("wrong-date", provider="agoda", paid_on="2026-10-01", amount_krw=100000, amount="100000"), card("c5", merchant="AGODA.COM", merchant_normalized="agoda.com", approval_date="2026-10-01", amount_krw=96000)),
        (event("wrong-currency", provider="agoda", currency="USD", amount="100000", amount_krw=100000), card("c6", merchant="AGODA.COM", merchant_normalized="agoda.com", amount_krw=96000)),
        (event("wrong-refund", provider="agoda", event_type="refund", refund_status="refunded", amount_krw=100000, amount="100000"), card("c7", merchant="AGODA.COM", merchant_normalized="agoda.com", transaction_direction="refund", amount_krw=-96000)),
        (event("wrong-off-step", provider="agoda", amount_krw=100000, amount="100000"), card("c8", merchant="AGODA.COM", merchant_normalized="agoda.com", amount_krw=95500)),
    ]
    for candidate, transaction in cases:
        result = match([candidate], [transaction], rules=[rule])[0]
        assert result["status"] != "MATCHED_AUTO", (candidate["ota_event_id"], result)


def test_acceptance_07_item_scoped_rule_exposes_exact_and_delta_edges_separately():
    room = event("room", provider="agoda", item="room", amount_krw=100000, amount="100000")
    flight = event("flight", provider="agoda", item="flight", card_last4="9999", amount_krw=100000, amount="100000")
    rules = [{"approved_by":"synthetic-owner", "active":True, "conditions":{
        "provider":"agoda", "item":"room", "merchant_normalized":"agoda.com",
        "issuer":"Bank A", "card_last4":"2042", "currency":"KRW", "event_type":"charge",
        "amount_delta_krw":-4000}}]
    cards = [card("room-exact", merchant="AGODA.COM", merchant_normalized="agoda.com", amount_krw=100000),
             card("room-delta", merchant="AGODA.COM", merchant_normalized="agoda.com", amount_krw=96000),
             card("flight-exact", merchant="AGODA.COM", merchant_normalized="agoda.com", card_tail="9999", amount_krw=100000),
             card("flight-delta", merchant="AGODA.COM", merchant_normalized="agoda.com", card_tail="9999", amount_krw=96000)]
    results = {row["ota_event_id"]:row for row in match([room, flight], cards, rules=rules)}
    assert results["room"]["status"] == "HOLD_PARTIAL_GROUP"
    assert set(results["room"]["candidates"]) == {"room-exact", "room-delta"}
    assert results["flight"]["status"] == "MATCHED_AUTO"
    assert results["flight"]["transaction_id"] == "flight-exact"


def test_acceptance_10_refresh_never_overwrites_two_hundred_manual_source_snapshots(tmp_path):
    from app.ota_review import OtaReviewStore

    store = OtaReviewStore(tmp_path / "synthetic-review.sqlite")
    events = [event(f"immutable-{index}", source_digest=f"{index:064x}",
                    source_ids=[f"synthetic:{index}"]) for index in range(200)]
    cards = [card(f"immutable-card-{index}") for index in range(200)]
    try:
        for index, (candidate, transaction) in enumerate(zip(events, cards)):
            preview = store.preview(candidate, transaction)
            store.confirm(candidate, transaction, preview["preview_digest"],
                request_id=f"immutable-{index}", user="synthetic-owner", allocations={})
        before = store.event_snapshots()
        stored_before = {row["event_id"]:(row["event_json"], row["transaction_json"], row["source_digest"])
                         for row in store.conn.execute(
                             "SELECT event_id,event_json,transaction_json,source_digest FROM ota_review_links")}
        changed = [dict(candidate, amount_krw=999999, amount="999999", paid_on="2026-12-31",
                        source_digest="f"*64, source_ids=["mutated:source"])
                   for candidate in events]
        store.refresh(changed, cards)
        after, links = store.event_snapshots(), store.links()
        stored_after = {row["event_id"]:(row["event_json"], row["transaction_json"], row["source_digest"])
                        for row in store.conn.execute(
                            "SELECT event_id,event_json,transaction_json,source_digest FROM ota_review_links")}
        snapshot_overwrite_count = sum(stored_before[event_id] != value
                                       for event_id, value in stored_after.items())
        assert len(after) == 200
        assert all(after[key]["ota_event_id"] == before[key]["ota_event_id"] and
                   after[key]["amount_krw"] == before[key]["amount_krw"] and
                   after[key]["paid_on"] == before[key]["paid_on"] and
                   after[key]["source_digest"] == before[key]["source_digest"] for key in before)
        assert all(after[key]["source_ids"] == before[key]["source_ids"] and
                   after[key]["evidence_status"] == before[key]["evidence_status"] for key in before)
        assert snapshot_overwrite_count == 0
        assert all(link["evidence_changed"] for link in links.values())
        assert store.conn.execute("SELECT COUNT(*) FROM ota_review_links").fetchone()[0] == 200
    finally:
        store.close()
