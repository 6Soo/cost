"""SPEC §11.2.1 '장부 조회 통합' 패리티 회귀 기준선 (테스트 전용 소유).

승인 배포본(origin/main 259bc187)을 기준으로, 같은 합성 저장소·같은 자료 시점·
권한·탭·필터에서 레거시 `/board?...&legacy=1` 조회 경로와 React
`/api/plush/ledger` 조회 경로가 동일한 거래와 합계를 보여야 한다.

수락 기준(거래·합계 대조): 두 경로의 행 ID 집합, 행별 부호 있는 금액,
전체·조회 건수와 합계, 여행 수입·지출·차액 차이가 모두 0이어야 하고 규칙집
기대값과도 일치해야 한다. 50건 초과 표본은 모든 페이지를 합쳐 대조한다.

이 파일은 테스트만 소유하며 구현 코드를 바꾸지 않는다. 현재 코드에서 실패하는
검사는 §11.2.1 조회 계약과 규칙집(RFND-021·022·023·070, ITEM-011) 기대값을
그대로 assert해 차이를 재현·기록한다. 기대를 완화하지 않는다. 합성 자료만
사용하며 운영 원본·운영 접속·쓰기는 일절 하지 않는다.

레거시 읽기는 실제 서버 읽기 함수(`ledger_design._selected_rows`,
`_trip_kpi_html`, `_quarter_page`, `refund_tab`)를 그대로 호출하고, React 읽기는
실제 `plush_api.dispatch`를 그대로 호출한다. 두 경로 모두 같은 바인딩 저장소를
읽으므로 입력 차이는 없다.
"""
from __future__ import annotations

import json
import re
import uuid
from urllib.parse import urlencode

import pytest

from webapp import (
    access_control,
    google_ledger_page as page,
    ledger_board,
    ledger_design,
    refund_tab,
)
from webapp.tests.test_cards_all import CARD_SCHEMA
from webapp.tests.test_plush_api import bound_store, call  # noqa: F401 - 공유 fixture/헬퍼
from webapp.tests.test_trip_google_income import income_context  # noqa: F401 - 공유 fixture


# ---------------------------------------------------------------------------
# 합성 자료 헬퍼 (모두 임시 저장소에 대한 쓰기; 운영 원본 아님)
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex


def make_trip(store, *, dest=None, starts="2026-11-10", ends="2026-11-20", kind="trip"):
    dest = dest or f"합성여행-{_uid()[:6]}"
    result = store.create_trip(
        starts_on=starts, ends_on=ends, destination=dest, tab_kind=kind,
        client_request_id=f"parity-trip-{_uid()}")
    return result["tab_id"]


def make_expense(store, tab, amount, *, item="식비", desc="합성 지출",
                 day="2026-11-12", memo=""):
    fields = {"display_tab_id": tab, "occurred_on": day, "amount_krw": amount,
              "item": item, "pay_method": "현금", "description": desc}
    if memo:
        fields["memo"] = memo
    result = store.create_manual_expense(
        fields=fields, client_request_id=f"parity-row-{_uid()}")
    return result["row_id"]


def _insert_card_row(store, row_id, tab, amount, *, source_event_id,
                     item="숙박", day="2026-11-12", merchant="합성가맹점"):
    """source_event_id가 카드 거래와 연결되는 합성 장부 행을 직접 시드한다."""
    record = {
        "amount_krw": amount, "occurred_on": day, "item": item,
        "description": f"합성 {item}", "source_kind": "카드",
        "source_event_id": source_event_id, "source_merchant": merchant,
        "operator_note": "", "pay_method": "카드", "evidence_type": "카드",
    }
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        (row_id, "expense", tab, 1, json.dumps(record, ensure_ascii=False)))
    store.conn.commit()


def _insert_transaction(store, tid, tab, amount, *, direction, approval,
                        original_approval="", day="2026-11-12", merchant="합성가맹점"):
    store.conn.execute(
        "INSERT INTO transactions VALUES (" + ",".join(["?"] * 33) + ")",
        (tid, f"hash-{tid}", "parity-batch", "CARD", "1234", "credit",
         direction, "card", approval, original_approval, day, day,
         merchant, merchant.lower(), amount, "", "", "", 1, "{}",
         None, "", "", "booked", "manual", "", "숙박", f"합성 {merchant}",
         tab, tab, 1, None, day))
    store.conn.commit()


