"""Approval-number padding regression tests; synthetic SQLite only."""
import sqlite3

from app.partial_refund import refund_group, refund_links


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE transactions (
            transaction_id TEXT, transaction_direction TEXT, issuer TEXT,
            card_tail TEXT, approval_number TEXT, original_approval_number TEXT,
            amount_krw INTEGER, duplicate_of TEXT, conflict_reason TEXT,
            parse_error TEXT, merchant_normalized TEXT,
            foreign_amount TEXT, foreign_currency TEXT,
            approval_date TEXT, posting_date TEXT, merchant TEXT
        )
    """)
    return conn


def _row(conn, id, direction, amount, approval="", original="", tail="1234"):
    conn.execute(
        "INSERT INTO transactions (transaction_id,transaction_direction,issuer,card_tail,approval_number,original_approval_number,amount_krw,duplicate_of,conflict_reason,parse_error) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (id, direction, "국민", tail, approval, original, amount, None, "", ""),
    )


def test_padded_approval_links_multiple_refunds_and_preserves_database():
    conn = _connection()
    _row(conn, "purchase", "purchase", 20000, approval=" 100 ")
    _row(conn, "refund-a", "cancellation", -5000, original="100")
    _row(conn, "refund-b", "cancellation", -3000, original=" 100 ")
    _row(conn, "other-card", "purchase", 20000, approval="100", tail="9999")
    before = list(conn.iterdump())
    links = refund_links(conn, ["refund-a", "refund-b"])
    assert set(links) == {"refund-a", "refund-b"}
    assert {item["original_id"] for item in links.values()} == {"purchase"}
    assert all(item["refund_count"] == 2 and item["net_krw"] == 12000
               and item["refunds_total_krw"] == -8000 for item in links.values())
    assert refund_group(conn, "purchase") == ["purchase", "refund-a", "refund-b"]
    assert list(conn.iterdump()) == before
    conn.close()


def test_trim_collision_is_ambiguous_and_never_auto_links():
    conn = _connection()
    _row(conn, "purchase-a", "purchase", 20000, approval="100")
    _row(conn, "purchase-b", "purchase", 20000, approval=" 100 ")
    _row(conn, "refund", "cancellation", -20000, original="100")
    before = list(conn.iterdump())
    assert refund_links(conn, ["refund"]) == {}
    assert refund_group(conn, "purchase-a") == ["purchase-a"]
    assert refund_group(conn, "purchase-b") == ["purchase-b"]
    assert list(conn.iterdump()) == before
    conn.close()


def test_missing_original_reference_does_not_link():
    conn = _connection()
    _row(conn, "purchase", "purchase", 20000, approval="100")
    _row(conn, "refund", "cancellation", -20000, original="   ")
    assert refund_links(conn, ["refund"]) == {}
    conn.close()


def test_tab_and_newline_padding_uses_same_sql_and_python_keys():
    conn = _connection()
    _row(conn, "purchase", "purchase", 20000, approval="\t100\n")
    _row(conn, "refund", "cancellation", -5000, original="\r100\t")
    before = list(conn.iterdump())
    assert refund_links(conn, ["refund"])["refund"]["net_krw"] == 15000
    assert refund_group(conn, "purchase") == ["purchase", "refund"]
    assert list(conn.iterdump()) == before
    conn.close()


def test_read_scope_reuses_global_links_and_invalidates_local_writes(monkeypatch):
    from app import partial_refund
    conn = _connection()
    _row(conn, 'purchase', 'purchase', 20000, approval='100')
    _row(conn, 'refund', 'cancellation', -5000, original='100')
    expected = refund_links(conn, ['refund'])
    scans = []
    original = partial_refund._number_links
    monkeypatch.setattr(partial_refund, '_number_links',
                        lambda *a, **kw: (scans.append(1), original(*a, **kw))[1])
    before = list(conn.iterdump())
    with partial_refund.read_only_scope():
        assert refund_links(conn, ['refund']) == expected
        assert refund_links(conn, ['purchase']) == {}
        assert partial_refund.count_held_cancellations(conn) == {}
        assert len(scans) == 1
        assert list(conn.iterdump()) == before
        changed_copy = refund_links(conn, ['refund'])
        changed_copy['refund']['net_krw'] = 0
        assert refund_links(conn, ['refund']) == expected
        conn.execute("UPDATE transactions SET amount_krw=-6000 WHERE transaction_id='refund'")
        assert refund_links(conn, ['refund'])['refund']['net_krw'] == 14000
        assert len(scans) == 2
    with partial_refund.read_only_scope():
        assert refund_links(conn, ['refund'])['refund']['net_krw'] == 14000
        assert len(scans) == 3
    # Outside a display scope, normal reads/commit validation do not use the memo.
    refund_links(conn, ['refund'])
    assert len(scans) == 4  # A fresh global analysis needs one numbered scan.
    conn.close()


def test_read_scope_invalidates_another_connection_commit(tmp_path):
    from app import partial_refund
    source = _connection()
    _row(source, 'purchase', 'purchase', 20000, approval='100')
    _row(source, 'refund', 'cancellation', -5000, original='100')
    source.commit()
    conn = sqlite3.connect(tmp_path / 'refund.sqlite')
    source.backup(conn)
    source.close()
    writer = sqlite3.connect(tmp_path / 'refund.sqlite')
    try:
        with partial_refund.read_only_scope():
            assert refund_links(conn, ['refund'])['refund']['net_krw'] == 15000
            writer.execute("UPDATE transactions SET amount_krw=-6000 WHERE transaction_id='refund'")
            writer.commit()
            assert refund_links(conn, ['refund'])['refund']['net_krw'] == 14000
    finally:
        writer.close()
        conn.close()
