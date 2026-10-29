"""Refund history destinations must follow the real tab without changing sources."""
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from webapp import card_transactions as ct, cards_all, refund_tab
from webapp.tests.test_cards_all import card_db_path


@pytest.mark.parametrize('scenario,expected', [
    ('full', True), ('multiple', True), ('partial', False),
    ('excess', False), ('conflict', False), ('ambiguous', False),
])
def test_refund_destination_matches_tab_and_unassigned_counts(card_db_path, monkeypatch, scenario, expected):
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET transaction_direction='purchase', approval_number='SYN100', "
                     "trip_id='', classification_state='preserved' WHERE transaction_id='TX-A-01'")
        conn.execute("UPDATE transactions SET transaction_direction='cancellation', original_approval_number='SYN100', "
                     "amount_krw=?, foreign_amount='', trip_id='', classification_state='preserved' "
                     "WHERE transaction_id='TX-A-02'", (-70000 if scenario in ('partial', 'multiple') else
                                                      -160000 if scenario == 'excess' else -150000,))
        if scenario == 'multiple':
            conn.execute("UPDATE transactions SET transaction_direction='cancellation', issuer='CARD', card_tail='1234', "
                         "original_approval_number='SYN100', amount_krw=-80000, foreign_amount='', trip_id='' "
                         "WHERE transaction_id='TX-B-01'")
        if scenario == 'conflict':
            conn.execute("UPDATE transactions SET conflict_reason='synthetic conflict' WHERE transaction_id='TX-A-02'")
        if scenario == 'ambiguous':
            conn.execute("UPDATE transactions SET transaction_direction='purchase', issuer='CARD', card_tail='1234', "
                         "approval_number='SYN100' WHERE transaction_id='TX-B-01'")
    with closing(sqlite3.connect(card_db_path)) as conn:
        before = conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        members = {r['transaction_id'] for g in refund_tab.groups(SimpleNamespace(conn=conn)) for r in g}
    assert ('TX-A-01' in members) is expected
    result = ct.list_for_month(card_db_path, 2026, 3)
    for row in result['items']:
        assert row['refund_tab_member'] == (row['transaction_id'] in members)
    filtered = ct.list_for_month(card_db_path, 2026, 3, unassigned=True)
    assert not (members & {r['transaction_id'] for r in filtered['items']})
    assert ct.year_summary(card_db_path, 2026, unassigned=True)['months'][3] == len(filtered['items'])
    search = ct.search_for_year(card_db_path, 2026, search='MERCURE')['items'][0]
    assert search['refund_tab_member'] is expected
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({}, set()))
    page = cards_all._render_month_rows([search])
    assert ("href='/board?tab=refunds'" in page) is expected
    assert ('>미배정</span>' in page) is not expected
    if expected:
        assert '실제 환급과 별개' in page and '원본 보존' in page
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        assert before == conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
        conn.execute("UPDATE transactions SET approval_date='' WHERE transaction_id IN ('TX-A-01','TX-A-02')")
    undated = ct.undated_list(card_db_path)['items']
    assert next(r for r in undated if r['transaction_id'] == 'TX-A-01')['refund_tab_member'] is expected
