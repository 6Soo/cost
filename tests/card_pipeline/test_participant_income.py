"""참가자와 수입 행 대조·결정의 표적 검사.

합성 자료만 쓴다. Google 원문 행과 금액은 이 검사가 바꾸지 않는다.
"""
import pytest

from app import participant_income as pi
from app import participant_roster as pr


def person(pid, name, nickname="", english_name="", state="confirmed"):
    return {"participant_id": pid, "trip_id": "trip-syn", "display_name": name,
            "nickname": nickname, "english_name": english_name, "state": state}


def income_row(row, name, *, nickname="", amount=None, amount_state="amounted",
               source="main", sheet="0404_에히메", date=""):
    cells = {"B": date, "C": name, "D": nickname, "E": "", "F": "", "G": ""}
    entry = {"row": row, "cells": cells, "name": name, "nickname": nickname,
             "amount": amount, "amount_state": amount_state}
    return pi.income_rows_from_index({"rows": [entry]}, source=source, sheet=sheet)[0]


def reconcile(participants, rows, **kwargs):
    options = {"trip_id": "trip-syn", "participants": participants, "income_rows": rows,
               "index_available": True, "roster_version": "v1", "google_generation": "gen1",
               "roster_complete": True}
    options.update(kwargs)
    return pi.reconcile(**options)


def test_a_unique_name_match_links_to_the_existing_income_row():
    result = reconcile([person("pt-1", "김가람")], [income_row(6, "김가람", amount=100000)])
    entry = result["participants"][0]
    assert entry["state"] == pi.STATE_NAME_MATCH
    assert entry["links"][0]["income_ref"] == "main|0404_에히메|6"
    assert entry["links"][0]["row"]["amount"] == 100000
    assert result["counts"]["linked_income_rows"] == 1


def test_a_person_without_income_is_shown_by_name_only():
    result = reconcile([person("pt-1", "이나래")], [income_row(6, "김가람", amount=100000)])
    entry = result["participants"][0]
    assert entry["state"] == pi.STATE_NO_INCOME
    assert entry["links"] == []
    assert result["counts"]["name_only"] == 1
    assert result["counts"]["linked_income_rows"] == 0
    assert result["counts"]["unlinked_income_rows"] == 1


def test_a_name_only_income_row_is_not_made_into_a_zero_income():
    rows = [income_row(7, "박다온", amount=None, amount_state="blank")]
    result = reconcile([person("pt-1", "박다온")], rows)
    entry = result["participants"][0]
    assert entry["state"] == pi.STATE_INCOME_PRESENT
    assert entry["links"][0]["row"]["amount"] is None
    assert result["counts"]["linked_income_rows"] == 1


def test_two_people_with_the_same_name_stay_unmerged():
    people = [person("pt-1", "김가람"), person("pt-2", "김가람")]
    result = reconcile(people, [income_row(6, "김가람", amount=100000)])
    assert [entry["state"] for entry in result["participants"]] == [pi.STATE_NEEDS_CHECK,
                                                                   pi.STATE_NEEDS_CHECK]
    assert result["counts"]["needs_check"] == 2
    assert result["counts"]["linked_income_rows"] == 0


def test_two_income_rows_with_the_same_name_are_not_merged():
    rows = [income_row(6, "김가람", amount=100000), income_row(7, "김가람", amount=50000)]
    result = reconcile([person("pt-1", "김가람")], rows)
    assert result["participants"][0]["state"] == pi.STATE_NEEDS_CHECK
    assert result["counts"]["linked_income_rows"] == 0


def test_a_manual_link_keeps_both_income_rows_and_counts_each_once():
    rows = [income_row(6, "김가람", amount=100000), income_row(7, "김가람", amount=50000)]
    decisions = [
        {"participant_id": "pt-1", "income_ref": "main|0404_에히메|6", "decision": "linked",
         "link_method": "manual", "income_fingerprint": rows[0]["fingerprint"]},
        {"participant_id": "pt-1", "income_ref": "main|0404_에히메|7", "decision": "linked",
         "link_method": "manual", "income_fingerprint": rows[1]["fingerprint"]},
    ]
    result = reconcile([person("pt-1", "김가람")], rows, decisions=decisions)
    entry = result["participants"][0]
    assert entry["state"] == pi.STATE_MANUAL
    assert len(entry["links"]) == 2
    assert result["counts"]["linked_income_rows"] == 2
    assert result["counts"]["participants"] == 1


