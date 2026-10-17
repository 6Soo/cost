import pytest
from webapp import card_catalog
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD, PAIR


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    flow = CardFlow(board)
    flow.pipeline.receive(CARD, 'one.csv')
    flow.pipeline.receive(PAIR, 'two.csv')
    yield board
    board.close()


def test_catalog_reads_every_batch_without_writing_or_hiding_refunds(stored):
    before = stored.conn.total_changes
    result = card_catalog.catalog(stored, {})
    assert result['total'] == 3 and len(result['rows']) == 3
    assert len({r['batch_id'] for r in result['rows']}) == 2
    assert 'cancellation' in {r['transaction_direction'] for r in result['rows']}
    assert stored.conn.total_changes == before
    assert all('raw_row_json' not in r for r in result['rows'])


def test_search_filters_and_pagination_preserve_zero_and_original_amount(stored):
    assert card_catalog.catalog(stored, {'q': ['no match']})['total'] == 0
    assert card_catalog.catalog(stored, {'card': ['1234']})['total'] == 3
    assert card_catalog.catalog(stored, {'card': ["' OR 1=1 --"]})['total'] == 0
    result = card_catalog.catalog(stored, {'page': ['999']})
    assert result['page'] == 1 and result['rows']
    markup = card_catalog.render_html(result, {})
    assert '37,000' in markup and '<h1>지출 정리 · 모든 자료</h1>' in markup
    assert '전체 카드 내역' not in markup
    assert '기록 가능' not in markup
    assert 'batch=' in markup


def test_all_pages_are_reachable_without_repeating_transactions(stored):
    header, line = CARD.decode('utf-8').splitlines()
    contents = header + '\n' + '\n'.join(line.replace('A123', f'PAGE{i:04}') for i in range(51)) + '\n'
    CardFlow(stored).pipeline.receive(contents.encode('utf-8'), 'pages.csv')
    first = card_catalog.catalog(stored, {})
    second = card_catalog.catalog(stored, {'page': ['2']})
    assert first['total'] == 54 and first['pages'] == 2
    assert len(first['rows']) == 50 and len(second['rows']) == 4
    assert not ({r['transaction_id'] for r in first['rows']} & {r['transaction_id'] for r in second['rows']})


def test_date_sort_month_filter_and_links_are_read_only(stored, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    ids = [r[0] for r in stored.conn.execute('SELECT transaction_id FROM transactions ORDER BY transaction_id')]
    for txid, approval, posting in zip(ids, ['2026-02-20', '2026-01-05', ''],
                                     ['2026-03-01', '2026-02-01', '2026-02-10']):
        stored.conn.execute('UPDATE transactions SET approval_date=?,posting_date=? WHERE transaction_id=?',
                            (approval, posting, txid))
    stored.conn.commit()
    before = stored.conn.total_changes
    assert [r['transaction_id'] for r in card_catalog.catalog(stored, {'sort': ['asc']})['rows']] == [ids[1], ids[2], ids[0]]
    assert [r['transaction_id'] for r in card_catalog.catalog(stored, {})['rows']] == [ids[1], ids[2], ids[0]]
    assert [r['transaction_id'] for r in card_catalog.catalog(stored, {'sort': ['desc']})['rows']] == [ids[0], ids[2], ids[1]]
    query = {'month': ['2026-02'], 'sort': ['asc'], 'card': ['1234']}
    result = card_catalog.catalog(stored, query)
    assert result['total'] == 2
    assert [r['transaction_id'] for r in result['rows']] == [ids[2], ids[0]]
    assert result['months'] == ['2026-01', '2026-02']
    assert card_catalog.catalog(stored, {**query, 'q': ['no match']})['total'] == 0
    assert card_catalog.catalog(stored, {'sort': ['asc; DELETE FROM transactions']})['total'] == 3
    monkeypatch.setattr(card_catalog, 'PAGE_SIZE', 1)
    result = card_catalog.catalog(stored, query)
    markup = card_catalog.render_html(result, query)
    assert 'month=2026-02' in markup and 'sort=asc' in markup and 'card=1234' in markup
    assert '<thead' in markup and "class='header-button'" in markup
    assert "aria-label='거래일'" in markup and '<select' not in markup
    assert stored.conn.total_changes == before
