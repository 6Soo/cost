"""Real Chromium check for the drawer's classification-origin line.

Reuses the synthetic port-0 server and owner session from
``test_plush_render_browser``. No operation port, no customer data.
"""
import threading

import pytest

from webapp import access_control, ledger_board

OWNER = "synthetic-render-owner"


@pytest.fixture
def origin_ui(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBLEDGER_DB", str(tmp_path / "origin-ui.sqlite"))
    monkeypatch.setenv("WEBLEDGER_PRIMARY_UI", "1")
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    previous_adapter = access_control.session_adapter()
    server = ledger_board.serve(port=0, with_worker=False, seed_demo=False)
    store = server.card_store
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    trip = store.create_trip(
        starts_on="2026-11-10", ends_on="2026-11-20",
        destination="합성 출처 여행", client_request_id="origin-ui-trip")["tab_id"]
    rows = {}
    for key, origin, basis, state in (
        ("code", "inference", "AUTO_TRIP_INFERRED 합성 기간", "classified"),
        ("ai", "ai_inference", "AI_INFERRED 합성 근거", "classified"),
        ("manual", "user_decision", "", "classified"),
        ("none", "", "", "needs_review"),
    ):
        row_id = f"card-origin-{key}"
        store.conn.execute(
            "INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)"
            " VALUES(?,?,?,?,?)",
            (row_id, "expense", trip, 1, _payload(row_id, origin, basis, state)))
        rows[key] = row_id
    store.conn.commit()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], trip, rows
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        ledger_board.bind_access(previous_access)
        access_control.bind_sessions(previous_adapter)
        ledger_board.bind_store(previous_store)
        store.close()


def _payload(row_id, origin, basis, state):
    import json
    return json.dumps({
        "row_id": row_id, "row_kind": "expense", "occurred_on": "2026-11-12",
        "amount_krw": 12000, "item": "숙박비", "description": "합성 출처 행",
        "source_kind": "카드", "source_event_id": row_id,
        "source_merchant": "합성 가맹점", "classification_state": state,
        "classification_source": origin, "classification_basis": basis,
        "revision": 1,
    }, ensure_ascii=False)


@pytest.fixture
def origin_page(origin_ui):
    from playwright.sync_api import sync_playwright

    port, trip, rows = origin_ui
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    contexts = []

    def open_drawer(width, row_id):
        context = browser.new_context(
            extra_http_headers={access_control.SyntheticSessionAdapter.HEADER: OWNER},
            viewport={"width": width, "height": 900})
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{port}/board?tab={trip}&row={row_id}")
        page.wait_for_selector(".cost-app-shell[data-role='owner']")
        contexts.append(context)
        return page

    try:
        yield open_drawer, rows
    finally:
        for context in contexts:
            context.close()
        browser.close()
        playwright.stop()


@pytest.mark.parametrize("key,label", [("code", "코드 추론"), ("ai", "AI 추론"), ("manual", "직접")])
@pytest.mark.parametrize("width", [390, 1440])
def test_drawer_shows_one_origin_line_and_no_judgement_card(origin_page, key, label, width):
    open_drawer, rows = origin_page
    page = open_drawer(width, rows[key])
    page.wait_for_selector(".cost-ledger__origin-chip")
    detail_text = page.locator(".cost-ledger__drawer-content").inner_text()
    assert page.locator(".cost-ledger__origin-chip").inner_text() == label
    assert "분류 출처" in detail_text
    assert "판정 상태" not in detail_text
    assert "판정 근거" not in detail_text
    assert "AI_INFERRED 합성 근거" not in detail_text
    assert "AUTO_TRIP_INFERRED 합성 기간" not in detail_text
    assert page.locator(".cost-ledger__origin-chip").count() == 1
    page.close()


def test_row_without_known_origin_shows_no_origin_line(origin_page):
    open_drawer, rows = origin_page
    page = open_drawer(390, rows["none"])
    page.get_by_role("heading", name="수정 이력").wait_for()
    assert page.locator(".cost-ledger__origin-chip").count() == 0
    assert "분류 출처" not in page.locator(".cost-ledger__drawer-content").inner_text()
    page.close()
