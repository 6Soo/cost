from urllib.parse import urlparse
from types import SimpleNamespace

from app import google_authority as ga
from webapp import google_ledger_page as page


def block(total, verified=True):
    return {"sheet_total": total, "row_sum": total, "total": total, "verified": verified}


def copy(sheet, income, expense, verified=True):
    return {"sheet": sheet, "layout": "rev", "flags": [], "income": block(income, verified),
            "expense": block(expense, verified)}


def snapshot_doc():
    dup = {"key": "0404_에히메", "closure": "closed", "closure_current": True, "canonical_source": "main",
           "income_total": 1000, "expense_total": 400, "net": 600, "verified": True,
           "reported": {"income_total": 1000, "expense_total": 400, "net": 600},
           "copies": {"main": copy("0404_에히메", 1000, 400), "archive": copy("0404_에히메", 900, 300)},
           "review": ["DUPLICATE_IN_BOTH"]}
    mismatch = {"key": "<script>0630", "closure": "open", "closure_current": True, "canonical_source": "main",
                "income_total": None, "expense_total": None, "net": None, "verified": False,
                "reported": {"income_total": 5, "expense_total": 2, "net": 3},
                "copies": {"main": copy("<script>0630", 5, 2, verified=False), "archive": None},
                "review": ["TOTAL_MISMATCH"]}
    return {"schema": "google-authority-readonly-v2", "synced_at": "2026-10-11T10:00:00+09:00",
            "sources": {"main": {"status": "ok", "error_code": None, "stale": False,
                                 "last_ok_at": "2026-10-11T10:00:00+09:00", "checked_at": "x"},
                        "archive": {"status": "error", "error_code": "SOURCE_UNREACHABLE", "stale": True,
                                    "last_ok_at": None, "checked_at": "x"}},
            "trips": [dup, mismatch], "rows_generation": "gen"}


class FakeHandler:
    def __init__(self, token=""):
        self.headers = {"X-CSRF-Token": token} if token else {}
        self.sent = []

    def _send_json(self, value, code=200, extra_headers=None):
        self.sent.append(("json", code, value))

    def _send(self, text, code=200):
        self.sent.append(("html", code, text))


def rows_doc():
    line = lambda row, payee, amount: {"row": row, "cells": {"B": "2027-08-02", "C": payee, "D": "식비",
                                                            "E": "", "F": "RESV-1", "G": "카드"}, "amount": amount}
    return {"schema": ga.ROWS_SCHEMA, "generation": "gen", "synced_at": "t",
            "sources": {"main": {"content_sha256": None, "trips": {
                "0404_에히메": {"income": [line(6, "INCOME-NAME", 1000)],
                                "expense": [line(12, "PAYEE-<b>", 400)]}}}}}


def test_retired_routes_are_unowned_and_dispatch_does_not_read_or_write(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(tmp_path / "snapshot.json"))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(tmp_path / "rows.json"))
    paths = (
        "/google-ledger",
        "/api/google-ledger",
        "/api/google-ledger/choice",
        "/api/google-ledger/grants",
        "/api/google-ledger/mapping",
        "/api/google-ledger/auto-mapping",
        "/google-ledger/rows",
        "/api/google-ledger/rows",
    )

    for path in paths:
        assert page.owns_route(path) is False
        handler = FakeHandler()
        assert page.dispatch(handler, urlparse(path), is_owner=True, raw=b"{}", csrf="valid") is False
        assert handler.sent == []

    assert list(tmp_path.iterdir()) == []


def test_trip_import_persists_only_schedule_availability_atomically(monkeypatch, tmp_path):
    board = SimpleNamespace(path=tmp_path / 'board.sqlite', list_trips=lambda **_kw: [])
    monkeypatch.setattr(page, '_schedule_overrides',
                        lambda: (_ for _ in ()).throw(OSError('synthetic missing schedule')))
    result = page.import_trips(board, {'trips': []})
    status_path = tmp_path / page.TRIP_IMPORT_STATUS_FILENAME
    assert result['schedule_unavailable'] == 1
    assert page.last_trip_import_result(tmp_path) == {'schedule_unavailable': True}
    assert status_path.read_text(encoding='utf-8') == '{"schedule_unavailable": true}'
    assert not list(tmp_path.glob(status_path.name + '.*.tmp'))


def test_trip_import_status_missing_or_corrupt_keeps_previous_no_warning_behavior(tmp_path):
    assert page.last_trip_import_result(tmp_path) is None
    (tmp_path / page.TRIP_IMPORT_STATUS_FILENAME).write_text('{bad json', encoding='utf-8')
    assert page.last_trip_import_result(tmp_path) is None


def _clean_trip(**over):
    base = {"key": "0404_에히메", "closure": "closed", "closure_current": True, "canonical_source": "main",
            "income_total": 1000, "expense_total": 400, "net": 600, "verified": True,
            "review": ["DUPLICATE_IN_BOTH"],
            "copies": {"main": copy("0404_에히메", 1000, 400),
                       "archive": copy("0404_에히메", 900, 300)}}
    base.update(over)
    return base


def _clean_sources(**over):
    ok = {"status": "ok", "stale": False, "last_ok_at": "t", "checked_at": "t"}
    sources = {"main": dict(ok), "archive": dict(ok)}
    sources.update(over)
    return sources


def _chosen(trip, sources, choice="archive"):
    snapshot = {"synced_at": "t", "sources": sources, "trips": [trip]}
    return page.owner_payload(snapshot, {"choices": {trip["key"]: choice}, "history": []})["trips"][0]


def test_clean_archive_choice_counts_the_selected_copy_figures():
    trip = _chosen(_clean_trip(), _clean_sources())
    assert trip["verified"] is True and trip["net"] == 600 and trip["blocked_by"] == []


def test_stale_source_keeps_financial_figures_blocked_after_copy_choice():
    stale_main = _clean_sources(main={"status": "error", "stale": True, "last_ok_at": "t", "checked_at": "t"})
    trip = _chosen(_clean_trip(review=["DUPLICATE_IN_BOTH", "SOURCE_STALE"]), stale_main)
    assert trip["verified"] is False and trip["net"] is None
    assert "SOURCE_NOT_CURRENT" in trip["blocked_by"]


def test_stale_archive_sync_blocks_archive_choice():
    stale_archive = _clean_sources(archive={"status": "error", "stale": True,
                                            "last_ok_at": "t", "checked_at": "t"})
    trip = _chosen(_clean_trip(), stale_archive)
    assert trip["verified"] is False and "SOURCE_NOT_CURRENT" in trip["blocked_by"]


def test_identity_uncertainty_is_not_lifted_by_copy_choice():
    for flag in ("POSSIBLE_DUPLICATE", "COPY_NAME", "DUPLICATE_IN_SOURCE"):
        trip = _chosen(_clean_trip(review=["DUPLICATE_IN_BOTH", flag]), _clean_sources())
        assert trip["verified"] is False, flag
        assert flag in trip["blocked_by"], flag


def test_noncurrent_closure_or_unverified_copy_blocks_selected_figures():
    assert "CLOSURE_NOT_CURRENT" in _chosen(
        _clean_trip(closure_current=False), _clean_sources())["blocked_by"]
    unverified = _clean_trip(copies={"main": copy("0404_에히메", 1000, 400),
                                     "archive": copy("0404_에히메", 900, 300, verified=False)})
    assert "COPY_NOT_VERIFIED" in _chosen(unverified, _clean_sources())["blocked_by"]
