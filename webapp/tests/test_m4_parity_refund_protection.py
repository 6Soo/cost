"""M4 검수 2차 — SPEC §11.2.1 수락 '회계 예외'의 공통 조회 패리티 회귀 (테스트 전용 소유).

1차 기준선(test_ledger_parity_spec_11_2_1.py, aab754d1)이 전액·단일 부분환불·
수동 교정·Google 수입 미연결/미검증을 커버한다. 이 파일은 그 기준선이 비워 둔
회계 예외를 같은 합성 저장소·같은 자료 시점에서 레거시 `/board?...&legacy=1`
조회와 React `/api/plush/ledger` 조회로 대조해 보강한다.

보강 대상(명세 근거):
- 여러 건의 부분환불: RFND-021 — 원결제 여행에 원결제·각 취소의 부호와 순비용 보존.
- 초과환불 보호: RFND-018 — 누적 환불이 원결제보다 크면 정상 환불 짝으로 기록·상계하지
  않는다. 순액 0이 아니므로 환불 탭 귀속(일반 지출 제외) 대상이 아니다.
- 중복 보호: RFND-061 — duplicate_of 표시 취소는 자동 연결하지 않고 원행을 보존한다.
- 원본 충돌 보호: RFND-006·034 — conflict_reason 원결제/취소는 자동 연결하지 않는다.
- 중복 원결제 경합: RFND-009·025 — 같은 승인번호 원결제가 둘이면 유일성이 깨져 연결하지 않는다.
- 분할 배분·잔여 행: §11.2.1 수락 회계 예외 — 원행은 활성 배분과 0이 아닌 잔여로 대체되고
  화면 행 금액은 배분액이지 원금 합계가 아니다(13.1). 두 조회 경로가 같은 배분·잔여를 본다.

환불 탭 귀속 제외(refund_tab._member_ids)는 비추론·전 구성원 기록·순액 0·동일 탭
그룹만 일반 지출에서 제외한다. 따라서 부분(순>0)·초과(순<0)·중복/충돌(미연결)은
여행에 그대로 남아야 하고, 두 경로가 같은 행·부호·합계를 보여야 한다.

이 파일은 테스트만 소유하며 구현·형제 테스트를 바꾸지 않는다. 현재 코드에서 실패하는
검사는 명세 기대값을 그대로 assert해 차이를 재현·기록한다(기대 완화 금지). 합성 자료만
사용하며 운영 원본·운영 접속·쓰기는 일절 하지 않는다.
"""
from __future__ import annotations

import pytest

from app.partial_refund import all_refund_links
from webapp import refund_tab
from webapp.tests.test_cards_all import CARD_SCHEMA
from webapp.tests.test_ledger_parity_spec_11_2_1 import (  # noqa: F401 - 공유 fixture/헬퍼
    _insert_card_row,
    _insert_transaction,
    _uid,
    bound_store,
    legacy_expense_map,
    legacy_income_map,
    legacy_owner,
    make_trip,
    react_all_pages,
    react_ledger,
)


def _seed_group(store, tab, purchase_amount, cancel_amounts, *, approval):
    """원결제 1건 + 취소 N건 카드 거래와 연결 장부 행을 합성한다(환불 분석 대상)."""
    store.conn.executescript(CARD_SCHEMA)
    _insert_transaction(store, "TX-P", tab, purchase_amount,
                        direction="purchase", approval=approval)
    _insert_card_row(store, "card-TX-P", tab, purchase_amount, source_event_id="TX-P")
    cancel_rows = []
    for index, amount in enumerate(cancel_amounts, start=1):
        tid = f"TX-C{index}"
        _insert_transaction(store, tid, tab, amount, direction="cancellation",
                            approval=f"{approval}-C{index}", original_approval=approval)
        rid = f"card-{tid}"
        _insert_card_row(store, rid, tab, amount, source_event_id=tid)
        cancel_rows.append(rid)
    return "card-TX-P", cancel_rows


def _assert_parity(store, tab, expected):
    """두 경로의 행 ID 집합·부호 있는 금액이 같고 기대 집합과 일치한다."""
    legacy = legacy_expense_map(tab)
    react_rows, _count, filtered_total, trip = react_all_pages(store, tab, kind="expense")
    assert set(legacy) == set(react_rows) == set(expected), (legacy, react_rows, expected)
    assert {rid: str(amount) for rid, amount in legacy.items()} == react_rows
    return legacy, filtered_total, trip


# ---------------------------------------------------------------------------
# 여러 건의 부분환불 (RFND-021)
# ---------------------------------------------------------------------------

