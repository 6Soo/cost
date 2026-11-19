"""SPEC §11.2.1 계약 1·4: 열람자 정상 진입 경로가 같은 공통 조회 결과를 읽는다.

레거시 열람자 화면은 세 곳에서 행을 따로 셌다. 초기 보드
(`ledger_board.access_control_render_viewer_board`), 목록(`/access/rows`),
그리고 새로고침 조각(`live_sync.viewer_fragments`)이 각각
`list_tab_rows(...)`의 `amount_krw`를 직접 합산했으므로 Google 수입 행이
어디에도 나오지 않았고, React(`/api/plush/ledger`)와 행 ID·건수가 갈릴 수 있었다.

이 파일은 세 진입점이 `ledger_query`의 표시 행 집합을 함께 읽는지, 그리고
같은 사용자·탭에서 React와 행 ID·금액·건수·합계가 같은지 실제 HTTP 경로로
검사한다. Google 부여(`load_grants`) 여부를 둘 다 대조하고, 권한 밖 탭과
허용 목록 밖 필드가 새지 않는지도 함께 본다.

합성 저장소와 합성 Google 스냅숏만 사용한다. 운영 원본·원격 쓰기는 없다.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from webapp import access_control, ledger_board as board_mod, plush_api
from webapp import plush_projection as projection
from webapp.ledger_store import LedgerStore

OWNER = "syn-viewer-owner"
VIEWER = "syn-viewer-staff"
OTHER = "syn-viewer-other"

SUPPLY = re.compile(
    r"수입 (\d[\d,]*원?|미확인) · 지출 (\d[\d,]*원?|미확인) · 차액 ([-−]?\d[\d,]*원?|미확인)")


def _money(text: str) -> int:
    assert text != "미확인", text
    return int(text.replace("−", "-").replace(",", ""))


def _rail(html: str) -> dict:
    """레일의 수입·지출·차액을 원 단위 정수 또는 None(미확인)으로 읽는다."""
    match = SUPPLY.search(html)
    assert match, f"열람자 레일에 합계가 없습니다: {html[:400]}"
    values = {}
    for name, raw in zip(("income", "expense", "balance"), match.groups()):
        values[name] = None if raw == "미확인" else int(raw.replace("−", "-").replace(",", ""))
    return values


@pytest.fixture
def google_block(tmp_path, monkeypatch):
    """합성 Google 스냅숏과 수입 행(1,000원)을 구성한다. 부여는 테스트가 고른다."""
    from webapp import google_ledger_page as page
    from webapp.tests.test_google_canonical_workflow import healthy_snapshot
    from webapp.tests.test_google_ledger_page import rows_doc

    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(tmp_path / "snapshot.json"))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(tmp_path / "rows.json"))
    snapshot = healthy_snapshot()
    key = snapshot["trips"][0]["key"]
    monkeypatch.setattr(page.google_authority, "load_consistent",
                        lambda *a: (snapshot, rows_doc()["sources"]))
    monkeypatch.setattr(page, "snapshot_for_display", lambda data: data)
    monkeypatch.setattr(page, "load_choices", lambda *a: {"choices": {key: "main"}})
    return key


@pytest.fixture
def viewer_board(tmp_path, monkeypatch, google_block):
    """합성 여행·COST 수입/지출·열람자 배정을 갖춘 실제 HTTP 보드."""
    key = google_block
    db = tmp_path / "viewer.sqlite"
    # `serve()` opens the store named by WEBLEDGER_DB, so bind that file first;
    # a store opened outside it would give the running server a different DB.
    monkeypatch.setenv("WEBLEDGER_DB", str(db))
    store = LedgerStore(db)
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    prev_store, prev_access = board_mod._STORE, board_mod._ACCESS
    prev_adapter = access_control.session_adapter()
    board_mod.bind_store(store)
    board_mod.bind_access(access)
    access_control.bind_synthetic_sessions(True)

    trip = store.create_trip(starts_on="2026-11-10", ends_on="2026-11-20",
                             destination="합성 열람자 여행",
                             client_request_id="viewer-synthetic-trip")
    tab = trip["tab_id"]
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        ("viewer-cost-income", "income", tab, 1, json.dumps({
            "amount_krw": 1000000, "occurred_on": "2026-11-11", "income_kind": "잔금",
            "customer_name": "합성 고객", "source_kind": "수기"}, ensure_ascii=False)))
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        ("viewer-cost-expense", "expense", tab, 1, json.dumps({
            "amount_krw": 250000, "occurred_on": "2026-11-12", "item": "식비",
            "pay_method": "현금", "description": "합성 지출", "source_kind": "수기"},
            ensure_ascii=False)))
    store.conn.commit()

    for user in (VIEWER, OTHER):
        access.create_account(user_id=user, role=access_control.ROLE_VIEWER)
    access.register_reservation_person(
        reservation_person_id="viewer-rp", display_name="합성 담당자")
    application = access.create_application(
        user_id=VIEWER, requested_name="합성 담당자",
        client_request_id="viewer-app")
    access.approve_application(
        application_id=application["application_id"], owner_id=OWNER,
        expected_revision=application["revision"],
        reservation_person_id="viewer-rp", client_request_id="viewer-approval")
    access.apply_assignment_snapshot(
        user_id=VIEWER,
        items=[{"tab_id": tab, "snapshot_revision": 1,
                "state": access_control.ASSIGN_ACTIVE}],
        source_version="viewer-synthetic", complete=True)

    # The Google mapping and grant checks stay real; only the trip link and the
    # grant contents are supplied by the test.
    from webapp import google_ledger_page as page
    monkeypatch.setattr(page, "load_mapping", lambda *a: {key: tab})

    server = board_mod.serve(port=0, with_worker=False, db_path=db)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, user=VIEWER, headers=None, *, as_json=True):
        head = dict(headers or {})
        if user:
            head[access_control.SyntheticSessionAdapter.HEADER] = user
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     headers=head, method="GET")
        try:
            with urllib.request.urlopen(req) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read()
        if not as_json:
            return status, body.decode("utf-8")
        try:
            return status, json.loads(body.decode("utf-8"))
        finally:
            pass

    def grant(users):
        if users is None:
            monkeypatch.setattr(page, "load_grants", lambda *a: {"grants": {}})
        else:
            monkeypatch.setattr(page, "load_grants",
                                lambda *a: {"grants": {user: [key] for user in users}})

    try:
        yield SimpleNamespace(store=store, access=access, tab=tab, key=key,
                              request=request, grant=grant, port=port,
                              # `serve()` opens its own store over the same file;
                              # a test that patches projection must patch that one.
                              server_store=server.card_store)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        board_mod.bind_access(prev_access)
        access_control.bind_sessions(prev_adapter)
        board_mod.bind_store(prev_store)
        store.close()


def _rail_totals(html: str) -> dict:
    """레일의 수입·지출·차액을 읽는다. 미확인은 None, 통화 단위 유무도 검사한다."""
    match = SUPPLY.search(html)
    assert match, f"열람자 레일에 합계가 없습니다: {html[:400]}"
    values = {}
    for name, raw in zip(("income", "expense", "balance"), match.groups()):
        values[name] = None if raw == "미확인" else int(
            raw.replace("원", "").replace("−", "-").replace(",", ""))
        # A number keeps its unit; only the unknown word may drop one.
        assert raw == "미확인" or raw.endswith("원"), f"{name} 금액에 원 단위 없음: {raw}"
    return values


def _assert_unknown_has_no_unit(html: str) -> None:
    """GGL-014: 미확인은 단어다. '미확인원'이나 '미확인 KRW'가 붙어선 안 된다."""
    assert "미확인원" not in html
    assert "미확인 KRW" not in html
    assert "미확인₩" not in html


def _react(env, user=VIEWER, **params):
    """React 경로는 실제 `plush_api.dispatch`를 그대로 호출한다."""
    from webapp.tests.test_plush_api import call

    query = urlencode({"tab": env.tab, **params})
    return call("/api/plush/ledger?" + query, user, env.store)


def test_viewer_paths_without_google_grant_match_react_and_stay_cost_only(viewer_board):
    """권한 경계: Google 부여가 없으면 세 진입점 모두 Google 행이 없고 React와 같다."""
    env = viewer_board
    env.grant(None)

    board_html = env.request(f"/board?tab={env.tab}", as_json=False)[1]
    assert _rail_totals(board_html) == {"income": 1000000, "expense": 250000, "balance": 750000}

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    assert listing["row_count"] == 2
    assert {row["row_id"] for row in listing["rows"]} == {"viewer-cost-income", "viewer-cost-expense"}
    assert listing["totals"] == {"income_krw": 1000000, "expense_krw": 250000,
                                 "balance_krw": 750000}

    status, fragment = env.request(f"/api/live/state?tab={env.tab}",
                                   headers={"X-Part": "live-state"}, as_json=False)
    assert status == 200
    assert _rail_totals(fragment) == {"income": 1000000, "expense": 250000, "balance": 750000}

    status, react = _react(env)
    assert status == 200
    assert react["total_count"] == 2
    assert {row["id"] for row in react["rows"]} == {row["row_id"] for row in listing["rows"]}
    # 조회 합계(부호 있는 COST 합계)와 열람자 차액(수입−지출)은 다른 계약이다.
    assert int(react["total"]) == 1000000 + 250000
    assert react["income_source"]["available"] is False
    assert react["income_source"]["reason"] == "FORBIDDEN"
    assert not any(row["id"].startswith("google-income|") for row in react["rows"])


def test_viewer_with_google_grant_sees_the_same_rows_on_all_three_paths(viewer_board):
    """GGL-003·GGL-014: 부여가 있으면 Google 행은 보이되 확정 수입에는 더하지 않는다."""
    env = viewer_board
    env.grant([VIEWER])

    board_html = env.request(f"/board?tab={env.tab}", as_json=False)[1]
    rail = _rail_totals(board_html)
    # COST 수입 1,000,000 + 지출 250,000. Google 1,000원은 확정 수입에 더해지지 않는다.
    assert rail == {"income": 1000000, "expense": 250000, "balance": 750000}

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    listing_ids = {row["row_id"] for row in listing["rows"]}
    assert "google-income|%s|main|6" % env.tab in listing_ids
    assert listing["row_count"] == 3
    # 같은 출처 분리: 조회 합계는 COST 기준이다.
    assert listing["totals"] == {"income_krw": 1000000, "expense_krw": 250000,
                                 "balance_krw": 750000}

    status, fragment = env.request(f"/api/live/state?tab={env.tab}",
                                   headers={"X-Part": "live-state"}, as_json=False)
    assert status == 200
    # 새로고침 조각과 초기 보드가 같은 그림이어야 한다.
    assert _rail_totals(fragment) == rail

    status, react = _react(env)
    assert status == 200
    assert react["total_count"] == listing["row_count"] == 3
    assert {row["id"] for row in react["rows"]} == listing_ids
    assert react["income_source"]["available"] is True
    # GGL-003: 조회 합계는 COST만, Google은 별도 출처 합계로 보고된다.
    assert int(react["total"]) == 1000000 + 250000
    assert int(react["source_totals"]["overall"]["google_income"]) == 1000
    assert int(react["source_totals"]["overall"]["income"]) == 1000000


def test_viewer_without_google_grant_never_receives_the_block(viewer_board):
    """다른 계정에 부여해도, 부여 없는 이 열람자는 Google 행·합계를 받지 않는다."""
    env = viewer_board
    env.grant([OTHER])

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    assert listing["row_count"] == 2
    assert not any(row["row_id"].startswith("google-income|") for row in listing["rows"])

    status, react = _react(env)
    assert status == 200
    assert react["income_source"]["available"] is False
    assert not any(row["id"].startswith("google-income|") for row in react["rows"])


def test_viewer_google_rows_keep_the_allowlist_and_read_only_boundary(viewer_board):
    """§13 보호 경계: 열람자 행은 허용 목록 밖 필드를 싣지 않고 Google 행은 읽기 전용이다."""
    env = viewer_board
    env.grant([VIEWER])

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    blob = json.dumps(listing, ensure_ascii=False)
    for denied in access_control.VIEWER_DENIED_FIELDS:
        assert denied not in blob, denied
    for row in listing["rows"]:
        assert set(row) <= set(access_control.VIEWER_ROW_FIELDS)

    status, react = _react(env)
    google = next(row for row in react["rows"] if row["id"].startswith("google-income|"))
    assert google["read_only"] is True
    assert all(row["read_only"] for row in react["rows"])


def _clear_cost_income(env):
    """합성 탭에서 COST 수입 행만 제거한다(운영 자료 아님, 임시 저장소)."""
    env.store.conn.execute("DELETE FROM board_rows WHERE row_id='viewer-cost-income'")
    env.store.conn.commit()


def test_no_cost_income_and_no_google_grant_shows_unknown_not_zero(viewer_board):
    """§11.2.1 계약 4 / GGL-014: COST 수입 없음 + Google 미부여는 수입·차액 미확인.

    이전 레일은 0원과 -250,000원을 확정으로 그렸는데, React는 미확인/미확인을
    보여 두 경로가 갈렸다. 확정 규칙(COST 수입 먼저, 없으면 verified Google,
    둘 다 없으면 미확인)을 레일도 같은 계약으로 읽어야 한다.
    """
    env = viewer_board
    env.grant(None)
    _clear_cost_income(env)

    board_html = env.request(f"/board?tab={env.tab}", as_json=False)[1]
    rail = _rail_totals(board_html)
    assert rail == {"income": None, "expense": 250000, "balance": None}
    _assert_unknown_has_no_unit(board_html)

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    # 기존 `totals` 키는 조회 합계 계약 그대로 보존된다(호환).
    assert listing["totals"] == {"income_krw": 0, "expense_krw": 250000,
                                 "balance_krw": -250000}
    # 확정 계약은 별도 키로 구별해 보고한다.
    assert listing["confirmed"] == {"income_krw": None, "balance_krw": None}

    status, fragment = env.request(f"/api/live/state?tab={env.tab}",
                                  headers={"X-Part": "live-state"}, as_json=False)
    assert status == 200
    assert _rail_totals(fragment) == rail
    _assert_unknown_has_no_unit(fragment)

    status, react = _react(env)
    assert status == 200
    # 소유자 결정 2026-11-19 ②: an income this ledger cannot confirm is one em dash.
    assert react["trip"]["income"] == projection.UNKNOWN_INCOME
    assert react["trip"]["profit"] == projection.UNKNOWN_INCOME


def test_no_cost_income_with_verified_google_grant_uses_the_google_figure(viewer_board):
    """확정 규칙의 두 번째 갈래: COST 수입이 없으면 verified Google이 확정 수입이 된다."""
    env = viewer_board
    env.grant([VIEWER])
    _clear_cost_income(env)

    board_html = env.request(f"/board?tab={env.tab}", as_json=False)[1]
    rail = _rail_totals(board_html)
    assert rail == {"income": 1000, "expense": 250000, "balance": -249000}

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    assert listing["confirmed"] == {"income_krw": 1000, "balance_krw": -249000}

    status, fragment = env.request(f"/api/live/state?tab={env.tab}",
                                   headers={"X-Part": "live-state"}, as_json=False)
    assert status == 200
    assert _rail_totals(fragment) == rail

    status, react = _react(env)
    assert status == 200
    assert react["trip"]["income"] == "1000"
    assert react["trip"]["profit"] == "-249000"


def test_no_cost_income_with_unverified_google_stays_unknown(viewer_board, monkeypatch):
    """확정 규칙의 세 번째 갈래: Google 블록이 미검증이면 확정 수입·차액은 미확인."""
    env = viewer_board
    env.grant([VIEWER])
    _clear_cost_income(env)
    from webapp import google_ledger_page as page
    from webapp.tests.test_google_ledger_page import rows_doc
    # The same synthetic block with an unreadable amount: available but unverified.
    monkeypatch.setattr(page, "owner_rows", lambda *a: {"income": [
        dict(row=6, date="2026-10-01", name="SYNTHETIC", amount="", deposit=1000)],
        "expense": []})

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    assert listing["confirmed"] == {"income_krw": None, "balance_krw": None}

    board_html = env.request(f"/board?tab={env.tab}", as_json=False)[1]
    assert _rail_totals(board_html) == {"income": None, "expense": 250000, "balance": None}
    _assert_unknown_has_no_unit(board_html)

    status, react = _react(env)
    assert status == 200
    # 소유자 결정 2026-11-19 ②: an income this ledger cannot confirm is one em dash.
    assert react["trip"]["income"] == projection.UNKNOWN_INCOME
    assert react["trip"]["profit"] == projection.UNKNOWN_INCOME


def test_viewer_bank_correction_matches_the_display_amount(viewer_board, monkeypatch):
    """§13.2: 열람자가 보는 금액은 저장 raw가 아니라 보정된 표시 금액이어야 한다."""
    env = viewer_board
    env.grant([VIEWER])
    original = env.server_store.projected

    def corrected(row):
        out = original(row)
        if row["row_id"] == "viewer-cost-income":
            out["display_amount_krw"] = 900000      # 저장 raw는 1000000
        if row["row_id"] == "viewer-cost-expense":
            out["display_amount_krw"] = 200000      # 저장 raw는 250000
        return out

    # The HTTP server and the in-process React helper each hold a store over the
    # same file, so both are patched with the same correction.
    monkeypatch.setattr(env.server_store, "projected", corrected)
    monkeypatch.setattr(env.store, "projected", corrected)

    status, listing = env.request(f"/access/rows?tab={env.tab}")
    assert status == 200
    by_id = {row["row_id"]: row for row in listing["rows"]}
    # §11.2.1 계약 1: the per-row figure is the display amount React sends,
    # not the stored raw amount (1,000,000 / 250,000 here).
    assert by_id["viewer-cost-income"]["amount_krw"] == 900000
    assert by_id["viewer-cost-expense"]["amount_krw"] == 200000
    # The allowlist shape is unchanged: no field was added or removed.
    assert set(by_id["viewer-cost-income"]) <= set(access_control.VIEWER_ROW_FIELDS)

    status, react = _react(env)
    assert status == 200
    react_amounts = {row["id"]: int(row["amount"]) for row in react["rows"]}
    listing_amounts = {row["row_id"]: int(row["amount_krw"]) for row in listing["rows"]}
    # Direct equality on the same IDs, as integers — no tolerance.
    assert listing_amounts == react_amounts
    assert react_amounts["viewer-cost-income"] == 900000
    assert react_amounts["viewer-cost-expense"] == 200000
    # Regression guard: the stored raw amounts (1,000,000 / 250,000) must not
    # reappear in the viewer list.
    assert 1000000 not in listing_amounts.values()
    assert 250000 not in listing_amounts.values()

    # The 조회 totals and the confirmed contract use the same display figure.
    assert listing["totals"] == {"income_krw": 900000, "expense_krw": 200000,
                                 "balance_krw": 900000 - 200000}
    assert listing["confirmed"]["income_krw"] == 900000
    assert listing["confirmed"]["balance_krw"] == 900000 - 200000

    rail = _rail_totals(env.request(f"/board?tab={env.tab}", as_json=False)[1])
    assert rail == {"income": 900000, "expense": 200000, "balance": 700000}

    assert react["trip"]["income"] == "900000"
    assert react["trip"]["profit"] == "700000"


def test_viewer_out_of_scope_trip_stays_a_404_and_names_nothing(viewer_board):
    """권한 밖 탭은 세 진입점에서 404이고 이름·행이 응답에 없다."""
    env = viewer_board
    env.grant([VIEWER])
    other = env.store.create_trip(
        starts_on="2026-11-10", ends_on="2026-11-20", destination="합성 비허가 여행",
        client_request_id="viewer-other-trip")["tab_id"]
    env.store.create_manual_expense(
        fields={"display_tab_id": other, "occurred_on": "2026-11-12",
                "amount_krw": 999999, "item": "식비", "pay_method": "현금",
                "description": "비허가 합성 자료"},
        client_request_id="viewer-other-row")

    for path in (f"/board?tab={other}", f"/access/rows?tab={other}",
                 f"/api/plush/ledger?tab={other}"):
        status, body = env.request(path, as_json=False)
        assert status == 404, path
        assert other not in body
        assert "비허가 합성 자료" not in body
