import pytest
from webapp import card_catalog
from webapp import card_transactions
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


def test_catalog_and_transaction_detail_keep_refund_states_for_both_rows(stored):
    lines = [
        ('FULL', 1000, -1000),
        ('PART', 1000, -700),
        ('EXCESS', 1000, -1100),
    ]
    header = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
              'Date,Post Date,Authorization Code,Cancel,Status\n')
    records = []
    for name, gross, refund in lines:
        records.append(f'국민,4321,domestic,purchase,합성환불{name},{gross},,,{gross},2026-10-01,2026-10-02,O-{name},,매입')
        records.append(f'국민,4321,domestic,cancellation,합성환불{name},{abs(refund)},,,{abs(refund)},2026-10-03,2026-10-04,R-{name},취소,취소')
    CardFlow(stored).pipeline.receive((header + '\n'.join(records) + '\n').encode('utf-8'), 'refund-ui.csv')
    for name, _gross, refund in lines:
        merchant = f'합성환불{name}'
        purchase_id = stored.conn.execute(
            "SELECT transaction_id FROM transactions WHERE merchant=? AND approval_date='2026-10-01'",
            (merchant,)).fetchone()[0]
        refund_id = stored.conn.execute(
            "SELECT transaction_id FROM transactions WHERE merchant=? AND approval_date='2026-10-03'",
            (merchant,)).fetchone()[0]
        stored.conn.execute("UPDATE transactions SET approval_number=?,transaction_direction='purchase' WHERE transaction_id=?",
                            (f'O-{name}', purchase_id))
        stored.conn.execute(
            "UPDATE transactions SET approval_number=?,transaction_direction='cancellation',amount_krw=?, "
            "original_approval_number=? WHERE transaction_id=?",
            (f'R-{name}', refund, f'O-{name}', refund_id))
    stored.conn.commit()

    catalog_rows = {row['merchant'].removeprefix('합성환불') + ':' + row['transaction_direction']: row
                    for row in card_catalog.catalog(stored, {})['rows']
                    if row['merchant'].startswith('합성환불')}
    expected = {'FULL': ('전액 환불', None),
                'PART': ('환불 상태 확인', '순액 300원'),
                'EXCESS': ('환불 상태 확인', '순액 -100원')}
    for name, (status, reason) in expected.items():
        for direction in ('purchase', 'cancellation'):
            row = catalog_rows[name + ':' + direction]
            detail = card_transactions.transaction_detail(row['transaction_id'], str(stored.path))
            assert row['next_action']['status'] == detail['next_action']['status'] == status
            if reason:
                assert reason in row['next_action']['reason']
                assert reason in detail['next_action']['reason']
            assert row['transaction_id'] == detail['transaction_id']
            assert row['amount_krw'] == detail['amount_krw']


def test_status_filters_partition_rows_and_source_filter_keeps_actual_origin(stored):
    rows = card_catalog.catalog(stored, {})['rows']
    ids = [row['transaction_id'] for row in rows]
    stored.conn.execute("UPDATE transactions SET transaction_direction='purchase',classification_state='classified'")
    stored.conn.execute("UPDATE transactions SET classification_source='inference' WHERE transaction_id=?", (ids[0],))
    stored.conn.execute("UPDATE transactions SET classification_source='ai_inference',duplicate_of=? WHERE transaction_id=?", (ids[0],ids[1]))
    stored.conn.execute("UPDATE transactions SET classification_source='rule' WHERE transaction_id=?", (ids[2],))
    stored.conn.execute("INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) "
        "SELECT transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,approval_date,transaction_direction,source_hash,'synthetic' FROM transactions WHERE transaction_id=?", (ids[0],))
    stored.conn.commit()
    before = stored.conn.total_changes
    groups = {key:card_catalog.catalog(stored, {'state':[key]}) for key in card_catalog.STATES}
    assert all(group['total'] == 1 for group in groups.values())
    for key, group in groups.items():
        assert group['rows'][0]['next_action']['group'] == key
    assert card_catalog.catalog(stored, {'origin':['ai_inference']})['rows'][0]['transaction_id'] == ids[1]
    assert card_catalog.catalog(stored, {'origin':['code_inference']})['rows'][0]['transaction_id'] == ids[0]
    assert stored.conn.total_changes == before


@pytest.mark.parametrize('source,label', [('rule','자동'),('inference','코드 추론'),('ai_inference','AI 추론')])
def test_recording_does_not_turn_automatic_classification_into_a_user_decision(stored, monkeypatch, source, label):
    monkeypatch.setattr(CardFlow,'trip_valid',lambda self,trip:True)
    monkeypatch.setattr(CardFlow,'ota_group_holds',lambda self,**kw:{})
    monkeypatch.setattr(CardFlow,'preview_metadata',lambda self,**kw:None)
    trip=stored.create_trip(starts_on='2026-10-01',ends_on='2026-10-05',
        destination='합성',client_request_id='catalog-source-trip')['tab_id']
    flow=CardFlow(stored)
    tid,batch=stored.conn.execute("SELECT transaction_id,batch_id FROM transactions WHERE amount_krw=37000").fetchone()
    stored.conn.execute("UPDATE transactions SET classification_state='classified',classification_source=?,item='숙박비',display_tab_id=?,trip_id=? WHERE transaction_id=?",(source,trip,trip,tid))
    stored.conn.commit()
    assert flow._auto_record_locked(batch,include_state=False,transaction_ids={tid})['auto_recorded']==1
    before=stored.conn.total_changes
    data=card_catalog.catalog(stored,{})
    data['rows']=[row for row in data['rows'] if row['transaction_id']==tid]
    assert data['rows'][0]['decided'] and data['rows'][0]['decided_at'] is None
    # wave3 #799 retired the duplicate catalog renderer; the provenance label lives in the row projection.
    action=data['rows'][0]['next_action']
    assert action['state_label']=='완료' and action['source_label']==label and action['source_label']!='직접'
    assert stored.conn.total_changes==before
    stored.conn.execute("UPDATE transactions SET classification_source='user_decision',decided_at='2026-11-02T00:00:00Z' WHERE transaction_id=?",(tid,))
    stored.conn.commit()
    data=card_catalog.catalog(stored,{})
    data['rows']=[row for row in data['rows'] if row['transaction_id']==tid]
    assert data['rows'][0]['next_action']['source_label']=='직접'


def test_search_filters_and_pagination_preserve_zero_and_original_amount(stored):
    assert card_catalog.catalog(stored, {'q': ['no match']})['total'] == 0
    assert card_catalog.catalog(stored, {'card': ['1234']})['total'] == 3
    assert card_catalog.catalog(stored, {'card': ["' OR 1=1 --"]})['total'] == 0
    result = card_catalog.catalog(stored, {'page': ['999']})
    assert result['page'] == 1 and result['rows']
    # wave3 #799: the duplicate catalog renderer is retired; it now redirects to /cards/all keeping the query.
    markup = card_catalog.render_html(result, {'card': ['1234']})
    assert "href='/cards/all?card=1234'" in markup
    assert '기록 가능' not in markup


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
    # wave3 #799: the table itself moved to /cards/all; the retired stub only preserves the query.
    assert "href='/cards/all?" in markup and '<select' not in markup
    assert stored.conn.total_changes == before
