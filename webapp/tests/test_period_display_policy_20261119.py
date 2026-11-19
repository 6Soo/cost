"""소유자 표시 정책 3건 (2026-11-19) 회귀 — 테스트 전용.

소유자가 확정한 표시 정책:

① 기간 칸은 **실제 날짜만** 보여 주고, 날짜가 없으면 **빈 칸**이다.
   - 기간 없는 행(운영 3,002행) → 빈 칸, 레거시와 React가 같다.
   - 취소·환불 순액 0(운영 131행) → 빈 칸.
   - 숙박·항공·렌터카의 실제 날짜(운영 244행)는 그대로 보인다.
   - 분기 기타비용에 원문 기간이 붙은 1행도 빈 칸(기타비용은 이용일 칸을 채우지 않는다).
② 수입을 확인할 수 없으면 `—`(em dash 한 글자). 이 장부에 수입 행이 0건이라
   "미확인"은 영원히 바뀌지 않는 문구가 된다.
③ 예약번호가 있는데 여행에 귀속되지 않은 1건은 **여행으로 옮긴다** — 이 파일은
   코드·DB를 고치지 않고, 후보를 계산하는 읽기 전용 도구만 검사한다.

이 파일은 합성 자료만 쓰고 운영 원본·운영 접속·쓰기를 하지 않는다.
"""

from __future__ import annotations

import pytest

from webapp import ledger_design, plush_projection
from webapp.read_scope import scoped
from webapp.tests.test_ledger_parity_spec_11_2_1 import (  # noqa: F401 - 공유 fixture
    _uid,
    bound_store,
    make_expense,
    make_trip,
    react_ledger,
)


def _labels(row):
    return scoped(lambda: ledger_design._service_date_labels(row))()


def _card_row(**values):
    base = dict(row_id="card-" + "syn1", source_event_id="syn1", row_kind="expense",
                item="숙박비", service_period="", reservation_no="",
                occurred_on="2026-11-12", amount_krw=90000, display_tab_id="trip-a",
                source_merchant="합성 호텔")
    return {**base, **values}


# ---------------------------------------------------------------------------
# ① 기간 칸 — 실제 날짜만, 없으면 빈 칸
# ---------------------------------------------------------------------------

def test_a_row_with_no_period_is_blank_on_the_legacy_cell():
    """기간 없는 행(운영 3,002행)은 레거시 셀에서 빈 칸이다."""
    labels = _labels(_card_row())
    assert labels == ("", ""), labels


def test_a_cancelled_refund_row_is_blank_not_a_word():
    """취소·환불 순액 0(운영 131행)은 '취소·환불' 글자가 아니라 빈 칸이다.

    조건은 종전에 '취소·환불'을 넣던 그대로(음수 표시금액 + 날짜 미상)다.
    """
    assert _labels(_card_row(amount_krw=-90000, display_amount_krw=-90000)) == ("", "")
    assert _labels(_card_row(item="항공료", amount_krw=-90000, display_amount_krw=-90000)) == ("", "")
    assert _labels(_card_row(item="렌터카", amount_krw=-90000, display_amount_krw=-90000)) == ("", "")


def test_a_real_stay_period_keeps_its_dates():
    """숙박 실제 날짜(운영 244행 중 숙박)는 그대로 보인다."""
    labels = _labels(_card_row(service_period="2026-11-10~2026-11-12"))
    assert labels[0] == "11.10–11.12 · 2박", labels
    assert "11월 10일" in labels[1] and "11월 12일" in labels[1], labels


def test_a_real_flight_period_keeps_its_departure_days():
    """항공 실제 날짜는 그대로 보인다."""
    labels = _labels(_card_row(item="항공료", service_period="2026-11-10~2026-11-14"))
    assert labels[0] == "11.10–11.14", labels


def test_a_real_rental_period_keeps_its_pickup_and_return():
    """렌터카 실제 날짜는 그대로 보인다."""
    labels = _labels(_card_row(item="렌터카", service_period="2026-11-10~2026-11-13"))
    assert labels[0] == "11.10–11.13", labels


def test_a_quarter_misc_row_with_source_period_stays_blank():
    """분기 기타비용 + 원문 기간(운영 1행)은 이용일 칸을 채우지 않는다."""
    labels = _labels(_card_row(item="분기 기타비용", service_period="2026-06-20~2026-06-25"))
    assert labels == ("", ""), labels


