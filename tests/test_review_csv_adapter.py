"""Bounded synthetic tests for REVIEW-ADAPTER-001 (Muse writer scope)."""
from __future__ import annotations

import csv
import io
import json

import pytest

from webapp.migration import build_reviewed_import_plan
from webapp.review_csv_adapter import ValidationError, normalize_review_csv

SNAP = "0123456789abcdef" * 4
OTHER_SNAP = "ff" * 32
FIELDS = [
    "source_ref_snapshot_only",
    "source_date",
    "source_amount",
    "candidate_count",
    "candidate_transaction_keys",
    "candidate_date_fields",
    "disposition",
    "reviewer_decision",
    "review_note",
    "review_schema_version",
    "review_snapshot_sha256",
]


def make_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def base_row(**over) -> dict:
    row = {
        "source_ref_snapshot_only": "ref-001",
        "source_date": "2026-01-01",
        "source_amount": "1000",
        "candidate_count": "1",
        "candidate_transaction_keys": json.dumps(["tx-001"]),
        "candidate_date_fields": "2026-01-01",
        "disposition": "candidate_review_required",
        "reviewer_decision": "",
        "review_note": "note",
        "review_schema_version": "review-csv-v1",
        "review_snapshot_sha256": SNAP,
    }
    row.update(over)
    return row


def test_approve_single_matched():
    text = make_csv([base_row(reviewer_decision="APPROVE:tx-001")])
    out = normalize_review_csv(text, SNAP)
    assert out["counts"] == {"approved": 1, "rejected": 0, "incomplete": 0}
    r = out["review_rows"][0]
    assert r["disposition"] == "matched" and r["approved"] is True
    assert r["chosen_candidate_key"] == "tx-001"
    assert set(r.keys()) == {
        "source_ref_snapshot_only", "candidate_count",
        "candidate_transaction_keys", "disposition", "approved",
        "chosen_candidate_key", "review_snapshot_sha256",
    }


def test_approve_multi_selects_one_sorted():
    keys = json.dumps(["tx-002", "tx-001"])
    text = make_csv([base_row(candidate_count="2",
                              candidate_transaction_keys=keys,
                              reviewer_decision="APPROVE:tx-002")])
    out = normalize_review_csv(text, SNAP)
    assert out["review_rows"][0]["candidate_transaction_keys"] == ["tx-001", "tx-002"]
    assert out["review_rows"][0]["chosen_candidate_key"] == "tx-002"


def test_zero_candidates_blank_incomplete():
    text = make_csv([base_row(candidate_count="0",
                              candidate_transaction_keys="[]",
                              disposition="candidate_review_required",
                              reviewer_decision="")])
    out = normalize_review_csv(text, SNAP)
    assert out["counts"]["incomplete"] == 1
    assert out["review_rows"][0]["approved"] is False
    assert out["review_rows"][0]["chosen_candidate_key"] is None


def test_reject_preserves_disposition():
    text = make_csv([base_row(reviewer_decision="REJECT")])
    out = normalize_review_csv(text, SNAP)
    assert out["counts"]["rejected"] == 1
    assert out["review_rows"][0]["disposition"] == "candidate_review_required"
    assert out["review_rows"][0]["approved"] is False


def test_unmatched_reject_and_blank():
    rows = [
        base_row(source_ref_snapshot_only="r1", disposition="unmatched_review_required",
                 reviewer_decision="REJECT"),
        base_row(source_ref_snapshot_only="r2", disposition="unmatched_review_required",
                 reviewer_decision=""),
    ]
    out = normalize_review_csv(make_csv(rows), SNAP)
    assert out["counts"] == {"approved": 0, "rejected": 1, "incomplete": 1}
    assert all(r["approved"] is False and r["chosen_candidate_key"] is None
               for r in out["review_rows"])


def test_missing_column_fails():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([f for f in FIELDS if f != "review_note"])
    w.writerow(["x"] * (len(FIELDS) - 1))
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(buf.getvalue(), SNAP)
    assert e.value.code == "MISSING_COLUMN"


def test_duplicate_header_fails():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(FIELDS + ["source_date"])
    w.writerow(["x"] * (len(FIELDS) + 1))
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(buf.getvalue(), SNAP)
    assert e.value.code == "DUPLICATE_HEADER"


def test_unexpected_extra_column_fails():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(FIELDS + ["extra_col"])
    w.writerow(["x"] * (len(FIELDS) + 1))
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(buf.getvalue(), SNAP)
    assert e.value.code == "UNEXPECTED_COLUMN"


def test_ragged_row_fails():
    text = make_csv([base_row()]) + "short,line\n"
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "ROW_LENGTH_MISMATCH"


def test_invalid_snapshot_param_fails():
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(make_csv([base_row()]), "not-hex")
    assert e.value.code == "INVALID_SHA256"


def test_snapshot_mismatch_fails():
    text = make_csv([base_row(review_snapshot_sha256=OTHER_SNAP)])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "SNAPSHOT_SHA_MISMATCH"


