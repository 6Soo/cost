from copy import deepcopy

from app.ota_reservation_groups import project_reservation_groups


def attestation(provider="agoda", identity="opaque:1", **changes):
    value = {
        "provider": provider,
        "identity": identity,
        "identity_status": "verified",
        "evidence_status": "verified",
        "source_status": "verified",
        "evidence_link_ids": ["link:1"],
    }
    value.update(changes)
    return value


def event(event_id, **values):
    att = values.get("reservation_identity_attestation")
    if isinstance(att, dict) and "_portal_reservation_provenance" not in values:
        values["_portal_reservation_provenance"] = {
            "provider": att.get("provider"), "identity": att.get("identity"),
            "source_digest": "synthetic-digest"}
    return {"ota_event_id": event_id, **values}


def memberships(result):
    return [group["event_ids"] for group in result["groups"]]


def test_only_explicit_verified_provider_identity_groups_events_and_preserves_axes():
    rows = [
        event("e2", provider="agoda", booking_ref="same", event_type="refund",
              status="HOLD_EVIDENCE_CONFLICT", refund_status="unknown",
              reservation_identity_attestation=attestation(),
              _portal_reservation_provenance={"provider":"agoda","identity":"opaque:1","source_digest":"d"}),
        event("e1", provider="agoda", booking_ref="same", event_type="charge",
              status="MATCHED_USER", manual=True,
              reservation_identity_attestation=attestation(),
              _portal_reservation_provenance={"provider":"agoda","identity":"opaque:1","source_digest":"d"}),
    ]
    before = deepcopy(rows)
    result = project_reservation_groups(rows)
    assert memberships(result) == [["e1", "e2"]]
    assert result["groups"][0]["verified"] is True
    assert rows == before
    assert rows[0]["status"] == "HOLD_EVIDENCE_CONFLICT"
    assert rows[1]["status"] == "MATCHED_USER" and rows[1]["manual"] is True


def test_source_lineage_raw_reference_and_solver_group_do_not_attest_identity():
    rows = [
        event("a", provider="trip", booking_ref="R", source_lineage_ids=["mail:x"],
              source_digests=["d"], solver_group_id="solver", amount=10, paid_on="2026-01-01"),
        event("b", provider="trip", booking_ref="R", source_lineage_ids=["mail:y"],
              source_digests=["d"], solver_group_id="solver", amount=10, paid_on="2026-01-01"),
    ]
    result = project_reservation_groups(rows)
    assert memberships(result) == [["a"], ["b"]]
    assert all(group["warnings"] == ["RESERVATION_IDENTITY_UNVERIFIED"]
               for group in result["groups"])


def test_duplicate_missing_and_nonstring_event_ids_are_warned_singletons():
    rows = [event("dup", reservation_identity_attestation=attestation()),
            event("dup", reservation_identity_attestation=attestation()),
            event(None), {"ota_event_id": 7}]
    result = project_reservation_groups(rows)
    assert memberships(result) == [["dup"], ["dup"], [], []]
    assert [group["warnings"] for group in result["groups"]] == [
        ["EVENT_ID_DUPLICATE"], ["EVENT_ID_DUPLICATE"],
        ["EVENT_ID_MISSING"], ["EVENT_ID_MISSING"]]
    assert [(g["input_index"], g["member_indices"]) for g in result["groups"]] == [
        (0, [0]), (1, [1]), (2, [2]), (3, [3])]


def test_conflict_source_mismatch_unknown_and_forged_incomplete_attestations_stay_singleton():
    rows = [
        event("conflict", provider="agoda", reservation_identity_attestation=attestation(identity_status="conflict")),
        event("evidence", provider="agoda", reservation_identity_attestation=attestation(evidence_status="conflict")),
        event("source", provider="agoda", reservation_identity_attestation=attestation(source_status="mismatch")),
        event("unknown", provider="agoda", reservation_identity_attestation=attestation(evidence_status="unknown")),
        event("forged", provider="agoda", reservation_identity_attestation={"provider": "agoda", "identity": "same"}),
    ]
    result = project_reservation_groups(rows)
    assert memberships(result) == [["conflict"], ["evidence"], ["source"], ["unknown"], ["forged"]]
    assert [group["warnings"][0] for group in result["groups"]] == [
        "RESERVATION_IDENTITY_CONFLICT", "RESERVATION_EVIDENCE_CONFLICT",
        "RESERVATION_SOURCE_MISMATCH", "RESERVATION_ATTESTATION_UNKNOWN",
        "RESERVATION_ATTESTATION_UNKNOWN"]


