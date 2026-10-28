"""Synthetic PA-01 baseline comparison and PA-06 ranking cost probe."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.provisional_assignment import rank_trip_candidates


def run(count):
    trips = [{"trip_id": f"trip-{i:05d}", "starts_on": "2026-01-01",
              "ends_on": "2026-12-31"} for i in range(10)]
    candidates = [{"trip_id": trips[i % len(trips)]["trip_id"], "score": i % 4,
                   "basis": f"synthetic-evidence-{i}"} for i in range(count)]
    started = time.perf_counter()
    decision = rank_trip_candidates(candidates, trips=trips)
    elapsed = time.perf_counter() - started
    baseline = {"rows": count, "assigned": sum(1 for row in candidates
                if row["trip_id"] == candidates[0]["trip_id"])}
    return {"rows": count, "seconds": round(elapsed, 6), "baseline_naive_assigned": baseline["assigned"],
            "ranker_status": decision["status"], "ranker_candidate_count": len(decision["candidates"]),
            "synthetic_only": True}


if __name__ == "__main__":
    print(json.dumps([run(n) for n in (10_000, 100_000)], indent=2))