def test_invalid_schema_version_fails():
    text = make_csv([base_row(review_schema_version="review-csv-v2")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "INVALID_SCHEMA_VERSION"


def test_duplicate_source_ref_fails():
    rows = [base_row(source_ref_snapshot_only="dup"),
            base_row(source_ref_snapshot_only="dup")]
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(make_csv(rows), SNAP)
    assert e.value.code == "DUPLICATE_SOURCE_REF"


def test_invalid_candidate_count_fails():
    for bad in ["-1", "2.0", " 2", "abc", ""]:
        text = make_csv([base_row(candidate_count=bad)])
        with pytest.raises(ValidationError) as e:
            normalize_review_csv(text, SNAP)
        assert e.value.code == "INVALID_CANDIDATE_COUNT"


def test_invalid_keys_json_types_fail():
    bads = ["tx-001,tx-002", "['tx-001']", '{"a": 1}', '"tx-001"', "[1, 2]", '[""]']
    for bad in bads:
        text = make_csv([base_row(candidate_transaction_keys=bad)])
        with pytest.raises(ValidationError) as e:
            normalize_review_csv(text, SNAP)
        assert e.value.code == "INVALID_CANDIDATE_KEYS_JSON"


def test_candidate_count_mismatch_fails():
    text = make_csv([base_row(candidate_count="1",
                              candidate_transaction_keys=json.dumps(["tx-001", "tx-002"]))])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "CANDIDATE_COUNT_MISMATCH"


def test_duplicate_candidate_keys_fail():
    text = make_csv([base_row(candidate_count="2",
                              candidate_transaction_keys=json.dumps(["tx-001", "tx-001"]))])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "APPROVED_KEY_DUPLICATED"


def test_invalid_disposition_and_casefold_fails():
    text = make_csv([base_row(disposition="Candidate_Review_Required")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "INVALID_DISPOSITION"


def test_decision_whitespace_and_case_fail():
    for bad in [" REJECT", "REJECT ", "approve", "APPROVE:", "APPROVE: ", "reject"]:
        text = make_csv([base_row(reviewer_decision=bad)])
        with pytest.raises(ValidationError) as e:
            normalize_review_csv(text, SNAP)
        assert e.value.code == "INVALID_REVIEW_DECISION"


def test_unmatched_approval_not_allowed():
    text = make_csv([base_row(disposition="unmatched_review_required",
                              reviewer_decision="APPROVE:tx-001")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "APPROVAL_NOT_ALLOWED"


def test_approved_key_not_found():
    text = make_csv([base_row(reviewer_decision="APPROVE:tx-999")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "APPROVED_KEY_NOT_FOUND"


def test_determinism_sorted_output():
    rows = [
        base_row(source_ref_snapshot_only="ref-b",
                 candidate_transaction_keys=json.dumps(["tx-002", "tx-001"]),
                 candidate_count="2", reviewer_decision="APPROVE:tx-001"),
        base_row(source_ref_snapshot_only="ref-a", reviewer_decision="REJECT"),
    ]
    out1 = normalize_review_csv(make_csv(rows), SNAP)
    out2 = normalize_review_csv(make_csv(list(reversed(rows))), SNAP)
    assert out1 == out2
    assert [r["source_ref_snapshot_only"] for r in out1["review_rows"]] == ["ref-a", "ref-b"]


def test_no_note_leak_and_error_no_echo():
    secret = "secret-note-xyz-123"
    text = make_csv([base_row(reviewer_decision="APPROVE:tx-001", review_note=secret)])
    out = normalize_review_csv(text, SNAP)
    assert secret not in json.dumps(out)
    bad = make_csv([base_row(source_ref_snapshot_only="sensitive-ref-999",
                              reviewer_decision="APPROVE:missing-key")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(bad, SNAP)
    assert "sensitive-ref-999" not in e.value.message
    assert "missing-key" not in e.value.message


def test_header_only_valid_empty():
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    out = normalize_review_csv(buf.getvalue(), SNAP)
    assert out == {"review_rows": [], "counts": {"approved": 0, "rejected": 0, "incomplete": 0}}


def test_empty_csv_fails():
    with pytest.raises(ValidationError) as e:
        normalize_review_csv("", SNAP)
    assert e.value.code == "MISSING_COLUMN"


def test_bom_stripped():
    text = "\ufeff" + make_csv([base_row(reviewer_decision="REJECT")])
    out = normalize_review_csv(text, SNAP)
    assert out["counts"]["rejected"] == 1


def test_arg_sha_trailing_newline_fails():
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(make_csv([base_row()]), SNAP + "\n")
    assert e.value.code == "INVALID_SHA256"


def test_row_sha_trailing_newline_fails():
    text = make_csv([base_row(review_snapshot_sha256=SNAP + "\n")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "INVALID_SHA256"


def test_count_trailing_newline_fails():
    text = make_csv([base_row(candidate_count="1\n")])
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "INVALID_CANDIDATE_COUNT"


def test_unclosed_quote_fails():
    text = make_csv([base_row()]) + '"unclosed,field\n'
    with pytest.raises(ValidationError) as e:
        normalize_review_csv(text, SNAP)
    assert e.value.code == "MALFORMED_CSV"


def test_integration_with_pure_plan():
    rows = [
        base_row(source_ref_snapshot_only="ok-1", reviewer_decision="APPROVE:tx-001"),
        base_row(source_ref_snapshot_only="no-1", reviewer_decision="REJECT"),
        base_row(source_ref_snapshot_only="no-2", reviewer_decision=""),
    ]
    adapted = normalize_review_csv(make_csv(rows), SNAP)
    plan = build_reviewed_import_plan(SNAP, adapted["review_rows"])
    assert plan["counts"]["eligible"] == 1
    assert plan["counts"]["refused"] == 2
    assert plan["eligible"][0]["source_ref_snapshot_only"] == "ok-1"
    assert plan["snapshot_sha256"] == SNAP
