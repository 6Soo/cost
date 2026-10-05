"""Tests for tools/build_reviewed_import_plan_from_csv.py.

Two layers, both against the module under test:

* Plumbing tests, using a controlled in-memory stand-in injected into
  ``sys.modules``. Nothing is written to disk outside the per-test
  temporary CSV, and no source file is ever edited or stubbed on disk.
* End-to-end tests against the real ``webapp.review_csv_adapter`` and the
  real pure planner, over synthetic eleven-field ``review-csv-v1`` CSVs.

The adapter is a required product import here, not an optional one: if
``webapp.review_csv_adapter`` is missing or broken, these tests fail and
say so instead of skipping.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import types
from contextlib import redirect_stderr, redirect_stdout

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
CLI_PATH = os.path.join(TOOLS_DIR, "build_reviewed_import_plan_from_csv.py")

from tools import build_reviewed_import_plan_from_csv as cli  # noqa: E402
from webapp import review_csv_adapter  # noqa: E402,F401

SNAPSHOT_SHA = "a" * 64
OTHER_SHA = "b" * 64

SENSITIVE_REF = "src-ref-customer-secret-4242"
SENSITIVE_NOTE = "note-must-not-leak@example.com"
SENSITIVE_DATE = "2026-01-01"
SENSITIVE_AMOUNT = "987654321"
SENSITIVE_DATE_FIELDS = '["2026-01-01","2026-02-02"]'

CSV_HEADER = (
    "review_schema_version,source_ref_snapshot_only,candidate_count,"
    "candidate_transaction_keys,disposition,review_decision,"
    "review_snapshot_sha256\n"
)


def _csv_text(rows=()) -> str:
    return CSV_HEADER + "".join(rows)


# ------------------------------------------- real review-csv-v1 fixtures

REVIEW_HEADERS = (
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
)


def _review_row(ref, *, keys, disposition="candidate_review_required",
                decision="", sha=SNAPSHOT_SHA, count=None, note=""):
    return {
        "source_ref_snapshot_only": ref,
        "source_date": SENSITIVE_DATE,
        "source_amount": SENSITIVE_AMOUNT,
        "candidate_count": (len(keys) if count is None else count),
        "candidate_transaction_keys": json.dumps(list(keys)),
        "candidate_date_fields": SENSITIVE_DATE_FIELDS,
        "disposition": disposition,
        "reviewer_decision": decision,
        "review_note": note,
        "review_schema_version": "review-csv-v1",
        "review_snapshot_sha256": sha,
    }


def _render_review_csv(rows, headers=REVIEW_HEADERS) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers),
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in headers})
    return buffer.getvalue()


def _write_review_csv(tmp_path, rows, name="review.csv",
                      headers=REVIEW_HEADERS):
    return _write_csv(tmp_path, _render_review_csv(rows, headers), name)


def _mixed_rows():
    """One approved, one rejected, one blank (incomplete) row."""
    return [
        _review_row("src-ref-001", keys=["tx-001", "tx-002"],
                    decision="APPROVE:tx-001"),
        _review_row("src-ref-002", keys=["tx-003"],
                    disposition="unmatched_review_required", decision="REJECT"),
        _review_row("src-ref-003", keys=["tx-004", "tx-005"],
                    decision=""),
    ]


def _write_csv(tmp_path, text: str, name: str = "review.csv") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _approved_row(ref: str = "src-ref-001") -> dict:
    return {
        "source_ref_snapshot_only": ref,
        "candidate_count": 2,
        "candidate_transaction_keys": ["tx-002", "tx-001"],
        "disposition": "matched",
        "approved": True,
        "chosen_candidate_key": "tx-001",
        "review_snapshot_sha256": SNAPSHOT_SHA,
    }


def _unmatched_row(ref: str = "src-ref-002") -> dict:
    return {
        "source_ref_snapshot_only": ref,
        "candidate_count": 1,
        "candidate_transaction_keys": ["tx-009"],
        "disposition": "unmatched_review_required",
        "approved": False,
        "chosen_candidate_key": None,
        "review_snapshot_sha256": SNAPSHOT_SHA,
    }


class _StubValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"refused: {code}")
        self.code = code


def _make_stub(*, rows=None, counts=None, raise_code=None,
               raise_message="", returns_non_dict=False):
    """Build a fake adapter module for sys.modules injection."""
    module = types.ModuleType("webapp.review_csv_adapter")
    module.ValidationError = _StubValidationError
    seen: dict = {}

    def normalize_review_csv(text, snapshot_sha256):
        seen["text"] = text
        seen["snapshot_sha256"] = snapshot_sha256
        if raise_code is not None:
            raise _StubValidationError(raise_code) from RuntimeError(raise_message)
        if returns_non_dict:
            return ["not", "a", "mapping"]
        return {
            "review_rows": list(rows or []),
            "counts": dict(counts or {"approved": 0, "rejected": 0,
                                      "incomplete": 0}),
        }

    module.normalize_review_csv = normalize_review_csv
    module.calls = seen
    return module


def _install(monkeypatch, stub) -> None:
    monkeypatch.setitem(sys.modules, "webapp.review_csv_adapter", stub)


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _run_with_stub(monkeypatch, tmp_path, *, stub, csv_text=None,
                   sha=SNAPSHOT_SHA):
    _install(monkeypatch, stub)
    path = _write_csv(tmp_path, csv_text if csv_text is not None else _csv_text())
    return _run(["--csv", path, "--snapshot-sha256", sha])


# --------------------------------------------------------------- success

def test_success_exit_zero_and_exact_payload_shape(monkeypatch, tmp_path):
    stub = _make_stub(rows=[_approved_row(), _unmatched_row()],
                      counts={"approved": 1, "rejected": 0, "incomplete": 1})
    code, out, err = _run_with_stub(monkeypatch, tmp_path, stub=stub)

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert set(payload) == {"snapshot_sha256", "counts", "reviewed_plan",
                            "plan_digest"}
    assert payload["snapshot_sha256"] == SNAPSHOT_SHA
    assert payload["counts"] == {"approved": 1, "rejected": 0, "incomplete": 1}
    assert payload["plan_digest"]
    assert payload["reviewed_plan"]["counts"] == {"eligible": 1, "refused": 1,
                                                 "total": 2}
    assert payload["reviewed_plan"]["eligible"][0]["plan_id"]
    assert out.endswith("\n")


def test_output_is_deterministic_and_sorted_compact(monkeypatch, tmp_path):
    stub = _make_stub(rows=[_approved_row(), _unmatched_row()],
                      counts={"approved": 1, "rejected": 0, "incomplete": 1})
    stub_b = _make_stub(rows=[_approved_row(), _unmatched_row()],
                        counts={"approved": 1, "rejected": 0, "incomplete": 1})
    first = _run_with_stub(monkeypatch, tmp_path, stub=stub)
    second = _run_with_stub(monkeypatch, tmp_path, stub=stub_b)

    assert first[0] == 0 and second[0] == 0
    assert first[1] == second[1]
    assert ", " not in first[1] and '": ' not in first[1]
    assert list(json.loads(first[1])) == sorted(json.loads(first[1]))


def test_bom_csv_is_read_as_utf8_sig(monkeypatch, tmp_path):
    stub = _make_stub(rows=[_approved_row()],
                      counts={"approved": 1, "rejected": 0, "incomplete": 0})
    _install(monkeypatch, stub)
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + _csv_text().encode("utf-8"))

    code, out, _ = _run(["--csv", str(path), "--snapshot-sha256", SNAPSHOT_SHA])

    assert code == 0
    assert json.loads(out)["counts"]["approved"] == 1
    assert not stub.calls["text"].startswith("\ufeff")


# ---------------------------------------------------------------- errors

def test_adapter_validation_error_exit_two_code_only(monkeypatch, tmp_path):
    stub = _make_stub(raise_code="SNAPSHOT_SHA_MISMATCH",
                      raise_message="secret-customer-9999 leaked here")
    code, out, err = _run_with_stub(monkeypatch, tmp_path, stub=stub)

    assert code == 2
    assert json.loads(out) == {"error": {"code": "SNAPSHOT_SHA_MISMATCH"}}
    assert err.strip() == "SNAPSHOT_SHA_MISMATCH"
    assert "secret-customer-9999" not in out
    assert "secret-customer-9999" not in err


def test_unexpected_adapter_error_is_stable_internal_code(monkeypatch,
                                                         tmp_path):
    stub = _make_stub(raise_code="NOT_A_REAL_CODE",
                      raise_message="leaky repr of a customer row")
    code, out, err = _run_with_stub(monkeypatch, tmp_path, stub=stub)

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INTERNAL_ERROR"}}
    assert err.strip() == "INTERNAL_ERROR"
    assert "leaky" not in out + err


def test_missing_file_exit_two(monkeypatch, tmp_path):
    stub = _make_stub()
    _install(monkeypatch, stub)
    missing = str(tmp_path / "not-here.csv")

    code, out, err = _run(["--csv", missing, "--snapshot-sha256", SNAPSHOT_SHA])

    assert code == 2
    assert json.loads(out) == {"error": {"code": "CSV_FILE_NOT_FOUND"}}
    assert "not-here" not in out + err
    assert err.strip() == "CSV_FILE_NOT_FOUND"


def test_malformed_utf8_and_directory_exit_two(monkeypatch, tmp_path):
    stub = _make_stub()
    _install(monkeypatch, stub)
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"\xff\xfe\x00review")

    code, out, _ = _run(["--csv", str(bad), "--snapshot-sha256", SNAPSHOT_SHA])
    assert code == 2
    assert json.loads(out) == {"error": {"code": "CSV_ENCODING_INVALID"}}

    code, out, _ = _run(["--csv", str(tmp_path), "--snapshot-sha256",
                         SNAPSHOT_SHA])
    assert code == 2
    assert json.loads(out) == {"error": {"code": "CSV_FILE_UNREADABLE"}}


@pytest.mark.parametrize("argv", [
    [],
    ["--csv", "only.csv"],
    ["--snapshot-sha256", SNAPSHOT_SHA],
    ["--csv", "only.csv", "--snapshot-sha256", "not-hex"],
    ["--csv", "only.csv", "--snapshot-sha256", "abc"],
    ["--csv", "only.csv", "--snapshot-sha256", SNAPSHOT_SHA, "--unknown", "x"],
])
def test_argument_failures_exit_two_without_usage_echo(monkeypatch, tmp_path,
                                                       argv):
    stub = _make_stub()
    _install(monkeypatch, stub)
    path = _write_csv(tmp_path, _csv_text())
    resolved = [path if part == "only.csv" else part for part in argv]

    code, out, err = _run(resolved)

    assert code == 2
    assert set(json.loads(out)) == {"error"}
    assert json.loads(out)["error"]["code"] in {
        "INVALID_ARGUMENT", "INVALID_SNAPSHOT_SHA256"}
    assert "usage:" not in (out + err).lower()
    assert path not in out + err
    assert stub.calls == {}


# --------------------------------------------------------------- privacy

def test_output_excludes_notes_refs_prose_and_sensitive_values(monkeypatch,
                                                               tmp_path):
    row = _approved_row(ref=SENSITIVE_REF)
    row["review_note"] = SENSITIVE_NOTE
    row["source_dates"] = "2026-01-01"
    row["amount_krw"] = 987654
    refused = _unmatched_row(ref="src-ref-002")
    refused["review_note"] = SENSITIVE_NOTE
    stub = _make_stub(rows=[row, refused],
                      counts={"approved": 1, "rejected": 0, "incomplete": 1})

    code, out, err = _run_with_stub(monkeypatch, tmp_path, stub=stub)

    assert code == 0
    payload = json.loads(out)
    plan = payload["reviewed_plan"]
    assert set(plan) == {"eligible", "refused", "counts"}
    for record in plan["eligible"] + plan["refused"]:
        assert set(record) <= {
            "source_ref_snapshot_only", "review_snapshot_sha256",
            "chosen_candidate_key", "candidate_transaction_keys", "plan_id",
            "disposition", "reason_code", "approved", "candidate_fingerprint",
            "candidate_count"}
        assert "review_note" not in record
        assert "reason" not in record
    assert SENSITIVE_NOTE not in out + err
    assert "2026-01-01" not in out + err
    assert "987654" not in out + err
    assert str(tmp_path) not in out + err
    # The ref itself is snapshot-scoped plan identity and stays, but the CSV
    # path never does.
    assert SENSITIVE_REF in out


# ------------------------------------- end-to-end with the real adapter

def test_mixed_approve_reject_blank_end_to_end(tmp_path):
    path = _write_review_csv(tmp_path, _mixed_rows())

    code, out, err = _run(["--csv", path, "--snapshot-sha256", SNAPSHOT_SHA])

    assert code == 0, out + err
    assert err == ""
    payload = json.loads(out)
    assert set(payload) == {"snapshot_sha256", "counts", "reviewed_plan",
                            "plan_digest"}
    assert payload["snapshot_sha256"] == SNAPSHOT_SHA
    # The adapter keeps human REJECT and blank (incomplete) apart, even
    # though the pure planner may park both on the refused side.
    assert payload["counts"] == {"approved": 1, "rejected": 1, "incomplete": 1}

    plan = payload["reviewed_plan"]
    assert plan["counts"] == {"eligible": 1, "refused": 2, "total": 3}

    eligible = plan["eligible"]
    assert len(eligible) == 1
    assert eligible[0]["source_ref_snapshot_only"] == "src-ref-001"
    assert eligible[0]["chosen_candidate_key"] == "tx-001"
    assert eligible[0]["candidate_transaction_keys"] == ["tx-001", "tx-002"]
    assert eligible[0]["plan_id"].startswith("rip-")

    refused = {item["source_ref_snapshot_only"]: item
               for item in plan["refused"]}
    assert set(refused) == {"src-ref-002", "src-ref-003"}
    for item in refused.values():
        assert item["approved"] is False
        assert item["chosen_candidate_key"] == ""
    assert refused["src-ref-002"]["disposition"] == "unmatched_review_required"
    assert refused["src-ref-003"]["disposition"] == "candidate_review_required"


def test_row_and_candidate_order_do_not_move_json_or_digest(tmp_path):
    rows = _mixed_rows()
    forward = _write_review_csv(tmp_path, rows, name="forward.csv")
    reversed_rows = list(reversed(rows))
    backward = _write_review_csv(tmp_path, reversed_rows, name="backward.csv")
    # Same candidate sets, opposite order inside the JSON array.
    swapped = [dict(row) for row in rows]
    for row in swapped:
        keys = json.loads(row["candidate_transaction_keys"])
        row["candidate_transaction_keys"] = json.dumps(list(reversed(keys)))
    swapped_csv = _write_review_csv(tmp_path, swapped, name="swapped.csv")

    first = _run(["--csv", forward, "--snapshot-sha256", SNAPSHOT_SHA])
    second = _run(["--csv", backward, "--snapshot-sha256", SNAPSHOT_SHA])
    third = _run(["--csv", swapped_csv, "--snapshot-sha256", SNAPSHOT_SHA])

    assert first[0] == second[0] == third[0] == 0
    assert first[1] == second[1] == third[1]
    digest = json.loads(first[1])["plan_digest"]
    assert digest == json.loads(third[1])["plan_digest"]
    eligible = json.loads(first[1])["reviewed_plan"]["eligible"]
    assert [item["source_ref_snapshot_only"] for item in eligible] == [
        "src-ref-001"]


def test_snapshot_sha_mismatch_exit_two(tmp_path):
    rows = _mixed_rows()
    rows[1]["review_snapshot_sha256"] = OTHER_SHA
    path = _write_review_csv(tmp_path, rows)

    code, out, err = _run(["--csv", path, "--snapshot-sha256", SNAPSHOT_SHA])

    assert code == 2
    assert json.loads(out) == {"error": {"code": "SNAPSHOT_SHA_MISMATCH"}}
    assert err.strip() == "SNAPSHOT_SHA_MISMATCH"
    assert path not in out + err
    assert OTHER_SHA not in out + err


def _raw_csv(headers, rows) -> str:
    """Hand-rolled CSV text with exact field lists (no dict convenience)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for row in [list(headers)] + [list(r) for r in rows]:
        writer.writerow(row)
    return buffer.getvalue()


