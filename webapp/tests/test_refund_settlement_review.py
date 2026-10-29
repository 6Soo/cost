from app.review import save_decision
from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.refund_tab import render_settlement_review


def test_reviewed_unlinked_and_held_rows_remain_visible_without_financial_writes(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    board=LedgerStore(tmp_path/'synthetic.sqlite',seed_demo=False)
    try:
        flow=CardFlow(board)
        batch=flow.pipeline.receive(make_csv([domestic_row(merchant='<SYNTHETIC>',amount=40000,approval='SETTLEMENT')]),'synthetic.csv')['batch_id']
        row=flow.pipeline.get_batch(batch)['rows'][0]
        tid=row['transaction_id']
        board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',(tid,row['source_hash'],'cancelled','refund not verified'))
        save_decision(flow.pipeline.store,tid,row['revision'],item='취소·환불',display_tab_id='refunds',
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
        assert list(board.conn.iterdump())==before
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==0
    finally:
        board.close()
