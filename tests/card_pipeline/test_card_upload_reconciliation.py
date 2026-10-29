# -*- coding: utf-8 -*-
"""Comprehensive synthetic tests for PR #349 card upload reconciliation (CUV-01 ~ CUV-07).

All tests use in-memory SQLite databases and synthetic files generated in memory.
No production database, real customer data, or external writes are involved.
"""
from __future__ import annotations

import io
import sqlite3
import pytest

from app import Pipeline
from app.card_preflight import validate_upload
from app.db import StoreError
from app.import_card import parse_card_file
from app.upload_reconciliation import summarize
from tests.card_pipeline.fixtures import (
    DOMESTIC_HEADERS,
    domestic_row,
    make_csv,
    make_xlsx,
)

TRIPS = [
    {"trip_id": "trip-seoul-2026", "starts_on": "2026-04-01", "ends_on": "2026-04-30"},
    {"trip_id": "trip-tokyo-2026", "starts_on": "2026-05-01", "ends_on": "2026-05-10"},
]


@pytest.fixture()
def pipe(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test_cost.sqlite"), isolation_level=None)
    pipeline = Pipeline(conn)
    yield pipeline
    conn.close()


def test_preflight_validation_rules():
    # 1. Empty content
    with pytest.raises(StoreError) as exc:
        validate_upload(b"", "test.xlsx")
    assert exc.value.code == "INVALID_UPLOAD_SIZE"

    # 2. Oversized content (>20MB)
    with pytest.raises(StoreError) as exc:
        validate_upload(b"x" * (20 * 1024 * 1024 + 1), "test.xlsx")
    assert exc.value.code == "INVALID_UPLOAD_SIZE"

    # 3. Invalid extension
    with pytest.raises(StoreError) as exc:
        validate_upload(b"dummy", "test.pdf")
    assert exc.value.code == "INVALID_UPLOAD_TYPE"

    # 4. Formula injection in CSV
    bad_csv = make_csv([domestic_row(merchant="=SUM(A1:A10)", amount=1000, approval="1111")])
    with pytest.raises(StoreError) as exc:
        validate_upload(bad_csv, "test.csv")
    assert exc.value.code == "UNSAFE_FORMULA"

    # 5. Formula injection in XLSX
    bad_xlsx = make_xlsx([domestic_row(merchant="=cmd|'/C calc'!A0", amount=1000, approval="1112")])
    with pytest.raises(StoreError) as exc:
        validate_upload(bad_xlsx, "test.xlsx")
    assert exc.value.code == "UNSAFE_FORMULA"

    # 6. Valid upload succeeds and provides inspection metadata
    good_xlsx = make_xlsx([
        domestic_row(merchant="합성식당", amount=12000, approval="1001"),
        domestic_row(merchant="합성카페", amount=5000, approval="1002"),
    ])
    parsed, inspection = validate_upload(good_xlsx, "test.xlsx")
    assert inspection["format"] == "xlsx"
    assert inspection["transaction_rows"] == 2
    assert len(parsed.rows) == 2


def test_preflight_rejects_unidentifiable_card_account():
    headers = list(DOMESTIC_HEADERS)
    row = domestic_row(merchant='합성', amount=1000, approval='NO_ACCOUNT')
    row[0] = ''
    content = make_csv([row], headers=headers)
    with pytest.raises(StoreError) as exc:
        validate_upload(content, 'missing-account.csv')
    assert exc.value.code == 'CARD_ACCOUNT_REQUIRED'


def test_preflight_limits_physical_rows_even_when_rows_are_not_transactions(monkeypatch):
    import app.card_preflight as preflight
    content = make_csv([domestic_row(merchant='합성', amount=1000, approval='ROW_LIMIT'),
                        ['unrecognized', 'non-transaction']])
    monkeypatch.setattr(preflight, 'MAX_ROWS', 1)
    with pytest.raises(StoreError) as exc:
        validate_upload(content, 'row-limit.csv')
    assert exc.value.code == 'UPLOAD_ROW_LIMIT'


def test_xlsx_security_scan_failure_stops_before_writes(monkeypatch, pipe):
    import openpyxl
    content = make_xlsx([domestic_row(merchant='합성', amount=1000, approval='12345678')])
    # Populate the existing parser cache before failing the independent formula scan.
    validate_upload(content, 'scan.xlsx')
    before = list(pipe.store.conn.iterdump())
    def broken_scan(*args, **kwargs):
        raise OSError('synthetic read failure')
    monkeypatch.setattr(openpyxl, 'load_workbook', broken_scan)
    with pytest.raises(StoreError) as exc:
        validate_upload(content, 'scan.xlsx')
    assert exc.value.code == 'INVALID_UPLOAD_CONTENT'
    assert list(pipe.store.conn.iterdump()) == before


def test_large_file_reconciliation_uses_only_uploaded_rows(pipe):
    content = make_csv([domestic_row(merchant=f'Synthetic {i}', amount=1000+i,
                                    approval=str(10000000+i)) for i in range(5000)])
    parsed, inspection = validate_upload(content, 'large.csv')
    received = pipe.receive(content, 'large.csv')
    summary = summarize(pipe, received, parsed, TRIPS, inspection=inspection)
    assert summary['counts']['T'] == summary['counts']['N'] == 5000
    assert sum(m['T'] for m in summary['monthly_reconciliation']) == 5000
    replay = pipe.receive(content, 'large.csv')
    assert replay['reused'] is True
    replay_summary = summarize(pipe, replay, parsed, TRIPS, inspection=inspection)
    assert replay_summary['counts']['N'] == 0
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 5000


def test_reupload_idempotency_preserves_existing_and_manual_decisions(pipe):
    """Spec Gate 1: Re-uploading 100 rows -> 0 new rows, manual decisions intact."""
    rows = [
        domestic_row(merchant=f"가맹점_{i}", amount=10000 + i, approval=f"APPR_{i:04d}")
        for i in range(100)
    ]
    content = make_xlsx(rows)
    parsed, inspection = validate_upload(content, "card.xlsx")

    # First upload
    rec1 = pipe.receive(content, "card.xlsx")
    assert rec1["reused"] is False
    assert rec1["inserted"] == 100

    # User manually decides 2 rows
    batch1 = pipe.get_batch(rec1["batch_id"])
    t0 = batch1["rows"][0]
    t1 = batch1["rows"][1]
    pipe.save_decision(
        t0["transaction_id"],
        t0["revision"],
        item="식비",
        description="점심",
        display_tab_id="trip-seoul-2026",
        tab_validator=lambda t: True,
        request_id="dec-t0",
    )
    pipe.save_decision(
        t1["transaction_id"],
        t1["revision"],
        item="교통비",
        description="택시",
        display_tab_id="trip-seoul-2026",
        tab_validator=lambda t: True,
        request_id="dec-t1",
    )

    # Re-upload the exact same file
    rec2 = pipe.receive(content, "card.xlsx")
    assert rec2["reused"] is True
    summary2 = summarize(pipe, rec2, parsed, TRIPS, inspection=inspection)

    # Verify counts over all 100 source rows.
    assert summary2["counts"]["T"] == 100
    assert summary2["counts"]["E"] == 100
    assert summary2["counts"]["N"] == 0
    assert summary2["counts"]["C"] == 2
    assert summary2["counts"]["U"] == 98
    assert summary2["counts"]["H"] == 0
    assert summary2["counts"]["P"] == 0
    assert summary2["duplicate_rows"] == 0

    # Verify manual decisions preserved
    batch2 = pipe.get_batch(rec2["batch_id"])
    t0_rechecked = next(r for r in batch2["rows"] if r["transaction_id"] == t0["transaction_id"])
    assert t0_rechecked["item"] == "식비"
    assert t0_rechecked["display_tab_id"] == "trip-seoul-2026"
    assert t0_rechecked["description"] == "점심"


def test_partial_overlap_upload(pipe):
    """Spec Gate 2: Existing 70 + new 30 -> N=30, E=70, T=100."""
    # First batch: 7 items
    first_rows = [
        domestic_row(merchant=f"기존가맹점_{i}", amount=10000 + i, approval=f"1000{i:04d}")
        for i in range(70)
    ]
    content1 = make_xlsx(first_rows)
    pipe.receive(content1, "file1.xlsx")

    # Second batch: 7 existing items + 3 new items = 10 items
    second_rows = list(first_rows) + [
        domestic_row(merchant=f"신규가맹점_{i}", amount=20000 + i, approval=f"2000{i:04d}")
        for i in range(30)
    ]
    content2 = make_xlsx(second_rows)
    parsed2, inspection2 = validate_upload(content2, "file2.xlsx")
    rec2 = pipe.receive(content2, "file2.xlsx")

    summary = summarize(pipe, rec2, parsed2, TRIPS, inspection=inspection2)
    assert summary["counts"]["T"] == 100
    assert summary["counts"]["E"] == 70
    assert summary["counts"]["N"] == 30
    assert summary["counts"]["E"] + summary["counts"]["N"] == summary["counts"]["C"] + summary["counts"]["U"]


def test_file_internal_duplicates(pipe):
    """Spec Gate 3: File with duplicate lines counted in T, duplicate_rows, but no duplicate storage."""
    row = domestic_row(merchant="중복식당", amount=15000, approval="88880001")
    content = make_xlsx([row, row])
    parsed, inspection = validate_upload(content, "dup.xlsx")
    rec = pipe.receive(content, "dup.xlsx")

    summary = summarize(pipe, rec, parsed, TRIPS, inspection=inspection)
    assert summary["counts"]["T"] == 2
    assert summary["counts"]["N"] == 1
    assert summary["counts"]["E"] == 1
    assert summary["duplicate_rows"] == 1


@pytest.mark.parametrize('changed', [
    {'issuer': '다른합성카드'}, {'card_tail': '5678'},
    {'card_kind': '체크'}, {'approval_date': '2026-04-10'},
    {'foreign_currency': 'USD'},
])
def test_duplicate_fallback_never_crosses_identity_scope(pipe, changed):
    from copy import deepcopy
    from dataclasses import replace
    content = make_xlsx([domestic_row(merchant='합성', amount=1000, approval='12345678')])
    parsed, _ = validate_upload(content, 'scope.xlsx')
    received = pipe.receive(content, 'scope.xlsx')
    parsed = deepcopy(parsed)
    assert parsed.rows[0].approval_number
    # A source occurrence without a batch position may only reuse the same identity.
    other = replace(parsed.rows[0], row_index=999, **changed)
    parsed.rows.append(other)
    summary = summarize(pipe, received, parsed, TRIPS)
    assert summary['counts']['H'] == 1
    assert summary['counts']['N'] == 1
    assert summary['duplicate_rows'] == 0


def test_invalid_dates_and_unresolved_rows_are_not_duplicates(pipe):
    from copy import deepcopy
    from dataclasses import replace
    content = make_xlsx([domestic_row(merchant='합성', amount=1000, approval='DATE')])
    parsed, _ = validate_upload(content, 'dates.xlsx')
    received = pipe.receive(content, 'dates.xlsx')
    parsed = deepcopy(parsed)
    parsed.rows = [replace(parsed.rows[0], row_index=998, approval_date='2026-99-99'),
                   replace(parsed.rows[0], row_index=999, approval_date='invalid')]
    summary = summarize(pipe, received, parsed, TRIPS)
    assert summary['counts']['P'] == 2
    assert summary['duplicate_rows'] == 0
    assert summary['status'] == 'incomplete'
    assert summary['unknown_date_reconciliation'][0]['T'] == 2


def test_unlinked_cancellation_financial_reconciliation(pipe):
    """Spec Gate 5: Cancellation without original purchase warns financial reconciliation."""
    row = domestic_row(merchant="취소매장", amount=-30000, approval="CANCEL_999", kind="취소")
    content = make_xlsx([row])
    parsed, inspection = validate_upload(content, "cancel.xlsx")
    rec = pipe.receive(content, "cancel.xlsx")

    # Manually classify so it completes classification
    tid = pipe.get_batch(rec["batch_id"])["rows"][0]["transaction_id"]
    pipe.save_decision(
        tid,
        1,
        item="취소·환불",
        description="환불건",
        display_tab_id="trip-seoul-2026",
        tab_validator=lambda t: True,
        request_id="dec-cancel",
    )

    summary = summarize(pipe, rec, parsed, TRIPS, inspection=inspection)
    assert summary["counts"]["C"] == 1
    assert summary["counts"]["U"] == 0
    assert summary["counts"]["R"] == 1
    assert "취소 원결제 미연결 또는 검증 미완료 1건" in summary["financial_warning"]
    assert summary["financial_complete"] is False
    assert summary["status"] == "passed"


def test_multi_month_and_unknown_date_breakdown(pipe):
    """Spec Gate 6: Multiple months and unparseable dates aggregate correctly."""
    r_apr = domestic_row(merchant="4월식당", amount=10000, approval="A001", date="2026-04-10")
    r_may = domestic_row(merchant="5월식당", amount=20000, approval="M001", date="2026-05-02")
    content = make_xlsx([r_apr, r_may])
    parsed, inspection = validate_upload(content, "dates.xlsx")
    rec = pipe.receive(content, "dates.xlsx")

    summary = summarize(pipe, rec, parsed, TRIPS, inspection=inspection)
    assert summary["counts"]["T"] == 2
    months = {m["month"]: m for m in summary["monthly_reconciliation"]}
    assert "2026-04" in months
    assert "2026-05" in months
    assert months["2026-04"]["T"] == 1
    assert months["2026-05"]["T"] == 1


def test_upload_confirmed_decision_audit_idempotent(pipe):
    """High-confidence auto decisions are logged once; re-upload does not duplicate audit."""
    row = domestic_row(merchant="고신뢰식당", amount=15000, approval="AUTO_999", date="2026-04-10")
    content = make_xlsx([row])
    parsed, inspection = validate_upload(content, "auto.xlsx")
    rec1 = pipe.receive(content, "auto.xlsx")

    # Simulate high confidence auto classification
    tid = pipe.get_batch(rec1["batch_id"])["rows"][0]["transaction_id"]
    pipe.store.conn.execute(
        "UPDATE transactions SET classification_state='classified', classification_source='AUTO_INFERRED', "
        "classification_basis='AUTO_INFERRED · high confidence', item='식비', trip_id='trip-seoul-2026', "
        "display_tab_id='trip-seoul-2026' WHERE transaction_id=?",
        (tid,)
    )

    summary1 = summarize(pipe, rec1, parsed, TRIPS, inspection=inspection)
    assert summary1["counts"]["C"] == 1

    # Check change_log has classification.upload_confirmed
    changes1 = pipe.store.changes(tid)
    confirmed1 = [c for c in changes1 if c["kind"] == "classification.upload_confirmed"]
    assert len(confirmed1) == 1

    # Re-upload same file
    rec2 = pipe.receive(content, "auto.xlsx")
    summary2 = summarize(pipe, rec2, parsed, TRIPS, inspection=inspection)
    assert summary2["counts"]["C"] == 1

    # Check change_log was NOT duplicated
    changes2 = pipe.store.changes(tid)
    confirmed2 = [c for c in changes2 if c["kind"] == "classification.upload_confirmed"]
    assert len(confirmed2) == 1


def test_api_imports_dispatch_success_and_csrf(monkeypatch, tmp_path):
    """Web endpoint /api/imports requires CSRF and returns upload_summary."""
    from urllib.parse import urlparse
    from webapp import card_flow, ledger_board
    from webapp.ledger_store import LedgerStore

    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "1")
    board = LedgerStore(tmp_path / "board.sqlite", seed_demo=False)
    ledger_board.bind_store(board)
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")

    class MockHandler:
        def __init__(self, token="valid-csrf", filename="test.xlsx"):
            self.headers = {"X-CSRF-Token": token, "X-Filename": filename}
            self.response = None
        def _send_json(self, data, status=200):
            self.response = (data, status)

    content = make_xlsx([domestic_row(merchant="웹테스트식당", amount=12000, approval="WEB_1001")])
    route = urlparse("/api/imports")

    # 1. CSRF required
    bad_handler = MockHandler(token="wrong-token")
    assert card_flow.dispatch(bad_handler, route, raw=content, csrf="valid-csrf")
    assert bad_handler.response[1] == 403
    assert bad_handler.response[0]["code"] == "CSRF_REQUIRED"

    # 2. Valid upload returns 200 with upload_summary
    good_handler = MockHandler(token="valid-csrf")
    assert card_flow.dispatch(good_handler, route, raw=content, csrf="valid-csrf")
    data, status = good_handler.response
    assert status == 200
    assert "upload_summary" in data
    summary = data["upload_summary"]
    assert summary["counts"]["T"] == 1
    assert summary["counts"]["N"] == 1
    assert "monthly_reconciliation" in summary
    assert "failures" in summary
    board.close()
