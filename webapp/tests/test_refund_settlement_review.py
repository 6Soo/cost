import pytest

from app.review import save_decision
from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp.card_flow import CardFlow
from webapp.refund_tab import render_settlement_review
from webapp.tests.test_plush_api import bound_store, call  # noqa: F401


@pytest.mark.parametrize('destination', ['refunds', 'unclassified'])
def test_reviewed_unlinked_and_held_rows_remain_visible_without_financial_writes(bound_store, monkeypatch, destination):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    board, access = bound_store
    access.create_account(user_id='syn-viewer', role='viewer', is_synthetic=True)
    flow=CardFlow(board)
    batch=flow.pipeline.receive(make_csv([domestic_row(merchant='<SYNTHETIC>',amount=40000,approval='SETTLEMENT')]),'synthetic.csv')['batch_id']
    row=flow.pipeline.get_batch(batch)['rows'][0]
    tid=row['transaction_id']
    board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',(tid,row['source_hash'],'cancelled','refund not verified'))
    save_decision(flow.pipeline.store,tid,row['revision'],item='취소·환불',display_tab_id=destination,
                  description='잔액 40,000원 · 성격 미확인',note='agent review; no refund confirmation',
                  request_id='synthetic-settlement-review',tab_validator=flow.tab_valid)
    before=list(board.conn.iterdump())
    html=render_settlement_review(board)
    assert '취소 정산 확인 중 · 1건' in html
    assert '&lt;SYNTHETIC&gt;' in html and '<SYNTHETIC>' not in html
    assert '실제 환급 완료를 뜻하지 않습니다' in html
    assert 'refund not verified' in html
    assert '내부 장부 미기록' in html
    assert render_settlement_review(board,{tid})==''
    assert render_settlement_review(board,query='no match')==''
    assert render_settlement_review(board,kind='in')==''
    endpoint = '/api/plush/transactions?view=refunds'
    status, payload = call(endpoint + '&q=agent+review&kind=ex', 'syn-owner', board)
    assert status == 200
    assert payload['rows'] == [] and payload['total_count'] == 0
    assert len(payload['settlement_review']) == 1
    review = payload['settlement_review'][0]
    assert review['id'] == tid
    assert review['merchant'] == '<SYNTHETIC>'
    assert review['amount'] == '40000'
    assert review['status'] == '내부 장부 미기록'
    assert review['hold'] == 'refund not verified'
    assert review['note'] == 'agent review; no refund confirmation'
    assert review['source_href'] == '/board?row=card-' + tid
    assert call(endpoint + '&kind=in', 'syn-owner', board)[1]['settlement_review'] == []
    assert call(endpoint + '&q=no+match', 'syn-owner', board)[1]['settlement_review'] == []
    assert call(endpoint, 'syn-viewer', board)[0] == 403
    assert list(board.conn.iterdump())==before
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
