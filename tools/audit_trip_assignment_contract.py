"""Read-only, AST-based locator for trip-assignment contract evidence.

This tool locates source definitions and relevant synthetic pytest cases. It
does not import or execute application source, contact Google, or inspect data.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = {
    "CardFlow.trip_valid": ("webapp/card_flow.py", "CardFlow", "trip_valid", "class"),
    "CardFlow.retail_trip": ("webapp/card_flow.py", "CardFlow", "retail_trip", "class"),
    "CardFlow.tab_valid": ("webapp/card_flow.py", "CardFlow", "tab_valid", "class"),
    "CardFlow.booking_trip": ("webapp/card_flow.py", "CardFlow", "booking_trip", "class"),
    "Google authority": ("app/google_authority.py", None, "build_trip_view", "module"),
    "manual precedence": ("webapp/card_flow.py", "CardFlow", "sync_ledger_rows", "class"),
    "existing decision precedence": ("app/classify.py", None, "_classify_transaction", "module"),
    "trip period closure": ("app/reconciliation.py", None, "open_trip_end", "module"),
    "Google open-end closure": ("app/google_authority.py", None, "_close_open_ends", "module"),
    "card use date": ("app/reconciliation.py", None, "card_use_date", "module"),
    "OTA service-period precedence": ("webapp/card_flow.py", "CardFlow", "booking_trip", "class"),
    "stay-period selection": ("app/reconciliation.py", None, "stay_trip", "module"),
}

TEST_HINTS = {
    "trip_valid": ("webapp/tests/test_trip_valid_google.py", ("verified", "trip")),
    "retail_trip": ("webapp/tests/test_trip_valid_google.py", ("purchase", "trip")),
    "tab_valid": ("webapp/tests/test_trip_valid_google.py", ("tab",)),
    "booking_trip": ("webapp/tests/test_ota_booking_trip.py", ("owner_assignment",)),
    "manual precedence": ("webapp/tests/test_priority_trip_assignment.py", ("priority_rule",)),
    "period": ("tests/card_pipeline/test_reconciliation_rules.py", ("stay",)),
    "card use date": ("tests/card_pipeline/test_reconciliation_rules.py", ("card_row",)),
    "service period": ("webapp/tests/test_ota_booking_trip.py", ("checkout",)),
    "Google authority": ("tests/card_pipeline/test_google_authority.py", ("trip",)),
}


def _safe_relative(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in ("..", "") for part in candidate.parts):
        raise ValueError("UNTRUSTED_PATH")
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("UNTRUSTED_PATH")
    return resolved


def _read_source(relative: str) -> tuple[str | None, dict | None]:
    try:
        path = _safe_relative(relative)
    except (ValueError, OSError):
        return None, {"status": "OPEN_QUESTION", "reason": "UNTRUSTED_PATH"}
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, {"status": "OPEN_QUESTION", "reason": "MISSING_SOURCE"}
    except (OSError, UnicodeError) as exc:
        reason = "ENCODING_ERROR" if isinstance(exc, UnicodeError) else "SOURCE_READ_ERROR"
        return None, {"status": "OPEN_QUESTION", "reason": reason}
    try:
        ast.parse(source, filename=relative)
    except SyntaxError as exc:
        return None, {"status": "OPEN_QUESTION", "reason": "SYNTAX_ERROR", "line": exc.lineno}
    return source, None


def _definitions(tree: ast.AST, owner: str | None, symbol: str, scope: str) -> list[int]:
    if scope == "module":
        body = tree.body
    elif scope == "class" and owner:
        owners = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner]
        if len(owners) != 1:
            return []
        body = owners[0].body
    else:
        return []
    return sorted(node.lineno for node in body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol)


def _test_evidence(label: str) -> dict:
    path, tokens = TEST_HINTS[label]
    source, error = _read_source(path)
    if error:
        return {"status": "OPEN_QUESTION", "path": path, **error}
    tree = ast.parse(source)
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            normalized = node.name.lower()
            if all(token.lower() in normalized for token in tokens):
                matches.append({"name": node.name, "line": node.lineno})
    matches.sort(key=lambda item: item["line"])
    return {"status": "SOURCE_LOCATED" if matches else "OPEN_QUESTION",
            "path": path, "pytest": f"python -m pytest {path} -q", "tests": matches}


def audit() -> dict:
    entries = []
    for label, (path, owner, symbol, scope) in SYMBOLS.items():
        source, error = _read_source(path)
        if error:
            entries.append({"topic": label, "path": path, **error})
            continue
        try:
            lines = _definitions(ast.parse(source), owner, symbol, scope)
        except (SyntaxError, ValueError):
            lines = []
        entries.append({"topic": label, "status": "SOURCE_LOCATED" if len(lines) == 1 else "OPEN_QUESTION",
                        "path": path, "symbol": f"{owner + '.' if owner else ''}{symbol}",
                        "lines": lines, "scope": scope,
                        "note": "Definition location only; behavior and real-data cause are not established."})
    tests = {label: _test_evidence(label) for label in TEST_HINTS}
    return {"schema": "trip-assignment-contract-audit-v1", "mode": "source-only-ast",
            "entries": entries, "synthetic_pytest_evidence": tests}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args(argv)
    report = audit()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for entry in report["entries"]:
            print(json.dumps(entry, ensure_ascii=False))
        for topic, evidence in report["synthetic_pytest_evidence"].items():
            print(json.dumps({"topic": topic, **evidence}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