def test_multiple_partial_refunds_preserve_each_sign_and_net(bound_store, legacy_owner):
    """원결제 100,000에 취소 -30,000·-20,000: 순 50,000을 여행 비용으로 보존한다.

    각 취소는 같은 원결제에 연결된 부분환불이고(refund_count 2), 순액이 0이 아니므로
    환불 탭 귀속(일반 지출 제외) 대상이 아니다. 두 경로 모두 세 행의 부호를 그대로 본다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_ids = _seed_group(store, tab, 100000, [-30000, -20000],
                                          approval="SYNMULTI")
    links = all_refund_links(store.conn)
    for tid in ("TX-C1", "TX-C2"):
        assert links[tid]["status"] == "partial", links[tid]
        assert links[tid]["net_krw"] == 50000
        assert links[tid]["refunds_total_krw"] == -50000
        assert links[tid]["refund_count"] == 2
    members = refund_tab.member_ids(store)
    assert not ({"TX-P", "TX-C1", "TX-C2"} & members), f"부분환불이 잘못 제외됨: {members}"

    expected = {purchase_id: 100000, cancel_ids[0]: -30000, cancel_ids[1]: -20000}
    _legacy, filtered_total, trip = _assert_parity(store, tab, expected)
    assert filtered_total == str(50000)
    assert trip["expense"] == str(50000)


# ---------------------------------------------------------------------------
# 초과환불 보호 (RFND-018)
# ---------------------------------------------------------------------------

def test_over_refund_is_not_netted_or_excluded_from_trip(bound_store, legacy_owner):
    """원결제 100,000에 취소 -150,000: 순 -50,000 'excess'는 정상 짝으로 상계·제외하지 않는다.

    초과환불은 기록이 차단되고(RFND-018) 순액 0이 아니므로 환불 탭 귀속 대상이 아니다.
    원결제·취소 각 부호가 여행에 그대로 남아 두 경로에서 같은 행·합계를 본다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_ids = _seed_group(store, tab, 100000, [-150000],
                                          approval="SYNOVER")
    links = all_refund_links(store.conn)
    assert links["TX-C1"]["status"] == "excess", links["TX-C1"]
    assert links["TX-C1"]["net_krw"] == -50000
    members = refund_tab.member_ids(store)
    assert not ({"TX-P", "TX-C1"} & members), f"초과환불이 잘못 제외됨: {members}"

    expected = {purchase_id: 100000, cancel_ids[0]: -150000}
    _legacy, filtered_total, trip = _assert_parity(store, tab, expected)
    assert filtered_total == str(-50000)
    assert trip["expense"] == str(-50000)


# ---------------------------------------------------------------------------
# 중복 보호 (RFND-061)
# ---------------------------------------------------------------------------

