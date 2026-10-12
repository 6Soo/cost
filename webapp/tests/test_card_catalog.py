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
    assert '37,000' in markup and '전체 카드 내역' in markup
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
