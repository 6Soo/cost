#!/usr/bin/env python3
"""Read-only parser verification driver for the KB card collection boundary.

Calls the repository's existing card parser (app/import_card.py) on one already
preserved file and prints counts only. Full row text, amounts, IDs, and
filenames never leave the parser boundary through this driver. This driver does
not write, classify, or link anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--file", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app.import_card import ParseError, parse_card_file
    except Exception as exc:  # dependency/import boundary is reported, never guessed
        print(json.dumps({"status": "unavailable", "error": type(exc).__name__}, ensure_ascii=False))
        return 3
    try:
        content = Path(args.file).read_bytes()
        parsed = parse_card_file(content, Path(args.file).name, use_cache=False)
    except ParseError as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "parsed",
        "rows": len(parsed.rows),
        "parse_issues": len(parsed.issues),
        "parser": str(parsed.parser),
        "channel": str(parsed.channel),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
