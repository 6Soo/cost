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


def test_refund_group_is_read_only_inline_and_guarded_api_remains_available(context):
    board, original, refund, unrelated = context
    start = list(board.conn.iterdump())
    html = card_flow.render_expense_cleanup(board, "synthetic-csrf")
    assert "\ub0b4 \ud655\uc778 \ud544\uc694 0\uac74" in html
    assert "cleanup-refund-action" not in html
    assert "data-original=" not in html
    assert "\uc6d0\uacb0\uc81c\u00b7\ud658\ubd88 \ubb36\uc74c \uae30\ub85d" not in html
    for member in (original, refund):
        row = html.split(f"data-transaction='{member}'", 1)[1].split("</li>", 1)[0]
        assert "<form" not in row
        assert "\ubcc0\uacbd \uc800\uc7a5" not in row
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
    for member in (original, refund):
        assert board.conn.execute(
            "SELECT classification_state,classification_source,display_tab_id,trip_id "
            "FROM transactions WHERE transaction_id=?", (member,)).fetchone() == (
                "classified", "refund_original", "refunds", "")
    assert board.conn.execute(
        "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?", (unrelated,)).fetchone()[0] == 0
    again = card_flow.render_expense_cleanup(board, "synthetic-csrf")
    assert f"data-transaction='{original}'" not in again
    assert f"data-transaction='{refund}'" not in again


def test_guarded_refund_apply_retry_is_idempotent(context):
    board, original, refund, _ = context
    _, preview = _post(board, original, "preview")
    request = {"digest": preview["digest"], "request_id": "owner-retry-request-001"}
    first_status, first = _post(board, original, "apply", request)
    before = list(board.conn.iterdump())
    second_status, second = _post(board, original, "apply", request)
    assert first_status == second_status == 200
    assert first["applied"] == 2
    assert second["applied"] == 2
    assert list(board.conn.iterdump()) == before
    assert board.conn.execute(
        "SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries WHERE transaction_id IN (?,?)",
        (original, refund),
    ).fetchone() == (2, 0)


@pytest.mark.parametrize('booked_side', ['original', 'refund'])
def test_guarded_apply_completes_only_missing_side_of_recorded_group(context, monkeypatch, booked_side):
    board, original, refund, unrelated = context
    recorded = original if booked_side == 'original' else refund
    board.conn.execute(
        "INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,"
        "amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) "
        "SELECT transaction_id,(SELECT MIN(batch_id) FROM import_batch_rows WHERE transaction_id=t.transaction_id),"
        "item,'','refunds','',amount_krw,merchant,approval_date,transaction_direction,source_hash,'synthetic' "
        "FROM transactions t WHERE transaction_id=?", (recorded,))
    existing = board.conn.execute('SELECT * FROM ledger_entries WHERE transaction_id=?', (recorded,)).fetchone()
    monkeypatch.setattr(CardFlow, '_already_projected',
                        lambda self, source, entry, *a: entry['transaction_id'] == recorded)
    status, preview = _post(board, original, 'preview')
    assert status == 200 and preview['recordable'] is True
    assert preview['to_book'] == 1 and preview['already_booked'] == 1
    status, applied = _post(board, original, 'apply',
                            {'digest': preview['digest'], 'request_id': 'complete-missing-side-' + booked_side})
    assert status == 200 and applied['applied'] == 1
    assert board.conn.execute('SELECT * FROM ledger_entries WHERE transaction_id=?', (recorded,)).fetchone() == existing
    assert board.conn.execute('SELECT COUNT(*),SUM(amount_krw) FROM ledger_entries').fetchone() == (2, 0)
    assert board.conn.execute('SELECT 1 FROM ledger_entries WHERE transaction_id=?', (unrelated,)).fetchone() is None


def test_guarded_preview_keeps_legacy_projection_without_ledger_blocked(context, monkeypatch):
    board, original, refund, _ = context
    monkeypatch.setattr(CardFlow, '_already_projected',
                        lambda self, source, entry, *a: entry['transaction_id'] == original)
    status, preview = _post(board, original, 'preview')
    assert status == 200 and not preview['recordable']
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_guarded_apply_same_request_id_with_changed_digest_conflicts(context):
    board, original, _, _ = context
    _, preview = _post(board, original, "preview")
    first = {"digest": preview["digest"], "request_id": "owner-scope-conflict-001"}
    assert _post(board, original, "apply", first)[0] == 200
    changed = {"digest": "f" * 64, "request_id": first["request_id"]}
    status, result = _post(board, original, "apply", changed)
    assert status == 409
    assert result["code"] == "REQUEST_ID_REUSED"


def test_guarded_apply_new_request_id_replays_without_duplicate_financial_writes(context):
    board, original, _, _ = context
    _, preview = _post(board, original, "preview")
    assert _post(
        board, original, "apply",
        {"digest": preview["digest"], "request_id": "owner-first-request-002"},
    )[0] == 200
    tables = ('ledger_entries', 'transactions', 'board_rows', 'board_revisions')
    before = {table: board.conn.execute('SELECT * FROM ' + table).fetchall() for table in tables}
    status, result = _post(
        board, original, "apply",
        {"digest": preview["digest"], "request_id": "owner-new-request-003"},
    )
    assert status == 200 and result['applied'] == 0
    assert {table: board.conn.execute('SELECT * FROM ' + table).fetchall() for table in tables} == before


def test_guarded_apply_rolls_back_partial_write_failure(context, monkeypatch):
    board, original, refund, _ = context
    _, preview = _post(board, original, "preview")
    before = list(board.conn.iterdump())
    original_execute = board.conn.execute
    ledger_inserts = 0

    class FailingConnection:
        def execute(self, sql, params=()):
            nonlocal ledger_inserts
            if sql.lstrip().upper().startswith("INSERT INTO LEDGER_ENTRIES"):
                ledger_inserts += 1
                if ledger_inserts == 2:
                    raise RuntimeError("synthetic second-row failure")
            return original_execute(sql, params)

        def __getattr__(self, name):
            return getattr(original_execute.__self__, name)

    monkeypatch.setattr(board, "conn", FailingConnection())
    with pytest.raises(RuntimeError, match="synthetic second-row failure"):
        _post(
            board, original, "apply",
            {"digest": preview["digest"], "request_id": "owner-rollback-request-001"},
        )
    board.conn = original_execute.__self__
    assert list(board.conn.iterdump()) == before
    assert board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0


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


@pytest.mark.parametrize("scenario", ["unmatched", "manual_hold", "over_refund"])
def test_refund_money_guards_still_block_guarded_action(context, scenario):
    board, original, refund, unrelated = context
    if scenario == "unmatched":
        board.conn.execute(
            "UPDATE transactions SET original_approval_number='',approval_date=date(approval_date,'+1 day') WHERE transaction_id=?", (refund,))
    elif scenario == "manual_hold":
        h = board.conn.execute("SELECT source_hash FROM transactions WHERE transaction_id=?", (refund,)).fetchone()[0]
        board.conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
                           (refund, h, "evidence_pending", "operator stop"))
    else:
        board.conn.execute("UPDATE transactions SET amount_krw=-700000 WHERE transaction_id=?", (refund,))
    board.conn.commit()
    status, result = _post(board, original, "preview")
    assert status == 409 or (status == 200 and result["recordable"] is False)
    assert board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
