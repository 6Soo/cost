"""읽기 전용: COST 여행과 reservation 여행의 브리지 현황과 대장 항공권 HOLD 통계를 출력한다. 개인정보 없음."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bridge_diagnostics, reservation_authority  # noqa: E402
from ledger.domain.direct_trip_schedule_authority import load_document  # noqa: E402
from webapp import guide_airfare_review  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", default="D:/WebLedgerHost/data/board.sqlite")
    parser.add_argument("--authority-doc", default="D:/WebLedgerHost/config/trip-authority.json")
    parser.add_argument("--token-file", default="D:/WebLedgerHost/secrets/reservation-internal-token.txt")
    parser.add_argument("--snapshot", default="D:/WebLedgerHost/data/ota-review/ota-snapshot.json")
    args = parser.parse_args(argv)

    token = reservation_authority.configured_token(args.token_file)
    authority = reservation_authority.fetch_authority(token=token)
    conn = sqlite3.connect(Path(args.board).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    trips = [dict(row) for row in conn.execute(
        "SELECT tab_id, display_key, starts_on, ends_on FROM trip_tabs WHERE deleted=0 AND archived=0")]
    records, _ = load_document(Path(args.authority_doc))
    by_code = {record.trip_code: record for record in records}
    for trip in trips:
        record = by_code.get(trip["display_key"])
        trip["valid"] = bool(record and record.is_authoritative and record.starts_on.isoformat() == trip["starts_on"]
                             and record.ends_on.isoformat() == trip["ends_on"])
    registrations = {}
    for trip_id, source_key in conn.execute("SELECT trip_id, source_key FROM reserve_trip_registrations"):
        parts = str(source_key).split(":")
        if len(parts) == 3:
            registrations[trip_id] = parts[1]
    coverage = guide_airfare_review.bridge_coverage(authority, trips, registrations)
    unbridgeable = [trip for trip in trips if trip["tab_id"] in set(coverage["unbridgeable"])]
    regions = {code: record.region for code, record in by_code.items()}
    report = {
        "reservation": {"guides": len(authority["guides"]), "tours": len(authority["tours"]),
                        "tours_with_code": sum(bool(tour["code"]) for tour in authority["tours"]),
                        "source_status": _count(tour.get("source_status") for tour in authority["tours"])},
        "cost_trips": sum(trip["valid"] for trip in trips),
        "coverage": {name: len(ids) for name, ids in coverage.items()},
        "unbridgeable": bridge_diagnostics.classify_unbridgeable(authority["tours"], unbridgeable, regions),
    }
    try:
        results = json.loads(Path(args.snapshot).read_text(encoding="utf-8")).get("results", [])
        report["guide_airfare_holds"] = bridge_diagnostics.hold_statistics(results)
    except (OSError, ValueError):
        report["guide_airfare_holds"] = None
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _count(values):
    counts = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


if __name__ == "__main__":
    main()
