"""Focused synthetic tests for app/google_authority.py CORE-06 reuse / error / change.

Only touches testing of sync(), load_consistent, generation reuse, previous-success
preservation, and actual change production. No external data / browser / network.
"""
import io
from pathlib import Path

import openpyxl

from app.google_authority import (
    SPREADSHEET_IDS,
    SourceError,
    sync,
    load_consistent,
    load_rows,
)


def _make_workbook(title: str = "2026_TestTrip", amount: int = 1000) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    # Minimal rev-like layout: income header row 5, expense header row 10
    ws["B5"] = "거래일자"
    ws["C5"] = "이름"
    ws["D5"] = "닉네임"
    ws["E5"] = "예약금"
    ws["F5"] = "잔금"
    ws["G5"] = "추가금"
    ws["H5"] = "금액(원)"
    ws["B10"] = "거래일자"
    ws["C10"] = "항목"
    ws["D10"] = "내용"
    ws["E10"] = "기간"
    ws["F10"] = "예약번호"
    ws["G10"] = "증빙유형"
    ws["H10"] = "금액(원)"
    ws["B6"] = "2026-01-01"
    ws["C6"] = "Name"
    ws["H6"] = amount
    ws["B11"] = "2026-01-01"
    ws["C11"] = "Item"
    ws["H11"] = amount
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fetcher_for(bytes_data: bytes, error_code: str | None = None):
    def fetcher(url: str) -> bytes:
        if error_code:
            raise SourceError(error_code)
        return bytes_data
    return fetcher


class TestCore06ReuseErrorChange:
    def test_unchanged_reuses_same_private_generation(self, tmp_path: Path):
        snap = tmp_path / "snap.json"
        rows = tmp_path / "rows.json"
        data = _make_workbook()
        snap_first = sync(snap, rows, fetcher=_fetcher_for(data), now=None)
        gen_first = snap_first["rows_generation"]
        # Second identical run must reuse generation, not write a new file.
        snap_second = sync(snap, rows, fetcher=_fetcher_for(data), now=None)
        gen_second = snap_second["rows_generation"]
        assert gen_second == gen_first, "unchanged must reuse generation"
        # Snapshot should have updated checked_at but same generation.
        assert snap_second["synced_at"] >= snap_first["synced_at"]
        # Private file should still describe the content (hash match).
        rows_data_first = load_rows(rows, gen_first)
        for role in SPREADSHEET_IDS:
            assert snap_first["sources"][role]["content_sha256"] == rows_data_first[role]["content_sha256"]
        # load_consistent must succeed across reused generation.
        consistent_snapshot, consistent_rows = load_consistent(snap, rows)
        assert consistent_snapshot["rows_generation"] == gen_first
        assert consistent_rows["main"]["content_sha256"] == snap_first["sources"]["main"]["content_sha256"]
        assert len(list(tmp_path.glob('rows.*.json'))) == 1

    def test_error_keeps_previous_success_and_load_consistent(self, tmp_path: Path):
        snap = tmp_path / "snap.json"
        rows = tmp_path / "rows.json"
        data = _make_workbook()
        snap_ok = sync(snap, rows, fetcher=_fetcher_for(data), now=None)
        gen_ok = snap_ok["rows_generation"]
        # Now source fails.
        snap_err = sync(snap, rows, fetcher=_fetcher_for(data, error_code="SOURCE_UNREACHABLE"), now=None)
        assert snap_err["sources"]["main"]["status"] == "error"
        assert snap_err["sources"]["main"]["stale"] is True
        assert snap_err["sources"]["main"]["last_ok_at"] == snap_ok["sources"]["main"]["last_ok_at"]
        # Previous good data preserved: generation same when unchanged private.
        assert snap_err["rows_generation"] == gen_ok
        # load_consistent must still work with preserved previous rows.
        full_snap, full_rows = load_consistent(snap, rows)
        assert full_snap["sources"]["main"]["last_ok_at"] == snap_ok["sources"]["main"]["last_ok_at"]

    def test_actual_change_produces_new_generation_with_new_hash(self, tmp_path: Path):
        snap = tmp_path / "snap.json"
        rows = tmp_path / "rows.json"
        data_first = _make_workbook(title="2026_A", amount=100)
        snap_first = sync(snap, rows, fetcher=_fetcher_for(data_first), now=None)
        gen_first = snap_first["rows_generation"]
        # Different content: title and amount changed -> digest change.
        data_second = _make_workbook(title="2026_B", amount=200)
        snap_second = sync(snap, rows, fetcher=_fetcher_for(data_second), now=None)
        gen_second = snap_second["rows_generation"]
        assert gen_second != gen_first, "actual change must produce new generation"
        # New private content must match new hash.
        rows_second = load_rows(rows, gen_second)
        assert snap_second["sources"]["main"]["content_sha256"] == rows_second["main"]["content_sha256"]
        # Previous generation preserved (not deleted) while new written.
        assert load_rows(rows, gen_first) is not None
        # Consistency must hold on the new pair.
        full_snap, full_rows = load_consistent(snap, rows)
        assert full_snap["rows_generation"] == gen_second

    def test_unchanged_run_retains_previous_generation_for_inflight_readers(self, tmp_path):
        snap, rows = tmp_path/'snap.json', tmp_path/'rows.json'
        first = sync(snap, rows, fetcher=_fetcher_for(_make_workbook(amount=100)))
        changed_bytes = _make_workbook(amount=200)
        second = sync(snap, rows, fetcher=_fetcher_for(changed_bytes))
        private_file = tmp_path/f"rows.{second['rows_generation']}.json"
        before = (private_file.read_bytes(), private_file.stat().st_mtime_ns)
        third = sync(snap, rows, fetcher=_fetcher_for(changed_bytes))
        assert third['rows_generation'] == second['rows_generation']
        assert third['rows_generation_previous'] == first['rows_generation']
        assert (private_file.read_bytes(), private_file.stat().st_mtime_ns) == before
        assert load_rows(rows, first['rows_generation'])

    def test_partial_failure_retains_other_source_and_recovers(self, tmp_path):
        snap, rows = tmp_path/'snap.json', tmp_path/'rows.json'
        first_bytes = _make_workbook(amount=100)
        changed_bytes = _make_workbook(amount=200)
        first = sync(snap, rows, fetcher=_fetcher_for(first_bytes))
        def partial(url):
            if SPREADSHEET_IDS['archive'] in url:
                raise SourceError('SOURCE_UNREACHABLE')
            return changed_bytes
        second = sync(snap, rows, fetcher=partial)
        assert second['rows_generation'] != first['rows_generation']
        snapshot, private = load_consistent(snap, rows)
        assert snapshot['sources']['archive']['stale']
        assert private['archive']['content_sha256'] == first['sources']['archive']['content_sha256']
        recovered = sync(snap, rows, fetcher=_fetcher_for(changed_bytes))
        assert recovered['sources']['archive']['status'] == 'ok'
        load_consistent(snap, rows)
