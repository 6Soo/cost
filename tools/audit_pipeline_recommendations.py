"""Read-only count audit for the existing reconciliation recommendation bridge."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webapp.review_context import (
    _attach_pipeline_recommendations,
    _build_candidate,
    _parse_master,
)


REFRESHED_ROOT = Path(r"D:\WebLedgerHost\review\refreshed")


def _latest_inputs() -> tuple[Path, Path]:
    bundles = [path for path in REFRESHED_ROOT.iterdir() if path.is_dir()]
    if not bundles:
        raise FileNotFoundError("NO_REFRESHED_REVIEW_BUNDLE")
    bundle = max(bundles, key=lambda path: path.stat().st_mtime_ns)
    return bundle / "review.csv", bundle / "master.csv"


def main() -> int:
    review_path, master_path = _latest_inputs()
    review_text = review_path.read_text(encoding="utf-8-sig")
    master_text = master_path.read_text(encoding="utf-8-sig")
    master = _parse_master(master_text)

    rows = []
    total_candidates = 0
    recorded_candidates = 0
    rows_with_recorded_candidate = 0
    for source in csv.DictReader(io.StringIO(review_text)):
        keys = json.loads(source["candidate_transaction_keys"])
        candidates = [_build_candidate(key, master) for key in keys]
        total_candidates += len(candidates)
        recorded_here = sum(1 for c in candidates if c.get("pipeline_recorded") is True)
        recorded_candidates += recorded_here
        if recorded_here:
            rows_with_recorded_candidate += 1
        rows.append({
            "decision": source.get("reviewer_decision", ""),
            "candidates": candidates,
        })

    _attach_pipeline_recommendations(rows)
    recommendations = [row["pipeline_recommendation"] for row in rows
                       if row.get("pipeline_recommendation")]
    already_decided = sum(1 for row in rows if row.get("decision"))
    print(json.dumps({
        "review_rows": len(rows),
        "total_candidates": total_candidates,
        "recorded_candidates": recorded_candidates,
        "rows_with_recorded_candidate": rows_with_recorded_candidate,
        "unique_pipeline_recommendations": len(recommendations),
        "suppressed_or_ambiguous_rows": rows_with_recorded_candidate - len(recommendations),
        "already_decided_rows": already_decided,
        "auto_approved_rows": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
