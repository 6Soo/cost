from app.classify import classify_transaction
import pytest


def transaction(**changes):
    return dict(dict(card_tail='3820', transaction_kind='purchase',
                     transaction_direction='purchase', merchant='합성 상점',
                     approval_date='2026-09-19', posting_date='2026-10-01',
                     amount_krw=37000), **changes)


def resolve(row, request):
    return 'trip-singapore' if request == {'owner_card3820_singapore': True} else ''


def test_owner_period_overrides_quarter_without_changing_source():
    for date in ('2026-09-19', '2026-09-24'):
        row = transaction(approval_date=date)
        before = dict(row)
        result = classify_transaction(row, rules=[], residual_policy=True, trip_resolver=resolve)
        assert result['trip_id'] == result['display_tab_id'] == 'trip-singapore'
        assert result['classification_source'] == 'user_exception'
        assert result['item'] == '현지경비'
        assert row == before
    result = classify_transaction(transaction(merchant='택시'), rules=[],
                                  residual_policy=True, trip_resolver=resolve)
    assert result['item'] == '택시비'


def test_period_card_year_and_existing_decision_boundaries():
    for change in ({'approval_date': '2026-09-18'}, {'approval_date': '2026-09-25'},
                   {'approval_date': '2025-09-19'}, {'card_tail': '1234'},
                   {'transaction_direction': 'cancellation'}, {'transaction_kind': '승인'},
                   {'parse_error': 'unreadable'}, {'amount_krw': -10}):
        result = classify_transaction(transaction(**change), rules=[], residual_policy=True,
                                      trip_resolver=resolve)
        assert result['trip_id'] != 'trip-singapore'
    result = classify_transaction(transaction(), rules=[], residual_policy=True,
        trip_resolver=resolve, prior_decision={'item': '기존 확정', 'trip_id': 'existing'})
    assert result['trip_id'] == 'existing'
    assert classify_transaction(transaction(), rules=[], residual_policy=True,
        trip_resolver=lambda *_: '')['trip_id'] == ''


@pytest.mark.parametrize('protection', ['', 'confirmed', 'booked', 'excluded', 'hold', 'duplicate'])
def test_card_flow_assignment_and_protected_originals(tmp_path, monkeypatch, protection):
    from webapp.card_flow import CardFlow
    from webapp.ledger_store import LedgerStore
    from webapp.tests.test_card_flow import CARD
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        trip = board.create_trip(starts_on='2026-09-19', ends_on='2026-09-24',
            destination='싱가포르', client_request_id='synthetic-singapore')
        flow = CardFlow(board)
        monkeypatch.setattr(flow, 'trip_valid', lambda target: target == trip['tab_id'])
        batch = flow.pipeline.receive(CARD.replace(b',1234,', b',3820,').replace(
            b'2026-10-01', b'2026-09-19'), 'synthetic.csv')['batch_id']
        tid = flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
        if protection == 'confirmed':
            board.conn.execute('UPDATE transactions SET user_confirmed=1 WHERE transaction_id=?', (tid,))
        elif protection == 'booked':
            board.conn.execute("INSERT INTO ledger_entries VALUES (?,?,'기존 기록','','unclassified','',37000,'합성상점','2026-09-19','purchase','','')", (tid, batch))
        elif protection == 'excluded':
            board.conn.execute("INSERT INTO transaction_company_exclusions VALUES (?, '', 1, 1, '', '')", (tid,))
        elif protection == 'hold':
            board.conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,'user_hold','합성 보류')",
                               (tid, flow.pipeline.get_batch(batch)['rows'][0]['source_hash']))
        elif protection == 'duplicate':
            board.conn.execute("UPDATE transactions SET duplicate_of='synthetic-other' WHERE transaction_id=?", (tid,))
        board.conn.commit()
        before = flow.pipeline.get_batch(batch)['rows'][0]
        flow.classify(batch)
        after = flow.pipeline.get_batch(batch)['rows'][0]
        assert after['trip_id'] == (trip['tab_id'] if not protection else '')
        for field in ('transaction_id', 'source_hash', 'amount_krw', 'approval_date',
                      'posting_date', 'raw_row', 'user_confirmed', 'revision'):
            assert after[field] == before[field]
        flow.classify(batch)
        assert flow.pipeline.get_batch(batch)['rows'][0] == after
    finally:
        board.close()
