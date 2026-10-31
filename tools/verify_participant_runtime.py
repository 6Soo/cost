"""Read-only preflight for participant CLI/web database identity."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.participant_runtime import verify_paths  # noqa: E402

# Fail-closed: receipt file must be small (100 KiB) to prevent memory exhaustion
MAX_RECEIPT_BYTES = 100 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="CLI participant DB")
    parser.add_argument("--web-db", type=Path, help="optional explicit web DB; defaults to resolver")
    parser.add_argument('--receipt', type=Path, help='optional private registration receipt to compare read-only')
    args = parser.parse_args()
    try:
        if args.receipt:
            with args.receipt.open('rb') as f:
                data = f.read(MAX_RECEIPT_BYTES + 1)
            if len(data) > MAX_RECEIPT_BYTES:
                raise ValueError('PARTICIPANT_RECEIPT_TOO_LARGE')
            receipt = json.loads(data.decode('utf-8'))
            if not isinstance(receipt, dict):
                raise ValueError('PARTICIPANT_RECEIPT_INVALID')
        else:
            receipt = None
    except (OSError, ValueError, UnicodeError) as e:
        code = str(e) if isinstance(e, ValueError) and str(e).startswith('PARTICIPANT_') else 'PARTICIPANT_RECEIPT_INVALID'
        print(json.dumps({'status': 'blocked', 'code': code}))
        return 2
    result = verify_paths(args.db, args.web_db, receipt=receipt)
    print(json.dumps(result, ensure_ascii=False))
    # Exit 0 means the configured read-only preflight passed. Registration
    # acceptance is stronger and is represented separately by status=accepted.
    return 0 if result["status"] in ("ready_for_receipt_check", "accepted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
