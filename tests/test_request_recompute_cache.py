"""Refund pairing and the OTA input key are not recomputed per request; a changed input always recomputes."""
import sqlite3
from types import SimpleNamespace

import pytest

from app import partial_refund
from tests.card_pipeline.test_partial_refund import build


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv('WEBLEDGER_LINKS_PRODUCER', raising=False)
    partial_refund._COMMITTED.clear()
    partial_refund._STAMPS.clear()


@pytest.fixture
def counted(monkeypatch):
    calls = []
    real = partial_refund._analyse
    monkeypatch.setattr(partial_refund, '_analyse', lambda conn: calls.append(1) or real(conn))
    return calls


def ids(conn):
    return [r[0] for r in conn.execute('SELECT transaction_id FROM transactions')]


def test_a_repeat_read_and_another_connections_unrelated_commit_do_not_rederive_the_pairs(counted, tmp_path):
    path = tmp_path / 'board.sqlite'
    disk = sqlite3.connect(path, isolation_level=None)
    build()[0].store.conn.backup(disk)
    writer = sqlite3.connect(path, isolation_level=None)
    first = partial_refund.all_refund_links(disk)
    assert first and len(counted) == 1
    partial_refund.refund_links(disk, ids(disk))
    writer.execute('CREATE TABLE unrelated(x)')
    writer.execute('INSERT INTO unrelated VALUES (1)')
    writer.execute("UPDATE transactions SET item='다른 항목'")
    assert partial_refund.all_refund_links(disk) == first
    assert len(counted) == 1


@pytest.mark.parametrize('change', [
    "UPDATE transactions SET original_approval_number='999' WHERE transaction_direction='cancellation'",
    "UPDATE transactions SET duplicate_of=transaction_id WHERE transaction_direction='cancellation'",
    "UPDATE transactions SET conflict_reason='x' WHERE transaction_direction='cancellation'",
    "UPDATE transactions SET amount_krw=amount_krw-1 WHERE transaction_direction='cancellation'",
])
def test_a_changed_pairing_column_rederives_with_the_uncached_result(counted, change):
    conn = build()[0].store.conn
    before = partial_refund.all_refund_links(conn)
    conn.execute(change)
    after = partial_refund.all_refund_links(conn)
    assert len(counted) == 2
    assert after == partial_refund._analyse(conn)[0]
    assert after != before


def test_uncommitted_rows_are_never_kept_and_a_rollback_restores_the_committed_answer(counted):
    conn = build()[0].store.conn
    committed = partial_refund.all_refund_links(conn)
    conn.execute('BEGIN')
    conn.execute("UPDATE transactions SET original_approval_number='999' WHERE transaction_direction='cancellation'")
    inside = partial_refund.all_refund_links(conn)
    assert inside != committed
    inside_again = partial_refund.all_refund_links(conn)
    assert inside_again == inside and len(counted) == 3
    conn.execute('ROLLBACK')
    assert partial_refund.all_refund_links(conn) == committed
    assert len(partial_refund._COMMITTED) == 1


def test_another_connection_commit_of_a_pairing_column_rederives(counted, tmp_path):
    path = tmp_path / 'board.sqlite'
    pipe, _ = build()
    disk = sqlite3.connect(path, isolation_level=None)
    pipe.store.conn.backup(disk)
    reader, writer = disk, sqlite3.connect(path, isolation_level=None)
    before = partial_refund.all_refund_links(reader)
    writer.execute('CREATE TABLE unrelated(x)')
    assert partial_refund.all_refund_links(reader) == before and len(counted) == 1
    writer.execute("UPDATE transactions SET original_approval_number='999' WHERE transaction_direction='cancellation'")
    assert partial_refund.all_refund_links(reader) != before and len(counted) == 2


def backend_for(conn, calls):
    def rows():
        calls.append(1)
        cursor = conn.execute('SELECT * FROM transactions ORDER BY rowid')
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, r)) for r in cursor.fetchall()]
    return SimpleNamespace(store=SimpleNamespace(), sources={}, payments=SimpleNamespace(), _transactions=rows,
                           board=SimpleNamespace(conn=conn))