def test_one_income_row_can_be_a_joint_payment_for_two_people():
    rows = [income_row(6, "김가람", amount=300000)]
    decisions = [
        {"participant_id": "pt-1", "income_ref": "main|0404_에히메|6", "decision": "linked",
         "link_method": "manual", "joint": True, "income_fingerprint": rows[0]["fingerprint"]},
        {"participant_id": "pt-2", "income_ref": "main|0404_에히메|6", "decision": "linked",
         "link_method": "manual", "joint": True, "income_fingerprint": rows[0]["fingerprint"]},
    ]
    result = reconcile([person("pt-1", "김가람"), person("pt-2", "이나래")], rows, decisions=decisions)
    assert [entry["state"] for entry in result["participants"]] == [pi.STATE_JOINT, pi.STATE_JOINT]
    assert result["counts"]["participants"] == 2
    # 입금 행은 한 번만 센다.
    assert result["counts"]["linked_income_rows"] == 1
    assert result["counts"]["income_rows"] == 1


def test_income_that_is_not_in_the_roster_is_kept_and_not_deleted():
    rows = [income_row(6, "김가람", amount=100000), income_row(7, "외부인", amount=20000)]
    result = reconcile([person("pt-1", "김가람")], rows)
    assert len(result["unlinked_income"]) == 1
    assert result["unlinked_income"][0]["name"] == "외부인"
    assert result["unlinked_income"][0]["state"] == pi.STATE_NOT_IN_ROSTER


def test_a_refund_row_stays_a_refund_and_does_not_confirm_a_person():
    rows = [income_row(6, "김가람", amount=-50000)]
    result = reconcile([person("pt-1", "김가람")], rows)
    entry = result["participants"][0]
    assert entry["links"][0]["row"]["amount"] == -50000
    assert entry["state"] == pi.STATE_NAME_MATCH


def test_a_manual_decision_wins_over_the_automatic_match():
    rows = [income_row(6, "김가람", amount=100000), income_row(7, "김가람", amount=50000)]
    decisions = [
        {"participant_id": "pt-1", "income_ref": "main|0404_에히메|7", "decision": "linked",
         "link_method": "manual", "income_fingerprint": rows[1]["fingerprint"]},
    ]
    result = reconcile([person("pt-1", "김가람")], rows, decisions=decisions)
    entry = result["participants"][0]
    assert entry["state"] == pi.STATE_MANUAL
    assert entry["links"][0]["income_ref"] == "main|0404_에히메|7"


def test_a_changed_income_row_asks_for_a_new_check():
    rows = [income_row(6, "김가람", amount=100000)]
    decisions = [
        {"participant_id": "pt-1", "income_ref": "main|0404_에히메|6", "decision": "linked",
         "link_method": "manual", "income_fingerprint": "stale-fingerprint"},
    ]
    result = reconcile([person("pt-1", "김가람")], rows, decisions=decisions)
    assert result["participants"][0]["state"] == pi.STATE_NEEDS_CHECK
    assert result["completion"]["complete"] is False


def test_without_a_name_index_no_one_is_called_missing():
    result = reconcile([person("pt-1", "이나래")], [], index_available=False)
    assert result["participants"][0]["state"] == pi.STATE_UNVERIFIED
    assert "INCOME_INDEX_UNAVAILABLE" not in result["participants"][0]["state"]
    assert result["counts"]["needs_check"] == 0


def test_a_stale_decision_is_refused(tmp_path):
    store = pr.ParticipantStore.open(tmp_path / "participant.sqlite")
    try:
        pi.ensure_decision_schema(store.conn)
        with pytest.raises(pi.ReconciliationError) as raised:
            pi.save_decision(store.conn, participant_id="pt-1", income_ref="main|0404_에히메|6",
                             decision="linked", presented_fingerprint="old", current_fingerprint="new")
        assert raised.value.code == "STALE_RECONCILIATION"
    finally:
        store.close()


