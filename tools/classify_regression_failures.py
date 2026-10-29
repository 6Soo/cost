"""Summarise pytest failures without exposing log contents or customer data.

The command is intentionally read-only.  It classifies nodeids and reports
the supplied process exit code; it never turns a known failure into a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(?P<nodeid>[^\s]+)")
_PASSED = re.compile(r"\b(?P<count>\d+)\s+passed(?:,|\s|$)")
_COLLECTED = re.compile(r"collected\s+(?P<count>\d+)\s+items", re.I)
_SAFE_NODEID = re.compile(r"^(?:tests/|webapp/tests/)[A-Za-z0-9_/]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*)+$")

CATEGORIES = {
    "ota_inferred_link": ("ota_inference", "inferred_link", "KeyError"),
    "signed_session": ("signed_session", "session_http", "session"),
    "google_asset": ("google", "asset", "ledger"),
    "card_flow": ("card_flow", "cardflow", "refund"),
}


def _safe_nodeid(value: str) -> str:
    # Parametrized IDs can contain private names, tokens or source text.
    value = value.strip().replace('\\', '/').split('[', 1)[0]
    if not value or len(value) > 240 or not _SAFE_NODEID.fullmatch(value):
        return "<redacted-nodeid>"
    return value


def _category(nodeid: str) -> str:
    lowered = nodeid.casefold()
    for category, needles in CATEGORIES.items():
        if any(needle.casefold() in lowered for needle in needles):
            return category
    return "other"


def classify_lines(lines: Iterable[str], *, exit_code: int | None = None) -> dict:
    failures: list[dict[str, str]] = []
    passed = collected = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        match = _FAILED.match(line)
        if match:
            nodeid = _safe_nodeid(match.group("nodeid"))
            failures.append({"nodeid": nodeid, "category": _category(nodeid),
                             '_key': hashlib.sha256(match.group('nodeid').encode()).hexdigest()})
            continue
        match = _PASSED.search(line.strip())
        if match:
            passed = int(match.group("count"))
        match = _COLLECTED.search(line)
        if match:
            collected = int(match.group("count"))
    # Preserve order while avoiding duplicate report entries.
    unique = []
    seen = set()
    for item in failures:
        key = item.pop('_key')
        if key not in seen:
            seen.add(key)
            unique.append(item)
    categories: dict[str, int] = {}
    for item in unique:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
    return {
        "schema_version": 1,
        "status": ("FAILED" if exit_code not in (None, 0) or unique else
                   "UNVERIFIED" if exit_code is None else
                   "PASSED" if passed is not None else
                   "COLLECTION_ONLY" if collected is not None else "UNVERIFIED"),
        "exit_code": exit_code,
        "failed": unique,
        "failure_count": len(unique),
        "categories": categories,
        "passed": passed,
        "collected": collected,
        "known_failures_are_not_passes": True,
        "raw_log_included": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="pytest text log; read only")
    parser.add_argument("--exit-code", type=int, default=None)
    parser.add_argument("--preview", action="store_true", help="explicit read-only preview")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.input is None:
        raise SystemExit("--input is required; no test command is executed")
    try:
        lines = args.input.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        result = {"schema_version": 1, "status": "BLOCKED", "reason": "input_unavailable",
                  "raw_log_included": False}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(classify_lines(lines, exit_code=args.exit_code), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
