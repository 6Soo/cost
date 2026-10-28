"""Existing refund rows can be fixed from the same expense cleanup screen.

Synthetic SQLite only; owner explicitly approves a zero-net verified group.
"""
import json
from urllib.parse import urlparse

import pytest

from tests.card_pipeline.test_partial_refund import HEADER
from webapp import card_flow, ledger_board
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


class Handler:
    def __init__(self, token="synthetic-csrf"):
        self.headers = {"X-CSRF-Token": token}
        self.result = None

    def _send_json(self, data, status=200):
        self.result = status, data


def _post(board, original, action, data=None, token="synthetic-csrf"):
    handler = Handler(token)
    parsed = urlparse(f"/api/maintenance/refund-pair/{original}/{action}")
    assert card_flow.dispatch(handler, parsed, raw=json.dumps(data or {}).encode(), csrf="synthetic-csrf")
    return handler.result


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "1")
    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "1")
    monkeypatch.setenv("WEBLEDGER_CARD_SCHEMA_POLICY", "create")
    board = LedgerStore(tmp_path / "inline-refund.sqlite", seed_demo=False)
    previous = ledger_board._STORE
    ledger_board.bind_store(board)
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
    monkeypatch.setattr(CardFlow, "trip_valid", lambda *a: True)
    monkeypatch.setattr(CardFlow, "tab_valid", lambda *a: True)
    monkeypatch.setattr(CardFlow, "ota_group_holds", lambda *a: {})
    monkeypatch.setattr(CardFlow, "_already_projected", lambda *a, **kw: False)
    monkeypatch.setattr(CardFlow, "_projection_index", lambda *a: {})
    monkeypatch.setattr(card_flow, "_ota_entries_by_card", lambda *a, **kw:
                        {"__snapshot_status__": {"fresh": False, "status": "refreshing"}})
    monkeypatch.setattr(ledger_board, "live_trips", lambda **kw: [])
    flow = CardFlow(board)
    original_batch = flow.pipeline.receive(
        (HEADER + "국민,1234,domestic,purchase,AGODA_NICE-Agoda,625280,,,625280,2026-09-22,2026-09-23,A100,,매입\n"
         + "국민,1234,domestic,purchase,합성식당,12345,,,12345,2026-09-22,2026-09-23,X300,,매입\n").encode(),
        "source-purchase.csv")["batch_id"]
    refund_batch = flow.pipeline.receive(
        (HEADER + "국민,1234,domestic,purchase,AGODA_NICE-Agoda,625280,,,625280,2026-09-22,2026-09-23,A200,,매입\n").encode(),
        "source-refund.csv")["batch_id"]
    original = board.conn.execute(
        "SELECT transaction_id FROM transactions WHERE approval_number='100'").fetchone()[0]
    refund = board.conn.execute(
        "SELECT transaction_id FROM transactions WHERE approval_number='200'").fetchone()[0]
    unrelated = board.conn.execute(
        "SELECT transaction_id FROM transactions WHERE approval_number='300'").fetchone()[0]
    board.conn.execute(
        "UPDATE transactions SET item='숙박비',classification_state='classified' WHERE transaction_id IN (?,?)",
        (original, refund))
    board.conn.execute(
        "UPDATE transactions SET transaction_direction='cancellation',amount_krw=-625280,"
        "original_approval_number='100' WHERE transaction_id=?", (refund,))
    board.conn.commit()
    try:
        yield board, original, refund, unrelated
    finally:
        ledger_board.bind_store(previous)
        board.close()


def test_existing_full_refund_is_actionable_inline_but_get_remains_read_only(context):
    board, original, refund, unrelated = context
    start = list(board.conn.iterdump())
    html = card_flow.render_expense_cleanup(board, "synthetic-csrf")
    assert f"data-original='{original}'" in html
    assert "전액 상쇄 묶음 기록" in html
    assert list(board.conn.iterdump()) == start
    status, preview = _post(board, original, "preview")
    assert status == 200
    assert preview["recordable"] is True
    assert preview["members"] == 2
    assert preview["net_krw"] == 0
    assert preview["to_book"] == 2
    assert list(board.conn.iterdump()) == start
    status, done = _post(board, original, "apply",
                         {"digest": preview["digest"], "request_id": "owner-confirms-001"})
    assert status == 200
    assert done["applied"] == 2
    assert set(r[0] for r in board.conn.execute("SELECT transaction_id FROM ledger_entries")) == {original, refund}
    assert board.conn.execute("SELECT SUM(amount_krw) FROM ledger_entries").fetchone()[0] == 0
    assert board.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?", (unrelated,)).fetchone()[0] == 0
    again = card_flow.render_expense_cleanup(board, "synthetic-csrf")
    assert f"data-transaction='{original}'" not in again
    assert f"data-transaction='{refund}'" not in again


def test_unconfirmed_group_cannot_commit_and_requires_token(context, monkeypatch):
    board, original, refund, unrelated = context
    monkeypatch.setattr(ledger_board, "current_role", lambda: "viewer")
    status, data = _post(board, original, "preview")
    assert status == 403 and data["code"] == "FORBIDDEN"
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
    status, data = _post(board, original, "preview", token="wrong")
    assert status == 403 and data["code"] == "CSRF_REQUIRED"
    status, data = _post(board, original, "apply",
                         {"digest": "0" * 64, "request_id": "owner-invalid-001"})
    assert status == 409 and data["code"] == "PREVIEW_STALE"
    assert board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0


@pytest.mark.parametrize("scenario", ["inferred", "manual_hold", "over_refund"])
def test_refund_money_guards_still_block_inline_action(context, scenario):
    board, original, refund, unrelated = context
    if scenario == "inferred":
        board.conn.execute(
            "UPDATE transactions SET original_approval_number='' WHERE transaction_id=?", (refund,))
    elif scenario == "manual_hold":
        h = board.conn.execute("SELECT source_hash FROM transactions WHERE transaction_id=?", (refund,)).fetchone()[0]
        board.conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
                           (refund, h, "manual_hold", "operator stop"))
    else:
        board.conn.execute("UPDATE transactions SET amount_krw=-700000 WHERE transaction_id=?", (refund,))
    board.conn.commit()
    status, result = _post(board, original, "preview")
    assert status == 409 or (status == 200 and result["recordable"] is False)
    assert board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
