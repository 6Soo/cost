"""M4 검수 2차 — 환불 귀속 제외의 합계 범위와 분기 기타비용 탭 행 대조 (테스트 전용 소유).

1차 기준선(test_ledger_parity_spec_11_2_1.py)과 2차 환불 보호
(test_m4_parity_refund_protection.py)가 고정한 "행 ID 집합·부호 있는 금액" 대조에
이어, 같은 계약(SPEC §11.2.1 계약 1·2·3)의 **합계 집합**을 고정한다.

고정 대상은 두 가지다.

1) 환불 귀속 제외(refund_tab.member_ids, RFND-022·ITEM-011)는 **지출 행**에만 적용된다.
   레거시 `_selected_rows`는 지출 목록에만 그 조건을 걸고 수입 목록은 그대로 둔다.
   React 공통 조회가 모든 행에 조건을 걸면, 수입 행이 우연히 같은 source_event_id를
   가질 때 두 경로의 행 집합·합계가 갈린다. 두 경로 모두 수입 행을 보존해야 한다.
   금액·부호·환불 관계 판정 자체는 바꾸지 않는다.

2) 분기 기타비용 탭(`quarter:YYYY:Q`)의 확정 기록은 `board_rows`에 그 탭의
   display_tab_id로 저장된다. 레거시 `board._expense_rows`는 `trip_tabs`와 미분류만
   순회하므로 분기 탭 행을 읽지 못해 화면 합계 0원·0건을 그렸고, React 공통 조회는
   `list_tab_rows`로 그 행을 읽어 수치가 갈렸다. 이제 두 경로가 같은 탭 행을 읽어
   건수와 합계가 같아야 한다. 저장 행·금액·부호는 그대로다.

이 파일은 테스트만 소유하며 구현·형제 테스트를 바꾸지 않는다. 기대를 완화하지 않는다.
합성 자료만 사용하며 운영 원본·운영 접속·쓰기는 일절 하지 않는다.
"""
from __future__ import annotations

import json

from webapp import ledger_board, ledger_design, refund_tab
from webapp.tests.test_cards_all import CARD_SCHEMA
from webapp.tests.test_ledger_parity_spec_11_2_1 import (  # noqa: F401 - 공유 fixture/헬퍼
    _insert_card_row,
    _insert_transaction,
    bound_store,
    grant_viewer_tabs,
    legacy_expense_map,
    legacy_income_map,
    legacy_owner,
    make_expense,
    make_trip,
    react_all_pages,
    react_ledger,
)


def _seed_refund_pair(store, tab, purchase_amount, cancel_amount, *, prefix, approval,
                      record_tab=None):
    """원결제 1건 + 취소 1건 카드 거래와 그 연결 장부 행을 합성한다."""
    store.conn.executescript(CARD_SCHEMA)
    purchase_id, cancel_id = f"{prefix}P", f"{prefix}C"
    _insert_transaction(store, purchase_id, tab, purchase_amount,
                        direction="purchase", approval=approval)
    _insert_transaction(store, cancel_id, tab, cancel_amount,
                        direction="cancellation", approval=f"{approval}-C",
                        original_approval=approval)
    target = tab if record_tab is None else record_tab
    _insert_card_row(store, f"card-{purchase_id}", target, purchase_amount,
                     source_event_id=purchase_id)
    _insert_card_row(store, f"card-{cancel_id}", target, cancel_amount,
                     source_event_id=cancel_id)
    return f"card-{purchase_id}", f"card-{cancel_id}"


# ---------------------------------------------------------------------------
# 1) 환불 귀속 제외는 지출 행에만 적용된다 (수입 행 보존)
# ---------------------------------------------------------------------------

def test_income_row_that_shares_a_refund_member_key_is_kept_on_both_paths(bound_store, legacy_owner):
    """수입 행의 source_event_id가 환불 묶음 구성원과 같아도 두 경로가 그 행을 보존한다.

    환불 관계는 카드 지출 사실이므로 레거시는 지출 목록에만 그 조건을 건다. React가
    수입 행까지 걸러 내면 같은 스냅샷에서 수입 행 하나와 그 금액이 사라지고, 여행 요약의
    수입·차액도 갈린다(RFND-022·ITEM-011은 지출 중복 노출을 막는 규칙이다).
    """
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_id = _seed_refund_pair(store, tab, 150000, -150000,
                                               prefix="TX-", approval="SYNESCM")
    members = refund_tab.member_ids(store)
    assert {"TX-P", "TX-C"} <= members, f"환불 짝이 연결되지 않음: {members}"

    # 수입 행 하나가 구성원의 원천 키를 그대로 쓴다(합성; 실제로는 키 충돌).
    income = {
        "amount_krw": 777000, "occurred_on": "2026-11-12",
        "income_kind": "deposit", "customer_name": "합성고객",
        "description": "합성 수입", "source_kind": "카드",
        "source_event_id": "TX-P",
    }
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        ("inc-shared-key", "income", tab, 1, json.dumps(income, ensure_ascii=False)))
    store.conn.commit()

    legacy_in = legacy_income_map(tab)
    assert "inc-shared-key" in legacy_in, "레거시가 수입 행을 숨김"
    assert legacy_in["inc-shared-key"] == 777000

    react_rows, _count, _total, trip = react_all_pages(store, tab, kind="income")
    assert "inc-shared-key" in react_rows, (
        "환불 귀속 제외가 수입 행에 적용되어 React에서 사라짐")
    assert react_rows["inc-shared-key"] == str(legacy_in["inc-shared-key"]) == "777000"
    assert trip["income"] == "777000"

    # 같은 이유로 지출 쪽은 두 경로 모두 짝을 제외한다.
    assert purchase_id not in legacy_expense_map(tab)
    expense_rows, _c, filtered_total, _t = react_all_pages(store, tab, kind="expense")
    assert purchase_id not in expense_rows and cancel_id not in expense_rows
    assert filtered_total == "0"


