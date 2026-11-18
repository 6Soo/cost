"""M4 검수 2차 — RFND-070 Google 복사 산출물·이용기간/대사 상태 공통 조회 회귀 (테스트 전용 소유).

1차 기준선(aab754d1)·2차 환불 보호(test_m4_parity_refund_protection.py, 388c70de)가
비워 둔 두 영역을 보강한다.

1) RFND-070 Google 복사(붙여넣기) 행 범위·산출물 같음 (§11.2.1 조회 계약 3):
   - 환불 탭에 있는 행도 원결제 위치를 확인할 수 있으면 원결제 여행 TSV에 **별도 행**으로
     포함하고 **원래 부호**를 보존한다. 환불액을 원결제에 합산하거나 원행을 상계하지 않는다.
   - 같은 대상·필터·산출물 종류라면 진입 경로(프레젠테이션 순서)가 달라도 산출물은 동일하다.
   - 화면 행 귀속은 ITEM-011에 따라 환불 탭에 남으므로 붙여넣기와 화면의 행 범위 차이는 정상이다.
   export_for_trip은 NEW_EXPENSE 행만 expense_tsv(layout='rev', 7열, 부호 정수 금액)로 출력한다.

2) 이용기간 출처·Google 대사 상태 (§11.2.1 조회 계약 1·4):
   - 공통 서버 조회는 행별 이용기간과 **출처(period_source)**, **Google 대사 상태(google_match)**를
     제공해야 한다. 저장된 기간은 확정 값으로 보존한다.
   - 현재 승인 배포본(origin/main)의 React 공통 조회 행에는 period_source·google_match가 없다
     (서버 공통 조회 c3b77206이 추가). 이 차이를 명세 기대값 그대로 assert해 재현·기록한다.

이 파일은 테스트만 소유하며 구현·형제 테스트를 바꾸지 않는다. 기대를 완화하지 않는다.
합성 자료만 사용하며 운영 원본·운영 접속·쓰기·Google 최종 장부 쓰기는 일절 하지 않는다.
"""
from __future__ import annotations

import json

from webapp import ledger_design
from webapp.sheet_expense_reconciliation import export_for_trip
from webapp.tests.test_ledger_parity_spec_11_2_1 import (  # noqa: F401 - 공유 fixture/헬퍼
    _uid,
    bound_store,
    legacy_owner,
    make_expense,
    make_trip,
    react_ledger,
)
from webapp.tests.test_sheet_expense_projection import (  # noqa: F401 - 공유 Google fixture
    TRIP_ID,
    Board,
    _cost,
    _engine,
    sources,
)


def _amount_cells(tsv: str) -> list[str]:
    """expense_tsv 7열의 마지막 열(부호 있는 금액 원문)을 행 순서대로 읽는다."""
    return [line.split("\t")[6] for line in tsv.splitlines() if line]


# ---------------------------------------------------------------------------
# RFND-070 Google 복사 행 범위·부호·산출물 같음
# ---------------------------------------------------------------------------

def test_rfnd070_copy_includes_refund_row_with_original_sign(sources, monkeypatch):
    """원결제 +300,000과 환불 -100,000은 원결제 여행 TSV에 별도 두 행으로 출력된다.

    환불액을 원결제에 합산(200,000 한 행)하거나 원행을 상계하지 않고, 각 원래 부호를
    보존한다(RFND-070). 복사 합계는 부호 있는 순액 200,000이다.
    """
    purchase = _cost("tx-purchase")
    purchase["amount_krw"] = 300000
    refund = _cost("tx-refund")
    refund["amount_krw"] = -100000
    refund["transaction_direction"] = "refund"
    _engine(monkeypatch, ["NEW_EXPENSE", "NEW_EXPENSE"])

    result = export_for_trip(Board(), [purchase, refund], TRIP_ID)
    assert result["source_available"] is True, result
    assert result["row_count"] == 2, f"환불 행이 별도 행으로 포함되지 않음: {result}"
    assert result["total_krw"] == 200000
    cells = _amount_cells(result["tsv"])
    assert sorted(cells) == sorted(["300000", "-100000"]), f"원래 부호 보존 실패: {cells}"
    # 원결제는 상계되지 않고 300,000 그대로 남아야 한다.
    assert "300000" in cells and "-100000" in cells


