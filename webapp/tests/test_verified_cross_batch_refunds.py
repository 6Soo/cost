"""Cross-batch verified refund posting and Kakao UPay review regression tests.

All rows and names are synthetic. Never touch the operational card DB.
"""
import pytest

from app import ledger
from app.partial_refund import refund_links
from tests.card_pipeline.test_partial_refund import HEADER
from webapp.card_flow import CardFlow, _render_refund_merchant_candidates
from webapp.ledger_store import LedgerStore


def _separate_batches(tmp_path, *, verified=True, hold=False):
    board = LedgerStore(tmp_path / "refund-cross-batch.sqlite", seed_demo=False)
    flow = CardFlow(board)
    purchase_batch = flow.pipeline.receive(
        (HEADER +
         "국민,1234,domestic,purchase,AGODA_NICE-Agoda,625280,,,625280,2026-09-22,2026-09-23,A100,,매입\n"
        ).encode(), "agoda-purchase.csv")["batch_id"]
    refund_batch = flow.pipeline.receive(
        (HEADER +
         "국민,1234,domestic,purchase,AGODA_NICE-Agoda,625280,,,625280,2026-09-22,2026-09-23,A200,,매입\n"
        ).encode(), "agoda-refund.csv")["batch_id"]
    original = flow.pipeline.get_batch(purchase_batch)["rows"][0]["transaction_id"]
    refund = flow.pipeline.get_batch(refund_batch)["rows"][0]["transaction_id"]
    board.conn.execute(
        "UPDATE transactions SET classification_state='classified',item='숙박비',"
        " display_tab_id='',trip_id='' WHERE transaction_id IN (?,?)",
        (original, refund),
    )
    board.conn.execute(
        "UPDATE transactions SET transaction_direction='cancellation',amount_krw=-625280,"
        " original_approval_number=? WHERE transaction_id=?",
        ("100" if verified else "", refund),
    )
    if hold:
        hash_value = board.conn.execute(
            "SELECT source_hash FROM transactions WHERE transaction_id=?",
            (refund,),
        ).fetchone()[0]
        board.conn.execute(
            "INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
            (refund, hash_value, "evidence_pending", "synthetic manual hold"),
        )
    board.conn.commit()
    return board, flow, purchase_batch, refund_batch, original, refund


def _preview(flow, batch):
    holds = flow.automatic_holds(batch, include_verified_full_refunds=True)
    return flow.pipeline.preview(
        batch,
        trip_validator=lambda _: True,
        tab_validator=lambda _: True,
        additional_holds=holds,
        include_verified_full_refunds=True,
    ), holds


def test_verified_full_agoda_cross_batch_is_booked_atomically_and_once(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "1")
    board, flow, original_batch, refund_batch, original, refund = _separate_batches(tmp_path)
    try:
        monkeypatch.setattr(flow, "ota_group_holds", lambda: {})
        monkeypatch.setattr(flow, "_already_projected", lambda *a: False)
        before = list(board.conn.iterdump())
        view, holds = _preview(flow, original_batch)
        assert {r["transaction_id"] for r in view["rows"]} == {original, refund}
        assert view["ready"] == 2
        assert all(not r.get("blocked") for r in view["rows"])
        assert list(board.conn.iterdump()) == before
        result = flow.pipeline.commit(
            original_batch, view["digest"], "verified-full-cross-batch",
            trip_validator=lambda _: True,
            tab_validator=lambda _: True,
            additional_holds=holds,
            automatic_record=True,
            include_verified_full_refunds=True,
        )
        assert result["applied"] == 2
        rows = board.conn.execute(
            "SELECT transaction_id,batch_id,display_tab_id,amount_krw FROM ledger_entries"
            " ORDER BY transaction_id"
        ).fetchall()
        assert {(t, b, tab, amount) for t, b, tab, amount in rows} == {
            (original, original_batch, "refunds", 625280),
            (refund, refund_batch, "refunds", -625280),
        }
        view2, holds2 = _preview(flow, refund_batch)
        done = flow.pipeline.commit(
            refund_batch, view2["digest"], "verified-full-cross-batch-repeat",
            trip_validator=lambda _: True, tab_validator=lambda _: True,
            additional_holds=holds2, automatic_record=True,
            include_verified_full_refunds=True,
        )
        assert done["applied"] == 0
        assert board.conn.execute("SELECT SUM(amount_krw),COUNT(*) FROM ledger_entries").fetchone() == (0, 2)
    finally:
        board.close()


