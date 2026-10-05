"""REVIEW-PREPARE-001 blank review template builder (Muse writer scope).

Pure string transformation only. No filesystem or database I/O.

Input is a legacy 9-column CSV with exact header order:
  source_ref_snapshot_only, source_date, source_amount,
  candidate_count, candidate_transaction_keys, candidate_date_fields,
  disposition, reviewer_decision, review_note

Output is a review-csv-v1 11-column CSV in existing adapter REQUIRED_HEADERS
order, with review_schema_version=review-csv-v1, review_snapshot_sha256 bound
to the passed snapshot hash, reviewer_decision blank for every row, refs
sorted deterministically, candidate arrays canonical sorted JSON, LF record
terminators, QUOTE_ALL, no BOM. Context fields (source_date, source_amount,
candidate_date_fields, review_note) are preserved byte-for-byte with no
stripping or normalization; embedded CR, CRLF, LF, commas and quotes inside
quoted fields are field data, not record terminators. Counts come from
existing normalize_review_csv; no separate decision logic is implemented here.
"""

from __future__ import annotations

import csv
import io
import json
import re

from webapp.review_csv_adapter import (
    REQUIRED_HEADERS,
    normalize_review_csv,
)

REVIEW_SCHEMA_VERSION = "review-csv-v1"

LEGACY_HEADERS = (
    "source_ref_snapshot_only",
    "source_date",
    "source_amount",
    "candidate_count",
    "candidate_transaction_keys",
    "candidate_date_fields",
    "disposition",
    "reviewer_decision",
    "review_note",
)

_HEX64_BODY = r"[0-9a-fA-F]{64}"


class TemplateError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.message = code


def _fail(code: str) -> None:
    raise TemplateError(code)


def _is_hex64(value: object) -> bool:
    return type(value) is str and re.fullmatch(_HEX64_BODY, value) is not None


def _map_adapter_error(code: str) -> str:
    if code in ("INVALID_SHA256", "SNAPSHOT_SHA_MISMATCH"):
        return "INVALID_SNAPSHOT_SHA256"
    if code == "DUPLICATE_SOURCE_REF":
        return "DUPLICATE_REVIEW_REF"
    if code in (
        "INVALID_CANDIDATE_COUNT",
        "INVALID_CANDIDATE_KEYS_JSON",
        "CANDIDATE_COUNT_MISMATCH",
        "APPROVED_KEY_DUPLICATED",
    ):
        return "INVALID_CANDIDATE_KEYS"
    if code == "INVALID_DISPOSITION":
        return "INVALID_DISPOSITION"
    return "LEGACY_CSV_INVALID"


def _canonical_keys_json(sorted_keys: list[str]) -> str:
    return json.dumps(sorted_keys, ensure_ascii=False, separators=(",", ":"))


