from app.classify import classify_transaction
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD
import pytest


def test_only_reconciled_residual_purchase_uses_the_quarter_policy():
    transaction = dict(card_tail='3820', transaction_kind='purchase', transaction_direction='purchase',
                       merchant='합성 잔여 상점', approval_date='2026-10-01', amount_krw=37000)
    assert classify_transaction(transaction, rules=[])['classification_state'] == 'needs_review'
    result = classify_transaction(transaction, rules=[], residual_policy=True)
    assert result['item'] == '분기 기타비용'
    assert result['description'] == '2026년 4분기 기타비용'
    assert result['trip_id'] == ''
    for changes in ({'card_tail': '1234'}, {'transaction_kind': 'refund'},
                    {'transaction_direction': 'cancellation'}, {'parse_error': 'unreadable'},
                    {'approval_date': 'not-a-date'}):
        assert classify_transaction(dict(transaction, **changes), rules=[], residual_policy=True)['item'] != '분기 기타비용'
    result = classify_transaction(transaction, rules=[], residual_policy=True,
        prior_decision={'item': '기존 확정', 'display_tab_id': 'trip-existing', 'trip_id': 'trip-existing'})
    assert result['item'] == '기존 확정' and result['trip_id'] == 'trip-existing'


def test_ota_residual_hold_can_be_reclassified_when_verified_source_arrives():
    from app.reconciliation import OTA_MAIL_ORIGIN

    transaction = dict(card_tail='3820', transaction_kind='purchase', transaction_direction='purchase',
                       merchant='SYNTHETIC GOTOGATE', merchant_normalized='synthetic gotogate',
                       source_hash='a' * 64, approval_date='2026-10-01', amount_krw=37000)
    held = classify_transaction(transaction, rules=[], residual_policy=True)
    assert held['classification_state'] == 'needs_review'
    assert held['classification_source'] != 'owner_card_residual'

    verified_booking = {
        'conditions': {'merchant_normalized': 'synthetic gotogate'},
        'optional': {'source_hash': transaction['source_hash']},
        'effects': {'item': '항공료', 'description': '합성 예약 증거'},
        'origin': OTA_MAIL_ORIGIN,
        'rule_id': 'synthetic-verified-ota',
    }
    resolved = classify_transaction(transaction, rules=[verified_booking], residual_policy=True)
    assert resolved['classification_state'] == 'classified'
    assert resolved['classification_source'] == 'rule'
    assert resolved['item'] == '항공료'


def test_card_flow_classifies_residual_without_changing_original_or_confirming(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive(CARD.replace(b',1234,', b',3820,'), 'synthetic-3820.csv')['batch_id']
        before = flow.pipeline.get_batch(batch)['rows'][0]
        flow.classify(batch)
        after = flow.pipeline.get_batch(batch)['rows'][0]
        assert after['item'] == '분기 기타비용'
        for field in ('transaction_id', 'source_hash', 'amount_krw', 'approval_date', 'posting_date'):
            assert after[field] == before[field]
        assert after['decided']  # 분류와 기록은 한 동작이라 잔여 거래도 자동으로 장부에 기록된다
        flow.classify(batch)
        assert flow.pipeline.get_batch(batch)['rows'][0]['description'] == '2026년 4분기 기타비용'
        actual_kind = dict(card_tail='3820', transaction_kind='일시불매입', transaction_direction='purchase',
                          merchant='합성 상점', approval_date='2026-04-01', amount_krw=10000)
        assert classify_transaction(actual_kind, rules=[], residual_policy=True)['description'] == '2026년 2분기 기타비용'
    finally:
        board.close()


@pytest.mark.parametrize('protection', ['decided', 'excluded', 'duplicate', 'conflict'])
def test_existing_protected_rows_do_not_receive_residual_policy(tmp_path, monkeypatch, protection):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'protected.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive(CARD.replace(b',1234,', b',3820,'), 'synthetic.csv')['batch_id']
        tid = flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
        if protection == 'decided':
            board.conn.execute("UPDATE transactions SET classification_source='user_decision',item='기존 사용자 분류' WHERE transaction_id=?", (tid,))
        elif protection == 'excluded':
            board.conn.execute("INSERT INTO transaction_company_exclusions VALUES (?, '', 1, 1, '', '')", (tid,))
        elif protection == 'booked':
            board.conn.execute("INSERT INTO ledger_entries VALUES (?,?,'기존 기록','','unclassified','',37000,'합성상점','2026-10-01','purchase','','')", (tid, batch))
        elif protection == 'duplicate':
            board.conn.execute("UPDATE transactions SET duplicate_of='synthetic-other' WHERE transaction_id=?", (tid,))
        else:
            board.conn.execute("UPDATE transactions SET conflict_reason='SOURCE_CONFLICT' WHERE transaction_id=?", (tid,))
        board.conn.commit()
        before = board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
        flow.classify(batch)
        after = flow.pipeline.get_batch(batch)['rows'][0]
        assert after['item'] != '분기 기타비용'
        if protection in ('decided', 'excluded', 'booked'):
            assert board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?', (tid,)).fetchone() == before
    finally:
        board.close()


def test_a_recorded_row_without_a_trip_is_reconciled_by_the_residual_rule(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'recorded.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive(CARD.replace(b',1234,', b',3820,'), 'synthetic.csv')['batch_id']
        tid = flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
        board.conn.execute("INSERT INTO ledger_entries VALUES (?,?,'기존 기록','','unclassified','',37000,'합성상점','2026-10-01','purchase','','')", (tid, batch))
        board.conn.commit()
        flow.classify(batch)
        assert flow.pipeline.get_batch(batch)['rows'][0]['item'] == '분기 기타비용'
    finally:
        board.close()