def test_provider_scope_and_equal_solver_attributes_do_not_cross_merge():
    rows = [
        event("a", provider="agoda", booking_ref="R", amount=10, paid_on="D",
              reservation_identity_attestation=attestation("agoda", "same"),
              _portal_reservation_provenance={"provider":"agoda","identity":"same","source_digest":"d1"}),
        event("b", provider="trip", booking_ref="R", amount=10, paid_on="D",
              reservation_identity_attestation=attestation("trip", "same"),
              _portal_reservation_provenance={"provider":"trip","identity":"same","source_digest":"d2"}),
        event("c", provider="agoda", booking_ref="R", amount=10, paid_on="D",
              reservation_identity_attestation=attestation("agoda", "other"),
              _portal_reservation_provenance={"provider":"agoda","identity":"other","source_digest":"d3"}),
    ]
    assert memberships(project_reservation_groups(rows)) == [["a"], ["b"], ["c"]]


def test_order_is_deterministic_and_empty_input_is_valid():
    rows = [event("z"), event("a")]
    first = project_reservation_groups(rows)
    assert project_reservation_groups(rows) == first
    assert project_reservation_groups([]) == {
        "grouping": "producer_attested_reservation_identity",
        "fallback_status": "all_singleton_fallback",
        "verified_group_count": 0, "singleton_fallback_count": 0, "groups": []}


def test_spoofed_missing_invalid_and_mismatched_event_provider_never_group():
    rows = [
        event("spoof-a", provider="agoda", reservation_identity_attestation=attestation("trip", "X")),
        event("spoof-b", provider="agoda", reservation_identity_attestation=attestation("trip", "X")),
        event("missing", reservation_identity_attestation=attestation()),
        event("invalid", provider=7, reservation_identity_attestation=attestation()),
    ]
    result = project_reservation_groups(rows)
    assert memberships(result) == [["spoof-a"], ["spoof-b"], ["missing"], ["invalid"]]
    assert [g["warnings"][0] for g in result["groups"]] == [
        "RESERVATION_PROVIDER_MISMATCH", "RESERVATION_PROVIDER_MISMATCH",
        "EVENT_PROVIDER_MISSING", "EVENT_PROVIDER_INVALID"]
    assert result["fallback_status"] == "all_singleton_fallback"
    assert result["verified_group_count"] == 0


def test_event_evidence_flags_veto_but_payment_hold_status_is_not_identity_conflict():
    rows = [
        event("changed", provider="agoda", evidence_changed=True,
              reservation_identity_attestation=attestation()),
        event("missing", provider="agoda", evidence_missing="source unavailable",
              reservation_identity_attestation=attestation()),
        event("hold", provider="agoda", status="HOLD_EVIDENCE_CONFLICT",
              refund_status="unknown", reservation_identity_attestation=attestation()),
        event("peer", provider="agoda", reservation_identity_attestation=attestation()),
    ]
    before = deepcopy(rows)
    result = project_reservation_groups(rows)
    assert memberships(result) == [["changed"], ["missing"], ["hold", "peer"]]
    assert result["groups"][0]["warnings"] == ["EVENT_EVIDENCE_UNVERIFIED"]
    assert result["groups"][1]["warnings"] == ["EVENT_EVIDENCE_UNVERIFIED"]
    assert result["groups"][2]["warnings"] == []
    assert rows == before


def test_output_mutation_does_not_alias_input_or_attestation():
    rows = [event("a", provider="agoda", reservation_identity_attestation=attestation()),
            event("b", provider="agoda", reservation_identity_attestation=attestation())]
    before = deepcopy(rows)
    result = project_reservation_groups(rows)
    result["groups"][0]["event_ids"].append("injected")
    result["groups"][0]["warnings"].append("injected")
    assert rows == before
    assert result["groups"][0]["event_ids"] != rows[0]["reservation_identity_attestation"]["evidence_link_ids"]
