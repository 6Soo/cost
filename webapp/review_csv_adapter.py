"""REVIEW-ADAPTER-001 synthetic CSV adapter (Sol contract).

Pure string parsing only. No filesystem or database I/O.

Contract summary:
- Input CSV headers (11, exact, any order, no duplicates, no extras):
  source_ref_snapshot_only, source_date, source_amount,
  candidate_count, candidate_transaction_keys, candidate_date_fields,
  disposition, reviewer_decision, review_note,
  review_schema_version, review_snapshot_sha256
- review_schema_version must be exactly ``review-csv-v1``.
- review_snapshot_sha256 must be 64 hex and exactly equal to the
  ``snapshot_sha256`` argument on every row (no trimming or case folding).
- candidate_transaction_keys is JSON array only, elements exact non-blank
  unique strings, kept byte-for-byte. candidate_count is decimal
  non-negative integer text and must equal list length.
- source_ref_snapshot_only is non-blank (empty or whitespace-only is
  blank) and unique (exact match).
- Raw disposition is exactly ``candidate_review_required`` or
  ``unmatched_review_required``.
- reviewer_decision is exactly ``""`` (blank/incomplete), ``REJECT``,
  or ``APPROVE:<candidate_key>`` with a non-blank key suffix. No trimming
  or case folding. Whitespace-only or any other text is invalid.
- Normalization:
  candidate_review_required + APPROVE:<key in list> -> matched/True/key
  candidate_review_required + REJECT -> raw disposition/False/None
  candidate_review_required + blank  -> raw disposition/False/None
  unmatched_review_required + APPROVE -> error APPROVAL_NOT_ALLOWED
  unmatched_review_required + REJECT -> raw disposition/False/None
  unmatched_review_required + blank  -> raw disposition/False/None
- Output rows carry only the 7 allowlisted fields and are sorted by ref;
  candidate lists are sorted. Source dates, amounts, date fields and notes
  are never returned.
- Any malformed header, row, JSON, CSV or decision fails the whole call
  with ValidationError. No partial plan. Error messages carry only a
  generic code-level message, never paths, row text, refs or keys.

Required ValidationError.code values (Sol contract):
  MISSING_COLUMN, INVALID_SCHEMA_VERSION, INVALID_SHA256,
  SNAPSHOT_SHA_MISMATCH, DUPLICATE_SOURCE_REF, INVALID_CANDIDATE_COUNT,
  INVALID_CANDIDATE_KEYS_JSON, CANDIDATE_COUNT_MISMATCH,
  INVALID_DISPOSITION, INVALID_REVIEW_DECISION, APPROVAL_NOT_ALLOWED,
  APPROVED_KEY_NOT_FOUND, APPROVED_KEY_DUPLICATED

Extra fail-closed codes used by this adapter:
  DUPLICATE_HEADER: header row repeats a column name exactly.
  UNEXPECTED_COLUMN: header has all required columns plus at least one
    column name outside the required set (covers extra, blank or
    whitespace-variant header cells when no required column is missing).
  ROW_LENGTH_MISMATCH: a data row has fewer or more fields than the header
    (ragged row or stray blank line).
  MALFORMED_CSV: CSV structure cannot be parsed, or the ``text`` input is
    not a string.
  INVALID_SOURCE_REF: source_ref_snapshot_only is empty or whitespace-only.
"""

from __future__ import annotations

import csv
import io
import json
import re

REVIEW_SCHEMA_VERSION = "review-csv-v1"

REQUIRED_HEADERS = (
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
REQUIRED_SET = frozenset(REQUIRED_HEADERS)

RAW_CANDIDATE = "candidate_review_required"
RAW_UNMATCHED = "unmatched_review_required"

_HEX64_BODY = r"[0-9a-fA-F]{64}"
_COUNT_BODY = r"[0-9]+"
_HEX64 = re.compile(_HEX64_BODY)
_COUNT_RE = re.compile(_COUNT_BODY)


class ValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str) -> None:
    messages = {
        "MISSING_COLUMN": "required column is missing",
        "INVALID_SCHEMA_VERSION": "schema version is invalid",
        "INVALID_SHA256": "snapshot hash format is invalid",
        "SNAPSHOT_SHA_MISMATCH": "snapshot binding does not match",
        "DUPLICATE_SOURCE_REF": "duplicate source ref",
        "INVALID_CANDIDATE_COUNT": "candidate count is invalid",
        "INVALID_CANDIDATE_KEYS_JSON": "candidate keys JSON is invalid",
        "CANDIDATE_COUNT_MISMATCH": "candidate count does not match keys",
        "INVALID_DISPOSITION": "disposition is invalid",
        "INVALID_REVIEW_DECISION": "review decision is invalid",
        "APPROVAL_NOT_ALLOWED": "approval is not allowed",
        "APPROVED_KEY_NOT_FOUND": "approved key was not found",
        "APPROVED_KEY_DUPLICATED": "candidate keys are duplicated",
        "DUPLICATE_HEADER": "header is duplicated",
        "UNEXPECTED_COLUMN": "header has unexpected column",
        "ROW_LENGTH_MISMATCH": "row length does not match header",
        "MALFORMED_CSV": "CSV text is malformed",
        "INVALID_SOURCE_REF": "source ref is invalid",
    }
    raise ValidationError(code, messages.get(code, "review CSV is invalid"))


