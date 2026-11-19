"""Read-only candidate finder for a reservation that never reached a trip.

소유자 결정 2026-11-19 ③. One board row carries a Trip.com reservation number
and a stay period but has no 여행 (`trip_id` empty, shown under
`quarter:2026:2`). The owner will move it to a trip; this tool does not move
anything. It only reads a **copy** of the board and lists the trips whose own
stored dates can hold that stay, each with the days it shares and the reason.

Guarantees:

* it never writes to the board (the connection is opened read-only, and the
  only statements issued are ``SELECT``);
* it never touches the production host — the database path is an argument and
  defaults to nothing, so a run without ``--db`` reads no data at all;
* it prints reservation numbers as they are stored. Treat that output as
  private and do not paste it into Git, a PR or a free model.

Run::

    python tools/audit_unassigned_reservation_trip.py --db <copy.sqlite> --row <row_id>
    python tools/audit_unassigned_reservation_trip.py --db <copy.sqlite> \\
        --reservation 1400827517097737 --period 2026-06-20~2026-06-25

The candidate order is the rule the board already uses for a booking with a
period (``policy/trip.md``): a trip that fully covers the period first, then the
trip sharing the most days, then the larger 잔액. The tool states which rule
produced each candidate; a human still decides ③.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date


def _trip_days(starts: str, ends: str) -> tuple[date, date] | None:
    try:
        start = date.fromisoformat(starts[:10])
        end = date.fromisoformat(ends[:10])
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return start, end


def _stay_days(period: str) -> tuple[date, date] | None:
    parts = [part.strip() for part in str(period or "").split("~")]
    if len(parts) != 2:
        return None
    try:
        start = date.fromisoformat(parts[0][:10])
        end = date.fromisoformat(parts[1][:10])
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def _shared_days(trip: tuple[date, date], stay: tuple[date, date]) -> int:
    first = max(trip[0], stay[0])
    last = min(trip[1], stay[1])
    return max(0, (last - first).days + 1)


def _open_readonly(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _find_row(conn: sqlite3.Connection, row_id: str = "", reservation: str = "") -> dict | None:
    rows = conn.execute("SELECT row_id, display_tab_id, payload_json FROM board_rows").fetchall()
    for found_id, tab_id, payload in rows:
        record = json.loads(payload)
        if row_id and found_id != row_id:
            continue
        if reservation and str(record.get("reservation_no") or "") != reservation:
            continue
        return {"row_id": found_id, "display_tab_id": tab_id, **record}
    return None


def _trips(conn: sqlite3.Connection) -> list[dict]:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(trip_tabs)").fetchall()]
    wanted = [name for name in ("tab_id", "starts_on", "ends_on", "display_key", "destination", "deleted")
              if name in columns]
    if not wanted:
        return []
    found = conn.execute(f"SELECT {','.join(wanted)} FROM trip_tabs").fetchall()
    trips = []
    for values in found:
        item = dict(zip(wanted, values))
        if item.get("deleted"):
            continue
        trips.append(item)
    return trips


def candidates(row: dict, trips: list[dict]) -> list[dict]:
    """Every trip whose stored dates touch the row's stay, with its evidence."""
    stay = _stay_days(str(row.get("service_period") or ""))
    if stay is None:
        return []
    found = []
    for trip in trips:
        trip_dates = _trip_days(str(trip.get("starts_on") or ""), str(trip.get("ends_on") or ""))
        if trip_dates is None:
            continue
        shared = _shared_days(trip_dates, stay)
        if not shared:
            continue
        covers = trip_dates[0] <= stay[0] and stay[1] <= trip_dates[1]
        found.append({
            "tab_id": str(trip.get("tab_id") or ""),
            "title": str(trip.get("display_key") or trip.get("destination") or ""),
            "starts_on": str(trip.get("starts_on") or ""),
            "ends_on": str(trip.get("ends_on") or ""),
            "covers_period": covers,
            "shared_days": shared,
            "rule": "이용기간 전체를 덮는 여행" if covers else "겹치는 날이 있는 여행",
        })
    found.sort(key=lambda item: (not item["covers_period"], -item["shared_days"], item["tab_id"]))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="보드 사본 경로(운영 DB 직접 지정 금지)")
    parser.add_argument("--row", default="", help="행 ID (card-로 시작)")
    parser.add_argument("--reservation", default="", help="예약번호")
    parser.add_argument("--period", default="", help="행 자료에 기간이 없을 때 쓰는 이용기간(YYYY-MM-DD~YYYY-MM-DD)")
    args = parser.parse_args(argv)

    if not (args.row or args.reservation):
        parser.error("--row 또는 --reservation 중 하나가 필요합니다")

    conn = _open_readonly(args.db)
    try:
        row = _find_row(conn, row_id=args.row, reservation=args.reservation)
        if row is None:
            print("지정한 조건의 행을 찾지 못했습니다.", file=sys.stderr)
            return 2
        if not str(row.get("service_period") or "").strip() and args.period:
            row["service_period"] = args.period
        print(f"행: {row['row_id']}  기간 칸(현재): {row.get('display_tab_id') or ''}")
        print(f"  가맹점: {row.get('source_merchant') or ''}")
        print(f"  설명: {row.get('description') or ''}")
        print(f"  예약번호: {row.get('reservation_no') or ''}")
        print(f"  이용기간: {row.get('service_period') or ''}")
        print(f"  금액: {row.get('amount_krw')}  분류 근거: {row.get('classification_basis') or ''}")
        print()
        found = candidates(row, _trips(conn))
        if not found:
            print("이용기간과 겹치는 여행이 없습니다. 후보 없음 — 사람이 새로 판단해야 합니다.")
            return 0
        print(f"후보 {len(found)}건 (읽기 전용 계산, 이 도구는 아무것도 옮기지 않습니다):")
        for index, item in enumerate(found, 1):
            print(f"  {index}. {item['title']} ({item['tab_id']})")
            print(f"     여행 기간: {item['starts_on']}~{item['ends_on']} · 겹치는 날 {item['shared_days']}일")
            print(f"     근거: {item['rule']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
