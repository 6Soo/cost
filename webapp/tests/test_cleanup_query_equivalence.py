"""Set-based cleanup refund protection preserves SQL NULL/equality semantics."""
import random
import sqlite3

import pytest

from webapp import read_scope
from webapp.card_cleanup_queries import completed_assignment_sql


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
        monkeypatch.setattr(read_scope, 'remember', lambda key, compute: ['valid'])
        optimized = completed_assignment_sql(None)
        reference = """(t.transaction_direction='purchase' AND t.amount_krw>0
            AND COALESCE(t.display_tab_id,'') IN ('valid')
            AND NOT EXISTS(SELECT 1 FROM transactions c
              WHERE c.issuer=t.issuer AND c.card_tail=t.card_tail
              AND (c.transaction_direction IN ('cancellation','refund') OR c.amount_krw<0)
              AND ((COALESCE(t.approval_number,'')!='' AND c.original_approval_number=t.approval_number)
                   OR c.merchant_normalized=t.merchant_normalized)))"""
        before = db.total_changes
        expected = db.execute('SELECT transaction_id FROM transactions t WHERE ' + reference).fetchall()
        assert {('unmatched',), ('null-issuer',), ('empty-approval',)} <= set(expected)
        assert ('numbered',) not in expected
        assert db.execute('SELECT transaction_id FROM transactions t WHERE ' + optimized).fetchall() == expected
        assert db.total_changes == before
    finally:
        db.close()
