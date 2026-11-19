"""SPEC §11.2.1 계약 4: 저장 이용기간은 두 조회 경로에서 같은 답을 낸다.

세 조건이 원인이었다.

(a) 구형 스키마 — 코어 decisions 표에 ``source_hash``/``revision`` 열이 없다.
(b) 보드가 그 거래를 지목할 수 없다 — 현재 트랜잭션 신원 행이 없다.
(c) 신원 읽기 자체가 실패한다.

레거시 화면은 이 세 경우 모두 저장값을 **확정**(``decision``)으로 표시했다.
React 경로가 같은 값을 "확인 불가"로 낮추면 두 경로가 갈린다.  이 검사는 먼저
React 쪽에서 실패해야 하고, 같은 입력에서 레거시와 같은 ``(period, status)``를
돌려줘야 통과한다.

합성 저장소·합성 코어 파일만 쓴다. 운영 원본·원격 없음.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

VERIFIED = {"kind": "verified", "starts_on": "2026-10-01", "ends_on": "2026-10-03"}
INFERRED = {"kind": "inferred", "starts_on": "2026-10-05", "ends_on": "2026-10-06",
            "basis": "reservation_period_inferred"}


def _row(row_id="card-t1", tid="t1", **extra):
    row = {"row_id": row_id, "source_event_id": tid, "service_period": "",
           "amount_krw": 1000, "item": "숙박비", "occurred_on": "2026-10-01",
           "display_tab_id": "tab-synthetic"}
    row.update(extra)
    return row


@pytest.fixture()
def core(tmp_path, monkeypatch):
    """A core.sqlite with one stored decision, plus the board-side identity."""
    from app import core_writer

    for name in (core_writer.WRITER_ENV, core_writer.BIN_ENV, core_writer.CORE_DB_ENV):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "core.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE decisions(transaction_id TEXT, source_hash TEXT,"
                     " revision INTEGER, service_period_json TEXT)")
        conn.execute("INSERT INTO decisions VALUES (?,?,?,?)",
                     ("t1", "hash-1", 1, json.dumps(VERIFIED)))
    monkeypatch.setenv(core_writer.WRITER_ENV, "rust")
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(path))
    core_writer._PERIOD_CACHE = {"entry": None}
    core_writer._LAST_READ["periods"] = None
    return tmp_path, path


def test_a_matching_identity_is_verified_on_both_paths(core, monkeypatch):
    """(baseline) 신원이 일치하면 두 경로 모두 확정으로 읽는다."""
    from app import core_writer
    from webapp import ledger_stay_evidence

    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _b: set())
    records = core_writer.load_stored_period_records()
    assert records is not None
    legacy_period, legacy_source = ledger_stay_evidence.read_period(
        _row(), records, set(), lambda: "")
    assert (legacy_period, legacy_source) == ("2026-10-01~2026-10-03", "decision")
    # the React helper must answer the same thing for the same row and record
    from webapp import plush_periods

    annotated = plush_periods.annotate(
        [_row()], board=_FakeBoard({"t1": {"source_hash": "hash-1", "revision": 1}}))[0]
    assert annotated["_plush_period"] == legacy_period, annotated
    assert annotated["_plush_period_status"] == "verified", annotated


def test_an_old_schema_record_does_not_become_stale_on_the_react_path(core, monkeypatch):
    """(a) 신원 열이 없는 코어 파일: 레거시가 읽는 값을 React도 그대로 읽는다."""
    from app import core_writer
    from webapp import ledger_stay_evidence

    plain = core[0] / "core-plain.sqlite"
    with sqlite3.connect(plain) as conn:
        conn.execute("CREATE TABLE decisions(transaction_id TEXT, service_period_json TEXT)")
        conn.execute("INSERT INTO decisions VALUES (?,?)", ("t1", json.dumps(VERIFIED)))
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(plain))
    core_writer._PERIOD_CACHE = {"entry": None}
    core_writer._LAST_READ["periods"] = None
    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _b: set())

    # the legacy screen's answer for this core file
    stored = core_writer.load_stored_periods()
    legacy_period, legacy_source = ledger_stay_evidence.read_period(
        _row(), stored, set(), lambda: "")
    assert (legacy_period, legacy_source) == ("2026-10-01~2026-10-03", "decision")

    from webapp import plush_periods

    annotated = plush_periods.annotate([_row()], board=_FakeBoard(None))[0]
    assert annotated["_plush_period"] == legacy_period, annotated
    assert annotated.get("_plush_period_status") != "stale", annotated


def test_a_transaction_the_board_cannot_name_is_not_stale(core, monkeypatch):
    """(b) 보드가 거래를 못 지목하는 것과 원천이 바뀐 것은 다르다."""
    from webapp import ledger_stay_evidence, plush_periods

    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _b: set())
    annotated = plush_periods.annotate([_row()], board=_FakeBoard({}))[0]
    assert annotated["_plush_period"] == "2026-10-01~2026-10-03", annotated
    assert annotated.get("_plush_period_status") != "stale", annotated


def test_an_unreadable_identity_still_fails_closed_on_both_paths(core, monkeypatch):
    """(c) 신원 읽기 실패: 저장값을 확정으로 표시하지 않는다 — 양쪽 동일."""
    from app import core_writer
    from webapp import ledger_stay_evidence, plush_periods

    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _b: set())
    monkeypatch.setattr(plush_periods, "_current_source_identities",
                        lambda _store, _ids: None)
    monkeypatch.setattr(plush_periods, "_evidence_index",
                        lambda _board: lambda: {})
    annotated = plush_periods.annotate([_row()], board=_FakeBoard(None))[0]
    assert annotated["_plush_period"] == "", annotated
    assert annotated.get("_plush_period_status") in ("stale", "", "unknown"), annotated


def test_a_real_source_change_is_never_shown(core, monkeypatch):
    """회귀: 원천이 정말 바뀐 경우는 양쪽 모두 저장값을 숨긴다."""
    from webapp import ledger_stay_evidence, plush_periods

    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _b: set())
    monkeypatch.setattr(plush_periods, "_evidence_index", lambda _board: lambda: {})
    annotated = plush_periods.annotate(
        [_row()], board=_FakeBoard({"t1": {"source_hash": "new", "revision": 2}}))[0]
    assert annotated["_plush_period"] != "2026-10-01~2026-10-03", annotated


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, identities):
        self._identities = identities

    def execute(self, sql, *args):
        if "board_manual_overrides" in sql:
            return _Result([])
        ids = args[0] if args else []
        found = [(t, self._identities[t]["source_hash"], self._identities[t]["revision"])
                 for t in ids if t in self._identities]
        return _Result(found)


class _FakeBoard:
    """The board surface the period helpers read: a store with identities."""

    def __init__(self, identities):
        import threading

        self.conn = _Conn(identities or {})
        self._lock = threading.Lock()


def test_the_legacy_screen_hides_a_changed_source_too(core, monkeypatch):
    """(e) DATE-017: 원천이 바뀌면 레거시 화면도 저장값을 무효화한다."""
    from app import core_writer
    from webapp import ledger_board, ledger_design, ledger_stay_evidence

    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _b: set())
    monkeypatch.setattr(ledger_design, "_manual_period_rows", lambda: set())
    monkeypatch.setattr(ledger_design, "_ledger_stay_index", lambda: {})
    # the board names the transaction but with a different identity
    fake = _FakeBoard({"t1": {"source_hash": "new", "revision": 2}})
    monkeypatch.setattr(ledger_board, "_active_store", lambda: fake)
    core_writer._PERIOD_RECORD_CACHE.clear()
    period, source = ledger_design._read_period(_row(), verified=False)
    assert period != "2026-10-01~2026-10-03", (period, source)


def test_manual_and_saved_period_precedence_is_preserved_without_mutating_rows(core, monkeypatch):
    """수동 값·수동 빈 칸이 저장 결정보다 우선하고, 저장 상태가 행에 그대로 남는다.

    #993 잔여 계약(합성): 행 원문 우선(상태 없음), 수동 빈 칸의 unknown·
    manual_blank 표시, 추정(inferred) 근거, 미상(unknown) 결정, 원천 변경(stale)
    숨김, 입력 행 불변. 합성 코어 파일만 쓰고 운영 원본·원격은 없다.
    """
    from copy import deepcopy

    from app import core_writer
    from webapp import ledger_stay_evidence, plush_periods

    with sqlite3.connect(core[1]) as conn:
        conn.executemany(
            "INSERT INTO decisions VALUES (?,?,?,?)",
            [
                ("manual-value", "mv-hash", 1, json.dumps(
                    {"kind": "verified", "starts_on": "2026-10-01", "ends_on": "2026-10-02"})),
                ("manual-empty", "me-hash", 1, json.dumps(
                    {"kind": "verified", "starts_on": "2026-10-03", "ends_on": "2026-10-04"})),
                ("inferred-t", "inf-hash", 3, json.dumps(
                    {"kind": "inferred", "starts_on": "2026-10-07", "ends_on": "2026-10-08",
                     "basis": "예약 자료 연결"})),
                ("unknown-t", "unk-hash", 4, json.dumps({"kind": "unknown", "reason": "근거 없음"})),
                ("stale-t", "old-hash", 1, json.dumps(
                    {"kind": "verified", "starts_on": "2026-10-09", "ends_on": "2026-10-10"})),
            ],
        )
    monkeypatch.setattr(core_writer, "_PERIOD_RECORD_CACHE", {})
    monkeypatch.setattr(core_writer, "_schedule_publish", lambda: None)
    monkeypatch.setattr(core_writer, "note_period_source", lambda *_a, **_k: None)
    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows",
                        lambda _b: {"card-manual-value", "card-manual-empty"})
    monkeypatch.setattr(plush_periods, "_evidence_index", lambda _board: lambda: {})

    rows = [
        _row("card-manual-value", "manual-value", service_period="2026-09-01~2026-09-02"),
        _row("card-manual-empty", "manual-empty"),
        _row("card-t1", "t1"),
        _row("card-inferred-t", "inferred-t"),
        _row("card-unknown-t", "unknown-t"),
        _row("card-stale-t", "stale-t"),
    ]
    before = deepcopy(rows)
    board = _FakeBoard({
        "manual-value": {"source_hash": "mv-hash", "revision": 1},
        "manual-empty": {"source_hash": "me-hash", "revision": 1},
        "t1": {"source_hash": "hash-1", "revision": 1},
        "inferred-t": {"source_hash": "inf-hash", "revision": 3},
        "unknown-t": {"source_hash": "unk-hash", "revision": 4},
        "stale-t": {"source_hash": "new-hash", "revision": 2},
    })

    annotated = plush_periods.annotate(rows, board=board)
    by_id = {row["row_id"]: row for row in annotated}

    assert by_id["card-manual-value"]["_plush_period"] == "2026-09-01~2026-09-02"
    assert "_plush_period_status" not in by_id["card-manual-value"]
    assert by_id["card-manual-empty"]["_plush_period"] == ""
    assert by_id["card-manual-empty"]["_plush_period_status"] == "unknown"
    assert by_id["card-manual-empty"]["_plush_period_manual_blank"] is True
    assert by_id["card-t1"]["_plush_period"] == "2026-10-01~2026-10-03"
    assert by_id["card-t1"]["_plush_period_status"] == "verified"
    assert by_id["card-inferred-t"]["_plush_period"] == "2026-10-07~2026-10-08"
    assert by_id["card-inferred-t"]["_plush_period_status"] == "inferred"
    assert by_id["card-inferred-t"]["_plush_period_basis"] == "예약 자료 연결"
    assert by_id["card-unknown-t"]["_plush_period"] == ""
    assert by_id["card-unknown-t"]["_plush_period_status"] == "unknown"
    assert by_id["card-stale-t"]["_plush_period"] == ""
    assert by_id["card-stale-t"]["_plush_period_status"] == "stale"
    assert rows == before


def test_period_status_basis_and_manual_blank_travel_in_the_row_dto(core, monkeypatch):
    """저장 상태·추정 근거·수동 빈 칸 표시가 React 행 DTO까지 같은 값으로 전달된다.

    #993 잔여 계약(합성): plush_projection.ledger_row가 _plush_period_status·
    _plush_period_basis·_plush_period_manual_blank를 period_status·period_basis·
    period_manual_blank로 내보낸다. 실제 호출 경로(plush_api ledger_rows)처럼
    ledger_periods.period_for_row·display_label로 라벨을 해소해投影한다.
    """
    from app import core_writer
    from webapp import (ledger_board, ledger_design, ledger_periods,
                        ledger_stay_evidence, plush_periods, plush_projection)

    with sqlite3.connect(core[1]) as conn:
        conn.executemany(
            "INSERT INTO decisions VALUES (?,?,?,?)",
            [
                ("inferred-t", "inf-hash", 3, json.dumps(
                    {"kind": "inferred", "starts_on": "2026-10-07", "ends_on": "2026-10-08",
                     "basis": "예약 자료 연결"})),
                ("manual-empty", "me-hash", 1, json.dumps(
                    {"kind": "verified", "starts_on": "2026-10-03", "ends_on": "2026-10-04"})),
            ],
        )
    monkeypatch.setattr(core_writer, "_PERIOD_RECORD_CACHE", {})
    monkeypatch.setattr(core_writer, "_schedule_publish", lambda: None)
    monkeypatch.setattr(core_writer, "note_period_source", lambda *_a, **_k: None)
    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows",
                        lambda _b: {"card-manual-empty"})
    monkeypatch.setattr(plush_periods, "_evidence_index", lambda _board: lambda: {})

    board = _FakeBoard({
        "inferred-t": {"source_hash": "inf-hash", "revision": 3},
        "manual-empty": {"source_hash": "me-hash", "revision": 1},
    })
    monkeypatch.setattr(ledger_board, "_active_store", lambda: board)
    monkeypatch.setattr(ledger_design, "_manual_period_rows", lambda: {"card-manual-empty"})
    monkeypatch.setattr(ledger_design, "_ledger_stay_index", lambda: {})

    rows = [_row("card-inferred-t", "inferred-t"), _row("card-manual-empty", "manual-empty")]
    annotated = plush_periods.annotate(rows, board=board)

    dtos = {}
    for row in annotated:
        period, period_source = ledger_periods.period_for_row(row, board)
        compact, full = ledger_periods.display_label(row)
        dto = plush_projection.ledger_row(
            row, period=period, period_source=period_source,
            period_label=compact, period_label_full=full)
        dtos[dto["id"]] = dto

    inferred = dtos["card-inferred-t"]
    assert inferred["period"] == "2026-10-07~2026-10-08", inferred
    assert inferred["period_status"] == "inferred", inferred
    assert inferred["period_basis"] == "예약 자료 연결", inferred
    manual_blank = dtos["card-manual-empty"]
    assert manual_blank["period"] == "", manual_blank
    assert manual_blank["period_status"] == "unknown", manual_blank
    assert manual_blank["period_manual_blank"] is True, manual_blank
