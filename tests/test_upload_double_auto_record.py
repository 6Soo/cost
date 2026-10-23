"""Synthetic dispatch integration coverage for both automatic-record boundaries."""
from urllib.parse import urlparse

from app import Pipeline
from tests.card_pipeline.fixtures import domestic_row, make_csv
from webapp import card_flow, ledger_board, ota_payment_review
from webapp.ledger_store import LedgerStore


class Handler:
    def __init__(self):
        self.headers = {"X-CSRF-Token": "synthetic-csrf", "X-Filename": "synthetic.csv"}
        self.response = None

    def _send_json(self, payload, code=200):
        self.response = (code, payload)


def _upload(payload):
    handler = Handler()
    assert card_flow.dispatch(handler, urlparse("/api/imports"), raw=payload,
                              csrf="synthetic-csrf")
    assert handler.response[0] == 200, handler.response
    return handler.response[1]


def test_dispatch_upload_records_before_and_after_refresh_without_duplicate_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(card_flow, "enabled", lambda: True)
    monkeypatch.setattr(ota_payment_review, "enabled", lambda: True)
    monkeypatch.setattr(card_flow.CardFlow, "trip_valid", lambda self, trip_id: True)
    state = {"late_hold": False, "refreshes": 0, "in_dispatch_auto": False,
             "snapshot_fresh": True}
    monkeypatch.setattr(card_flow.CardFlow, "_held_ota_snapshot",
                        lambda self: ({"data": {}}, state["snapshot_fresh"]))
    monkeypatch.setattr(card_flow.CardFlow, "_ota_card_statuses", lambda self, rows: ({}, "synthetic", {}))
    monkeypatch.setattr(card_flow.CardFlow, "_ota_candidate_notes", lambda self, rows: {})
    monkeypatch.setattr(card_flow.CardFlow, "_canonical_candidate_period_assignments", lambda *args: [])

    observations = []
    original_locked = card_flow.CardFlow._auto_record_locked
    original_auto_record = card_flow.CardFlow.auto_record

    def holds(self):
        if state["late_hold"]:
            return {row[0]: {"kind": "synthetic_late_evidence", "reason": "synthetic refresh pending"}
                    for row in self.board.conn.execute("SELECT transaction_id FROM transactions")}
        return {}

    monkeypatch.setattr(card_flow.CardFlow, "ota_group_holds", holds)

    def snapshot(flow, stage, result):
        observations.append({
            "stage": stage,
            "auto_recorded": result.get("auto_recorded", 0),
            "ledger": tuple(flow.board.conn.execute(
                "SELECT transaction_id,amount_krw FROM ledger_entries ORDER BY transaction_id")),
            "board_count": flow.board.conn.execute(
                    "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'card-%'").fetchone()[0],
            "refreshes": state["refreshes"],
            "digest": (result.get("preview") or {}).get("digest"),
            "request_ids": tuple(row[0] for row in flow.board.conn.execute(
                    "SELECT request_id FROM requests WHERE scope='commit' ORDER BY request_id")),
            })

    def tracked_locked(flow, batch_id, *, include_state=True):
        result = original_locked(flow, batch_id, include_state=include_state)
        if not state["in_dispatch_auto"]:
            snapshot(flow, "classify_internal", result)
        return result

    def tracked_auto_record(flow, batch_id):
        state["in_dispatch_auto"] = True
        try:
            result = original_auto_record(flow, batch_id)
        finally:
            state["in_dispatch_auto"] = False
        snapshot(flow, "dispatch_after_refresh", result)
        return result

    monkeypatch.setattr(card_flow.CardFlow, "_auto_record_locked", tracked_locked)
    monkeypatch.setattr(card_flow.CardFlow, "auto_record", tracked_auto_record)

    class Backend:
        def refresh_after_import(self, transaction_ids):
            state["refreshes"] += 1
            state["refreshed_ids"] = tuple(transaction_ids)
            state["late_hold"] = False
            state["snapshot_fresh"] = True

        def close(self):
            pass

    monkeypatch.setattr(ota_payment_review, "backend_for_request", lambda *args, **kwargs: Backend())
    store = LedgerStore(tmp_path / "synthetic.sqlite", seed_demo=True)
    monkeypatch.setattr(ledger_board, "_active_store", lambda: store)
    try:
        pipeline = Pipeline(store.conn)
        pipeline.save_rule({"conditions": {"merchant_normalized": "SYNTHETIC CAFE"},
                            "effects": {"item": "\uC2DD\uBE44"}})
        file_one = make_csv([domestic_row(merchant="Synthetic Cafe", amount=25000,
                                          approval="SYNTH-001", date="2026-04-09")])

        response_one = _upload(file_one)
        assert [(x["stage"], x["auto_recorded"]) for x in observations[:2]] == [
            ("classify_internal", 1), ("dispatch_after_refresh", 0)]
        first, second = observations[:2]
        assert first["ledger"] == second["ledger"]
        assert first["digest"] == second["digest"]
        assert first["request_ids"] == second["request_ids"]
        assert first["ledger"][0][1] == 25000
        assert first["board_count"] == second["board_count"] == 1
        assert response_one["auto_recorded"] == 0
        assert response_one["ota_refresh_status"] == "refreshed"
        first_id = first["ledger"][0][0]
        request_ids = [row[0] for row in store.conn.execute(
            "SELECT request_id FROM requests WHERE scope='commit' ORDER BY request_id")]
        assert len(request_ids) == 1 and request_ids[0].startswith("auto-record:")

        # Exact file re-upload is idempotent at transaction and ledger boundaries.
        response_again = _upload(file_one)
        assert response_again["auto_recorded"] == 0
        assert store.conn.execute("SELECT transaction_id,amount_krw FROM ledger_entries").fetchall() == [(first_id, 25000)]
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM requests WHERE scope='commit'").fetchone()[0] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='ledger.booked'").fetchone()[0] == 1

        # Refresh removes a synthetic late-evidence hold; only the second boundary records this row.
        state["late_hold"] = True
        state["snapshot_fresh"] = False
        before = len(observations)
        file_two = make_csv([domestic_row(merchant="Synthetic Cafe", amount=31000,
                                          approval="SYNTH-002", date="2026-04-10")])
        response_two = _upload(file_two)
        late = observations[before:]
        assert [(x["stage"], x["auto_recorded"]) for x in late] == [
            ("classify_internal", 0), ("dispatch_after_refresh", 1)]
        assert len(late[0]["ledger"]) == 1 and len(late[1]["ledger"]) == 2
        assert late[0]["digest"] != late[1]["digest"]
        assert late[0]["request_ids"] == first["request_ids"]
        assert len(late[1]["request_ids"]) == 2
        late_id = store.conn.execute(
            "SELECT transaction_id FROM transactions WHERE approval_number='002'").fetchone()[0]
        assert state["refreshed_ids"] == (late_id,)
        assert response_two["auto_recorded"] == 1
        assert store.conn.execute("SELECT SUM(amount_krw),COUNT(*) FROM ledger_entries").fetchone() == (56000, 2)

        # Reuse the canonical synthetic partial-refund fixture for source amount and net guards.
        from tests.card_pipeline.test_partial_refund import build, confirm_original, preview, by_approval
        refund_pipeline, refund_batch = build(gross=25000, refunds=(-15000,))
        try:
            confirm_original(refund_pipeline, refund_batch)
            refund_rows = by_approval(refund_pipeline, preview(refund_pipeline, refund_batch))
            assert refund_rows["100"]["amount_krw"] == 25000
            assert refund_rows["200"]["amount_krw"] == -15000
            assert refund_rows["200"]["refund_link"]["net_krw"] == 10000
            refund_preview = preview(refund_pipeline, refund_batch)
            refund_pipeline.commit(refund_batch, refund_preview["digest"], "synthetic-refund-commit",
                                   tab_validator=lambda _: True, trip_validator=lambda _: True)
            assert refund_pipeline.store.conn.execute(
                "SELECT SUM(amount_krw),COUNT(*) FROM ledger_entries").fetchone() == (10000, 2)
            assert refund_pipeline.store.conn.execute(
                "SELECT amount_krw FROM transactions WHERE approval_number='100'").fetchone()[0] == 25000
            assert refund_pipeline.store.conn.execute(
                "SELECT amount_krw FROM transactions WHERE approval_number='200'").fetchone()[0] == -15000
        finally:
            refund_pipeline.store.conn.close()
        # Owner trip move A->B survives a subsequent upload and reclassification.
        row = store.get_row("card-" + first_id)
        store.save(row_id=row["row_id"], expected_revision=row["revision"],
                   client_request_id="synthetic-manual-trip-move", change_mode="rule_change",
                   changes={"display_tab_id": "trip-demo-b"}, actor="owner")
        _upload(file_one)
        assert store.get_row("card-" + first_id)["display_tab_id"] == "trip-demo-b"
        assert store.conn.execute("SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                                  (first_id,)).fetchone()[0] == 1
        assert store.conn.execute("SELECT amount_krw FROM transactions WHERE transaction_id=?",
                                  (first_id,)).fetchone()[0] == 25000
    finally:
        store.close()