def normalize_review_csv(text: str, snapshot_sha256: str) -> dict:
    if type(snapshot_sha256) is not str or re.fullmatch(_HEX64_BODY, snapshot_sha256) is None:
        _fail("INVALID_SHA256")
    if type(text) is not str:
        _fail("MALFORMED_CSV")
    if text.startswith("\ufeff"):
        text = text[1:]
    if text == "":
        _fail("MISSING_COLUMN")
    try:
        reader = csv.reader(io.StringIO(text), strict=True)
        rows = list(reader)
    except Exception:
        _fail("MALFORMED_CSV")
    if not rows:
        _fail("MISSING_COLUMN")
    header = rows[0]
    if len(header) == 0 or (len(header) == 1 and header[0] == ""):
        _fail("MISSING_COLUMN")
    if len(set(header)) != len(header):
        _fail("DUPLICATE_HEADER")
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        _fail("MISSING_COLUMN")
    extra = [h for h in header if h not in REQUIRED_SET]
    if extra:
        _fail("UNEXPECTED_COLUMN")
    if len(header) != len(REQUIRED_HEADERS):
        _fail("UNEXPECTED_COLUMN")
    data = rows[1:]
    if not data:
        return {"review_rows": [], "counts": {"approved": 0, "rejected": 0, "incomplete": 0}}
    # Fail on fully empty trailing stray rows as ragged; a single trailing
    # newline does not produce an extra row via csv.reader.
    records: list[dict] = []
    for row in data:
        if len(row) != len(header):
            _fail("ROW_LENGTH_MISMATCH")
        records.append(dict(zip(header, row)))
    # Blank ref check first (fail-closed, no echo).
    for rec in records:
        ref = rec.get("source_ref_snapshot_only")
        if type(ref) is not str or ref == "" or ref.strip() == "":
            _fail("INVALID_SOURCE_REF")
    # Duplicate ref check (exact match, no trimming).
    seen: set[str] = set()
    for rec in records:
        ref = rec["source_ref_snapshot_only"]
        if ref in seen:
            _fail("DUPLICATE_SOURCE_REF")
        seen.add(ref)

    review_rows: list[dict] = []
    approved = 0
    rejected = 0
    incomplete = 0
    for rec in records:
        ref = rec["source_ref_snapshot_only"]
        if rec.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
            _fail("INVALID_SCHEMA_VERSION")
        binding = rec.get("review_snapshot_sha256")
        if type(binding) is not str or re.fullmatch(_HEX64_BODY, binding) is None:
            _fail("INVALID_SHA256")
        if binding != snapshot_sha256:
            _fail("SNAPSHOT_SHA_MISMATCH")
        count_text = rec.get("candidate_count")
        if type(count_text) is not str or re.fullmatch(_COUNT_BODY, count_text) is None:
            _fail("INVALID_CANDIDATE_COUNT")
        try:
            count = int(count_text, 10)
        except Exception:
            _fail("INVALID_CANDIDATE_COUNT")
        keys_text = rec.get("candidate_transaction_keys")
        if type(keys_text) is not str:
            _fail("INVALID_CANDIDATE_KEYS_JSON")
        try:
            parsed = json.loads(keys_text)
        except Exception:
            _fail("INVALID_CANDIDATE_KEYS_JSON")
        if type(parsed) is not list:
            _fail("INVALID_CANDIDATE_KEYS_JSON")
        keys: list[str] = []
        for entry in parsed:
            if type(entry) is not str or entry == "" or entry.strip() == "":
                _fail("INVALID_CANDIDATE_KEYS_JSON")
            keys.append(entry)
        if len(set(keys)) != len(keys):
            _fail("APPROVED_KEY_DUPLICATED")
        if count != len(keys):
            _fail("CANDIDATE_COUNT_MISMATCH")
        disposition = rec.get("disposition")
        if disposition not in (RAW_CANDIDATE, RAW_UNMATCHED):
            _fail("INVALID_DISPOSITION")
        decision = rec.get("reviewer_decision")
        if type(decision) is not str:
            _fail("INVALID_REVIEW_DECISION")
        if decision == "":
            review_rows.append({
                "source_ref_snapshot_only": ref,
                "candidate_count": count,
                "candidate_transaction_keys": sorted(keys),
                "disposition": disposition,
                "approved": False,
                "chosen_candidate_key": None,
                "review_snapshot_sha256": binding,
            })
            incomplete += 1
        elif decision == "REJECT":
            review_rows.append({
                "source_ref_snapshot_only": ref,
                "candidate_count": count,
                "candidate_transaction_keys": sorted(keys),
                "disposition": disposition,
                "approved": False,
                "chosen_candidate_key": None,
                "review_snapshot_sha256": binding,
            })
            rejected += 1
        elif decision.startswith("APPROVE:"):
            chosen = decision[len("APPROVE:"):]
            if chosen == "" or chosen.strip() == "":
                _fail("INVALID_REVIEW_DECISION")
            if disposition == RAW_UNMATCHED:
                _fail("APPROVAL_NOT_ALLOWED")
            if chosen not in keys:
                _fail("APPROVED_KEY_NOT_FOUND")
            review_rows.append({
                "source_ref_snapshot_only": ref,
                "candidate_count": count,
                "candidate_transaction_keys": sorted(keys),
                "disposition": "matched",
                "approved": True,
                "chosen_candidate_key": chosen,
                "review_snapshot_sha256": binding,
            })
            approved += 1
        else:
            _fail("INVALID_REVIEW_DECISION")
    review_rows.sort(key=lambda r: r["source_ref_snapshot_only"])
    return {
        "review_rows": review_rows,
        "counts": {"approved": approved, "rejected": rejected, "incomplete": incomplete},
    }
