"""Bounded synthetic tests for REVIEW-PREPARE-001 (Muse writer scope)."""
from __future__ import annotations

import csv
import io
import json

import pytest

from webapp.migration import build_reviewed_import_plan
from webapp.review_csv_adapter import REQUIRED_HEADERS, normalize_review_csv
from webapp.review_template import TemplateError, build_blank_review_template

SNAP = "0123456789abcdef" * 4
OTHER_SNAP = "ab" * 32

LEGACY_FIELDS = [
    "source_ref_snapshot_only",
    "source_date",
    "source_amount",
    "candidate_count",
    "candidate_transaction_keys",
    "candidate_date_fields",
    "disposition",
    "reviewer_decision",
    "review_note",
]


def make_legacy(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=LEGACY_FIELDS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def legacy_row(**over) -> dict:
    row = {
        "source_ref_snapshot_only": "ref-001",
        "source_date": "2026-01-02",
        "source_amount": "1500",
        "candidate_count": "1",
        "candidate_transaction_keys": json.dumps(["tx-001"]),
        "candidate_date_fields": "2026-01-02",
        "disposition": "candidate_review_required",
        "reviewer_decision": "",
        "review_note": "note-1",
    }
    row.update(over)
    return row


def test_positive_blank_single():
    out = build_blank_review_template(make_legacy([legacy_row()]), SNAP)
    assert out["row_count"] == 1
    assert out["counts"] == {"approved": 0, "rejected": 0, "incomplete": 1}
    header = next(csv.reader(io.StringIO(out["csv_text"])))
    assert header == list(REQUIRED_HEADERS)
    adapted = normalize_review_csv(out["csv_text"], SNAP)
    assert adapted["counts"] == {"approved": 0, "rejected": 0, "incomplete": 1}


def test_header_only_valid_zero():
    out = build_blank_review_template(make_legacy([]), SNAP)
    assert out["counts"] == {"approved": 0, "rejected": 0, "incomplete": 0}
    assert out["row_count"] == 0
    header = next(csv.reader(io.StringIO(out["csv_text"])))
    assert header == list(REQUIRED_HEADERS)
    assert out["csv_text"].endswith("\n")
    assert not out["csv_text"].startswith("\ufeff")
    adapted = normalize_review_csv(out["csv_text"], SNAP)
    assert adapted["counts"] == {"approved": 0, "rejected": 0, "incomplete": 0}


def test_canonical_ref_and_candidate_ordering():
    rows = [
        legacy_row(
            source_ref_snapshot_only="ref-b",
            candidate_count="2",
            candidate_transaction_keys=json.dumps(["tx-002", "tx-001"]),
        ),
        legacy_row(source_ref_snapshot_only="ref-a"),
    ]
    out = build_blank_review_template(make_legacy(rows), SNAP)
    parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
    assert [r["source_ref_snapshot_only"] for r in parsed] == ["ref-a", "ref-b"]
    for r in parsed:
        if r["source_ref_snapshot_only"] == "ref-b":
            assert r["candidate_transaction_keys"] == '["tx-001","tx-002"]'
            assert r["candidate_count"] == "2"


def test_korean_context_quoting_preserved():
    note = "메모, 따옴표 \"포함\" 한글"
    amount = "1,500원"
    rows = [legacy_row(review_note=note, source_amount=amount)]
    out = build_blank_review_template(make_legacy(rows), SNAP)
    parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
    assert parsed[0]["review_note"] == note
    assert parsed[0]["source_amount"] == amount
    assert parsed[0]["source_date"] == "2026-01-02"


def test_output_lf_no_bom_and_version_sha():
    rows = [legacy_row(), legacy_row(source_ref_snapshot_only="ref-002")]
    out = build_blank_review_template(make_legacy(rows), SNAP)
    assert not out["csv_text"].startswith("\ufeff")
    assert "\r" not in out["csv_text"]
    assert out["csv_text"].endswith("\n")
    parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
    assert all(r["review_schema_version"] == "review-csv-v1" for r in parsed)
    assert all(r["review_snapshot_sha256"] == SNAP for r in parsed)
    assert all(r["reviewer_decision"] == "" for r in parsed)


def test_reordered_header_fails():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    fields = list(LEGACY_FIELDS)
    fields[0], fields[1] = fields[1], fields[0]
    w.writerow(fields)
    w.writerow(["x"] * 9)
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(buf.getvalue(), SNAP)
    assert e.value.code == "LEGACY_SCHEMA_MISMATCH"


def test_missing_and_extra_header_fail():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([f for f in LEGACY_FIELDS if f != "review_note"])
    w.writerow(["x"] * 8)
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(buf.getvalue(), SNAP)
    assert e.value.code == "LEGACY_SCHEMA_MISMATCH"
    buf2 = io.StringIO()
    w2 = csv.writer(buf2, lineterminator="\n")
    w2.writerow(LEGACY_FIELDS + ["extra_col"])
    w2.writerow(["x"] * 10)
    with pytest.raises(TemplateError) as e2:
        build_blank_review_template(buf2.getvalue(), SNAP)
    assert e2.value.code == "LEGACY_SCHEMA_MISMATCH"


def test_unclosed_quote_fails():
    text = make_legacy([legacy_row()]) + '"unclosed,field\n'
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.code == "LEGACY_CSV_INVALID"


def test_ragged_row_fails():
    text = make_legacy([legacy_row()]) + "only,two\n"
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.code == "LEGACY_CSV_INVALID"


def test_preexisting_approve_fails():
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(
            make_legacy([legacy_row(reviewer_decision="APPROVE:tx-001")]), SNAP
        )
    assert e.value.code == "LEGACY_APPROVAL_PRESENT"


def test_preexisting_reject_and_whitespace_fail():
    for bad in ["REJECT", " ", "  ", "REJECT ", " APPROVE:tx-001"]:
        with pytest.raises(TemplateError) as e:
            build_blank_review_template(
                make_legacy([legacy_row(reviewer_decision=bad)]), SNAP
            )
        assert e.value.code == "LEGACY_APPROVAL_PRESENT"


def test_invalid_snapshot_param_fails():
    for bad in ["not-hex", "", SNAP + "\n", "z" * 64, 123]:
        with pytest.raises(TemplateError) as e:
            build_blank_review_template(make_legacy([legacy_row()]), bad)
        assert e.value.code == "INVALID_SNAPSHOT_SHA256"


def test_invalid_candidate_json_fails():
    for bad in ["tx-001,tx-002", "['tx-001']", '{"a": 1}', "[1, 2]", '[""]']:
        text = make_legacy(
            [legacy_row(candidate_count="1", candidate_transaction_keys=bad)]
        )
        # Align count for JSON-shape cases that parse as non-list is still invalid.
        with pytest.raises(TemplateError) as e:
            build_blank_review_template(text, SNAP)
        assert e.value.code == "INVALID_CANDIDATE_KEYS"


def test_candidate_count_mismatch_and_bad_count_fail():
    text = make_legacy(
        [
            legacy_row(
                candidate_count="1",
                candidate_transaction_keys=json.dumps(["tx-001", "tx-002"]),
            )
        ]
    )
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.code == "INVALID_CANDIDATE_KEYS"
    for bad_count in ["-1", "2.0", " 2", "abc"]:
        t2 = make_legacy([legacy_row(candidate_count=bad_count)])
        with pytest.raises(TemplateError) as e2:
            build_blank_review_template(t2, SNAP)
        assert e2.value.code == "INVALID_CANDIDATE_KEYS"


def test_duplicate_candidate_keys_fail():
    text = make_legacy(
        [
            legacy_row(
                candidate_count="2",
                candidate_transaction_keys=json.dumps(["tx-001", "tx-001"]),
            )
        ]
    )
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.code == "INVALID_CANDIDATE_KEYS"


def test_duplicate_ref_fails():
    rows = [
        legacy_row(source_ref_snapshot_only="dup"),
        legacy_row(source_ref_snapshot_only="dup"),
    ]
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(make_legacy(rows), SNAP)
    assert e.value.code == "DUPLICATE_REVIEW_REF"


def test_invalid_disposition_fails():
    text = make_legacy([legacy_row(disposition="Candidate_Review_Required")])
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.code == "INVALID_DISPOSITION"
    text2 = make_legacy([legacy_row(disposition="matched")])
    with pytest.raises(TemplateError) as e2:
        build_blank_review_template(text2, SNAP)
    assert e2.value.code == "INVALID_DISPOSITION"


def test_blank_ref_fails_without_echo():
    secret = "sensitive-ref-999"
    text = make_legacy([legacy_row(source_ref_snapshot_only="   ")])
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.code == "LEGACY_CSV_INVALID"
    assert secret not in str(e.value.message)
    assert e.value.message == e.value.code


def test_error_message_code_only():
    text = make_legacy(
        [legacy_row(source_ref_snapshot_only="dup"),
         legacy_row(source_ref_snapshot_only="dup")]
    )
    with pytest.raises(TemplateError) as e:
        build_blank_review_template(text, SNAP)
    assert e.value.message == "DUPLICATE_REVIEW_REF"
    assert "dup" not in e.value.message


def test_adapter_counts_and_planner_eligible_zero():
    rows = [
        legacy_row(source_ref_snapshot_only="p-1"),
        legacy_row(
            source_ref_snapshot_only="p-2",
            disposition="unmatched_review_required",
            candidate_count="0",
            candidate_transaction_keys="[]",
        ),
    ]
    out = build_blank_review_template(make_legacy(rows), SNAP)
    adapted = normalize_review_csv(out["csv_text"], SNAP)
    assert adapted["counts"] == {"approved": 0, "rejected": 0, "incomplete": 2}
    plan = build_reviewed_import_plan(SNAP, adapted["review_rows"])
    assert plan["counts"]["eligible"] == 0
    assert plan["counts"]["refused"] == 2


def test_context_cr_only_roundtrip():
    note = "a\rb"
    text = make_legacy([legacy_row(review_note=note)])
    out = build_blank_review_template(text, SNAP)
    parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
    assert parsed[0]["review_note"] == note
    assert parsed[0]["source_date"] == "2026-01-02"
    adapted = normalize_review_csv(out["csv_text"], SNAP)
    assert adapted["counts"]["incomplete"] == 1


def test_context_crlf_roundtrip():
    note = "a\r\nb"
    date_field = "2026-01-02\r\nnote"
    text = make_legacy(
        [legacy_row(review_note=note, candidate_date_fields=date_field)]
    )
    out = build_blank_review_template(text, SNAP)
    parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
    assert parsed[0]["review_note"] == note
    assert parsed[0]["candidate_date_fields"] == date_field


def test_context_lf_comma_quote_roundtrip():
    cases = [
        {"review_note": "a\nb"},
        {"review_note": "a,b"},
        {"review_note": 'a"b'},
        {"source_amount": "1,500\n원"},
        {"source_date": "2026-01-0,2"},
        {"candidate_date_fields": 'q"q,q\nq'},
    ]
    for i, over in enumerate(cases):
        ref = f"ctx-{i:03d}"
        text = make_legacy([legacy_row(source_ref_snapshot_only=ref, **over)])
        out = build_blank_review_template(text, SNAP)
        parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
        assert len(parsed) == 1
        for key, expected in over.items():
            assert parsed[0][key] == expected
        legacy_parsed = list(csv.DictReader(io.StringIO(text)))
        assert parsed[0][key] == legacy_parsed[0][key]


def test_context_fields_preserved_byte_for_byte():
    note = " 한글, \"인용\"\r\n다음줄\rmixed\nend "
    amount = " 1,500원 "
    date_val = " 2026-01-02 "
    date_fields = " f1, f2\r\nf3 "
    text = make_legacy(
        [
            legacy_row(
                review_note=note,
                source_amount=amount,
                source_date=date_val,
                candidate_date_fields=date_fields,
            )
        ]
    )
    out = build_blank_review_template(text, SNAP)
    parsed = list(csv.DictReader(io.StringIO(out["csv_text"])))
    assert parsed[0]["review_note"] == note
    assert parsed[0]["source_amount"] == amount
    assert parsed[0]["source_date"] == date_val
    assert parsed[0]["candidate_date_fields"] == date_fields