def build_blank_review_template(legacy_csv_text: str, snapshot_sha256: str) -> dict:
    if not _is_hex64(snapshot_sha256):
        _fail("INVALID_SNAPSHOT_SHA256")
    if type(legacy_csv_text) is not str:
        _fail("LEGACY_CSV_INVALID")

    text = legacy_csv_text
    if text.startswith("\ufeff"):
        text = text[1:]
    if text == "":
        _fail("LEGACY_SCHEMA_MISMATCH")

    try:
        reader = csv.reader(io.StringIO(text), strict=True)
        rows = list(reader)
    except Exception:
        _fail("LEGACY_CSV_INVALID")

    if not rows:
        _fail("LEGACY_SCHEMA_MISMATCH")
    header = rows[0]
    if list(header) != list(LEGACY_HEADERS):
        _fail("LEGACY_SCHEMA_MISMATCH")

    data = rows[1:]
    records: list[dict] = []
    for row in data:
        if len(row) != len(LEGACY_HEADERS):
            _fail("LEGACY_CSV_INVALID")
        rec = dict(zip(LEGACY_HEADERS, row))
        if rec.get("reviewer_decision") != "":
            _fail("LEGACY_APPROVAL_PRESENT")
        records.append(rec)

    # Deterministic ref sort before publishing.
    records.sort(key=lambda r: r["source_ref_snapshot_only"])

    # Provisional v1 CSV preserves context verbatim; candidate/count/
    # disposition pass through for adapter validation.
    prov_buf = io.StringIO()
    prov_w = csv.DictWriter(
        prov_buf,
        fieldnames=list(REQUIRED_HEADERS),
        lineterminator="\n",
        quoting=csv.QUOTE_ALL,
    )
    prov_w.writeheader()
    for rec in records:
        prov_w.writerow(
            {
                "source_ref_snapshot_only": rec["source_ref_snapshot_only"],
                "source_date": rec["source_date"],
                "source_amount": rec["source_amount"],
                "candidate_count": rec["candidate_count"],
                "candidate_transaction_keys": rec["candidate_transaction_keys"],
                "candidate_date_fields": rec["candidate_date_fields"],
                "disposition": rec["disposition"],
                "reviewer_decision": "",
                "review_note": rec["review_note"],
                "review_schema_version": REVIEW_SCHEMA_VERSION,
                "review_snapshot_sha256": snapshot_sha256,
            }
        )
    provisional_text = prov_buf.getvalue()

    try:
        provisional = normalize_review_csv(provisional_text, snapshot_sha256)
    except Exception as exc:
        code = getattr(exc, "code", "")
        if type(code) is str and code:
            _fail(_map_adapter_error(code))
        _fail("LEGACY_CSV_INVALID")

    counts = provisional["counts"]
    if counts.get("approved") != 0 or counts.get("rejected") != 0:
        _fail("LEGACY_CSV_INVALID")

    # Canonicalize candidate fields from normalized rows without touching
    # preserved context (ref/date/amount/date_fields/note/disposition source).
    by_ref: dict[str, dict] = {}
    for rec in records:
        # Duplicate refs are reported via adapter mapping; keep first here.
        if rec["source_ref_snapshot_only"] not in by_ref:
            by_ref[rec["source_ref_snapshot_only"]] = rec

    final_buf = io.StringIO()
    final_w = csv.DictWriter(
        final_buf,
        fieldnames=list(REQUIRED_HEADERS),
        lineterminator="\n",
        quoting=csv.QUOTE_ALL,
    )
    final_w.writeheader()
    for nrow in provisional["review_rows"]:
        ref = nrow["source_ref_snapshot_only"]
        orig = by_ref.get(ref)
        if orig is None:
            _fail("LEGACY_CSV_INVALID")
        sorted_keys = list(nrow["candidate_transaction_keys"])
        final_w.writerow(
            {
                "source_ref_snapshot_only": ref,
                "source_date": orig["source_date"],
                "source_amount": orig["source_amount"],
                "candidate_count": str(nrow["candidate_count"]),
                "candidate_transaction_keys": _canonical_keys_json(sorted_keys),
                "candidate_date_fields": orig["candidate_date_fields"],
                "disposition": nrow["disposition"],
                "reviewer_decision": "",
                "review_note": orig["review_note"],
                "review_schema_version": REVIEW_SCHEMA_VERSION,
                "review_snapshot_sha256": snapshot_sha256,
            }
        )
    final_text = final_buf.getvalue()

    # Final validation supplies the returned counts and guarantees the
    # published text itself passes the existing adapter.
    try:
        final = normalize_review_csv(final_text, snapshot_sha256)
    except Exception as exc:
        code = getattr(exc, "code", "")
        if type(code) is str and code:
            _fail(_map_adapter_error(code))
        _fail("LEGACY_CSV_INVALID")

    final_counts = final["counts"]
    if final_counts.get("approved") != 0 or final_counts.get("rejected") != 0:
        _fail("LEGACY_CSV_INVALID")
    row_count = len(final["review_rows"])
    if final_counts.get("incomplete") != row_count:
        _fail("LEGACY_CSV_INVALID")
    if row_count != len(records):
        _fail("LEGACY_CSV_INVALID")

    # Output guarantees: no BOM, LF record terminators. Embedded CR/CRLF/LF
    # inside quoted field data is preserved and is not a terminator, so no
    # global "\r" refusal is applied here.
    if final_text.startswith("\ufeff"):
        _fail("LEGACY_CSV_INVALID")

    return {
        "csv_text": final_text,
        "counts": {
            "approved": final_counts["approved"],
            "rejected": final_counts["rejected"],
            "incomplete": final_counts["incomplete"],
        },
        "row_count": row_count,
    }