def _valid_raw_row(ref="src-ref-001", decision="REJECT",
                   disposition="candidate_review_required", sha=None):
    return [ref, "2026-01-01", "1000", "1", '["tx-001"]', "[]", disposition,
            decision, "note", "review-csv-v1", sha or SNAPSHOT_SHA]


@pytest.mark.parametrize("text,code", [
    ("", "MISSING_COLUMN"),
    ("source_ref_snapshot_only\n", "MISSING_COLUMN"),
    (_raw_csv(REVIEW_HEADERS, [["src-ref-001", "2026-01-01", "1000", "1"]]),
     "ROW_LENGTH_MISMATCH"),
    (_raw_csv(list(REVIEW_HEADERS) + ["review_note"], []),
     "DUPLICATE_HEADER"),
    (_raw_csv(list(REVIEW_HEADERS) + ["surprise_column"], []),
     "UNEXPECTED_COLUMN"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row(ref=" ")]),
     "INVALID_SOURCE_REF"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row(decision="maybe")]),
     "INVALID_REVIEW_DECISION"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row(decision="approve:tx-001")]),
     "INVALID_REVIEW_DECISION"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row(decision="APPROVE:tx-404")]),
     "APPROVED_KEY_NOT_FOUND"),
    (_raw_csv(REVIEW_HEADERS,
              [_valid_raw_row(disposition="unmatched_review_required",
                              decision="APPROVE:tx-001")]),
     "APPROVAL_NOT_ALLOWED"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row(), _valid_raw_row()]),
     "DUPLICATE_SOURCE_REF"),
    (_raw_csv(REVIEW_HEADERS,
              [list(_valid_raw_row(decision="APPROVE:tx-001")[:3])
               + ["3", '["tx-001"]'] + _valid_raw_row()[5:]]),
     "CANDIDATE_COUNT_MISMATCH"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row()[:9]
                               + ["review-csv-v2", SNAPSHOT_SHA]]),
     "INVALID_SCHEMA_VERSION"),
    (_raw_csv(REVIEW_HEADERS, [_valid_raw_row(sha=OTHER_SHA)]),
     "SNAPSHOT_SHA_MISMATCH"),
])
def test_known_adapter_codes_reach_stdout(tmp_path, text, code):
    path = _write_csv(tmp_path, text, name="bad.csv")

    exit_code, out, err = _run(["--csv", path, "--snapshot-sha256",
                                SNAPSHOT_SHA])

    assert exit_code == 2, out + err
    assert json.loads(out) == {"error": {"code": code}}
    assert err.strip() == code
    assert path not in out + err
    assert "Traceback" not in err


