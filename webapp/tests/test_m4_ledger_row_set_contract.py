"""The row-set relationship behind the figures, on one mixed tab (SPEC §11.2.1).

`plush_api._ledger` builds one list and derives every figure from it:

    rows          = list_tab_rows(tab)            # the store's rows for this tab
    rows          = _with_income(rows, income)    # + the Google income block
    rows          = projected(rows)               # the store's display correction
    [exclusion]   = refund_tab.member_ids, owner only, refunds tab excepted
    all_rows      = rows                          # <- the trip summary's input
    kind_rows     = all_rows filtered by kind     # <- `total`
    rows          = kind_rows filtered by q       # <- `filtered_total`, and the page

So the exclusion happens once, before `all_rows`, and every later figure inherits
it. `_confirmed_total` then drops Google and unreadable amounts from a sum, which
cannot re-introduce an excluded row because it is already gone from the list.

The contract (계약 2) fixes what each figure means:

* the trip summary is the tab-wide value and does not change with the list filter;
* `total` applies permission/tab/kind, before search;
* `filtered_total` applies search over every page.

This pins those meanings on a synthetic tab that mixes a net-zero refund pair, a
partial refund, COST income and a plain expense.
"""
from __future__ import annotations

import json

import pytest

from webapp import access_control, ledger_board, ledger_design, plush_api
from webapp.ledger_store import LedgerStore
from webapp.tests.test_ledger_parity_spec_11_2_1 import (
    _insert_card_row, _insert_transaction, seed_refund_pair)

OWNER = "syn-owner"


class Handler:
    command = "GET"

    def __init__(self, user):
        self.headers = {access_control.SyntheticSessionAdapter.HEADER: user} if user else {}
        self.responses = []

    def _send_json(self, value, code=200, **_kwargs):
        self.responses.append((code, value))


def _call(path, user, store):
    from types import SimpleNamespace

    parsed = SimpleNamespace(path=path.split("?", 1)[0],
                             query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    return handler.responses[-1]


@pytest.fixture()
def mixed_tab(tmp_path, monkeypatch):
    """One tab: net-zero refund pair, partial refund, COST income, plain expense."""
    store = LedgerStore(tmp_path / "sets.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    tab = store.create_trip(starts_on="2026-11-10", ends_on="2026-11-20",
                            destination="합성 혼합 여행",
                            client_request_id="sets-trip")["tab_id"]
    # a net-zero pair belongs to the refund tab (RFND-022 / ITEM-011)
    seed_refund_pair(store, tab, 150000, -150000, approval="PAIR1")
    # a partial refund: the trip keeps both signs (RFND-021)
    _insert_transaction(store, "TX-P2", tab, 90000, direction="purchase", approval="PAIR2")
    _insert_transaction(store, "TX-C2", tab, -30000, direction="cancellation",
                        approval="PAIR2-C", original_approval="PAIR2")
    _insert_card_row(store, "card-TX-P2", tab, 90000, source_event_id="TX-P2")
    _insert_card_row(store, "card-TX-C2", tab, -30000, source_event_id="TX-C2")
    store.create_direct_income(
        fields={"display_tab_id": tab, "occurred_on": "2026-11-11",
                "customer_name": "합성 고객", "income_kind": "deposit",
                "amount_krw": 1000000, "source_kind": "수기"},
        client_request_id="sets-income")
    store.create_manual_expense(
        fields={"display_tab_id": tab, "occurred_on": "2026-11-12",
                "amount_krw": 7000, "item": "식비", "pay_method": "현금",
                "description": "합성 일반 지출 marker-only"},
        client_request_id="sets-row")
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
    try:
        yield store, tab
    finally:
        ledger_board.bind_access(previous_access)
        ledger_board.bind_store(previous_store)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        store.close()


def _legacy_expense(store, tab) -> tuple[int, list[str]]:
    _incomes, expenses, _wi, _we = ledger_design._selected_rows(tab, "", "")
    return (sum(ledger_board._shown_amount(row) for row in expenses),
            [row["row_id"] for row in expenses])


def test_the_exclusion_happens_after_the_projection_and_before_both_totals(
        mixed_tab):
    """The refund exclusion lands before `all_rows`, so every figure inherits it."""
    store, tab = mixed_tab
    legacy_total, legacy_ids = _legacy_expense(store, tab)
    status, body = _call(f"/api/plush/ledger?tab={tab}&kind=expense", OWNER, store)
    assert status == 200, body

    # the net-zero pair is gone from both, the partial refund stays in both
    react_ids = sorted(row["id"] for row in body["rows"])
    assert react_ids == sorted(legacy_ids), (react_ids, legacy_ids)
    assert "card-TX-P" not in react_ids and "card-TX-C" not in react_ids
    assert "card-TX-P2" in react_ids and "card-TX-C2" in react_ids

    # and every figure over that set agrees
    assert body["total"] == str(legacy_total), (body["total"], legacy_total)
    assert body["filtered_total"] == str(legacy_total), body
    assert body["trip"]["expense"] == str(legacy_total), body["trip"]
    assert body["trip"]["income"] == "1000000", body["trip"]


def test_the_summary_is_tab_wide_while_the_totals_follow_the_filter(mixed_tab):
    """계약 2: 요약은 탭 전체, total은 검색 전, filtered_total은 검색 후."""
    store, tab = mixed_tab
    legacy_total, _ids = _legacy_expense(store, tab)
    # one row carries this token, so the search keeps one row out of three
    status, body = _call(
        f"/api/plush/ledger?tab={tab}&kind=expense&q=marker-only", OWNER, store)
    assert status == 200, body
    assert len(body["rows"]) == 1, body["rows"]
    assert body["filtered_total"] == "7000", body
    # the pre-search set is unchanged by `q`
    assert body["total"] == str(legacy_total), (body["total"], legacy_total)
    # and the trip summary never changes with the list filter
    assert body["trip"]["expense"] == str(legacy_total), body["trip"]


def test_the_exclusion_applies_to_every_page_not_only_the_first(mixed_tab):
    """A second page cannot reintroduce an excluded row."""
    store, tab = mixed_tab
    status, first = _call(f"/api/plush/ledger?tab={tab}&kind=expense&page=1&page_size=2",
                          OWNER, store)
    assert status == 200, first
    status, second = _call(f"/api/plush/ledger?tab={tab}&kind=expense&page=2&page_size=2",
                           OWNER, store)
    assert status == 200, second
    seen = [row["id"] for row in first["rows"]] + [row["id"] for row in second["rows"]]
    assert "card-TX-P" not in seen and "card-TX-C" not in seen, seen
    assert first["total"] == second["total"] == first["filtered_total"]


def test_a_google_block_is_excluded_from_totals_and_the_summary(mixed_tab, monkeypatch, tmp_path):
    """`_with_income` adds rows; neither the totals nor the summary may count them."""
    store, tab = mixed_tab
    from webapp import google_ledger_page as page
    from webapp.tests.test_google_canonical_workflow import healthy_snapshot
    from webapp.tests.test_google_ledger_page import rows_doc

    # `plush_income.load` fails closed without both paths configured
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(tmp_path / "snap.json"))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(tmp_path / "rows.json"))
    snapshot = healthy_snapshot()
    key = snapshot["trips"][0]["key"]
    monkeypatch.setattr(page.google_authority, "load_consistent",
                        lambda *a: (snapshot, rows_doc()["sources"]))
    monkeypatch.setattr(page, "snapshot_for_display", lambda data: data)
    monkeypatch.setattr(page, "load_choices", lambda *a: {"choices": {key: "main"}})
    monkeypatch.setattr(page, "load_mapping", lambda *a: {key: tab})
    # Nothing memoised may survive a later test: the memo is per render scope.
    from webapp import read_scope
    read_scope._MEMO.set(None)

    legacy_total, _ids = _legacy_expense(store, tab)
    status, body = _call(f"/api/plush/ledger?tab={tab}&kind=income", OWNER, store)
    assert status == 200, body
    google_ids = [row["id"] for row in body["rows"] if row["id"].startswith("google-income|")]
    assert google_ids, body["rows"]
    # `kind=income` totals over income rows only: the COST income is 1,000,000
    # and the Google 1,000 is not added to it (GGL-003).
    assert body["total"] == "1000000", body
    assert body["trip"]["income"] == "1000000", body["trip"]
    # the Google row is listed as evidence, never in a figure
    assert body["income_source"]["available"] is True, body["income_source"]


