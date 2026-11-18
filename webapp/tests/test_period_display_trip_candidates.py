"""The read-only trip-candidate finder — synthetic board only (소유자 결정 2026-11-19 ③).

The tool must never move, write, or invent a trip. It reads a board copy and
ranks the trips whose stored dates touch the row's stay.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from tools import audit_unassigned_reservation_trip as tool


def _board(tmp_path):
    path = tmp_path / "board.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE board_rows(row_id TEXT, display_tab_id TEXT, payload_json TEXT)")
    conn.execute("CREATE TABLE trip_tabs(tab_id TEXT, starts_on TEXT, ends_on TEXT,"
                 " display_key TEXT, destination TEXT, deleted INTEGER)")
    conn.execute("INSERT INTO board_rows VALUES (?,?,?)", (
        "card-syn-row", "quarter:2026:2", json.dumps({
            "row_kind": "expense", "source_merchant": "네이버페이-트립닷컴",
            "description": "예약 1400827517097737", "reservation_no": "1400827517097737",
            "service_period": "2026-06-20~2026-06-25", "amount_krw": 499505,
            "classification_basis": "GOOGLE_MANUAL_ROW · 2분기_기타비용!138",
        }, ensure_ascii=False)))
    trips = [
        ("trip-full", "2026-06-18", "2026-06-28", "합성 전체 포함", "합성", 0),
        ("trip-part", "2026-06-25", "2026-07-02", "합성 일부 겹침", "합성", 0),
        ("trip-away", "2026-08-01", "2026-08-09", "합성 안 겹침", "합성", 0),
        ("trip-gone", "2026-06-18", "2026-06-28", "삭제된 여행", "합성", 1),
    ]
    conn.executemany("INSERT INTO trip_tabs VALUES (?,?,?,?,?,?)", trips)
    conn.commit()
    conn.close()
    return str(path)


def test_candidates_rank_a_covering_trip_before_a_partial_overlap(tmp_path):
    conn = tool._open_readonly(_board(tmp_path))
    try:
        row = tool._find_row(conn, reservation="1400827517097737")
        found = tool.candidates(row, tool._trips(conn))
    finally:
        conn.close()
    assert [item["tab_id"] for item in found] == ["trip-full", "trip-part"], found
    assert found[0]["covers_period"] is True and found[0]["shared_days"] == 6
    assert found[1]["covers_period"] is False and found[1]["shared_days"] == 1
    assert "trip-away" not in [item["tab_id"] for item in found]
    assert "trip-gone" not in [item["tab_id"] for item in found]


def test_the_tool_writes_nothing_to_the_board(tmp_path):
    path = _board(tmp_path)
    before = sqlite3.connect(path)
    before_rows = before.execute("SELECT row_id, display_tab_id, payload_json FROM board_rows").fetchall()
    before_trips = before.execute("SELECT * FROM trip_tabs").fetchall()
    before.close()

    assert tool.main(["--db", path, "--reservation", "1400827517097737"]) == 0

    after = sqlite3.connect(path)
    assert after.execute("SELECT row_id, display_tab_id, payload_json FROM board_rows").fetchall() == before_rows
    assert after.execute("SELECT * FROM trip_tabs").fetchall() == before_trips
    after.close()


def test_an_opened_read_only_connection_refuses_a_write(tmp_path):
    conn = tool._open_readonly(_board(tmp_path))
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM trip_tabs")
    finally:
        conn.close()


def test_no_overlapping_trip_reports_none_rather_than_guessing(tmp_path):
    conn = tool._open_readonly(_board(tmp_path))
    try:
        row = {"service_period": "2027-01-01~2027-01-03"}
        assert tool.candidates(row, tool._trips(conn)) == []
    finally:
        conn.close()