def seed_refund_pair(store, tab, purchase_amount, cancel_amount, *, approval="SYNPAIR"):
    """원결제+취소 카드 거래와 그에 연결된 장부 행을 합성한다(환불 짝 분석 대상)."""
    store.conn.executescript(CARD_SCHEMA)
    _insert_transaction(store, "TX-P", tab, purchase_amount,
                        direction="purchase", approval=approval)
    _insert_transaction(store, "TX-C", tab, cancel_amount,
                        direction="cancellation", approval="SYNPAIR-C",
                        original_approval=approval)
    _insert_card_row(store, "card-TX-P", tab, purchase_amount, source_event_id="TX-P")
    _insert_card_row(store, "card-TX-C", tab, cancel_amount, source_event_id="TX-C")
    return "card-TX-P", "card-TX-C"


@pytest.fixture
def legacy_owner(monkeypatch):
    """요청 컨텍스트 밖에서 레거시 읽기가 소유자 범위로 동작하게 한다."""
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")


def legacy_expense_map(tab, q="", kind=""):
    _incomes, expenses, _whole_in, _whole_ex = ledger_design._selected_rows(tab, q, kind)
    return {r["row_id"]: ledger_board._shown_amount(r) for r in expenses}


def legacy_income_map(tab, q="", kind=""):
    incomes, _expenses, _whole_in, _whole_ex = ledger_design._selected_rows(tab, q, kind)
    return {r["row_id"]: ledger_board._shown_amount(r) for r in incomes}


def legacy_kpi(tab):
    """실제 렌더된 여행 요약 KPI에서 수입·지출·차액을 읽는다('—'는 미확인 None)."""
    html = ledger_design._trip_kpi_html(tab)
    out = {}
    for label in ("수입", "지출", "차액"):
        match = re.search(rf"<dt>{label}</dt><dd>(.*?)</dd>", html, re.S)
        assert match, f"KPI에서 {label} 값을 찾지 못함: {html}"
        text = match.group(1).strip()
        if text == "—":
            out[label] = None
        else:
            out[label] = int(text.replace("원", "").replace("−", "-").replace(",", "").strip())
    return out


def react_ledger(store, tab, *, user="syn-owner", **params):
    query = {"tab": tab, **params}
    status, body = call("/api/plush/ledger?" + urlencode(query), user, store)
    return status, body


def react_all_pages(store, tab, *, user="syn-owner", page_size=50, **params):
    """50건 기본 페이지를 모두 합쳐 행 ID·금액을 모은다(중복·누락 검사용)."""
    rows = {}
    page_no = 1
    total_count = None
    filtered_total = None
    trip = None
    while True:
        status, body = react_ledger(store, tab, user=user, page=page_no,
                                    page_size=page_size, **params)
        assert status == 200, body
        total_count = body["total_count"]
        filtered_total = body["filtered_total"]
        trip = body["trip"]
        for row in body["rows"]:
            assert row["id"] not in rows, f"페이지 사이 중복 행: {row['id']}"
            rows[row["id"]] = row["amount"]
        if page_no * page_size >= total_count or not body["rows"]:
            break
        page_no += 1
    return rows, total_count, filtered_total, trip


def grant_viewer_tabs(access, user, tabs):
    """실제 신청·승인·배정 경로를 그대로 거쳐 열람자에게 탭을 허가한다."""
    access.create_account(user_id=user, role=access_control.ROLE_VIEWER)
    person = f"parity-person-{_uid()[:8]}"
    access.register_reservation_person(
        reservation_person_id=person, display_name="합성 담당자")
    application = access.create_application(
        user_id=user, requested_name="합성 담당자",
        client_request_id=f"parity-app-{_uid()}")
    access.approve_application(
        application_id=application["application_id"], owner_id="syn-owner",
        expected_revision=application["revision"], reservation_person_id=person,
        client_request_id=f"parity-approval-{_uid()}")
    access.apply_assignment_snapshot(
        user_id=user,
        items=[{"tab_id": tab, "snapshot_revision": 1, "state": "active"} for tab in tabs],
        source_version=f"parity-{_uid()}", complete=True)