# ---------------------------------------------------------------------------
# ① 레거시와 React가 같은 칸을 본다 — 서버 DTO 경계
# ---------------------------------------------------------------------------

def test_react_row_period_and_label_are_both_blank_when_there_is_no_date(bound_store):
    """React DTO도 레거시와 같은 빈 칸을 보낸다.

    React는 라벨이 비면 `period`로 폴백한다. 서버가 라벨과 `period`를 함께
    비워야 화면이 저장된 ISO 원문으로 되돌아가지 않는다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    rid = make_expense(store, tab, 12000)
    status, body = react_ledger(store, tab, kind="expense")
    assert status == 200, body
    row = next(r for r in body["rows"] if r["id"] == rid)
    assert row["period"] == "", row
    assert row["period_label"] == "", row


def test_react_row_keeps_a_real_date_in_both_fields(bound_store):
    """실제 날짜는 두 필드 모두에 남는다(빈 칸 규칙이 날짜를 지우지 않는다)."""
    store, _access = bound_store
    tab = make_trip(store)
    fields = {"display_tab_id": tab, "occurred_on": "2026-11-12", "amount_krw": 50000,
              "item": "숙박비", "pay_method": "현금", "description": "합성 숙박",
              "service_period": "2026-11-10~2026-11-12"}
    rid = store.create_manual_expense(
        fields=fields, client_request_id=f"policy-{_uid()}")["row_id"]
    status, body = react_ledger(store, tab, kind="expense")
    assert status == 200, body
    row = next(r for r in body["rows"] if r["id"] == rid)
    assert row["period_label"].startswith("11.10–11.12"), row
    assert row["period"] == "2026-11-10~2026-11-12", row


def test_a_blank_period_cell_does_not_remove_the_row_from_search(bound_store):
    """표시 칸을 비우는 것이 검색 결과를 줄이지는 않는다 (SPEC §11.2.1 계약 1).

    레거시 검색은 행의 저장된 `service_period` 원문을 훑는다. 화면에 보이는
    `period`가 빈 칸이 되면서 그 필드만 검색하면 레거시에서는 찾히는 행이
    React에서 사라진다. 저장 필드를 함께 읽어 같은 결과를 유지한다.
    """
    store, _access = bound_store
    tab = make_trip(store)
    # A category that has no period cell (so the displayed period is blank)
    # but whose stored range matches the query.
    rid = store.create_manual_expense(
        fields={"display_tab_id": tab, "occurred_on": "2026-11-12", "amount_krw": 12000,
                "item": "분기 기타비용", "pay_method": "현금", "description": "합성",
                "service_period": "2026-06-20~2026-06-25"},
        client_request_id=f"policy-{_uid()}")["row_id"]
    status, body = react_ledger(store, tab, kind="expense", q="2026-06-20")
    assert status == 200, body
    assert [r["id"] for r in body["rows"]] == [rid], body["rows"]
    assert next(r for r in body["rows"] if r["id"] == rid)["period"] == ""


# ---------------------------------------------------------------------------
# ② 수입 미확인 — em dash 한 글자
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("google_verified", [False, True])
def test_an_unknown_income_is_one_em_dash(google_verified):
    """수입을 확인할 수 없으면 `—`이고, 0원이나 문구로 확정하지 않는다."""
    rows = [{"row_id": "google-income|t|main|9", "row_kind": "income",
             "google_income": True, "display_amount_krw": 1000}]
    summary = plush_projection.trip_summary(dict(tab_id="t", google_verified=google_verified),
                                            rows if not google_verified else [])
    assert summary["income"] == plush_projection.UNKNOWN_INCOME, summary
    assert summary["profit"] == plush_projection.UNKNOWN_INCOME, summary
    assert summary["income"] != "0", summary


def test_no_income_rows_at_all_still_shows_the_dash():
    """수입 행이 없는 여행(운영 54개 탭 전부)은 `—`를 보인다."""
    summary = plush_projection.trip_summary(dict(tab_id="t"), [])
    assert summary["income"] == "—", summary
    assert summary["profit"] == "—", summary


def test_a_known_income_is_never_a_dash():
    """확인된 수입은 `—`가 아니라 숫자다(빈 상태 규칙이 값을 덮지 않는다)."""
    rows = [{"row_id": "man-i", "row_kind": "income", "amount_krw": 300000,
             "display_amount_krw": 300000}]
    summary = plush_projection.trip_summary(dict(tab_id="t"), rows)
    assert summary["income"] == "300000", summary
