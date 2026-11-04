"""Set-based cleanup refund protection preserves SQL NULL/equality semantics."""
import random
import sqlite3

import pytest

from webapp import read_scope
from webapp.card_cleanup_queries import completed_assignment_sql
from app.partial_refund import refund_review_originals


@pytest.mark.parametrize('seed', [7, 19, 101, 509])
def test_refund_membership_matches_correlated_exists_with_nullable_sources(monkeypatch, seed):
    db = sqlite3.connect(':memory:')
    try:
        db.execute('CREATE TABLE transactions(transaction_id,transaction_direction,amount_krw,display_tab_id,issuer,card_tail,approval_number,original_approval_number,merchant_normalized)')
        rng = random.Random(seed)
        rows = [(str(i), rng.choice(['purchase', 'cancellation', 'refund', 'other', None]),
                 rng.choice([-1004, -2000, 0, 1004, 2000, None]),
                 rng.choice(['valid', 'other', '', None]),
                 rng.choice(['issuer-a', 'issuer-b', '', None]),
                 rng.choice(['1234', '5678', '', None]),
                 rng.choice(['A1', 'A2', '', None]),
                 rng.choice(['A1', 'A2', '', None]),
                 rng.choice(['same merchant', 'other merchant', '', None]))
                for i in range(350)]
        rows.extend([
            ('unmatched', 'purchase', 1004, 'valid', 'unique', 'tail', 'A', '', 'store'),
            ('null-issuer', 'purchase', 1004, 'valid', None, 'tail', None, None, None),
            ('null-refund', 'cancellation', -1004, 'valid', None, 'tail', None, None, None),
            ('empty-approval', 'purchase', 1004, 'valid', 'empty', 'tail', '', '', 'purchase'),
            ('empty-reference', 'refund', -1004, 'valid', 'empty', 'tail', '', '', 'refund'),
            ('numbered', 'purchase', 1004, 'valid', 'numbered', 'tail', 'A', '', 'purchase'),
            ('numbered-refund', 'cancellation', -1, 'valid', 'numbered', 'tail', '', 'A', 'refund'),
        ])
        db.executemany('INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?)', rows)
        protected = [row[0] for row in db.execute("""SELECT p.transaction_id FROM transactions p
            WHERE COALESCE(TRIM(p.approval_number),'')!='' AND EXISTS(SELECT 1 FROM transactions c
            WHERE c.issuer=p.issuer AND c.card_tail=p.card_tail
            AND (c.transaction_direction IN ('cancellation','refund') OR c.amount_krw<0)
            AND TRIM(c.original_approval_number)=TRIM(p.approval_number))""")]
        monkeypatch.setattr(read_scope, 'remember', lambda key, compute:
                            ['valid'] if key[0]=='cleanup-completed-trips' else protected)
        optimized = completed_assignment_sql(None)
        reference = """(t.transaction_direction='purchase' AND t.amount_krw>0
            AND COALESCE(t.display_tab_id,'') IN ('valid')
            AND NOT EXISTS(SELECT 1 FROM transactions c
              WHERE c.issuer=t.issuer AND c.card_tail=t.card_tail
              AND (c.transaction_direction IN ('cancellation','refund') OR c.amount_krw<0)
              AND COALESCE(TRIM(t.approval_number),'')!=''
              AND TRIM(c.original_approval_number)=TRIM(t.approval_number)))"""
        before = db.total_changes
        expected = db.execute('SELECT transaction_id FROM transactions t WHERE ' + reference).fetchall()
        assert {('unmatched',), ('null-issuer',), ('empty-approval',)} <= set(expected)
        assert ('numbered',) not in expected
        assert db.execute('SELECT transaction_id FROM transactions t WHERE ' + optimized).fetchall() == expected
        assert db.total_changes == before
    finally:
        db.close()


def test_same_merchant_unrelated_purchase_is_completed_but_foreign_link_stays_protected(monkeypatch):
    from types import SimpleNamespace
    from app import Pipeline
    from tests.card_pipeline.test_partial_refund import HEADER
    pipe=Pipeline(sqlite3.connect(':memory:',isolation_level=None))
    batch=pipe.receive((HEADER+'\n'.join([
        '국민,1234,overseas,purchase,FUKUTAKE FOUNDATION,1000,100,JPY,1000,2026-10-01,2026-10-01,A1,,매입',
        '국민,1234,overseas,purchase,FUKUTAKE FOUNDATION,2000,200,JPY,2000,2026-10-01,2026-10-01,A2,,매입',
        '국민,1234,overseas,purchase,FUKUTAKE FOUNDATION,1000,100,JPY,1000,2026-10-03,2026-10-03,A3,,매입',
        '국민,1234,overseas,purchase,FUKUTAKE FOUNDATION,1000,100,JPY,1000,2026-10-02,2026-10-02,C4,,매입',
    ])+'\n').encode(),'synthetic.csv')['batch_id']
    conn=pipe.store.conn
    rows=pipe.get_batch(batch)['rows']
    ids={r['approval_number']:r['transaction_id'] for r in rows}
    conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-1000,original_approval_number='' WHERE transaction_id=?",(ids['4'],))
    before=conn.total_changes
    protected=refund_review_originals(conn)
    assert ids['1'] in protected
    assert ids['2'] not in protected  # Different foreign amount, same merchant.
    assert ids['3'] not in protected  # Purchase after the refund.
    assert conn.total_changes==before
    # A dirty cancellation still protects matching candidates, without a link.
    conn.execute("UPDATE transactions SET parse_error='synthetic conflict' WHERE transaction_id=?",(ids['4'],))
    assert ids['1'] in refund_review_originals(conn)
    assert ids['2'] not in refund_review_originals(conn)
    conn.close()


def test_ambiguous_domestic_amount_candidates_stay_protected_without_creating_links():
    from types import SimpleNamespace
    from tests.card_pipeline.test_partial_refund import build
    from app.partial_refund import refund_links
    pipe,_=build(gross=1000,refunds=(-1000,-1000),original_ref='')
    conn=pipe.store.conn
    conn.execute("UPDATE transactions SET approval_date='2026-10-01',posting_date='2026-10-01'")
    ids=[r[0] for r in conn.execute("SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
    assert refund_links(conn,ids)=={}
    purchase=conn.execute("SELECT transaction_id FROM transactions WHERE transaction_direction='purchase'").fetchone()[0]
    before=conn.total_changes
    assert purchase in refund_review_originals(conn)
    assert conn.total_changes==before
    conn.close()
