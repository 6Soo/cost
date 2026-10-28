from app.provisional_assignment import (ota_service_period_candidate, rank_trip_candidates,
                                        canonical_trip_periods, propose_correction_pattern,
                                        approve_correction_pattern)
from app import Pipeline
from app.classify import classify_transaction
from .fixtures import make_csv, domestic_row
import sqlite3
import pytest
from unittest.mock import patch


TRIPS = [
    {"trip_id": "A", "starts_on": "2026-08-01", "ends_on": "2026-08-05"},
    {"trip_id": "B", "starts_on": "2026-08-01", "ends_on": "2026-08-05"},
]


def test_low_evidence_unique_authoritative_trip_is_provisional():
    result = rank_trip_candidates([{"trip_id": "A", "score": 1, "basis": "날짜 근접"}], trips=TRIPS)
    assert (result["status"], result["trip_id"], result["confidence"]) == ("AUTO_PROVISIONAL", "A", "낮음")


def test_equal_top_candidates_are_held_for_review():
    result = rank_trip_candidates([{"trip_id": "A", "score": 5}, {"trip_id": "B", "score": 5}], trips=TRIPS)
    assert result["status"] == "CONFLICT_REVIEW"
    assert result["trip_id"] == ""
    assert [candidate["trip_id"] for candidate in result["candidates"]] == ["A", "B"]


def test_manual_choice_and_financial_hold_are_protected():
    candidate = [{"trip_id": "A", "score": 99}]
    assert rank_trip_candidates(candidate, trips=TRIPS, manual_trip_id="B")["trip_id"] == "B"
    held = rank_trip_candidates(candidate, trips=TRIPS, financial_hold=True)
    assert held["status"] == "FINANCIAL_HOLD" and held["trip_id"] == ""
    assert held["candidates"][0]["trip_id"] == "A"


def test_non_authoritative_or_out_of_period_candidate_is_rejected():
    result = rank_trip_candidates([{"trip_id": "ghost", "score": 99}], trips=TRIPS)
    assert result["status"] == "UNASSIGNED_NO_VALID_TRIP"
    result = rank_trip_candidates([{"trip_id": "A", "score": 99,
                                    "service_period": {"starts_on": "2026-09-01", "ends_on": "2026-09-02"}}], trips=TRIPS)
    assert result["status"] == "UNASSIGNED_NO_VALID_TRIP"


def test_ota_service_period_beats_card_date_and_requires_authoritative_period():
    candidates = ota_service_period_candidate(
        {"service_period": {"starts_on": "2026-08-03", "ends_on": "2026-08-04"}}, TRIPS)
    assert {candidate["trip_id"] for candidate in candidates} == {"A", "B"}
    assert ota_service_period_candidate({"service_period": {"starts_on": "bad", "ends_on": "bad"}}, TRIPS) == []
    assert ota_service_period_candidate({"service_period": {"starts_on": "2026-08-03", "ends_on": "2026-08-04"},
                                          "service_period_conflict": True}, TRIPS) == []


def test_open_trip_ends_before_next_trip_and_duplicate_evidence_is_aggregated():
    trips = [{"trip_id": "open", "starts_on": "2026-08-01", "ends_on": None},
             {"trip_id": "next", "starts_on": "2026-08-05", "ends_on": "2026-08-09"}]
    periods = canonical_trip_periods(trips)
    assert periods["open"]["ends_on"] == "2026-08-04"
    result = rank_trip_candidates([
        {"trip_id": "open", "score": 3, "basis": "service"},
        {"trip_id": "open", "score": 3, "basis": "date"},
        {"trip_id": "next", "score": 3, "basis": "date"}], trips=trips)
    assert result["status"] == "CONFLICT_REVIEW"
    assert [c["trip_id"] for c in result["candidates"]] == ["next", "open"]
    assert "service" in next(c["basis"] for c in result["candidates"] if c["trip_id"] == "open")


