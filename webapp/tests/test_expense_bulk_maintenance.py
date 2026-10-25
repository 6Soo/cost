from urllib.parse import urlparse

import pytest

from webapp import card_flow, expense_bulk_maintenance as maintenance, ledger_board
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows


def _dump(conn):
    return tuple(conn.iterdump())


def test_preview_simulates_on_memory_copy_without_mutating_live_store(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / "preview.sqlite", seed_demo=False)
    try:
        card_rows(board, 1)
        before = _dump(board.conn)
        monkeypatch.setattr(card_flow.CardFlow, "_ota_report", lambda _self: None)

        result = maintenance.create_preview(board)

        assert result["summary"]["processed"] == 1
        assert result["summary"]["target_counts"]["classified"] == 1
        assert len(result["summary"]["targets"]["classified"][0]) == 64
        assert _dump(board.conn) == before
        assert not hasattr(board, "_ota_snapshot_service")
    finally:
        board.close()


def test_preview_rejects_stale_store_before_any_apply(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / "stale.sqlite", seed_demo=False)
    try:
        _, _, rows = card_rows(board, 1)
        monkeypatch.setattr(card_flow.CardFlow, "_ota_report", lambda _self: None)
        preview = maintenance.create_preview(board)
        board.conn.execute("UPDATE transactions SET description='changed' WHERE transaction_id=?",
                           (rows[0]["transaction_id"],))
        board.conn.commit()
        before_entries = board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]

        with pytest.raises(maintenance.PreviewError, match="자료가 바뀌었습니다") as error:
            maintenance.apply_preview(board, preview["preview_id"],
                                      "classification+ledger_record+existing_trip_assignment",
                                      confirmed=True)

        assert error.value.code == "PREVIEW_STALE"
        assert board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == before_entries
    finally:
        board.close()


def test_apply_requires_explicit_confirmation_and_replay_is_idempotent(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / "apply.sqlite", seed_demo=False)
    try:
        card_rows(board, 1)
        monkeypatch.setattr(card_flow.CardFlow, "_ota_report", lambda _self: None)
        preview = maintenance.create_preview(board)
        scope = "classification+ledger_record+existing_trip_assignment"

        with pytest.raises(maintenance.PreviewError) as error:
            maintenance.apply_preview(board, preview["preview_id"], scope)
        assert error.value.code == "CONFIRMATION_REQUIRED"

        first = maintenance.apply_preview(board, preview["preview_id"], scope, confirmed=True)
        replay = maintenance.apply_preview(board, preview["preview_id"], scope, confirmed=True)

        assert first == replay
        assert first["actual"]["processed"] == 1
        assert board.conn.execute(
            "SELECT kind FROM change_log WHERE kind LIKE 'expense.bulk.%' ORDER BY rowid"
        ).fetchall() == [("expense.bulk.started",), ("expense.bulk.completed",)]
    finally:
        board.close()


def test_preview_discloses_ota_refresh_and_requires_its_confirmation(tmp_path, monkeypatch):
    from webapp import ota_payment_review

    board = LedgerStore(tmp_path / "ota-scope.sqlite", seed_demo=False)
    try:
        _, _, rows = card_rows(board, 1)
        board.conn.execute("UPDATE transactions SET merchant='AGODA.COM' WHERE transaction_id=?",
                           (rows[0]["transaction_id"],))
        board.conn.commit()
        monkeypatch.setattr(card_flow.CardFlow, "_ota_report", lambda _self: None)
        monkeypatch.setattr(ota_payment_review, "enabled", lambda: True)

        preview = maintenance.create_preview(board)
        assert preview["summary"]["requires_ota_snapshot_refresh"] is True
        with pytest.raises(maintenance.PreviewError) as error:
            maintenance.apply_preview(
                board, preview["preview_id"],
                "classification+ledger_record+existing_trip_assignment", confirmed=True)
        assert error.value.code == "SCOPE_REQUIRED"
    finally:
        board.close()