# ---------------------------------------------------------------------------
# 수락: 거래·합계 대조 — 일반 여행 기준선 (두 경로가 같은 행·금액·합계)
# ---------------------------------------------------------------------------

def test_general_trip_rows_amounts_and_totals_parity(bound_store, legacy_owner):
    """§11.2.1 계약 1·2: 같은 탭의 행 ID 집합·부호 있는 금액·합계가 두 경로에서 같다."""
    store, _access = bound_store
    tab = make_trip(store)
    ids = [
        make_expense(store, tab, 12000, desc="합성 식비", day="2026-11-12"),
        make_expense(store, tab, -1200, desc="합성 환불 음수", day="2026-11-13"),
        make_expense(store, tab, 9007199254740993, desc="합성 정밀 금액", day="2026-11-14"),
    ]
    legacy = legacy_expense_map(tab)
    react_rows, total_count, filtered_total, trip = react_all_pages(store, tab, kind="expense")

    assert set(legacy) == set(react_rows) == set(ids)
    assert {rid: str(amount) for rid, amount in legacy.items()} == react_rows
    assert total_count == 3
    expected_sum = str(12000 - 1200 + 9007199254740993)
    assert filtered_total == expected_sum
    assert trip["expense"] == expected_sum


def test_kind_filter_in_ex_maps_to_income_expense(bound_store, legacy_owner):
    """적용 순서 2: 기존 kind=in·kind=ex와 React income·expense는 같은 필터다."""
    store, _access = bound_store
    tab = "trip-demo-a"  # 데모 시드에 수입·지출이 모두 있는 탭
    legacy_ex = legacy_expense_map(tab, kind="ex")
    status, react_ex = react_ledger(store, tab, kind="expense", page_size=200)
    assert status == 200
    assert set(legacy_ex) == {r["id"] for r in react_ex["rows"]}

    legacy_in = legacy_income_map(tab, kind="in")
    status, react_in = react_ledger(store, tab, kind="income", page_size=200)
    assert status == 200
    assert set(legacy_in) == {r["id"] for r in react_in["rows"]}


def test_pagination_over_50_combines_all_pages_without_dup_or_miss(bound_store, legacy_owner):
    """수락: 50건 초과 표본은 모든 페이지를 합쳐 대조한다(중복·누락 0, 동률 ID 정렬)."""
    store, _access = bound_store
    tab = make_trip(store)
    ids = [make_expense(store, tab, 1000 + index, day="2026-11-12",
                        desc=f"합성 동률 {index:03d}") for index in range(60)]
    legacy = legacy_expense_map(tab)
    react_rows, total_count, filtered_total, _trip = react_all_pages(store, tab, kind="expense")

    assert total_count == 60
    assert set(react_rows) == set(legacy) == set(ids)
    assert len(react_rows) == 60  # 페이지 사이 중복·누락 없음
    assert filtered_total == str(sum(1000 + index for index in range(60)))
    # 동률(같은 날짜)에는 행 ID로 정렬해 페이지 경계가 안정적이어야 한다.
    status, first = react_ledger(store, tab, kind="expense", sort="date_desc", page_size=50)
    assert status == 200
    shown_ids = [r["id"] for r in first["rows"]]
    assert shown_ids == sorted(shown_ids, reverse=True)


# ---------------------------------------------------------------------------
# 수락: 거래·합계 대조 — 환불 탭·분기 기타비용 탭이 공통 조회로 열리는가
# ---------------------------------------------------------------------------

def test_refunds_tab_served_by_common_ledger_query(bound_store, legacy_owner):
    """§11.2.1 계약 1·3: 환불 탭도 공통 서버 조회가 행 ID 기준으로 제공해야 한다.

    레거시 `/board?tab=refunds`는 환불 묶음을 읽지만, React 공통 장부 조회는
    환불 탭을 여행 목록에서 찾지 못해 404를 돌려준다(별도 소유자 전용
    `/api/plush/transactions?view=refunds`만 존재, 행 식별자도 transaction_id).
    """
    store, _access = bound_store
    legacy_html = refund_tab.render(store, "", "")
    assert isinstance(legacy_html, str) and legacy_html  # 레거시 환불 탭은 열린다

    status, body = react_ledger(store, "refunds")
    assert status == 200, f"환불 탭이 공통 장부 조회에서 열리지 않음: {status} {body}"
    assert "rows" in body


