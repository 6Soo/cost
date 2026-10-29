"""Read-only preflight for participant CLI/web database identity."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.participant_runtime import verify_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="CLI participant DB")
    parser.add_argument("--web-db", type=Path, help="optional explicit web DB; defaults to resolver")
    parser.add_argument('--receipt', type=Path, help='optional private registration receipt to compare read-only')
    args = parser.parse_args()
    try:
        receipt = json.loads(args.receipt.read_text(encoding='utf-8')) if args.receipt else None
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({'status':'blocked','code':'PARTICIPANT_RECEIPT_INVALID'}))
        return 2
    result = verify_paths(args.db, args.web_db, receipt=receipt)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" and result["schema_present"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