def test_apply_is_owner_scoped_and_requires_csrf(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / "route.sqlite", seed_demo=False)
    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "1")
    monkeypatch.setattr(ledger_board, "_active_store", lambda: board)

    class Handler:
        headers = {"X-CSRF-Token": "csrf"}

        def _send_json(self, data, status=200):
            self.response = data, status

        def _send(self, _html, code=200):
            self.response = "html", code

    handler = Handler()
    route = urlparse("/api/maintenance/expense-bulk/preview")
    try:
        monkeypatch.setattr(ledger_board, "current_role", lambda: "viewer")
        assert maintenance.dispatch(handler, route, board=board, raw=b"{}", csrf="csrf")
        assert handler.response == ({"code": "FORBIDDEN"}, 403)

        monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
        assert maintenance.dispatch(handler, route, board=board, raw=b"{}", csrf="")
        assert handler.response == ({"code": "CSRF_REQUIRED"}, 403)
    finally:
        board.close()


def test_maintenance_dispatch_is_registered_without_navigation_link(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / "page.sqlite", seed_demo=False)
    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "1")
    monkeypatch.setattr(ledger_board, "_active_store", lambda: board)
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")

    class Handler:
        headers = {}

        def _send_json(self, data, status=200):
            self.response = data, status

        def _send(self, body, code=200):
            self.response = body, code

    handler = Handler()
    try:
        assert card_flow.dispatch(handler, urlparse("/maintenance/expense-bulk"), raw=None)
        assert handler.response[1] == 200
        assert "읽기 전용 미리보기" in handler.response[0]
        assert "href='/maintenance/expense-bulk'" not in handler.response[0]
    finally:
        board.close()


def test_registered_preview_route_uses_read_only_simulation(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / "integrated-preview.sqlite", seed_demo=False)
    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "1")
    monkeypatch.setattr(ledger_board, "_active_store", lambda: board)
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
    monkeypatch.setattr(card_flow.CardFlow, "_ota_report", lambda _self: None)
    card_rows(board, 1)
    before = _dump(board.conn)

    class Handler:
        headers = {"X-CSRF-Token": "csrf"}

        def _send_json(self, data, status=200):
            self.response = data, status

        def _send(self, _html, code=200):
            self.response = None, code

    handler = Handler()
    try:
        route = urlparse("/api/maintenance/expense-bulk/preview")
        assert card_flow.dispatch(handler, route, raw=b"{}", csrf="csrf")
        assert handler.response[1] == 200
        assert handler.response[0]["summary"]["processed"] == 1
        assert "preview_id" in handler.response[0]
        assert _dump(board.conn) == before
    finally:
        board.close()


def test_browser_owner_preview_requires_explicit_confirmation_before_apply():
    import json
    from playwright.sync_api import sync_playwright
    from webapp import site_shell

    requests = []
    preview = {"preview_id": "synthetic-preview", "summary": {
        "processed": 1, "requires_ota_snapshot_refresh": False,
        "target_counts": {"classified": 1}}}
    document = maintenance._render_page("synthetic-csrf")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("webapp.ledger_design.nav_region", lambda *_args: "")
        document = site_shell.wrap_document(document, "/maintenance/expense-bulk")

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 375, "height": 812})
            page.route("http://cost.test/maintenance/expense-bulk", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=document))

            def api_route(route):
                body = route.request.post_data_json
                requests.append((route.request.url, body,
                                 route.request.headers.get("x-csrf-token")))
                response = preview if route.request.url.endswith("/preview") else {
                    "actual": {"processed": 1}}
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(response))

            page.route("**/api/maintenance/expense-bulk/**", api_route)
            page.goto("http://cost.test/maintenance/expense-bulk")
            apply = page.get_by_role("button", name="확인한 미리보기 적용")
            assert apply.is_disabled()
            page.get_by_role("button", name="읽기 전용 미리보기").click()
            page.get_by_text('"processed": 1').wait_for()
            assert apply.is_disabled()
            page.locator("#confirm").check()
            assert not apply.is_disabled()
            apply.click()
            page.get_by_text("예상 결과와 실제 결과를 확인해 주세요.").wait_for()
            assert apply.is_disabled()
            assert [item[0].rsplit("/", 1)[-1] for item in requests] == ["preview", "apply"]
            assert all(item[2] == "synthetic-csrf" for item in requests)
            assert requests[1][1] == {"preview_id": "synthetic-preview",
                "scope": "classification+ledger_record+existing_trip_assignment",
                "confirmed": True}
        finally:
            browser.close()