def test_privacy_end_to_end_keeps_identity_and_drops_prose(tmp_path):
    rows = _mixed_rows()
    for row in rows:
        row["review_note"] = SENSITIVE_NOTE
    path = _write_review_csv(tmp_path, rows)

    code, out, err = _run(["--csv", path, "--snapshot-sha256", SNAPSHOT_SHA])

    assert code == 0
    payload = json.loads(out)
    plan = payload["reviewed_plan"]

    # Snapshot-scoped plan identity is contract output and stays.
    assert "src-ref-001" in out
    assert "tx-001" in out
    assert "rip-" in out

    # Free prose, input path, raw row text, dates and amounts do not. The
    # raw disposition string is contract output, so it is not in this list.
    for absent in (SENSITIVE_NOTE, SENSITIVE_DATE, SENSITIVE_AMOUNT,
                   SENSITIVE_DATE_FIELDS, "APPROVE:", "reviewer_decision",
                   "review_note", "review-csv-v1", "REJECT", str(tmp_path)):
        assert absent not in out + err, absent
    for record in plan["eligible"] + plan["refused"]:
        assert "review_note" not in record
        assert "reason" not in record
        assert "source_date" not in record
        assert "source_amount" not in record


# ------------------------------------------------- invocation styles

def test_script_entry_point_runs_from_a_foreign_cwd(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    csv_path = _write_review_csv(tmp_path, _mixed_rows())
    argv = [sys.executable, CLI_PATH, "--csv", csv_path,
            "--snapshot-sha256", SNAPSHOT_SHA]

    proc = subprocess.run(argv, cwd=str(tmp_path), env=env,
                          capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["counts"] == {"approved": 1, "rejected": 1, "incomplete": 1}
    assert proc.stderr == ""
    assert str(tmp_path) not in proc.stdout + proc.stderr


def test_module_entry_point_runs_from_the_project_root(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    csv_path = _write_review_csv(tmp_path, _mixed_rows())
    argv = [sys.executable, "-m", "tools.build_reviewed_import_plan_from_csv",
            "--csv", csv_path, "--snapshot-sha256", SNAPSHOT_SHA]

    proc = subprocess.run(argv, cwd=PROJECT_ROOT, env=env,
                          capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["counts"] == {"approved": 1, "rejected": 1,
                                                 "incomplete": 1}


def test_help_is_available_through_both_entry_points(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    cases = (
        ([sys.executable, "-m", "tools.build_reviewed_import_plan_from_csv",
          "--help"], PROJECT_ROOT),
        ([sys.executable, CLI_PATH, "--help"], tmp_path),
    )
    for argv, workdir in cases:
        proc = subprocess.run(argv, cwd=str(workdir), env=env,
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "usage:" in proc.stdout.lower()
        assert "--snapshot-sha256" in proc.stdout
