"""Build a reviewed import plan from a review CSV file.

This CLI is the thin shell for the review CSV adapter
(``webapp.review_csv_adapter``) and the unchanged pure planner
(``webapp.migration.build_reviewed_import_plan``). It owns no review
semantics of its own: every decision rule, every refusal and every
``ValidationError.code`` belongs to the adapter, and every plan id,
ordering and ``plan_digest`` belongs to the pure planner.

Contract shape
--------------
Success is exit 0 with exactly one deterministic JSON object on stdout::

    {"counts": {...}, "plan_digest": "...", "reviewed_plan": {...},
     "snapshot_sha256": "..."}

``counts`` is the adapter's ``approved`` / ``rejected`` / ``incomplete``
tally, which is deliberately not the pure planner's eligible/refused
split: the adapter keeps human ``REJECT`` and blank (incomplete) rows
apart, while the pure planner may park both on the refused side.

Failure is exit 2 with exactly one JSON object on stdout::

    {"error": {"code": "SNAPSHOT_SHA_MISMATCH"}}

Privacy
-------
The plan identity itself is output on purpose: source refs, candidate
transaction keys and plan ids are snapshot-scoped plan material and are
part of the contract payload. Everything outside that identity stays
inside. Free-form reviewer prose (``review_note`` and the pure planner's
``reason``), the input path, raw CSV or row text, source dates, amounts
and candidate date fields, and exception messages or exception reprs are
never written to stdout or stderr, for expected and unexpected errors
alike. Diagnostics are limited to a short code on stderr, and an
unexpected internal failure is reported as the stable ``INTERNAL_ERROR``
code with no traceback.

Side effects
------------
The only file access is a single read of the exact ``--csv`` path given
on the command line, decoded as UTF-8 with an optional BOM. No implicit
path is resolved, nothing is written, no database, network or manifest
is touched. ``--snapshot-sha256`` is only cross-checked against the CSV
by the adapter for internal consistency; no snapshot file is opened and
no digest is recomputed from one.

Usage::

    python tools/build_reviewed_import_plan_from_csv.py \\
        --csv PATH --snapshot-sha256 SHA256HEX
    python -m tools.build_reviewed_import_plan_from_csv \\
        --csv PATH --snapshot-sha256 SHA256HEX
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Independent of the current working directory: the file is invoked either
# as a direct script (where sys.path[0] is the tools/ directory) or as
# ``python -m tools.build_reviewed_import_plan_from_csv`` from the project
# root, so the project root is put on sys.path before the package imports
# below are resolved.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

EXIT_OK = 0
EXIT_ERROR = 2

# CLI-owned codes. These are deliberately outside the adapter's
# ValidationError vocabulary: they cover the shell concerns (arguments and
# file access) that never reach the adapter at all.
CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_INVALID_SNAPSHOT_SHA256 = "INVALID_SNAPSHOT_SHA256"
CODE_CSV_FILE_NOT_FOUND = "CSV_FILE_NOT_FOUND"
CODE_CSV_FILE_UNREADABLE = "CSV_FILE_UNREADABLE"
CODE_CSV_ENCODING_INVALID = "CSV_ENCODING_INVALID"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"

# Adapter codes are passed through only when they are on this allowlist, so
# an unexpected string in ``ValidationError.code`` can never widen what the
# CLI is willing to print.
_ADAPTER_CODES = frozenset({
    "MISSING_COLUMN",
    "INVALID_SCHEMA_VERSION",
    "INVALID_SHA256",
    "SNAPSHOT_SHA_MISMATCH",
    "DUPLICATE_SOURCE_REF",
    "INVALID_CANDIDATE_COUNT",
    "INVALID_CANDIDATE_KEYS_JSON",
    "CANDIDATE_COUNT_MISMATCH",
    "INVALID_DISPOSITION",
    "INVALID_REVIEW_DECISION",
    "APPROVAL_NOT_ALLOWED",
    "APPROVED_KEY_NOT_FOUND",
    "APPROVED_KEY_DUPLICATED",
    "DUPLICATE_HEADER",
    "UNEXPECTED_COLUMN",
    "ROW_LENGTH_MISMATCH",
    "MALFORMED_CSV",
    "INVALID_SOURCE_REF",
})

_COUNT_FIELDS = ("approved", "rejected", "incomplete")

# Per-record output allowlist, mirroring the material the pure planner's own
# digest allowlists. Snapshot-scoped plan identity (source ref, candidate
# keys, plan id) is kept; reviewer prose (``review_note``, ``reason``) and
# anything a row carries beyond the contract fields -- source dates, amounts,
# candidate date fields -- are dropped, so no free text reaches stdout.
_ELIGIBLE_FIELDS = (
    "source_ref_snapshot_only",
    "review_snapshot_sha256",
    "chosen_candidate_key",
    "candidate_transaction_keys",
    "plan_id",
)
_REFUSED_FIELDS = (
    "source_ref_snapshot_only",
    "disposition",
    "reason_code",
    "review_snapshot_sha256",
    "approved",
    "chosen_candidate_key",
    "candidate_fingerprint",
    "candidate_count",
)
_PLAN_COUNT_FIELDS = ("eligible", "refused", "total")

_SHA256_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")

_PROG = "build_reviewed_import_plan_from_csv"


class _CliError(Exception):
    """A refusal already reduced to a stable, printable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ParserError(Exception):
    """Raised instead of argparse's usage-and-exit behaviour."""