def test_the_row_detail_gives_the_owner_the_stored_reservation_and_evidence(mixed_tab):
    """SPEC §11.2.1 계약 4: 상세는 예약·증빙 근거를 확인할 수 있어야 한다.

    The React drawer can only show what this response carries. If `detail`
    dropped `reservation_no`/`evidence_type`/`source_merchant`, the value the
    legacy panel prints (``ledger_design`` '예약번호 (고정)') would be
    unreachable on the React path — the two entry paths would disagree (계약 1).
    """
    store, tab = mixed_tab
    _insert_card_row(store, "card-tx-evidence-1", tab, 210000,
                     source_event_id="TX-EV",
                     item="숙박", day="2026-11-13", merchant="합성 원문 가맹점")
    store.conn.execute(
        "UPDATE board_rows SET payload_json = ? WHERE row_id = ?",
        (json.dumps({
            "amount_krw": 210000, "occurred_on": "2026-11-13", "item": "숙박",
            "source_kind": "카드", "source_event_id": "TX-EV",
            "source_merchant": "합성 원문 가맹점", "pay_method": "카드",
            "evidence_type": "카드", "reservation_no": "SYNTH-PNR-11",
            "service_period": "2026-11-13~2026-11-15",
        }, ensure_ascii=False), "card-tx-evidence-1"))
    store.conn.commit()

    status, body = _call(f"/api/plush/row?id=card-tx-evidence-1", OWNER, store)
    assert status == 200, body
    detail = body["detail"]
    assert detail["reservation_no"] == "SYNTH-PNR-11", detail
    assert detail["evidence_type"] == "카드", detail
    assert detail["source_merchant"] == "합성 원문 가맹점", detail
    assert detail["service_period"] == "2026-11-13~2026-11-15", detail


def test_the_bootstrap_summary_uses_the_same_row_set_as_the_ledger(mixed_tab):
    """§11.2.1 계약 1: the list summary and the bootstrap summary agree."""
    store, tab = mixed_tab
    legacy_total, _ids = _legacy_expense(store, tab)
    _s, ledger = _call(f"/api/plush/ledger?tab={tab}&kind=expense", OWNER, store)
    _s2, boot = _call("/api/plush/bootstrap", OWNER, store)
    trip = next(t for t in boot["trips"] if t["id"] == tab)
    assert trip["expense"] == ledger["trip"]["expense"], (trip, ledger["trip"])
    assert trip["expense"] == str(legacy_total), trip