def test_manual_unassigned_hold_and_exclude_are_protected():
    for state in ("MANUAL_UNASSIGNED", "MANUAL_HOLD", "MANUAL_EXCLUDED"):
        result = rank_trip_candidates([{"trip_id": "A", "score": 99}], trips=TRIPS,
                                      manual_status=state)
        assert result["status"] == state and result["trip_id"] == ""


def test_disabled_invalid_and_conflicted_trips_are_not_candidates():
    trips = [dict(TRIPS[0], enabled=False), dict(TRIPS[1], conflict=True)]
    assert rank_trip_candidates([{"trip_id": "A", "score": 1}, {"trip_id": "B", "score": 1}],
                                trips=trips)["status"] == "UNASSIGNED_NO_VALID_TRIP"


def test_invalid_trip_start_does_not_break_or_truncate_valid_open_trip():
    trips = [{"trip_id": "valid-open", "starts_on": "2026-08-01", "ends_on": None},
             {"trip_id": "invalid-date", "starts_on": "2026-99-99", "ends_on": None},
             {"trip_id": "disabled", "starts_on": "2026-08-05", "ends_on": None,
              "enabled": False},
             {"trip_id": "valid-next", "starts_on": "2026-08-10", "ends_on": "2026-08-12"}]
    periods = canonical_trip_periods(trips)
    assert set(periods) == {"valid-open", "valid-next"}
    assert periods["valid-open"]["ends_on"] == "2026-08-09"


def test_owner_approved_corrections_persist_source_exact_rules_in_existing_audit_core(tmp_path):
    conn = sqlite3.connect(tmp_path / "synthetic.sqlite", isolation_level=None)
    try:
        pipe = Pipeline(conn)
        rows = [domestic_row(merchant="SYNTHETIC HOTEL", amount=5000 + n, approval=f"a{n}")
                for n in range(2)]
        batch = pipe.receive(make_csv(rows), "synthetic.csv")["batch_id"]
        transactions = conn.execute(
            "SELECT transaction_id,source_hash,merchant_normalized,revision FROM transactions ORDER BY transaction_id"
        ).fetchall()
        for index, (txid, _, _, revision) in enumerate(transactions):
            pipe.save_decision(txid, revision, item="숙박비", description="합성 교정",
                               trip_id="trip-a", trip_validator=lambda trip: trip == "trip-a",
                               request_id=f"synthetic-decision-{index}")
        corrections = []
        for txid, digest, merchant, revision in conn.execute(
                "SELECT transaction_id,source_hash,merchant_normalized,revision FROM transactions"):
            corrections.append({"transaction_id": txid, "source_hash": digest,
                "merchant_normalized": merchant, "revision": revision, "trip_id": "trip-a",
                "item": "숙박비", "confidence": "낮음", "basis": "사용자 반복 교정",
                "owner_approved": True})
        proposal = propose_correction_pattern(corrections)
        assert proposal["status"] == "PENDING_OWNER_APPROVAL"
        # A later revision for the same transaction supersedes that transaction's old correction.
        assert propose_correction_pattern(corrections + [dict(corrections[0], revision=3,
                                                               owner_approved=False)])["status"] == "NO_PROPOSAL"
        with pytest.raises(ValueError, match="OWNER_APPROVAL_REQUIRED"):
            approve_correction_pattern(pipe.store, proposal, approved_by="", trips=TRIPS)
        approved = approve_correction_pattern(pipe.store, proposal, approved_by="synthetic-owner",
             trips=[{"trip_id": "trip-a", "starts_on": "2026-08-01", "ends_on": "2026-08-31"}])
        assert approved["status"] == "APPROVED" and len(approved["rules"]) == 2
        assert approve_correction_pattern(pipe.store, proposal, approved_by="synthetic-owner",
            trips=[{"trip_id": "trip-a", "starts_on": "2026-08-01", "ends_on": "2026-08-31"}])["status"] == "ALREADY_APPROVED"
        tampered = dict(proposal, scope=dict(proposal["scope"], item="다른 항목"))
        with pytest.raises(ValueError, match="PROPOSAL_CONTENT_CHANGED"):
            approve_correction_pattern(pipe.store, tampered, approved_by="synthetic-owner", trips=TRIPS)
        active = pipe.list_rules()
        assert len([rule for rule in active if rule["origin"] == "owner-approved-trip-correction"]) == 2
        assert all(rule["optional"].get("source_hash") and rule["optional"].get("inferred_assignment")
                   for rule in active if rule["origin"] == "owner-approved-trip-correction")
        assert conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='trip_correction_rules.approved'").fetchone()[0] == 1
        first = transactions[0]
        decision = classify_transaction({"merchant": first[2], "source_hash": first[1],
             "transaction_direction": "purchase", "transaction_kind": "purchase",
             "approval_date": "2026-08-02", "amount_krw": 5000}, rules=active,
             trip_resolver=lambda transaction, hint: "trip-a")
        assert decision["trip_id"] == "trip-a"
        other = classify_transaction({"merchant": first[2], "source_hash": "f" * 64,
             "transaction_direction": "purchase", "transaction_kind": "purchase",
             "approval_date": "2026-08-02", "amount_krw": 5000}, rules=active,
             trip_resolver=lambda transaction, hint: "trip-a")
        assert not other["trip_id"]
    finally:
        conn.close()


