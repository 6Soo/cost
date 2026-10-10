import sqlite3

from app import Pipeline
from app import source_links


def _pipeline():
    return Pipeline(sqlite3.connect(":memory:", isolation_level=None))


def _acquired(conn, transaction_id, approval_date):
    conn.execute(
        "INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,"
        "transaction_direction,transaction_kind,approval_number,original_approval_number,approval_date,"
        "posting_date,merchant,merchant_normalized,amount_krw,foreign_amount,foreign_currency,"
        "description_raw,row_index,raw_row_json,conflict_reason,parse_error,classification_state,"
        "classification_source,classification_basis,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (transaction_id, "source-" + transaction_id, "acquired-batch", "국민", "1234", "국내",
         "purchase", "일시불", "AUTH-1", "", approval_date, approval_date,
         "합성 상점", "합성 상점", 1000, "", "", "", 2, "{}", "", "",
         "needs_review", "", "", "2026-10-10T00:00:00+00:00"),
    )


def _approval(conn, approval_key, approval_date):
    conn.execute(
        "INSERT INTO approval_evidence(approval_key,source_hash,batch_id,row_index,issuer,card_tail,"
        "card_kind,transaction_direction,approval_number,approval_date,merchant,amount_krw,raw_row_json,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (approval_key, "source-" + approval_key, "approval-batch", 2, "국민", "1234", "국내",
         "purchase", "AUTH-1", approval_date, "합성 상점", 1000, "{}", "2026-10-10T00:00:00+00:00"),
    )


def test_domestic_approval_with_different_acquired_date_is_held():
    pipeline = _pipeline()
    conn = pipeline.store.conn
    _acquired(conn, "acquired-before", "2026-04-24")
    _approval(conn, "approval-later", "2026-04-27")

    result = source_links.reconcile(pipeline.store)

    assert result["states"] == {source_links.AMBIGUOUS: 1}
    row = conn.execute(
        "SELECT linked_transaction_id,link_note FROM approval_evidence WHERE approval_key='approval-later'"
    ).fetchone()
    assert row[0] is None
    assert "승인일이 다른" in row[1]


def test_domestic_approval_uses_exact_date_when_number_repeats_across_dates():
    pipeline = _pipeline()
    conn = pipeline.store.conn
    _acquired(conn, "acquired-other-date", "2026-04-24")
    _acquired(conn, "acquired-exact-date", "2026-04-27")
    _approval(conn, "approval-exact", "2026-04-27")

    result = source_links.reconcile(pipeline.store)

    assert result["states"] == {source_links.LINKED: 1}
    row = conn.execute(
        "SELECT linked_transaction_id FROM approval_evidence WHERE approval_key='approval-exact'"
    ).fetchone()
    assert row[0] == "acquired-exact-date"