def test_duplicate_cancellation_is_not_auto_linked(bound_store, legacy_owner):
    """duplicate_of 표시 취소는 자동 연결하지 않고 원행·부호를 보존한다.

    순액이 우연히 0이어도 중복 취소는 확인된 환불 짝이 아니므로 일반 지출에서
    제외하지 않는다. 두 경로가 같은 두 행을 본다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_ids = _seed_group(store, tab, 100000, [-100000],
                                          approval="SYNDUP")
    store.conn.execute("UPDATE transactions SET duplicate_of='TX-OTHER' "
                       "WHERE transaction_id='TX-C1'")
    store.conn.commit()
    links = all_refund_links(store.conn)
    assert "TX-C1" not in links, f"중복 취소가 자동 연결됨: {links}"
    members = refund_tab.member_ids(store)
    assert not ({"TX-P", "TX-C1"} & members), f"중복 취소가 잘못 제외됨: {members}"

    expected = {purchase_id: 100000, cancel_ids[0]: -100000}
    _assert_parity(store, tab, expected)


# ---------------------------------------------------------------------------
# 원본 충돌 보호 (RFND-006·034)
# ---------------------------------------------------------------------------

def test_original_conflict_is_not_auto_linked(bound_store, legacy_owner):
    """conflict_reason 원결제는 자동 연결하지 않고 원행·부호를 보존한다."""
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_ids = _seed_group(store, tab, 100000, [-100000],
                                          approval="SYNCONF")
    store.conn.execute("UPDATE transactions SET conflict_reason='amount conflict' "
                       "WHERE transaction_id='TX-P'")
    store.conn.commit()
    links = all_refund_links(store.conn)
    assert "TX-C1" not in links, f"원본 충돌이 자동 연결됨: {links}"
    members = refund_tab.member_ids(store)
    assert not ({"TX-P", "TX-C1"} & members), f"원본 충돌이 잘못 제외됨: {members}"

    expected = {purchase_id: 100000, cancel_ids[0]: -100000}
    _assert_parity(store, tab, expected)


# ---------------------------------------------------------------------------
# 중복 원결제 경합 (RFND-009·025)
# ---------------------------------------------------------------------------

def test_duplicate_originals_prevent_pairing(bound_store, legacy_owner):
    """같은 승인번호 원결제가 둘이면 유일성이 깨져 취소를 연결하지 않는다.

    세 원행(원결제 2·취소 1) 모두 부호를 보존하고 두 경로에서 같은 행을 본다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    store.conn.executescript(CARD_SCHEMA)
    for tid in ("TX-P1", "TX-P2"):
        _insert_transaction(store, tid, tab, 100000, direction="purchase",
                            approval="SYNAMB")
        _insert_card_row(store, f"card-{tid}", tab, 100000, source_event_id=tid)
    _insert_transaction(store, "TX-C1", tab, -100000, direction="cancellation",
                        approval="SYNAMB-C", original_approval="SYNAMB")
    _insert_card_row(store, "card-TX-C1", tab, -100000, source_event_id="TX-C1")

    links = all_refund_links(store.conn)
    assert "TX-C1" not in links, f"중복 원결제 경합이 자동 연결됨: {links}"
    members = refund_tab.member_ids(store)
    assert not ({"TX-P1", "TX-P2", "TX-C1"} & members), f"경합 묶음이 잘못 제외됨: {members}"

    expected = {"card-TX-P1": 100000, "card-TX-P2": 100000, "card-TX-C1": -100000}
    _legacy, filtered_total, _trip = _assert_parity(store, tab, expected)
    assert filtered_total == str(100000)


# ---------------------------------------------------------------------------
# 분할 배분·잔여 행 (§11.2.1 수락 회계 예외, 13.1)
# ---------------------------------------------------------------------------

def test_split_allocation_and_remainder_parity(bound_store, legacy_owner):
    """원금 500,000을 300,000·150,000으로 배분하면 잔여 50,000이 남는다.

    대상 탭 화면 행은 배분액(300,000)이지 원금(500,000)이 아니고, 원행은 숨겨진다.
    잔여는 미분류에 남는다. 두 조회 경로가 같은 배분·잔여 행을 본다.
    """
    store, _access = bound_store
    tab_a = make_trip(store)
    tab_b = make_trip(store)
    created = store.create_direct_income(
        fields={"display_tab_id": None, "occurred_on": "2026-11-12",
                "amount_krw": 500000, "income_kind": "deposit",
                "customer_id": None, "customer_name": "합성 P1",
                "nickname": "", "memo": ""},
        client_request_id=f"parity-split-src-{_uid()}")
    source_id = created["row_id"]
    result = store.save_allocations(
        source_row_id=source_id, expected_source_revision=1,
        allocations=[
            {"customer_name": "합성 U1", "display_tab_id": tab_a,
             "income_kind": "deposit", "amount_krw": 300000},
            {"customer_name": "합성 U2", "display_tab_id": tab_b,
             "income_kind": "balance", "amount_krw": 150000},
        ],
        client_request_id=f"parity-split-plan-{_uid()}")
    assert result["remainder"] == 50000
    assert store.split_remainder(source_id) == 50000

    # 대상 탭: 배분액만 보이고 원금·원행은 숨겨진다(두 경로 일치).
    legacy_a = legacy_income_map(tab_a)
    status, react_a = react_ledger(store, tab_a, kind="income", page_size=200)
    assert status == 200, react_a
    react_a_map = {r["id"]: r["amount"] for r in react_a["rows"]}
    assert {rid: str(amount) for rid, amount in legacy_a.items()} == react_a_map
    assert source_id not in legacy_a and source_id not in react_a_map
    assert "300000" in react_a_map.values()
    assert "500000" not in react_a_map.values()

    # 잔여: 미분류에 50,000이 남고 원행은 숨겨진다(두 경로 일치).
    legacy_u = legacy_income_map("unclassified")
    status, react_u = react_ledger(store, "unclassified", kind="income", page_size=200)
    assert status == 200, react_u
    react_u_map = {r["id"]: r["amount"] for r in react_u["rows"]}
    assert {rid: str(amount) for rid, amount in legacy_u.items()} == react_u_map
    assert source_id not in legacy_u and source_id not in react_u_map
    assert "50000" in react_u_map.values()