def test_quarter_tab_served_by_common_ledger_query(bound_store, legacy_owner):
    """§11.2.1 계약 1·3: 분기 기타비용 탭(quarter:연도:분기)도 공통 조회가 제공해야 한다."""
    store, _access = bound_store
    tab = "quarter:2026:1"
    legacy_html = ledger_design._quarter_page(tab, "2026년 1분기 기타비용")
    assert "분기 기타비용" in legacy_html  # 레거시 분기 탭은 열린다

    status, body = react_ledger(store, tab)
    assert status == 200, f"분기 탭이 공통 장부 조회에서 열리지 않음: {status} {body}"
    assert "rows" in body


# ---------------------------------------------------------------------------
# 수락: 회계 예외 — 환불 귀속·부분환불 (RFND-021·022·023, ITEM-011)
# ---------------------------------------------------------------------------

def test_full_refund_pair_not_double_counted_in_trip_expenses(bound_store, legacy_owner):
    """§11.2.1 계약 3 + RFND-022·023: 순액 0 전액환불 짝은 일반 지출에 중복 합산하지 않는다.

    레거시 소유자 조회는 연결된 순액 0 짝을 여행 지출에서 제외하지만, React 공통
    조회는 같은 행을 여행 지출에 그대로 노출·합산한다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_id = seed_refund_pair(store, tab, 150000, -150000)
    # 환불 짝이 실제로 분석되어 순액 0 묶음으로 인지되는지 먼저 확인한다.
    members = refund_tab.member_ids(store)
    assert {"TX-P", "TX-C"} <= members, f"환불 짝이 연결되지 않음: {members}"

    legacy = legacy_expense_map(tab)
    react_rows, _count, filtered_total, trip = react_all_pages(store, tab, kind="expense")

    assert purchase_id not in legacy and cancel_id not in legacy  # 레거시는 제외
    # SPEC 기대: React도 환불 탭 귀속 거래를 일반 지출에 중복 노출·합산하지 않는다.
    assert purchase_id not in react_rows, "전액환불 원결제가 React 여행 지출에 중복 노출됨"
    assert cancel_id not in react_rows, "전액환불 취소가 React 여행 지출에 중복 노출됨"
    assert filtered_total == "0"
    assert trip["expense"] == "0"


def test_partial_refund_preserves_signs_and_net_on_trip(bound_store, legacy_owner):
    """RFND-021: 잔액이 남는 부분환불은 원결제 여행에 두 부호와 순비용을 보존한다."""
    store, _access = bound_store
    tab = make_trip(store)
    purchase_id, cancel_id = seed_refund_pair(store, tab, 100000, -30000, approval="SYNPART")
    members = refund_tab.member_ids(store)
    assert "TX-P" not in members and "TX-C" not in members  # 순액!=0 → 제외 대상 아님

    legacy = legacy_expense_map(tab)
    react_rows, _count, filtered_total, trip = react_all_pages(store, tab, kind="expense")

    for row_id, amount in ((purchase_id, "100000"), (cancel_id, "-30000")):
        assert legacy.get(row_id) == int(amount)
        assert react_rows.get(row_id) == amount
    assert filtered_total == "70000"  # 순비용 보존
    assert trip["expense"] == "70000"


# ---------------------------------------------------------------------------
# 수락: 거래·합계 대조 — 검색 필터 의미 (적용 순서 2: 기존 검색 의미 유지·통합)
# ---------------------------------------------------------------------------

def test_search_case_insensitive_parity(bound_store, legacy_owner):
    """§11.2.1 계약 1: 같은 검색어는 두 경로에서 같은 행 집합을 돌려줘야 한다.

    React는 대소문자 무시(casefold) 검색, 레거시는 대소문자 구분 검색이라
    같은 q에서 행 집합이 갈린다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    row_id = make_expense(store, tab, 5000, desc="ABC Cafe 합성")
    make_expense(store, tab, 7000, desc="무관한 합성 행")

    react_rows, _count, _total, _trip = react_all_pages(store, tab, kind="expense", q="abc")
    legacy = legacy_expense_map(tab, q="abc")

    assert row_id in react_rows  # React는 대소문자 무시로 찾는다
    assert set(legacy) == set(react_rows), "같은 검색어의 행 집합이 두 경로에서 다름"


