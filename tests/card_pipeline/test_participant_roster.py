"""참가자 명단 수신·저장 경로의 표적 검사.

합성 자료만 쓴다. 실제 명단·실명·운영 DB는 이 파일에 들어오지 않는다.
"""
import hashlib
import json
import threading
from pathlib import Path

import pytest

from app import participant_roster as pr

SOURCE_BYTES = b"synthetic-roster-source-1"
OTHER_SOURCE_BYTES = b"synthetic-roster-source-2"


def build_batch(root: Path, *, batch_id="batch-syn-001", roster_id="roster-syn-001", revision=1,
                items=None, scope="partial", pages=(1,), expected_pages=None, declared_people=None,
                authority="owner_confirmed_insurance", trip_ref=None, source_bytes=SOURCE_BYTES,
                manifest_overrides=None, participant_overrides=None):
    items = items if items is not None else [
        {"source_item_id": "item-syn-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "김가람", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
    ]
    trip_ref = trip_ref or {"cost_trip_id": "trip-syn", "google_trip_key": "0404_에히메"}
    (root / "sources").mkdir(parents=True, exist_ok=True)
    source = root / "sources" / "page-01.png"
    source.write_bytes(source_bytes)
    manifest = {
        "schema_version": 1,
        "batch_id": batch_id,
        "roster_id": roster_id,
        "revision": revision,
        "authority": authority,
        "trip_ref": trip_ref,
        "submitted_by": "local-roster-agent",
        "submitted_at": "2026-10-20T18:00:00+09:00",
        "coverage": {"scope": scope, "received_pages": list(pages),
                     "expected_pages": expected_pages, "declared_people": declared_people},
        "sources": [{"source_id": "source-syn-001", "path": "sources/page-01.png",
                     "sha256": hashlib.sha256(source_bytes).hexdigest()}],
    }
    manifest.update(manifest_overrides or {})
    participants = {"schema_version": 1, "items": items}
    participants.update(participant_overrides or {})
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "participants.json").write_text(json.dumps(participants, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
def store(tmp_path):
    opened = pr.ParticipantStore.open(tmp_path / "participant.sqlite")
    yield opened
    opened.close()


def resolver(trip_id="trip-syn", google_key="0404_에히메"):
    return pr.mapping_resolver({google_key: trip_id})


def test_mapped_roster_confirms_participants(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    result = pr.register_roster(store, batch, trip_resolver=resolver())
    assert result["status"] == "registered"
    assert result["new_participants"] == 1 and result["reused_participants"] == 0
    assert result["pending_items"] == [] and result["conflict_items"] == []
    assert result["income_reconciliation"] == "available"
    people = store.participants("trip-syn")
    assert [p["display_name"] for p in people] == ["김가람"]
    assert people[0]["state"] == "confirmed" and people[0]["authority"] == "owner_confirmed_insurance"


def test_unreadable_item_is_held_and_is_not_a_person(tmp_path, store):
    batch = build_batch(tmp_path / "batch", items=[
        {"source_item_id": "item-syn-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "김가람", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
        {"source_item_id": "item-syn-002", "source_id": "source-syn-001", "page": 1,
         "row_label": "2", "name": None, "nickname": None, "english_name": None,
         "transcription_status": "unreadable"},
    ])
    result = pr.register_roster(store, batch, trip_resolver=resolver())
    assert result["new_participants"] == 1
    assert result["pending_items"] == ["item-syn-002"]
    assert len(store.participants("trip-syn")) == 1


def test_partial_coverage_registers_people_without_a_total_claim(tmp_path, store):
    batch = build_batch(tmp_path / "batch", scope="partial")
    result = pr.register_roster(store, batch, trip_resolver=resolver())
    assert result["status"] == "registered"
    assert store.batch("batch-syn-001")["scope"] == "partial"
    assert store.batch("batch-syn-001")["declared_people"] is None


def test_complete_coverage_needs_pages_and_people(tmp_path, store):
    batch = build_batch(tmp_path / "batch", scope="complete", pages=(1,), expected_pages=2,
                        declared_people=2)
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "COVERAGE_INCOMPLETE"


def test_same_batch_and_content_gives_the_same_answer_and_no_extra_person(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    first = pr.register_roster(store, batch, trip_resolver=resolver())
    items_before = store.items("roster-syn-001")
    events_before = store.events("batch-syn-001")
    second = pr.register_roster(store, batch, trip_resolver=resolver())
    # 같은 배치·같은 지문이면 최초 결과를 그대로 돌려준다.
    assert second["reused"] is True
    assert second["new_participants"] == first["new_participants"]
    assert second["reused_participants"] == first["reused_participants"]
    assert second["registered_at"] == first["registered_at"]
    assert len(store.participants("trip-syn")) == 1
    assert first["batch_id"] == second["batch_id"]
    # 항목과 감사 이력은 다시 쓰지 않는다.
    assert store.items("roster-syn-001") == items_before
    assert store.events("batch-syn-001") == events_before


def test_same_batch_id_with_other_content_is_a_conflict(tmp_path, store):
    build_batch(tmp_path / "batch")
    pr.register_roster(store, tmp_path / "batch", trip_resolver=resolver())
    build_batch(tmp_path / "batch2", batch_id="batch-syn-001", roster_id="roster-syn-002",
                source_bytes=OTHER_SOURCE_BYTES)
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, tmp_path / "batch2", trip_resolver=resolver())
    assert raised.value.code == "SOURCE_ID_CONFLICT"
    assert len(store.participants("trip-syn")) == 1


def test_unmapped_trip_is_held_and_the_batch_is_kept(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    result = pr.register_roster(store, batch, trip_resolver=resolver(trip_id="trip-other"))
    assert result["status"] == "held" and result["status_reason"] == "TRIP_MAPPING_REQUIRED"
    assert result["new_participants"] == 0
    assert store.participants("trip-syn") == []
    assert store.batch("batch-syn-001")["status"] == "held"


def test_a_held_batch_can_be_attached_when_the_trip_becomes_clear(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    pr.register_roster(store, batch, trip_resolver=resolver(trip_id="trip-other"))
    result = pr.register_roster(store, batch, trip_resolver=resolver())
    assert result["status"] == "registered" and result["new_participants"] == 1
    assert len(store.participants("trip-syn")) == 1


def test_a_changed_name_becomes_a_correction_and_keeps_the_old_name(tmp_path, store):
    build_batch(tmp_path / "batch")
    pr.register_roster(store, tmp_path / "batch", trip_resolver=resolver())
    build_batch(tmp_path / "batch2", batch_id="batch-syn-002", revision=2, items=[
        {"source_item_id": "item-syn-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "김가람이", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
    ])
    result = pr.register_roster(store, tmp_path / "batch2", trip_resolver=resolver())
    assert result["new_participants"] == 0 and result["reused_participants"] == 1
    assert result["corrections"]
    people = store.participants("trip-syn")
    assert len(people) == 1 and people[0]["display_name"] == "김가람"
    assert people[0]["state"] == "correction_pending"
    corrections = store.corrections()
    assert corrections[0]["before_value"] == "김가람" and corrections[0]["after_value"] == "김가람이"
    # 원문 이력도 덮어쓰지 않는다.
    items = store.items("roster-syn-001")
    assert items[0]["name"] == "김가람"


def test_resend_with_a_new_roster_id_keeps_one_person(tmp_path, store):
    build_batch(tmp_path / "batch")
    pr.register_roster(store, tmp_path / "batch", trip_resolver=resolver())
    build_batch(tmp_path / "batch2", batch_id="batch-syn-002", roster_id="roster-syn-002",
                items=[
        {"source_item_id": "item-other-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "김가람", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
    ])
    result = pr.register_roster(store, tmp_path / "batch2", trip_resolver=resolver())
    assert result["new_participants"] == 0 and result["reused_participants"] == 1
    assert len(store.participants("trip-syn")) == 1


def test_the_same_item_on_another_trip_does_not_move_the_person(tmp_path, store):
    build_batch(tmp_path / "batch")
    pr.register_roster(store, tmp_path / "batch", trip_resolver=resolver())
    build_batch(tmp_path / "batch2", batch_id="batch-syn-002", revision=2,
                trip_ref={"cost_trip_id": "trip-other", "google_trip_key": "0404_에히메"})
    result = pr.register_roster(store, tmp_path / "batch2",
                                trip_resolver=resolver(trip_id="trip-other"))
    assert result["status"] == "conflict"
    assert result["conflict_items"] == ["item-syn-001"]
    assert len(store.participants("trip-syn")) == 1
    assert store.participants("trip-other") == []


def test_a_source_outside_the_batch_is_refused(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    manifest["sources"][0]["path"] = "../outside.png"
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "SOURCE_PATH_INVALID"


def test_a_wrong_source_hash_is_refused(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = "0" * 64
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "SOURCE_HASH_MISMATCH"


def test_a_placeholder_hash_is_refused(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = "<실제 파일의 SHA-256 값>"
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "SOURCE_HASH_INVALID"


def test_a_personal_field_is_refused(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    participants = json.loads((batch / "participants.json").read_text(encoding="utf-8"))
    participants["items"][0]["주민등록번호"] = "000000-0000000"
    (batch / "participants.json").write_text(json.dumps(participants, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "PERSONAL_FIELD_REJECTED"


def test_an_unknown_field_is_refused(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    participants = json.loads((batch / "participants.json").read_text(encoding="utf-8"))
    participants["items"][0]["cost"] = 1000
    (batch / "participants.json").write_text(json.dumps(participants, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "PARTICIPANT_FIELD_UNKNOWN"


def test_a_number_is_not_a_name(tmp_path, store):
    batch = build_batch(tmp_path / "batch", items=[
        {"source_item_id": "item-syn-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "123456-7890123", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
    ])
    with pytest.raises(pr.RosterError) as raised:
        pr.register_roster(store, batch, trip_resolver=resolver())
    assert raised.value.code == "PARTICIPANT_NAME_INVALID"


def test_two_registrars_at_once_keep_one_person(tmp_path):
    path = tmp_path / "participant.sqlite"
    batch = build_batch(tmp_path / "batch")
    results = []
    errors = []

    def run():
        opened = pr.ParticipantStore.open(path)
        try:
            results.append(pr.register_roster(opened, batch, trip_resolver=resolver()))
        except Exception as error:  # a failure must be visible, not swallowed
            errors.append(repr(error))
        finally:
            opened.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert len(results) == 2
    # 한 등록기만 실제로 기록하고 다른 등록기는 같은 결과를 받는다.
    assert sum(1 for item in results if item["reused"] is False) == 1
    assert results[0]["new_participants"] == results[1]["new_participants"]
    opened = pr.ParticipantStore.open(path)
    try:
        assert len(opened.participants("trip-syn")) == 1
        assert len(opened.events("batch-syn-001")) == 1
    finally:
        opened.close()


def test_the_event_log_records_the_registration(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    pr.register_roster(store, batch, trip_resolver=resolver())
    events = store.events("batch-syn-001")
    assert events and events[0]["kind"] == "roster_registered"


def test_the_owner_can_correct_a_name_and_the_change_is_recorded(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    pr.register_roster(store, batch, trip_resolver=resolver())
    participant = store.participants("trip-syn")[0]
    pr.correct_participant_name(store, participant["participant_id"], "김가람이",
                                 reason="전사 오류", decided_by="owner")
    people = store.participants("trip-syn")
    assert people[0]["display_name"] == "김가람이"
    kinds = [event["kind"] for event in store.events(participant["participant_id"])]
    assert "participant_name_corrected" in kinds


def test_the_owner_can_move_a_participant_to_another_trip(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    pr.register_roster(store, batch, trip_resolver=resolver())
    participant = store.participants("trip-syn")[0]
    pr.remap_participant_trip(store, participant["participant_id"], "trip-other",
                              reason="다른 여행", decided_by="owner")
    assert store.participants("trip-syn") == []
    assert [p["participant_id"] for p in store.participants("trip-other")] == [
        participant["participant_id"]]


def test_the_owner_can_confirm_that_two_items_are_one_person(tmp_path, store):
    batch = build_batch(tmp_path / "batch", items=[
        {"source_item_id": "item-syn-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "김가람", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
        {"source_item_id": "item-syn-002", "source_id": "source-syn-001", "page": 1,
         "row_label": "2", "name": "가람", "nickname": None, "english_name": None,
         "transcription_status": "verified"},
    ])
    pr.register_roster(store, batch, trip_resolver=resolver())
    people = store.participants("trip-syn")
    assert len(people) == 2
    pr.confirm_same_person(store, people[0]["participant_id"], people[1]["participant_id"],
                           decided_by="owner")
    active = store.participants("trip-syn")
    assert len(active) == 1
    assert len(store.conn.execute(
        "SELECT participant_id FROM participant_item_links WHERE participant_id=?",
        (people[0]["participant_id"],)).fetchall()) == 2


def test_the_owner_can_confirm_an_alias(tmp_path, store):
    batch = build_batch(tmp_path / "batch")
    pr.register_roster(store, batch, trip_resolver=resolver())
    participant = store.participants("trip-syn")[0]
    pr.add_participant_alias(store, participant["participant_id"], "가람이", decided_by="owner")
    assert store.participants("trip-syn")[0]["nickname"] == "가람이"
