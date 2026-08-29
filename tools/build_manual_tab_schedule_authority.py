"""Build the trip schedule authority from manual-ledger trip tabs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.manual_tab_schedule_authority import write_manual_tab_documents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, default=Path("ledger/data/ledger_current.xlsx"))
    parser.add_argument(
        "--authority",
        type=Path,
        default=Path("ledger/data/trip_schedule_authority_v3.json"),
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("outputs/manual-tab-schedule-candidates-20260825.json"),
    )
    args = parser.parse_args()
    result = write_manual_tab_documents(args.workbook, args.authority, args.candidates)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
