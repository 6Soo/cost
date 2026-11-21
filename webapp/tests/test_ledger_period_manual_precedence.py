"""A person's explicit 이용기간 wins in the Python-writer mode too (synthetic only).

`ledger_stay_evidence.read_period` read `manual` only after a stored decision existed.
With `stored is None` (Python writer) a manual value or blank was skipped and the
compute fallback ran, so a person's field was overridden by a recomputation.  The
shared precedence is: the row's own value, then a manual value or blank, then the
stored decision, then computing — on every call path (legacy read, React helper, and
the Plush annotation that feeds the ledger DTO).
"""
from __future__ import annotations

import pytest


def _card(row_id, tid, **extra):
    row = {"row_id": row_id, "source_event_id": tid, "service_period": "",
           "amount_krw": 1000, "item": "숙박비", "occurred_on": "2026-10-01",
           "display_tab_id": "trip-synthetic"}
    row.update(extra)
    return row


def test_read_period_honours_manual_in_python_writer_mode():
    """회귀: stored=None이면 수동 값을 건너뛰고 compute하던 경로."""
    from webapp import ledger_stay_evidence

    calls = []
    def compute():
        calls.append(1)
        return '2026-08-01~2026-08-03'

    row = _card("card-mp-1", "mp-1")
    assert ledger_stay_evidence.read_period(row, None, {"card-mp-1"}, compute) == ("", "manual")
    # a person's typed value outranks the compute fallback as well
    typed = _card("card-mp-2", "mp-2", service_period="2026-10-01~2026-10-02")
    assert ledger_stay_evidence.read_period(typed, None, {"card-mp-2"}, compute) == (
        "2026-10-01~2026-10-02", "row")
    assert calls == []


def test_legacy_read_period_prefers_manual_in_python_writer_mode(monkeypatch):
    """같은 규칙을 쓰는 레거시 조회 경로도 수동 값을 지킨다."""
    from webapp import ledger_design

    monkeypatch.setattr(ledger_design, "_stored_periods", lambda: None)
    monkeypatch.setattr(ledger_design, "_manual_period_rows", lambda: {"card-mp-3"})
    monkeypatch.setattr(ledger_design, "_ledger_stay_index", lambda: pytest.fail("index built"))

    assert ledger_design._read_period(_card("card-mp-3", "mp-3"), verified=False) == ("", "manual")
    assert ledger_design._read_period(_card("card-mp-3", "mp-3"), verified=True) == ("", "manual")


def test_react_period_for_row_reads_manual_in_python_writer_mode(monkeypatch):
    """React 헬퍼가 저장 스코프 없이도 수동 집합을 전달한다."""
    from app import core_writer
    from webapp import ledger_periods, ledger_stay_evidence

    monkeypatch.setattr(core_writer, "load_stored_periods", lambda: None)
    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _store: {"card-mp-4"})
    monkeypatch.setattr(ledger_stay_evidence, "stay_index", lambda _store: pytest.fail("index built"))
    monkeypatch.setattr(ledger_stay_evidence, "period_for", lambda _row, _index: pytest.fail("computed"))

    assert ledger_periods.period_for_row(_card("card-mp-4", "mp-4"), None) == ("", "manual")


def test_annotate_marks_python_writer_manual_blank_as_unknown(monkeypatch):
    """Plush 주석: 수동 공란은 저장 스코프가 없어도 unknown으로 표시된다."""
    from webapp import ledger_stay_evidence, plush_periods

    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows", lambda _board: {"card-mp-5"})
    monkeypatch.setattr(plush_periods, "_stored_records", lambda _core_writer: None)
    monkeypatch.setattr(ledger_stay_evidence, "stay_index", lambda _board: pytest.fail("index built"))
    monkeypatch.setattr(ledger_stay_evidence, "period_for", lambda _row, _index: pytest.fail("computed"))

    [annotated] = plush_periods.annotate([_card("card-mp-5", "mp-5")], board=object())
    assert annotated["_plush_period"] == ""
    assert annotated["_plush_period_status"] == "unknown"
    assert annotated["_plush_period_manual_blank"] is True
