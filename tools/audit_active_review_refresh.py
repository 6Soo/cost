"""Read-only aggregate inspection of activated inputs and repeat collection."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from webapp.real_review import BoundInputs, load_manifest, refresh_status_path
from webapp.review_context import _parse_amount


def main():
    evidence = ROOT / "docs/handoff/2026-10-01"
    config = Path(r"D:\WebLedgerHost\config\real-review.json")
    manifest = load_manifest(str(config))
    inputs = BoundInputs(manifest)
    saved = json.loads((evidence / "source-refresh-backup.json").read_text(encoding="utf-8-sig"))
    before = load_manifest(str(Path(saved["backup_directory"]) / "real-review.json"))
    previous = Path(before["review_path"]).read_text(encoding="utf-8-sig")
    old = {row["source_ref_snapshot_only"]: row for row in csv.DictReader(io.StringIO(previous))}
    new = {row["source_ref_snapshot_only"]: row for row in csv.DictReader(io.StringIO(inputs.review_text.lstrip("\ufeff")))}
    added = set(new) - set(old)
    status_path = refresh_status_path(str(config))
    status = json.loads(Path(status_path).read_text(encoding="utf-8-sig")) if Path(status_path).exists() else {}
    result = {
        "read_only": True,
        "active_binding": inputs.binding,
        "active_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "original_rows": len(old),
        "active_rows": len(new),
        "omitted_refs": len(set(old) - set(new)),
        "added_refs": len(added),
        "added_zero_amount_rows": sum(_parse_amount(new[ref]["source_amount"]) == 0 for ref in added),
        "added_negative_amount_rows": sum(_parse_amount(new[ref]["source_amount"]) < 0 for ref in added),
        "all_decisions_blank": all(row["reviewer_decision"] == "" for row in new.values()),
        "collector_status": status,
        "actual_import_performed": False,
    }
    (evidence / "source-active-runtime-audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("ACTIVE_REVIEW_AUDIT_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