def test_cross_batch_preview_without_opt_in_stays_originally_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "1")
    board, flow, original_batch, _, original, refund = _separate_batches(tmp_path)
    try:
        bare = flow.pipeline.preview(
            original_batch, trip_validator=lambda _: True, tab_validator=lambda _: True,
        )
        assert {row["transaction_id"] for row in bare["rows"]} == {original}
        assert bare["ready"] == 0
    finally:
        board.close()


@pytest.mark.parametrize("verified,held", [(False, False), (True, True)])
def test_inferred_pairs_auto_book_but_manual_holds_still_block(tmp_path, monkeypatch, verified, held):
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "1")
    board, flow, original_batch, _, original, refund = _separate_batches(
        tmp_path, verified=verified, hold=held,
    )
    try:
        monkeypatch.setattr(flow, "ota_group_holds", lambda: {})
        view, holds = _preview(flow, original_batch)
        if not verified and not held:
            assert refund in {row["transaction_id"] for row in view["rows"]}
            assert view["ready"] == 2
        else:
            assert all(row.get("blocked") for row in view["rows"] if not row.get("already_booked"))
        result = flow.pipeline.commit(
            original_batch, view["digest"], "no-unsafe-post",
            trip_validator=lambda _: True, tab_validator=lambda _: True,
            additional_holds=holds, automatic_record=True,
            include_verified_full_refunds=True,
        )
        assert result["applied"] == (0 if held else 2)
        assert board.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == (0 if held else 2)
    finally:
        board.close()


def test_kakao_upay_on_same_card_is_a_review_candidate_not_a_payment_link(tmp_path):
    board = LedgerStore(tmp_path / "kakao-upay-review.sqlite", seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive(
            (HEADER +
             "국민,1234,domestic,purchase,유페이일반결제,9800,,,9800,2026-10-01,2026-10-02,A100,,매입\n" +
             "국민,1234,domestic,purchase,카카오T가승인,9800,,,9800,2026-10-02,2026-10-03,A200,,매입\n" +
             "국민,1234,domestic,purchase,카카오페이편의점,9800,,,9800,2026-10-01,2026-10-02,A300,,매입\n" +
             "국민,9999,domestic,purchase,유페이일반결제,9800,,,9800,2026-10-01,2026-10-02,A400,,매입\n"
            ).encode(), "kakao-review-only.csv")["batch_id"]
        ids = {r["approval_number"]: r["transaction_id"]
               for r in flow.pipeline.get_batch(batch)["rows"]}
        board.conn.execute(
            "UPDATE transactions SET transaction_direction='cancellation',"
            " amount_krw=-9800 WHERE transaction_id=?", (ids["200"],))
        board.conn.commit()
        assert ids["200"] not in refund_links(board.conn, [ids["200"]])
        html = _render_refund_merchant_candidates(board, ids["200"])
        assert "유페이일반결제" in html
        assert "유페이 결제중계 후보" in html
        assert ids["300"] not in html
        assert ids["400"] not in html
    finally:
        board.close()


def test_cardflow_automatic_record_uses_cross_batch_verified_pair(tmp_path, monkeypatch):
    """The real CardFlow recording path must not stop after displaying the pair."""
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "1")
    board, flow, original_batch, _, original, refund = _separate_batches(tmp_path)
    try:
        monkeypatch.setattr(flow, "ota_group_holds", lambda: {})
        monkeypatch.setattr(flow, "_already_projected", lambda *a, **kw: False)
        monkeypatch.setattr(flow, "preview_metadata", lambda: lambda _: {})
        result = flow._auto_record_locked(original_batch, include_state=False)
        assert result["auto_recorded"] == 2
        posted = set(row[0] for row in board.conn.execute(
            "SELECT transaction_id FROM ledger_entries"))
        assert posted == {original, refund}
        card_rows = set(row[0] for row in board.conn.execute(
            "SELECT row_id FROM board_rows WHERE row_id LIKE 'card-%'"))
        assert card_rows == {"card-" + original, "card-" + refund}
        assert flow._auto_record_locked(original_batch, include_state=False)["auto_recorded"] == 0
    finally:
        board.close()
