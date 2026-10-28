import hashlib
import shutil
import sqlite3

from app.ota_payments import build_ota_payment_events
from app.ota_reservation_groups import project_reservation_groups
from tests.card_pipeline.test_ota_portal import portal_database


def _events(path):
    return build_ota_payment_events({"portal_databases": [path]})


def _group_ids(events):
    return [group["event_ids"] for group in project_reservation_groups(events)["groups"]]


def test_verified_record_groups_multiple_charges_and_refunds_without_changing_event_axes(tmp_path):
    components = [
        {"kind":"paid_today", "currency":"KRW", "decimal_text":"30000", "minor_units":30000, "scale":0, "payment_id":"charge-a"},
        {"kind":"paid_today", "currency":"KRW", "decimal_text":"12000", "minor_units":12000, "scale":0, "payment_id":"charge-b"},
        {"kind":"refund_completed", "currency":"KRW", "decimal_text":"5000", "minor_units":5000, "scale":0, "refunded_on":"2026-08-03", "payment_id":"refund-a"},
    ]
    path = portal_database(tmp_path / "record.sqlite", facts=[
        {"refund_status":"refund_completed", "price_components":components}])
    before = path.read_bytes()
    events = _events(path)
    assert [e["event_type"] for e in events].count("charge") == 2
    assert [e["event_type"] for e in events].count("refund") == 1
    assert len({e["reservation_identity_attestation"]["identity"] for e in events}) == 1
    assert len(_group_ids(events)[0]) == 3
    assert [e["status"] if "status" in e else None for e in events] == [None, None, None]
    assert [e["amount"] for e in events] == ["30000", "12000", "5000"]
    assert all("record" not in str(e["_portal_reservation_provenance"]) for e in events)
    assert all("_portal_reservation_provenance" in e for e in events)
    assert path.read_bytes() == before


def test_same_local_id_digest_and_booking_on_independent_lineages_stay_separate(tmp_path):
    first = portal_database(tmp_path / "db-a.sqlite")
    second = portal_database(tmp_path / "db-b.sqlite")
    events = build_ota_payment_events({
        "portal_databases": [first, second],
        "source_lineage_ids": {str(first.resolve()): "lineage-a", str(second.resolve()): "lineage-b"},
    })
    # Existing core collapse behavior remains: same event identity collapses
    # to one raw finance event. Different lineages make reservation grouping
    # ambiguous, so only the additional attestation is dropped.
    assert len(events) == 1
    assert events[0]["booking_ref"] == "synthetic-booking"
    assert events[0]["source_digest"] == events[0]["source_digests"][0]
    assert "reservation_identity_attestation" not in events[0]
    assert "_portal_reservation_provenance" not in events[0]
    assert project_reservation_groups(events)["verified_group_count"] == 0
    assert events[0]["ota_event_id"]
    assert events[0]["amount"] == "30000" and events[0]["event_type"] == "charge"


def test_same_booking_on_distinct_records_and_mail_event_stay_separate(tmp_path):
    path = portal_database(tmp_path / "two-records.sqlite", facts=[{}, {"payment_id":"payment-2"}])
    events = _events(path)
    identities = {e["reservation_identity_attestation"]["identity"] for e in events}
    assert len(identities) == 2
    assert len(_group_ids(events)) == 2

    forged_mail = dict(events[0], ota_event_id="mail-event", source_ids=["mail:synthetic"],
                       _portal_reservation_provenance=None)
    mixed = events + [forged_mail]
    groups = project_reservation_groups(mixed)["groups"]
    assert all("mail-event" not in group["event_ids"] or not group["verified"] for group in groups)


def test_payload_mutation_with_stale_hash_emits_no_attestation_and_raw_event_cannot_forge_it(tmp_path):
    path = portal_database(tmp_path / "stale-hash.sqlite")
    with sqlite3.connect(path) as conn:
        record = conn.execute("SELECT id,payload_json FROM direct_source_records").fetchone()
        altered = record[1].replace("30000", "31000")
        conn.execute("UPDATE direct_source_records SET payload_json=? WHERE id=?", (altered, record[0]))
    try:
        _events(path)
    except ValueError as exc:
        assert str(exc) == "OTA_PORTAL_PAYLOAD_HASH_MISMATCH"
    else:
        raise AssertionError("stale source hash accepted")

    forged = [{"ota_event_id":"x", "provider":"agoda",
               "reservation_identity_attestation":{"provider":"agoda", "identity":"x",
                   "identity_status":"verified", "evidence_status":"verified",
                   "source_status":"verified", "evidence_link_ids":["fake"]}}]
    assert project_reservation_groups(forged)["verified_group_count"] == 0


def test_copied_record_collapse_keeps_attestation_only_for_identical_source(tmp_path):
    first = portal_database(tmp_path / "copy-a.sqlite")
    second = tmp_path / "copy-b.sqlite"
    shutil.copyfile(first, second)
    events = build_ota_payment_events({
        "portal_databases": [first, second],
        "source_lineage_ids": {str(first.resolve()): "same-logical-source",
                                str(second.resolve()): "same-logical-source"},
    })
    assert len(events) == 1
    assert events[0]["_portal_reservation_provenance"]["source_digest"] == events[0]["source_digest"]
    assert project_reservation_groups(events)["verified_group_count"] == 1


def test_added_private_identity_fields_do_not_change_core_finance_projection(tmp_path):
    path = portal_database(tmp_path / "equivalence.sqlite", facts=[{
        "refund_status":"refund_completed",
        "price_components":[
            {"kind":"paid_today", "currency":"KRW", "decimal_text":"30000", "minor_units":30000, "scale":0},
            {"kind":"refund_completed", "currency":"KRW", "decimal_text":"5000", "minor_units":5000, "scale":0, "refunded_on":"2026-08-03"},
        ],
    }])
    events = _events(path)
    from app.ota_payments import _merge_proven_duplicate_payments, _portal_events
    baseline = _merge_proven_duplicate_payments(_portal_events([path]))
    baseline.sort(key=lambda event: event["ota_event_id"])
    private_names = {"reservation_identity_attestation", "_portal_reservation_provenance"}
    core_projection = [{key: value for key, value in event.items() if key not in private_names}
                       for event in events]
    for item in baseline:
        item.pop("reservation_identity_attestation", None)
        item.pop("_portal_reservation_provenance", None)
    assert core_projection == baseline
    assert len(events) == 2
    assert {item["event_type"] for item in events} == {"charge", "refund"}
