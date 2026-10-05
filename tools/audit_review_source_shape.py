"""Read-only source layout audit. Emit counts and column numbers only."""
from __future__ import annotations

import collections
import csv
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webapp.real_review import BoundInputs, load_manifest
from webapp.review_context import _parse_source_ref, _resolve_header
import openpyxl


def main() -> int:
    manifest = load_manifest(r"D:\WebLedgerHost\config\real-review.json")
    inputs = BoundInputs(manifest)
    workbook = openpyxl.load_workbook(io.BytesIO(inputs.snapshot_bytes), data_only=True)
    layouts = collections.Counter()
    sufficient = insufficient = 0
    for row in csv.DictReader(io.StringIO(inputs.review_text.lstrip("\ufeff"))):
        ref = _parse_source_ref(row["source_ref_snapshot_only"])
        labels, _block_kind = _resolve_header(workbook[ref.sheet], ref)
        layouts[(ref.date_col, ref.amount_col)] += 1
        if labels is None:
            insufficient += 1
        else:
            sufficient += 1
    workbook.close()
    result = {
        "read_only": True,
        "sheet_count": len(workbook.sheetnames),
        "review_rows": sufficient + insufficient,
        "header_available": sufficient,
        "header_insufficient": insufficient,
        "expense_column_layouts": [
            {"date_column": start, "amount_column": end, "rows": count}
            for (start, end), count in sorted(layouts.items())
        ],
    }
    target = Path(__file__).resolve().parents[1] / "docs/handoff/2026-10-01/source-layout-audit.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("SOURCE_LAYOUT_AUDIT_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