def _pending_synthetic_correction(pipe):
    rows = [domestic_row(merchant="SYNTHETIC INN", amount=7100 + n, approval=f"p{n}")
            for n in range(2)]
    pipe.receive(make_csv(rows), "synthetic-protection.csv")
    txs = pipe.store.conn.execute(
        "SELECT transaction_id,source_hash,merchant_normalized,revision FROM transactions ORDER BY transaction_id"
    ).fetchall()
    corrections = []
    for index, (txid, digest, merchant, revision) in enumerate(txs):
        pipe.save_decision(txid, revision, item="숙박비", description="합성 교정",
                           trip_id="trip-a", trip_validator=lambda trip: trip == "trip-a",
                           request_id=f"synthetic-protection-{index}")
        current_revision = pipe.store.conn.execute(
            "SELECT revision FROM transactions WHERE transaction_id=?", (txid,)).fetchone()[0]
        corrections.append({"transaction_id": txid, "source_hash": digest,
            "merchant_normalized": merchant, "revision": current_revision, "trip_id": "trip-a",
            "item": "숙박비", "confidence": "낮음", "basis": "반복 교정",
            "owner_approved": True})
    return propose_correction_pattern(corrections), txs


@pytest.mark.parametrize("protection", ["user_hold", "refund_pending", "evidence_pending",
                                         "parse_error", "cancel_direction", "cancel_kind",
                                         "company_exclusion"])
def test_approval_rechecks_current_transaction_protection(tmp_path, protection):
    conn = sqlite3.connect(tmp_path / f"{protection}.sqlite", isolation_level=None)
    try:
        pipe = Pipeline(conn)
        proposal, txs = _pending_synthetic_correction(pipe)
        txid, digest = txs[0][:2]
        if protection in ("user_hold", "refund_pending", "evidence_pending"):
            conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
                         (txid, digest, protection, "synthetic"))
        elif protection == "parse_error":
            conn.execute("UPDATE transactions SET parse_error='synthetic parse error' WHERE transaction_id=?", (txid,))
        elif protection == "cancel_direction":
            conn.execute("UPDATE transactions SET transaction_direction='refund' WHERE transaction_id=?", (txid,))
        elif protection == "cancel_kind":
            conn.execute("UPDATE transactions SET transaction_kind='refund' WHERE transaction_id=?", (txid,))
        else:
            conn.execute("INSERT INTO transaction_company_exclusions VALUES (?,?,?,?,?,?)",
                         (txid, digest, 1, 1, "synthetic", "2026-10-28T00:00:00Z"))
        with pytest.raises(ValueError, match="CORRECTION_PROTECTED"):
            approve_correction_pattern(pipe.store, proposal, approved_by="synthetic-owner",
                trips=[{"trip_id": "trip-a", "starts_on": "2026-08-01", "ends_on": "2026-08-31"}])
        assert conn.execute("SELECT COUNT(*) FROM cost_classification_rules").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='trip_correction_rules.approved'").fetchone()[0] == 0
    finally:
        conn.close()


