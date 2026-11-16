"""Read-only issuer and format verification for preserved Hana/IBK exports.

The driver emits aggregate parser facts only. It never prints source rows,
amounts, card identifiers, file paths, or exception text.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


EXPECTED = {
    "hana": {"issuer": "하나", "channel": "domestic_acquired"},
    "ibk": {"issuer": "기업", "channel": "statement"},
}


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--file", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    prefix = Path(args.file).name.split("-", 1)[0].lower()
    expected = EXPECTED.get(prefix)
    if expected is None:
        print(json.dumps({"status": "failed", "error": "unknown_provider"}))
        return 1

    try:
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app.card_preflight import validate_upload
        content = Path(args.file).read_bytes()
        parsed, _ = validate_upload(content, Path(args.file).name)
    except Exception as exc:
        code = getattr(exc, "code", "")
        safe_code = code if isinstance(code, str) and code.replace("_", "").isalnum() else "format_invalid"
        print(json.dumps({"status": "failed", "error": safe_code}))
        return 1

    issues = len(parsed.issues) + sum(1 for row in parsed.rows if row.parse_error)
    issuer_matches = all(row.issuer == expected["issuer"] for row in parsed.rows)
    channel_matches = parsed.channel == expected["channel"]
    print(json.dumps({
        "status": "parsed",
        "rows": len(parsed.rows),
        "parse_issues": issues,
        "parser": str(parsed.parser),
        "channel": str(parsed.channel),
        "issuer_matches": issuer_matches,
        "channel_matches": channel_matches,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