def test_search_operator_note_field_parity(bound_store, legacy_owner):
    """§11.2.1 계약 1: 검색 대상 필드 집합이 두 경로에서 같아야 한다.

    레거시는 operator_note를 검색하지만 React 투영 검색은 operator_note를
    제외해, 같은 q에서 행 집합이 갈린다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    row_id = make_expense(store, tab, 5000, desc="평범한 합성 행", memo="SYNNOTE")
    make_expense(store, tab, 7000, desc="다른 합성 행")

    legacy = legacy_expense_map(tab, q="SYNNOTE")
    react_rows, _count, _total, _trip = react_all_pages(store, tab, kind="expense", q="SYNNOTE")

    assert row_id in legacy  # 레거시는 메모에서 찾는다
    assert set(legacy) == set(react_rows), "검색 필드 집합 차이로 행 집합이 갈림"


# ---------------------------------------------------------------------------
# 수락: 거래·합계 대조 — 여행 요약 수입·지출·차액 (계약 2·4, Google 수입)
# ---------------------------------------------------------------------------

def test_trip_summary_income_keeps_cost_and_google_separate(bound_store, income_context, monkeypatch):
    """§11.2.1 계약 1·4 + GGL-003·GGL-014: 요약 수입은 COST만 확정, Google은 별도 증거.

    내부 COST 수입과 Google 수입은 합산하지 않는다(GGL-003). 연결된 Google 출처와
    검증 값은 별도 증거(income_source)로 표시하고 확정 수입·차액에 혼합하지 않는다(GGL-014).
    COST 수입이 있는 탭에서 두 경로 모두 요약 수입은 COST 1,000,000이어야 한다.
    현재 React는 Google 수입을 합산해 이 정본 기대를 위반한다(독립 서버 수정 별도 진행 중).
    """
    store, _access = bound_store
    _snapshot, key = income_context
    tab = "trip-demo-a"  # 데모 COST 수입이 있는 탭
    monkeypatch.setattr(page, "load_mapping", lambda *a: {key: tab})
    monkeypatch.setattr(page, "owner_rows", lambda *a: {
        "income": [dict(row=6, date="2026-10-28", name="합성고객",
                        deposit=1000, balance=0, extra=0, amount=1000)],
        "expense": []})
    _snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=True)

    cost_income = store.tab_totals(tab)["income"]
    assert cost_income > 0  # COST 수입이 실제로 있는 전제

    status, body = react_ledger(store, tab, page_size=200)
    assert status == 200
    react_income = int(body["trip"]["income"])
    legacy = legacy_kpi(tab)

    # GGL-003: COST 수입과 Google 수입을 합산하지 않는다. 두 경로 모두 COST만 확정.
    assert react_income == cost_income, (
        f"React가 Google 수입을 합산함(GGL-003 위반): {react_income} != COST {cost_income}")
    assert legacy["수입"] == cost_income, "레거시 요약 수입이 COST 확정값과 다름"
    assert legacy["수입"] == react_income, "여행 요약 수입이 두 경로에서 다름"
    # GGL-014: 연결 Google 출처·검증 값은 별도 증거(확정 수입·차액에 혼합 금지).
    assert body["income_source"]["available"] is True
    assert body["income_source"]["verified"] is True
    assert body["income_source"]["total"] == "1000"
    # 차액도 COST 확정 수입 기준(미검증 Google 혼합 금지).
    assert legacy["차액"] == int(body["trip"]["profit"])


def test_unconnected_income_not_displayed_as_zero(bound_store, legacy_owner):
    """§11.2.1 계약 4: 원장 미연결·미확인 수입을 0원으로 표시하지 않는다.

    COST 수입이 없고 Google 원장이 미연결이면 레거시는 '—'(미확인)로 표시하지만
    React 여행 요약은 수입을 "0"으로 확정 표시한다.
    """
    store, _access = bound_store
    tab = make_trip(store)  # 수입 행 없음, Google env 미설정 → NOT_CONNECTED
    make_expense(store, tab, 30000)

    status, body = react_ledger(store, tab)
    assert status == 200
    assert body["income_source"]["available"] is False
    assert body["income_source"]["reason"] == "NOT_CONNECTED"
    legacy = legacy_kpi(tab)
    assert legacy["수입"] is None  # 레거시는 미확인 표시

    # SPEC 기대: 미연결 상태에서 수입을 확정 0원으로 표시하지 않는다.
    assert body["trip"]["income"] != "0", "미연결 수입을 0원으로 확정 표시함"


def test_google_income_missing_amount_stays_unknown(bound_store, income_context, monkeypatch):
    """§11.2.1 계약 4: 금액 미확인 Google 수입 행은 0원이 아니라 '미확인'으로 표시한다."""
    store, _access = bound_store
    _snapshot, key = income_context
    tab = "trip-demo-a"
    monkeypatch.setattr(page, "load_mapping", lambda *a: {key: tab})
    monkeypatch.setattr(page, "owner_rows", lambda *a: {
        "income": [dict(row=18, date="2026-10-01", name="합성고객", amount="", deposit=200000)],
        "expense": []})

    status, body = react_ledger(store, tab, kind="income", page_size=200)
    assert status == 200
    google = [r for r in body["rows"] if r["id"].startswith("google-income|")]
    assert len(google) == 1
    assert google[0]["amount"] == "미확인"
    assert "200000원" in google[0]["description"]
    assert body["income_source"]["verified"] is False


# ---------------------------------------------------------------------------
# 수락: 업무 흐름과 접근 — 권한·마감·직링크 (계약 1·4, 보호 경계 §13.10)
# ---------------------------------------------------------------------------

def test_viewer_cannot_read_out_of_allowlist_trip_or_row(bound_store):
    """수락(업무 흐름과 접근): 권한 밖 탭·행은 직링크와 API에서 노출되지 않는다."""
    store, access = bound_store
    allowed = make_trip(store, dest="합성 허가 여행")
    forbidden = make_trip(store, dest="합성 비허가 여행")
    secret_row = make_expense(store, forbidden, 999999, desc="비허가 합성 기밀")
    grant_viewer_tabs(access, "syn-viewer", [allowed])

    status, body = react_ledger(store, forbidden, user="syn-viewer")
    assert status == 404
    assert "비허가 합성 기밀" not in json.dumps(body, ensure_ascii=False)

    status, body = call(f"/api/plush/row?id={secret_row}", "syn-viewer", store)
    assert status == 404
    assert "비허가 합성 기밀" not in json.dumps(body, ensure_ascii=False)

    status, body = react_ledger(store, allowed, user="syn-viewer")
    assert status == 200
    assert all(r["read_only"] for r in body["rows"])


def test_closed_trip_is_read_only_in_common_query(bound_store, legacy_owner):
    """수락(업무 흐름과 접근): 마감 표시된 여행은 공통 조회에서 읽기 전용이다."""
    store, _access = bound_store
    tab = make_trip(store)
    row_id = make_expense(store, tab, 4000)
    store.save_trip_visual_close(
        tab_id=tab, expected_closed=False, closed=True,
        client_request_id=f"parity-close-{_uid()}")

    status, body = react_ledger(store, tab)
    assert status == 200
    assert body["closed"] is True
    assert body["trip"]["closed"] is True
    listed = next(r for r in body["rows"] if r["id"] == row_id)
    assert listed["read_only"] is True


def test_manual_correction_projection_used_by_both_paths(bound_store, legacy_owner, monkeypatch):
    """§11.2.1 계약 1·4: 저장된 수동 교정 투영을 목록·상세가 함께 쓴다(보호 경계 §13.2)."""
    store, _access = bound_store
    tab = make_trip(store)
    row_id = make_expense(store, tab, 10000, day="2026-11-12")
    original_projected = store.projected

    def corrected(row):
        out = original_projected(row)
        if row["row_id"] == row_id:
            out["display_amount_krw"] = 76543
            out["display_occurred_on"] = "2026-11-16"
        return out

    monkeypatch.setattr(store, "projected", corrected)

    legacy = legacy_expense_map(tab)
    status, body = react_ledger(store, tab, kind="expense", page_size=200)
    assert status == 200
    listed = next(r for r in body["rows"] if r["id"] == row_id)
    assert legacy[row_id] == 76543
    assert listed["amount"] == "76543"
    assert listed["date"] == "2026-11-16"

    status, detail = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
    assert status == 200
    assert detail["row"]["amount"] == listed["amount"] == "76543"
    assert detail["row"]["date"] == listed["date"] == "2026-11-16"
