"""Synthetic lifecycle proof for a separate isolated OTA review database."""
import hashlib
import sqlite3
from types import SimpleNamespace

import pytest

from app import ota_payments
from app.ota_review import OtaReviewStore
from webapp.ota_payment_review import CoreOtaPaymentBackend


def test_isolated_review_reload_and_removal_leave_readonly_board_unchanged(tmp_path, monkeypatch):
    production = tmp_path / "board.sqlite"
    review = tmp_path / "pilot" / "review.sqlite"
    with sqlite3.connect(production) as setup:
        setup.execute("CREATE TABLE board_rows (row_id INTEGER PRIMARY KEY)")
        setup.executemany("INSERT INTO board_rows VALUES (?)", [(i,) for i in range(734)])
        setup.execute("CREATE TABLE existing_holds (id TEXT)")
        setup.execute("INSERT INTO existing_holds VALUES ('synthetic-hold')")
    before = hashlib.sha256(production.read_bytes()).hexdigest()
    conn = sqlite3.connect(production.as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    board = SimpleNamespace(conn=conn, path=production)
    monkeypatch.setenv("WEBLEDGER_OTA_REVIEW_MODE", "isolated")
    monkeypatch.setenv("WEBLEDGER_OTA_REVIEW_DB", str(review))
    from webapp.ota_payment_review import enabled, review_db_path
    assert enabled() and review_db_path() == str(review)
    with pytest.raises(ValueError, match="separate"):
        CoreOtaPaymentBackend(board, production, read_only=False,
                              payments=ota_payments, store_type=OtaReviewStore, sources={})
    event = dict(ota_event_id="synthetic-event", provider="agoda", booking_ref="SYNTHETIC",
                 item="lodging", event_type="charge", paid_on="2026-08-01", amount=30000,
                 currency="KRW", amount_krw=30000, card_last4="1234",
                 evidence_status="paid_verified", payment_status="paid",
                 source_digest="a" * 64, source_ids=["synthetic-mail:1"])
    card = dict(transaction_id="synthetic-card", source_hash="b" * 64,
                merchant="UNKNOWN", merchant_normalized="unknown", issuer="synthetic-bank",
                card_tail="1234", approval_date="2026-08-01",
                transaction_direction="purchase", amount_krw=30000)
    readonly = CoreOtaPaymentBackend(board, review, read_only=True,
                                    payments=ota_payments, store_type=OtaReviewStore, sources={})
    with pytest.raises(RuntimeError, match="read-only"):
        readonly.confirm("synthetic-event", "synthetic-card", "digest", request_id="x", user="owner")
    readonly.close()
    assert not review.exists()
    store = OtaReviewStore(review)
    preview = store.preview(event, card)
    assert not review.exists()
    store.confirm(event, card, preview["preview_digest"], request_id="synthetic-request",
                  user="synthetic-owner", allocations={})
    store.close()
    reloaded = OtaReviewStore(review)
    assert reloaded.links()["synthetic-event"]["transaction_id"] == "synthetic-card"
    assert len(reloaded.proposals()) == 1
    assert reloaded.active_rules() == []
    assert reloaded.group_pins() == []
    reloaded.close()
    assert conn.execute("SELECT COUNT(*) FROM board_rows").fetchone()[0] == 734
    assert conn.total_changes == 0
    conn.close()
    review.unlink()
    assert hashlib.sha256(production.read_bytes()).hexdigest() == before