def test_a_saved_decision_is_kept_with_its_revision(tmp_path):
    import json
    import hashlib
    batch = tmp_path / "batch"
    (batch / "sources").mkdir(parents=True)
    (batch / "sources" / "page-01.png").write_bytes(b"synthetic-source")
    manifest = {
        "schema_version": 1, "batch_id": "batch-syn-001", "roster_id": "roster-syn-001",
        "revision": 1, "authority": "owner_confirmed_insurance",
        "trip_ref": {"cost_trip_id": "trip-syn", "google_trip_key": "0404_에히메"},
        "submitted_by": "local-roster-agent", "submitted_at": "2026-10-20T18:00:00+09:00",
        "coverage": {"scope": "partial", "received_pages": [1], "expected_pages": None,
                     "declared_people": None},
        "sources": [{"source_id": "source-syn-001", "path": "sources/page-01.png",
                     "sha256": hashlib.sha256(b"synthetic-source").hexdigest()}],
    }
    participants = {"schema_version": 1, "items": [
        {"source_item_id": "item-syn-001", "source_id": "source-syn-001", "page": 1,
         "row_label": "1", "name": "김가람", "nickname": None, "english_name": None,
         "transcription_status": "verified"}]}
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (batch / "participants.json").write_text(json.dumps(participants, ensure_ascii=False), encoding="utf-8")

    store = pr.ParticipantStore.open(tmp_path / "participant.sqlite")
    try:
        pr.register_roster(store, batch,
                           trip_resolver=pr.mapping_resolver({"0404_에히메": "trip-syn"}))
        pi.ensure_decision_schema(store.conn)
        participant_id = store.participants("trip-syn")[0]["participant_id"]
        first = pi.save_decision(store.conn, participant_id=participant_id,
                                 income_ref="main|0404_에히메|6",
                                 decision="linked", decided_by="owner", presented_fingerprint="a",
                                 current_fingerprint="a")
        second = pi.save_decision(store.conn, participant_id=participant_id,
                                  income_ref="main|0404_에히메|6",
                                  decision="unlinked", decided_by="owner", presented_fingerprint="a",
                                  current_fingerprint="a")
        assert first["revision"] == 1 and second["revision"] == 2
        stored = pi.decisions_for_trip(store.conn, "trip-syn")
        assert len(stored) == 1 and stored[0]["decision"] == "unlinked"
    finally:
        store.close()


def test_the_completion_flag_needs_everything_to_be_classified():
    rows = [income_row(6, "외부인", amount=20000)]
    result = reconcile([person("pt-1", "김가람")], rows, roster_complete=False)
    assert result["completion"]["complete"] is False
    assert "ROSTER_INCOMPLETE" in result["completion"]["blocked_by"]
    assert "INCOME_UNCLASSIFIED" in result["completion"]["blocked_by"]


def test_the_name_comparison_ignores_case_and_spacing_but_not_the_original_text():
    rows = [income_row(6, "GARAM KIM", amount=100000)]
    result = reconcile([person("pt-1", "garam  kim")], rows)
    assert result["participants"][0]["state"] == pi.STATE_NAME_MATCH
    assert result["participants"][0]["display_name"] == "garam  kim"


def test_a_partial_name_is_not_a_match():
    rows = [income_row(6, "김가람수", amount=100000)]
    result = reconcile([person("pt-1", "김가람")], rows)
    assert result["participants"][0]["state"] == pi.STATE_NO_INCOME


def test_a_row_the_owner_unlinked_is_not_linked_again_by_name():
    rows = [income_row(6, "김가람", amount=100000)]
    decisions = [{"participant_id": "pt-1", "income_ref": "main|0404_에히메|6",
                  "decision": "unlinked"}]
    result = reconcile([person("pt-1", "김가람")], rows, decisions=decisions)
    assert result["participants"][0]["state"] == pi.STATE_NO_INCOME
    assert result["participants"][0]["links"] == []
    assert result["counts"]["linked_income_rows"] == 0


def test_a_manual_link_keeps_the_name_matched_row_too():
    rows = [income_row(6, "김가람", amount=100000),
            income_row(7, "박다온", amount=None, amount_state="blank")]
    decisions = [{"participant_id": "pt-1", "income_ref": "main|0404_에히메|7",
                  "decision": "linked", "link_method": "manual",
                  "income_fingerprint": rows[1]["fingerprint"]}]
    result = reconcile([person("pt-1", "김가람")], rows, decisions=decisions)
    entry = result["participants"][0]
    assert entry["state"] == pi.STATE_MANUAL
    assert sorted(link["income_ref"] for link in entry["links"]) == [
        "main|0404_에히메|6", "main|0404_에히메|7"]
    # 고유 원본 행을 한 번씩만 센다.
    assert result["counts"]["linked_income_rows"] == 2
    assert result["counts"]["participants"] == 1
