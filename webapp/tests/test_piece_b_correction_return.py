"""Piece B: the React correction return round-trip, synthetic only.

A React ledger row opens the legacy correction screen with the narrow correction
entry marker plus a `return_to` naming the list view it came from. The server
re-validates that target and adopts it only for a row this tab really holds,
handing it back on the save result and rendering it as a data attribute on the
panel form; the page script then navigates to that server-verified target after
a save or a cancel that passed the shared leave guard.

Every other panel keeps its existing behaviour. Synthetic store, loopback port 0,
no production access.
"""
from __future__ import annotations

import html as html_module
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from webapp import access_control, ledger_board
from webapp.ledger_store import LedgerStore

OWNER = "pieceb-owner"


@pytest.fixture()
def piece_b_board(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBLEDGER_DB", str(tmp_path / "pieceb.sqlite"))
    store = LedgerStore(tmp_path / "pieceb.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    trip = store.create_trip(starts_on="2026-11-10", ends_on="2026-11-20",
                             destination="합성 조각 B 여행",
                             client_request_id="pieceb-trip")
    other = store.create_trip(starts_on="2026-12-01", ends_on="2026-12-05",
                              destination="합성 다른 여행",
                              client_request_id="pieceb-other")
    row = store.create_manual_expense(
        fields={"display_tab_id": trip["tab_id"], "occurred_on": "2026-11-12",
                "amount_krw": 5000, "item": "식비", "pay_method": "현금",
                "description": "합성 조각 B 행"},
        client_request_id="pieceb-row")
    server = ledger_board.serve(port=0, with_worker=False,
                                db_path=str(tmp_path / "pieceb.sqlite"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def call(path, *, data=None):
        head = {access_control.SyntheticSessionAdapter.HEADER: OWNER}
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            head["Content-Type"] = "application/json"
            head["X-CSRF-Token"] = ledger_board.CSRF_TOKEN
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=body, headers=head,
            method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    try:
        yield {"store": store, "tab": trip["tab_id"], "other": other["tab_id"],
               "row": row["row_id"], "call": call}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        ledger_board.bind_access(previous_access)
        ledger_board.bind_store(previous_store)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        store.close()


def _panel(env, return_to, *, tab=None, row=None, entry=True):
    """Open the panel. `entry=False` is the ordinary row-click path."""
    target_tab = tab or env["tab"]
    params = {"tab": target_tab, "kind": "ex", "row": row or env["row"],
              "return_to": return_to}
    if entry:
        params["legacy"] = "1"
    status, body = env["call"](f"/board?{urllib.parse.urlencode(params)}")
    assert status == 200, body[:200]
    return body


def _verified_return(body: str) -> str:
    marker = "data-verified-return='"
    start = body.find(marker)
    assert start >= 0, body[:400]
    start += len(marker)
    return html_module.unescape(body[start:body.index("'", start)])


def _save(env, *, return_to, entry, revision=1, row=None, tab=None, **extra):
    payload = {
        "csrf": ledger_board.CSRF_TOKEN, "expected_revision": str(revision),
        "client_request_id": f"pieceb-save-{revision}-{tab or ''}", "change_mode": "exception",
        "item": "식비", "description": f"합성 수정 {revision}",
        "occurred_on": "2026-11-12", "amount_krw": "5000",
        "display_tab_id": tab or env["tab"], "return_to": return_to,
    }
    payload.update(extra)
    if entry:
        payload["correction"] = "1"
    status, body = env["call"](f"/api/rows/{row or env['row']}/save", data=payload)
    assert status == 200, body[:200]
    return json.loads(body)




def test_a_correction_of_this_tab_adopts_the_exact_list_view(piece_b_board):
    """(1) 같은 탭 교정: 패널과 저장 결과가 정확히 그 뷰를 채택한다."""
    env = piece_b_board
    back = f"/board?tab={env['tab']}&kind=expense&sort=merchant_asc&page=3&page_size=100"
    html = _panel(env, back)
    assert _verified_return(html) == back, _verified_return(html)
    assert html_module.unescape(back) in html_module.unescape(html)

    result = _save(env, return_to=back, entry=True)
    assert result["return_to"] == back, result
    assert result["outcome"] == "saved"
    assert result["revision"] == 2


def test_search_page_and_implicit_default_tab_survive():
    """(2) q·page>1·page_size·암시적 기본 탭이 실제 상태로 유지된다."""
    assert ledger_board.board_return_path(
        "/board?tab=t1&q=foo&page=2&page_size=25") == \
        "/board?tab=t1&q=foo&page=2&page_size=25"
    adopted = ledger_board.board_back_path("t1", "foo", "expense", "",
                                           "/board?tab=t1&page=2&page_size=25")
    assert adopted == "/board?tab=t1&page=2&page_size=25", adopted
    fallback = ledger_board.board_back_path("t1", "foo", "expense", "",
                                            "/board?tab=t2&page=2")
    assert fallback == "/board?tab=t1&q=foo&kind=expense", fallback


def test_a_save_that_moves_the_row_returns_to_the_list_it_was_opened_from(piece_b_board):
    """(2b) 여행을 옮기는 저장도 원래 목록으로 복귀하고 revision은 한 번만 증가한다."""
    env = piece_b_board
    back = f"/board?tab={env['tab']}&kind=expense&sort=merchant_asc&page=2&page_size=25"
    before = env["store"].get_row(env["row"])["revision"]
    result = _save(env, return_to=back, entry=True, revision=before,
                   tab=env["other"])
    assert result["outcome"] == "saved", result
    assert result["return_to"] == back, result
    assert env["other"] not in (result["return_to"] or "")
    moved = env["store"].get_row(env["row"])
    assert moved["display_tab_id"] == env["other"], moved
    assert moved["revision"] == before + 1, moved
    assert env["store"].get_row(env["row"])["revision"] == before + 1




def test_a_return_naming_another_tab_is_refused(piece_b_board):
    """(3) 다른 탭 복귀: 패널과 저장 결과 모두 채택하지 않는다."""
    env = piece_b_board
    other_view = f"/board?tab={env['other']}&sort=merchant_asc&page=3"
    html = _panel(env, other_view)
    assert _verified_return(html) == "", _verified_return(html)
    result = _save(env, return_to=other_view, entry=True)
    assert "return_to" not in result, result


def test_an_external_return_is_refused(piece_b_board):
    """(4) 외부 출처 복귀는 채택하지 않는다."""
    env = piece_b_board
    external = f"https://evil.example/board?tab={env['tab']}"
    html = _panel(env, external)
    assert _verified_return(html) == ""
    result = _save(env, return_to=external, entry=True)
    assert "return_to" not in result, result


def test_an_ordinary_panel_has_no_verified_return(piece_b_board):
    """(5) 전용 교정 진입이 아닌 일반 패널은 복귀 목적지가 없다(동작 불변)."""
    env = piece_b_board
    back = f"/board?tab={env['tab']}&sort=merchant_asc&page=3"
    html = _panel(env, back, entry=False)
    assert _verified_return(html) == "", "일반 패널에 복귀 목적지가 실림"
    result = _save(env, return_to=back, entry=False)
    assert "return_to" not in result, result
    assert env["store"].get_row(env["row"])["revision"] == 2


def test_a_correction_entry_for_a_row_of_another_tab_is_refused(piece_b_board):
    """(6) 표지가 있어도 이 탭의 행이 아니면 채택하지 않는다."""
    env = piece_b_board
    back = f"/board?tab={env['other']}&sort=merchant_asc&page=3"
    html = _panel(env, back, tab=env["other"])   # row belongs to env['tab']
    assert _verified_return(html) == "", _verified_return(html)


def test_a_correction_entry_without_a_row_is_refused(piece_b_board):
    """(7) 수정 대상 행이 없으면 패널 자체가 없고, 복귀 목적지도 없다."""
    env = piece_b_board
    back = f"/board?tab={env['tab']}&page=2"
    status, body = env["call"](f"/board?{urllib.parse.urlencode({'tab': env['tab'], 'legacy': '1', 'return_to': back})}")
    assert status == 200, body[:200]
    assert "data-verified-return='/" not in body, "행 없는 교정 진입에 목적지가 실림"


def test_the_save_branch_never_selects_a_rejected_return(piece_b_board):
    """(8) 저장 분기: 검증 실패 값은 Location/결과 목적지로 선택되지 않는다."""
    env = piece_b_board
    rejected = f"/board?tab={env['tab']}&sort=not-a-sort"
    result = _save(env, return_to=rejected, entry=True)
    assert "return_to" not in result, result
    assert result["outcome"] == "saved", result


@pytest.mark.parametrize("bad", [
    "page=0", "page=-1", "page=abc", "page= 3", "page=1.5",
    "page_size=201", "page_size=0", "page_size=abc",
])
def test_out_of_range_values_are_refused_without_error(bad):
    """(9) 범위 밖 페이지 값은 예외 없이 거절된다(API 계약: 1 ≤ page_size ≤ 200)."""
    assert ledger_board.board_return_path(f"/board?tab=t1&{bad}") == ""


@pytest.mark.parametrize("bad", ["9999999999", "9" * 4000, "1" * 3000])
def test_a_very_long_numeral_is_refused_before_conversion(bad):
    """(10) 숫자 변환 전 길이로 막는다 — 예외 없이 폴백."""
    assert ledger_board.board_return_path(f"/board?tab=t1&page={bad}") == ""
    assert ledger_board.board_return_path(f"/board?tab=t1&page_size={bad}") == ""


def test_accepted_bounds_include_two_hundred_and_exclude_more():
    """(11) 허용 범위는 실제 API 계약과 일치한다."""
    assert ledger_board.board_return_path("/board?tab=t1&page_size=200") == \
        "/board?tab=t1&page_size=200"
    assert ledger_board.board_return_path("/board?tab=t1&page_size=201") == ""
    assert ledger_board.board_return_path("/board?tab=t1&page=9999") == \
        "/board?tab=t1&page=9999"


def test_the_archived_marker_is_preserved_as_the_board_round_trips_it():
    """(12) arch는 legacy 보드가 그대로 되돌려주는 표지이므로 보존한다."""
    assert ledger_board.board_return_path("/board?tab=t1&arch=previous") == \
        "/board?tab=t1&arch=previous"


def test_an_allocated_row_save_adopts_the_same_verified_target(piece_b_board):
    """(13) 배분 행(POST)도 같은 합성 HTTP에서 같은 규칙으로 목적지를 받는다."""
    env = piece_b_board
    store = env["store"]
    source = store.create_direct_income(
        fields={"display_tab_id": env["tab"], "occurred_on": "2026-11-11",
                "customer_name": "합성 배분 원천", "income_kind": "deposit",
                "amount_krw": 9000, "source_kind": "수기"},
        client_request_id="pieceb-income")
    plan = store.save_allocations(
        source_row_id=source["row_id"], expected_source_revision=1,
        allocations=[{"customer_name": "합성 고객", "display_tab_id": env["tab"],
                      "income_kind": "deposit", "amount_krw": 4000}],
        client_request_id="pieceb-plan")
    allocation_id = plan["alloc_after"][0]["allocation_id"]
    back = f"/board?tab={env['tab']}&kind=expense&sort=merchant_asc&page=3"
    payload = {
        "csrf": ledger_board.CSRF_TOKEN,
        "expected_revision": str(store.get_allocation(allocation_id)["source_revision"]),
        "client_request_id": "pieceb-alloc-save", "return_to": back,
        "correction": "1", "customer_name": "합성 고객",
        "nickname": "", "display_tab_id": env["tab"], "income_kind": "deposit",
    }
    status, body = env["call"](f"/api/rows/{allocation_id}/save", data=payload)
    assert status == 200, body[:200]
    result = json.loads(body)
    assert result["return_to"] == back, result
    assert result["outcome"] in ("saved", "unchanged"), result
    assert ledger_board._is_correction_payload({"correction": "1"}) is True
    assert ledger_board._is_correction_payload({}) is False
    assert ledger_board._verified_save_return(
        {"correction": "1", "return_to": "https://evil.example/x"},
        {"display_tab_id": env["tab"]}) == ""
    assert ledger_board._verified_save_return(
        {"return_to": "/board?tab=" + env["tab"]},
        {"display_tab_id": env["tab"]}) == ""