def test_the_input_key_is_not_recomputed_until_a_stored_input_changes(monkeypatch):
    from webapp import ota_payment_review as review
    monkeypatch.setattr(review, '_guide_input_digest', lambda _: 'synthetic')
    review._TX_DIGESTS.clear()
    review._TX_STAMPS.clear()
    conn = build()[0].store.conn
    calls = []
    backend = backend_for(conn, calls)
    key = review.input_key_for(backend)
    assert review.input_key_for(backend) == key and len(calls) == 1
    conn.execute('CREATE TABLE unrelated(x)')
    conn.execute("INSERT INTO unrelated VALUES (1)")
    assert review.input_key_for(backend) == key and len(calls) == 1
    conn.execute("UPDATE transactions SET item='바뀐 항목'")
    changed = review.input_key_for(backend)
    assert changed != key and len(calls) == 2
    conn.execute("UPDATE transactions SET amount_krw=amount_krw+1 WHERE rowid=1")
    assert review.input_key_for(backend) != changed and len(calls) == 3
    fresh_backend = backend_for(conn, [])
    review._TX_DIGESTS.clear()
    review._TX_STAMPS.clear()
    assert review.input_key_for(fresh_backend) == review.input_key_for(backend)


def test_the_input_key_keeps_nothing_from_an_open_transaction(monkeypatch):
    from webapp import ota_payment_review as review
    monkeypatch.setattr(review, '_guide_input_digest', lambda _: 'synthetic')
    review._TX_DIGESTS.clear()
    review._TX_STAMPS.clear()
    conn = build()[0].store.conn
    calls = []
    backend = backend_for(conn, calls)
    committed = review.input_key_for(backend)
    conn.execute('BEGIN')
    conn.execute("UPDATE transactions SET amount_krw=amount_krw+5 WHERE rowid=1")
    inside = review.input_key_for(backend)
    assert inside != committed and len(calls) == 2
    assert review.input_key_for(backend) == inside and len(calls) == 3
    conn.execute('ROLLBACK')
    assert review.input_key_for(backend) == committed


def test_refund_tab_groups_equal_the_full_table_derivation():
    from webapp import refund_tab, refund_tab_ui
    pipe, _ = build(refunds=(-300000, -700000), extra=True)
    conn = pipe.store.conn
    records = conn.execute(
        "SELECT transaction_id, merchant, amount_krw, COALESCE(NULLIF(approval_date,''),posting_date), item "
        "FROM transactions ORDER BY transaction_id").fetchall()
    sources = {r[0]: dict(transaction_id=r[0], merchant=r[1], amount_krw=r[2], occurred_on=r[3], item=r[4])
               for r in records}
    links = partial_refund.refund_links(conn, list(sources))
    expected = refund_tab_ui.assemble_refund_groups(sources, links, is_preserved_fn=lambda periods: False)
    assert expected and refund_tab.groups(SimpleNamespace(conn=conn)) == expected


def test_a_new_connection_never_reuses_a_closed_connections_stamp(monkeypatch, tmp_path):
    from webapp import ota_payment_review as review
    monkeypatch.setattr(review, '_guide_input_digest', lambda _: 'synthetic')
    review._TX_DIGESTS.clear()
    review._TX_STAMPS.clear()
    path = tmp_path / 'board.sqlite'
    seed = sqlite3.connect(path, isolation_level=None)
    build()[0].store.conn.backup(seed)
    seed.close()
    other = sqlite3.connect(path, isolation_level=None)
    first = sqlite3.connect(path, isolation_level=None)
    key = review.input_key_for(backend_for(first, []))
    first.close()
    del first
    other.execute("UPDATE transactions SET amount_krw=amount_krw+1 WHERE rowid=1")
    second = sqlite3.connect(path, isolation_level=None)
    assert review.input_key_for(backend_for(second, [])) != key
