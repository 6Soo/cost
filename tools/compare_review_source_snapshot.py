"""Compare snapshot cell contents locally; emit aggregate counts only."""
import datetime
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import openpyxl
from webapp.real_review import BoundInputs, load_manifest


def cell_value(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return type(value).__name__, value.isoformat()
    return type(value).__name__, repr(value)


def cells(workbook):
    result = {}
    for sheet in workbook:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    result[(sheet.title, cell.coordinate)] = cell_value(cell.value)
    return result


def main():
    evidence = Path(__file__).resolve().parents[1] / "docs/handoff/2026-10-01"
    probe = json.loads((evidence / "source-export-probe.json").read_text(encoding="utf-8"))
    inputs = BoundInputs(load_manifest(r"D:\WebLedgerHost\config\real-review.json"))
    new_bytes = (Path(r"D:\WebLedgerHost\review\source-refresh-probe") / (probe["snapshot_sha256"] + ".xlsx")).read_bytes()
    old = openpyxl.load_workbook(io.BytesIO(inputs.snapshot_bytes), data_only=True)
    new = openpyxl.load_workbook(io.BytesIO(new_bytes), data_only=True)
    old_cells, new_cells = cells(old), cells(new)
    old_keys, new_keys = set(old_cells), set(new_cells)
    changes = sum(old_cells[key] != new_cells[key] for key in old_keys & new_keys)
    result = {
        "read_only": True,
        "snapshot_bytes_equal": inputs.snapshot_bytes == new_bytes,
        "cell_contents_equal": old_cells == new_cells,
        "changed_cells": changes,
        "added_nonempty_cells": len(new_keys - old_keys),
        "removed_nonempty_cells": len(old_keys - new_keys),
        "old_sheet_count": len(old.sheetnames),
        "new_sheet_count": len(new.sheetnames),
        "sheet_names_equal": set(old.sheetnames) == set(new.sheetnames),
        "activated": False,
    }
    (evidence / "source-snapshot-comparison.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("SOURCE_COMPARISON_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