def test_approval_rejects_forged_duplicate_references_even_with_recomputed_proposal_id(tmp_path):
    conn = sqlite3.connect(tmp_path / "duplicate-ref.sqlite", isolation_level=None)
    try:
        pipe = Pipeline(conn)
        proposal, _ = _pending_synthetic_correction(pipe)
        for bad_refs in ([proposal["corrections"][0]] * 2,
                         [proposal["corrections"][0], dict(proposal["corrections"][0], transaction_id="other")]):
            forged = dict(proposal, corrections=bad_refs)
            from app.provisional_assignment import _correction_proposal_id
            forged["id"] = _correction_proposal_id(forged["scope"], bad_refs)
            with pytest.raises(ValueError, match="INSUFFICIENT_DISTINCT_CORRECTIONS"):
                approve_correction_pattern(pipe.store, forged, approved_by="synthetic-owner",
                    trips=[{"trip_id": "trip-a", "starts_on": "2026-08-01", "ends_on": "2026-08-31"}])
        assert conn.execute("SELECT COUNT(*) FROM cost_classification_rules").fetchone()[0] == 0
    finally:
        conn.close()


def test_approval_rechecks_revision_and_manual_correction_after_proposal(tmp_path):
    conn = sqlite3.connect(tmp_path / "stale-correction.sqlite", isolation_level=None)
    try:
        pipe = Pipeline(conn)
        proposal, txs = _pending_synthetic_correction(pipe)
        txid = txs[0][0]
        revision = conn.execute("SELECT revision FROM transactions WHERE transaction_id=?", (txid,)).fetchone()[0]
        pipe.save_decision(txid, revision, item="교정 변경", description="최신 합성 수동 교정",
                           trip_id="trip-a", trip_validator=lambda trip: trip == "trip-a",
                           request_id="synthetic-later-correction")
        with pytest.raises(ValueError, match="CORRECTION_STALE_OR_PROTECTED"):
            approve_correction_pattern(pipe.store, proposal, approved_by="synthetic-owner",
                trips=[{"trip_id": "trip-a", "starts_on": "2026-08-01", "ends_on": "2026-08-31"}])
        assert conn.execute("SELECT COUNT(*) FROM cost_classification_rules").fetchone()[0] == 0
    finally:
        conn.close()


def test_second_rule_failure_rolls_back_rules_and_audit_but_preserves_outer_savepoint(tmp_path):
    conn = sqlite3.connect(tmp_path / "atomic.sqlite", isolation_level=None)
    try:
        pipe = Pipeline(conn)
        proposal, _ = _pending_synthetic_correction(pipe)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES ('now','outer.marker','keep','{}')")
        from app import rules
        original = rules.save_rule
        calls = 0

        def fail_second(store, rule):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic second rule failure")
            return original(store, rule)

        with patch("app.rules.save_rule", side_effect=fail_second):
            with pytest.raises(RuntimeError, match="synthetic second rule failure"):
                approve_correction_pattern(pipe.store, proposal, approved_by="synthetic-owner",
                    trips=[{"trip_id": "trip-a", "starts_on": "2026-08-01", "ends_on": "2026-08-31"}])
        assert conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM cost_classification_rules").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='rule.created'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='outer.marker'").fetchone()[0] == 1
        conn.rollback()
    finally:
        conn.close()