class _Parser(argparse.ArgumentParser):
    """argparse parser that never echoes arguments back to the caller.

    The stock parser prints a usage line that embeds the offending option
    and its value, which would put a filesystem path on stdout. Argument
    problems are surfaced as a code instead.
    """

    def error(self, message):  # noqa: D102 - argparse hook
        raise _ParserError()


def _read_csv_text(path: str) -> str:
    """Read the one explicit file, or refuse with a stable IO code."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        raise _CliError(CODE_CSV_FILE_NOT_FOUND) from None
    except (IsADirectoryError, OSError):
        # IsADirectoryError and PermissionError are OSError subclasses, so
        # one arm covers directories, denied access and every other
        # unreadable-path case. The path itself is never reported.
        raise _CliError(CODE_CSV_FILE_UNREADABLE) from None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _CliError(CODE_CSV_ENCODING_INVALID) from None


def _load_adapter():
    """Import the adapter lazily, so argument errors never depend on it."""
    import importlib

    return importlib.import_module("webapp.review_csv_adapter")


def _build_plan(snapshot_sha256: str, review_rows):
    from webapp.migration import build_reviewed_import_plan

    return build_reviewed_import_plan(snapshot_sha256, review_rows)


def _allowlisted(entry, fields) -> dict:
    return {name: entry.get(name) for name in fields}


def _reviewed_plan_view(plan) -> dict:
    eligible = [_allowlisted(item, _ELIGIBLE_FIELDS)
                for item in plan.get("eligible") or []]
    refused = [_allowlisted(item, _REFUSED_FIELDS)
               for item in plan.get("refused") or []]
    counts = _allowlisted(plan.get("counts") or {}, _PLAN_COUNT_FIELDS)
    return {"eligible": eligible, "refused": refused, "counts": counts}


def _emit(payload: dict) -> None:
    sys.stdout.write(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(code: str) -> int:
    _emit({"error": {"code": code}})
    sys.stderr.write(code + "\n")
    return EXIT_ERROR


def _build_parser() -> _Parser:
    parser = _Parser(
        prog=_PROG,
        description=("Normalize a review CSV for one snapshot and print a "
                     "deterministic reviewed import plan as JSON."),
        add_help=True,
    )
    parser.add_argument(
        "--csv", dest="csv_path", required=True, metavar="PATH",
        help="review CSV file to read (UTF-8, optional BOM)")
    parser.add_argument(
        "--snapshot-sha256", dest="snapshot_sha256", required=True,
        metavar="SHA256HEX",
        help="64-hex snapshot hash the review CSV must be bound to")
    return parser


def _normalize(adapter, text: str, snapshot_sha256: str) -> dict:
    try:
        result = adapter.normalize_review_csv(text, snapshot_sha256)
    except adapter.ValidationError as exc:
        code = getattr(exc, "code", None)
        if type(code) is not str or code not in _ADAPTER_CODES:
            raise _CliError(CODE_INTERNAL_ERROR) from None
        raise _CliError(code) from None
    if not isinstance(result, dict):
        raise _CliError(CODE_INTERNAL_ERROR)
    return result


def _run(argv) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except _ParserError:
        raise _CliError(CODE_INVALID_ARGUMENT) from None

    snapshot_sha256 = args.snapshot_sha256
    if type(snapshot_sha256) is not str or _SHA256_RE.match(snapshot_sha256) is None:
        raise _CliError(CODE_INVALID_SNAPSHOT_SHA256)

    text = _read_csv_text(args.csv_path)

    adapter = _load_adapter()
    result = _normalize(adapter, text, snapshot_sha256)

    review_rows = result.get("review_rows")
    adapter_counts = result.get("counts")
    if not isinstance(review_rows, (list, tuple)):
        raise _CliError(CODE_INTERNAL_ERROR)
    if not isinstance(adapter_counts, dict):
        raise _CliError(CODE_INTERNAL_ERROR)

    plan = _build_plan(snapshot_sha256, list(review_rows))
    if not isinstance(plan, dict):
        raise _CliError(CODE_INTERNAL_ERROR)

    payload = {
        "snapshot_sha256": plan.get("snapshot_sha256"),
        "counts": {name: adapter_counts.get(name, 0) for name in _COUNT_FIELDS},
        "reviewed_plan": _reviewed_plan_view(plan),
        "plan_digest": plan.get("plan_digest"),
    }
    _emit(payload)
    return EXIT_OK


def main(argv=None) -> int:
    """Entry point. Returns 0 on success and 2 on any refusal."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        return _run(argv)
    except _CliError as exc:
        return _fail(exc.code)
    except Exception:
        # No traceback, no exception repr, no message: an unexpected internal
        # failure is still just a stable code.
        return _fail(CODE_INTERNAL_ERROR)


if __name__ == "__main__":
    sys.exit(main())