def test_partial_refund_stays_on_the_trip_on_both_paths(bound_store, legacy_owner):
    """RFND-021: 잔액이 남는 부분환불은 지출·합계 모두 원결제 여행에 그대로 남는다."""
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_id = _seed_refund_pair(store, tab, 100000, -30000,
                                               prefix="TX-", approval="SYNPARTSCOPE")
    assert not ({"TX-P", "TX-C"} & refund_tab.member_ids(store))

    legacy = legacy_expense_map(tab)
    react_rows, _count, filtered_total, trip = react_all_pages(store, tab, kind="expense")
    assert {rid: str(amount) for rid, amount in legacy.items()} == react_rows
    assert filtered_total == "70000"
    assert trip["expense"] == "70000"


def test_viewer_keeps_the_net_zero_pair_on_both_paths(bound_store):
    """열람자는 환불 탭 귀속 제외를 받지 않는다: 짝의 각 부호와 순액이 두 경로에서 같다.

    RFND-022·ITEM-011의 제외는 소유자 귀속 판단이다. 열람자 조회는 같은 스냅샷에서
    짝을 숨기지 않아야 하며, 두 경로의 합계도 그래서 0원이 아니라 순액이다.
    """
    store, access = bound_store
    tab = make_trip(store)
    _seed_refund_pair(store, tab, 150000, -150000, prefix="TX-", approval="SYNVIEWER")
    make_expense(store, tab, 30000, desc="합성 식비")
    grant_viewer_tabs(access, "syn-viewer", [tab])

    ledger_board.current_role = lambda: "viewer"
    legacy = legacy_expense_map(tab)
    pair = {"card-TX-P": 150000, "card-TX-C": -150000}
    assert all(legacy.get(row_id) == amount for row_id, amount in pair.items()), (
        f"열람자 레거시가 짝을 숨김: {legacy}")
    assert sum(legacy.values()) == 30000

    react_rows, _count, filtered_total, trip = react_all_pages(
        store, tab, user="syn-viewer", kind="expense")
    assert {rid: str(amount) for rid, amount in legacy.items()} == react_rows
    assert filtered_total == "30000"
    assert trip["expense"] == "30000"


def test_quarter_tab_header_excludes_a_pair_key_it_shares_with_a_trip(bound_store, legacy_owner):
    """분기 탭 행이 여행 탭 순액 0 짝의 source_event_id를 공유해도 화면 전체가 같은 행 집합을 센다.

    ``_selected_rows``(실시간 요약)는 소유자에게 짝의 키를 가진 지출 행을 숨긴다.
    분기 헤더·본문이 그 배제를 적용하지 않으면 같은 화면에서 단계 표기는 2건·81,000원,
    바로 옆 실시간 요약은 1건·20,000원을 그린다(이 화면 안의 모순). React 공통 조회는
    배제를 적용해 1건·20,000원을 준다. 세 곳이 같은 행 집합·합계를 세야 한다.
    """
    store, _access = bound_store
    trip = make_trip(store)
    _seed_refund_pair(store, trip, 50000, -50000, prefix="TR-", approval="SYNSHARED")
    quarter = "quarter:2026:3"
    # 분기 탭 지출 행 하나가 짝 구성원의 원천 키를 그대로 쓴다(합성; 실제로는 키 충돌).
    _insert_card_row(store, "card-Q-shared", quarter, 61000, source_event_id="TR-P")
    _insert_card_row(store, "card-Q-clean", quarter, 20000, source_event_id="QONLY")
    assert {"TR-P", "TR-C"} <= refund_tab.member_ids(store), "환불 짝이 연결되지 않음"

    kept = {"card-Q-clean": 20000}
    _in, selected, _whole_in, whole_ex = ledger_design._selected_rows(quarter)
    assert {r["row_id"]: ledger_board._shown_amount(r) for r in selected} == kept
    assert {r["row_id"]: ledger_board._shown_amount(r) for r in whole_ex} == kept

    html = ledger_design._quarter_page(quarter, "2026년 3분기 기타비용")
    assert "거래 1건 · 20,000원" in html, "분기 헤더가 실시간 요약과 다른 행 집합을 셈"
    assert "81,000원" not in html
    summary = ledger_design.summary_part(quarter)
    assert "지출 1건" in summary and "20,000원" in summary

    status, body = react_ledger(store, quarter, kind="expense", page_size=200)
    assert status == 200, body
    assert {r["id"]: int(r["amount"]) for r in body["rows"]} == kept
    assert int(body["filtered_total"]) == 20000
    assert body["trip"]["expense"] == "20000"


