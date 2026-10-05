"""Verify source discovery against the bound source; emit aggregate results."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from webapp.real_review import BoundInputs, load_manifest
from webapp.review_context import build_review_context, _parse_amount, _parse_source_ref
from webapp.contracts import sha256_bytes, sha256_text


def main():
    evidence = ROOT / "docs/handoff/2026-10-01"
    candidate = evidence / "source-reviewed-candidate/review_refresh.py"
    spec = importlib.util.spec_from_file_location("refresh_candidate_audit", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = BoundInputs(load_manifest(r"D:\WebLedgerHost\config\real-review.json"))
    result = {
        "read_only": True,
        "activated": False,
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }
    try:
        generated = module.build_review_csv(inputs.snapshot_bytes, inputs.master_text, inputs.review_text)
        old_rows = {row["source_ref_snapshot_only"]: row for row in csv.DictReader(io.StringIO(inputs.review_text.lstrip("\ufeff")))}
        new_rows = {row["source_ref_snapshot_only"]: row for row in csv.DictReader(io.StringIO(generated))}
        model = build_review_context(inputs.snapshot_bytes, generated, inputs.master_text,
                                     sha256_bytes(inputs.snapshot_bytes), sha256_text(generated), sha256_text(inputs.master_text))
        result.update(
            validation_passed=True,
            original_rows=len(old_rows),
            generated_rows=len(new_rows),
            omitted_refs=len(set(old_rows) - set(new_rows)),
            added_refs=len(set(new_rows) - set(old_rows)),
            generated_model_rows=len(model["rows"]),
            all_decisions_blank=all(row["reviewer_decision"] == "" for row in new_rows.values()),
        )
        added = set(new_rows) - set(old_rows)
        layouts = {}
        for ref in added:
            location = _parse_source_ref(ref)
            key = f"{location.date_col}:{location.amount_col}"
            layouts[key] = layouts.get(key, 0) + 1
        result["added_ref_layout_counts"] = layouts
        result["added_zero_amount_rows"] = sum(_parse_amount(new_rows[ref]["source_amount"]) == 0 for ref in added)
        result["added_negative_amount_rows"] = sum(_parse_amount(new_rows[ref]["source_amount"]) < 0 for ref in added)
        result["added_header_available_rows"] = sum(
            row["ref"] in added and row["source"]["evidence_status"] == "available"
            for row in model["rows"]
        )
    except Exception as error:
        result.update(validation_passed=False, failure_code=getattr(error, "code", "CANDIDATE_AUDIT_FAILED"))
    (evidence / "source-candidate-baseline-audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