def test_rfnd070_copy_artifact_identical_across_entry_order(sources, monkeypatch):
    """같은 대상·필터·산출물 종류면 입력(진입) 순서가 달라도 복사 산출물이 동일하다.

    expense_tsv는 (거래일자, transaction_id)로 정렬하므로 프레젠테이션 순서에 의존하지 않는다.
    """
    purchase = _cost("tx-purchase")
    purchase["amount_krw"] = 300000
    refund = _cost("tx-refund")
    refund["amount_krw"] = -100000
    refund["transaction_direction"] = "refund"
    _engine(monkeypatch, ["NEW_EXPENSE", "NEW_EXPENSE"])

    forward = export_for_trip(Board(), [purchase, refund], TRIP_ID)
    reverse = export_for_trip(Board(), [refund, purchase], TRIP_ID)
    assert forward["source_available"] and reverse["source_available"]
    assert forward["tsv"] == reverse["tsv"], "진입 순서에 따라 산출물이 달라짐"
    assert forward["row_count"] == reverse["row_count"] == 2
    assert forward["total_krw"] == reverse["total_krw"] == 200000


# ---------------------------------------------------------------------------
# 이용기간 출처·Google 대사 상태 (조회 계약 1·4)
# ---------------------------------------------------------------------------

def _expense_with_period(store, tab, amount, period):
    """저장 이용기간(service_period)을 가진 합성 장부 행을 시드한다."""
    rid = f"parity-period-{_uid()}"
    record = {
        "amount_krw": amount, "occurred_on": "2026-11-12", "item": "숙박",
        "description": "합성 숙박", "source_kind": "카드", "source_event_id": "",
        "source_merchant": "합성가맹점", "operator_note": "", "pay_method": "카드",
        "evidence_type": "카드", "service_period": period,
    }
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        (rid, "expense", tab, 1, json.dumps(record, ensure_ascii=False)))
    store.conn.commit()
    return rid


def test_common_query_exposes_period_source_and_google_match(bound_store, legacy_owner):
    """§11.2.1 계약 1·4: 공통 조회 행은 이용기간 출처와 Google 대사 상태를 제공해야 한다.

    현재 React 공통 조회 행에는 period_source·google_match가 없다(서버 공통 조회
    c3b77206이 추가하는 필드). 명세 기대값 그대로 assert해 차이를 재현한다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    make_expense(store, tab, 12000)
    status, body = react_ledger(store, tab, kind="expense")
    assert status == 200, body
    row = body["rows"][0]
    assert "period_source" in row, f"이용기간 출처(period_source) 미제공: {row}"
    assert "google_match" in row, f"Google 대사 상태(google_match) 미제공: {row}"


def test_stored_service_period_preserved_in_common_query(bound_store, legacy_owner):
    """§11.2.1 계약 4: 저장된 이용기간은 확정 값으로 두 경로에서 그대로 보존된다."""
    store, _access = bound_store
    tab = make_trip(store)
    period = "2026-11-10~2026-11-12"
    rid = _expense_with_period(store, tab, 50000, period)

    _incomes, expenses, _whole_in, _whole_ex = ledger_design._selected_rows(tab, "", "")
    legacy_row = next(r for r in expenses if r["row_id"] == rid)
    status, body = react_ledger(store, tab, kind="expense")
    assert status == 200, body
    react_row = next(r for r in body["rows"] if r["id"] == rid)
    assert legacy_row.get("service_period") == period
    assert react_row["period"] == period, f"저장 이용기간 확정 값이 보존되지 않음: {react_row}"
