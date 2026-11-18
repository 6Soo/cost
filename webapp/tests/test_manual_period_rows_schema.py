"""`manual_period_rows` reads an old board file without failing the render (synthetic only).

The legacy `/board` renderer and the React ledger both ask this module which rows a
person gave an explicit service period.  SPEC §11.2.1 적용 순서 2 keeps permission,
retention and manual-correction reads on the existing server boundary, so a board file
written before `board_manual_overrides` gained its `field` column must still be read:
an old board file that cannot answer the question is an empty answer, not a failed page.

Three shapes are pinned here, in the order a real board file can have them:

  (a) the current table (`row_id` · `field` · `event_id`)   -> the same rows as before;
  (b) a row-id-only table (`row_id`) with no revision table  -> no row is claimed;
  (c) no `board_manual_overrides` table at all               -> no row is claimed.

(b) and (c) return the empty set on purpose.  With no `field` column nothing records
*which* field a person overrode, so no row can be read as a service-period override.
Returning the table's row_ids would instead let an override of some other field blank
a stored Rust decision and show "이용일 확인 필요" for a row nobody corrected — a read
would be inventing a person's correction.

`app/manual_overrides.py` already degrades this way for the override list itself.  A
service period has two answers (which rows, and which field), so it degrades to "no
service-period rows" rather than to "every row".
"""
from __future__ import annotations

import sqlite3

from webapp import ledger_stay_evidence

ROWS = ("card-R1", "card-R2", "man-M1")


class FakeStore:
    """The only shape `manual_period_rows` reads: a connection and its lock."""

    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def __init__(self, conn):
        self.conn = conn
        self._lock = self._Lock()


def _store_with(sql: str | None, rows=ROWS):
    conn = sqlite3.connect(":memory:")
    if sql is not None:
        conn.executescript(sql)
        for row_id in rows:
            conn.execute("INSERT INTO board_manual_overrides(row_id) VALUES (?)",
                         (row_id,))
    return FakeStore(conn)


def test_current_schema_keeps_the_existing_answer():
    """(a) 정상 스키마: 서비스기간을 지정한 행만, 이전과 같은 값이다."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE board_manual_overrides (row_id TEXT NOT NULL, field TEXT NOT NULL,"
        " event_id TEXT NOT NULL, PRIMARY KEY (row_id, field));"
        "CREATE TABLE board_revisions (row_id TEXT, revision INTEGER, event_id TEXT);")
    conn.executemany(
        "INSERT INTO board_manual_overrides VALUES (?,?,?)",
        [("card-R1", "service_period", ""), ("card-R2", "item", ""),
         ("man-M1", "service_period", "")])
    store = FakeStore(conn)

    assert ledger_stay_evidence.manual_period_rows(store) == {"card-R1", "man-M1"}


def test_row_id_only_legacy_schema_reads_as_no_override():
    """(b) row_id만 있는 구형 스키마: 예외 없이, 어떤 행도 서비스기간 지정으로 세지 않는다."""
    store = _store_with("CREATE TABLE board_manual_overrides (row_id TEXT NOT NULL);")

    assert ledger_stay_evidence.manual_period_rows(store) == set()


def test_missing_override_table_reads_as_no_override():
    """(c) 수동 기록 테이블 자체가 없는 파일: 예외 없이 빈 집합."""
    store = _store_with(None)

    assert ledger_stay_evidence.manual_period_rows(store) == set()


def test_row_id_only_schema_does_not_blank_a_stored_period():
    """(b)의 결과: 구형 스키마에서 Rust가 저장한 기간은 그대로 확정값으로 읽힌다.

    같은 행을 '수동 미확인'으로 세면 저장 판정이 가려진다. 빈 집합이면 `read_period`가
    저장 판정을 읽고, 근거가 없을 때만 '미확인'이 된다.
    """
    row = {"row_id": "card-R1", "source_event_id": "R1", "service_period": ""}
    stored = {"R1": {"kind": "verified", "starts_on": "2026-10-01", "ends_on": "2026-10-03"}}
    store = _store_with("CREATE TABLE board_manual_overrides (row_id TEXT NOT NULL);")
    manual = ledger_stay_evidence.manual_period_rows(store)

    period, source = ledger_stay_evidence.read_period(
        row, stored, manual, lambda: "", export=False)

    assert source == "decision", (period, source)
    assert period == "2026-10-01~2026-10-03", "저장된 기간이 구형 스키마 때문에 사라짐"