# ---------------------------------------------------------------------------
# 2) 분기 기타비용 탭: 레거시 화면과 공통 조회가 같은 탭 행·건수·합계를 본다
# ---------------------------------------------------------------------------

def test_quarter_tab_booked_rows_and_total_match_the_common_query(bound_store, legacy_owner):
    """분기 기타비용 탭에 저장된 확정 기록을 두 경로가 같은 건수·합계로 본다.

    레거시는 `board._expense_rows`(여행 탭·미분류만 순회)로 그 탭 행을 읽지 못해
    0원·0건을 그렸고, React는 `list_tab_rows`로 그 행을 읽었다. 이제 레거시 분기
    화면·실시간 요약도 같은 탭 행을 읽어 두 경로의 건수와 합계가 같아야 한다.
    저장된 행·금액·부호는 바꾸지 않는다.
    """
    store, _access = bound_store
    quarter = "quarter:2026:3"
    rows = [("card-Q1", 40000), ("card-Q2", 60000)]
    for row_id, amount in rows:
        _insert_card_row(store, row_id, quarter, amount, source_event_id=row_id)

    ledger_rows = {r["row_id"]: ledger_board._shown_amount(r)
                   for r in ledger_design._selected_rows(quarter)[1]}
    assert ledger_rows == dict(rows), f"레거시 분기 탭이 자기 탭 행을 읽지 않음: {ledger_rows}"

    status, body = react_ledger(store, quarter, kind="expense", page_size=200)
    assert status == 200
    react_rows = {r["id"]: int(r["amount"]) for r in body["rows"]}
    assert ledger_rows == react_rows, "분기 탭 행 집합이 두 경로에서 다름"
    assert body["total_count"] == len(rows)
    assert int(body["filtered_total"]) == sum(amount for _id, amount in rows) == 100000
    assert body["trip"]["expense"] == "100000"

    # 분기 화면의 단계 표기와 건수·합계도 같은 탭 행을 센다.
    html = ledger_design._quarter_page(quarter, "2026년 3분기 기타비용")
    assert "거래 2건 · 100,000원" in html
    # 실시간 요약(라이브 새로고침이 다시 그리는 블록)도 같은 값을 그린다.
    summary = ledger_design.summary_part(quarter)
    assert "100,000원" in summary and "지출 2건" in summary


def test_quarter_tab_keeps_signs_so_partial_pairs_net_on_both_paths(bound_store, legacy_owner):
    """분기 탭에 남는 부분환불·취소 행의 각 부호를 두 경로가 그대로 보존한다(RFND-021)."""
    store, _access = bound_store
    quarter = "quarter:2026:3"
    _insert_card_row(store, "card-QP", quarter, 100000, source_event_id="QP")
    _insert_card_row(store, "card-QC", quarter, -30000, source_event_id="QC")

    legacy_rows = {r["row_id"]: ledger_board._shown_amount(r)
                   for r in ledger_design._selected_rows(quarter)[1]}
    status, body = react_ledger(store, quarter, page_size=200)
    assert status == 200
    react_rows = {r["id"]: int(r["amount"]) for r in body["rows"]}
    assert legacy_rows == react_rows == {"card-QP": 100000, "card-QC": -30000}
    assert int(body["filtered_total"]) == 70000


def test_quarter_tab_income_row_is_read_by_both_paths(bound_store, legacy_owner):
    """분기 탭에 저장된 수입 행도 두 경로가 같은 행·금액으로 본다.

    분기 탭은 지출 기록용이지만 store는 그 탭의 수입 행도 `board_rows`에 저장할
    수 있다. 레거시가 지출만 읽으면 그 행과 수입 합계가 React에서만 보인다.
    """
    store, _access = bound_store
    quarter = "quarter:2026:3"
    _insert_card_row(store, "card-QE", quarter, 40000, source_event_id="QE")
    income = {
        "amount_krw": 50000, "occurred_on": "2026-11-12",
        "income_kind": "deposit", "customer_name": "합성고객",
        "description": "합성 수입", "source_kind": "직접 입력",
        "source_event_id": "QI",
    }
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        ("inc-quarter", "income", quarter, 1, json.dumps(income, ensure_ascii=False)))
    store.conn.commit()

    legacy_income = {r["row_id"]: ledger_board._shown_amount(r)
                     for r in ledger_design._selected_rows(quarter)[0]}
    assert legacy_income == {"inc-quarter": 50000}, (
        f"레거시 분기 탭이 자기 수입 행을 읽지 않음: {legacy_income}")

    status, body = react_ledger(store, quarter, kind="income", page_size=200)
    assert status == 200
    react_rows = {r["id"]: int(r["amount"]) for r in body["rows"]}
    assert react_rows == legacy_income
    assert int(body["filtered_total"]) == 50000
    assert body["trip"]["income"] == "50000"
