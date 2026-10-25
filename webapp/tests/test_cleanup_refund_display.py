"""환불 표시만 검사하며 금융 연결/기장 로직은 기존 함수를 사용한다."""
import pytest

from app.partial_refund import refund_links
from webapp.card_flow import CardFlow, _render_refund_evidence
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


@pytest.mark.parametrize('scenario,expected', [
    ('missing', '원결제 자료 미확인'), ('ambiguous', '후보를 하나로 정할 수 없습니다'),
    ('conflict', '원본 충돌'), ('linked', '환불 기록 처리 대기'),
    ('recorded', '환불 기록 완료'), ('excess', '원결제를 초과'),
])
def test_refund_display_separates_source_pair_and_recording(tmp_path, scenario, expected):
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            '국민,1234,domestic,purchase,합성숙박,625280,,,625280,2026-09-22,2026-09-23,A100,,매입\n' +
            '국민,1234,domestic,purchase,합성숙박,625280,,,625280,2026-09-22,2026-09-23,A200,,매입\n').encode(), 'synthetic.csv')['batch_id']
        rows = flow.pipeline.get_batch(batch)['rows']
        original = next(r['transaction_id'] for r in rows if r['approval_number'] == '100')
        refund = next(r['transaction_id'] for r in rows if r['approval_number'] == '200')
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,original_approval_number=? WHERE transaction_id=?",
                           (-700000 if scenario == 'excess' else -625280, '999' if scenario == 'missing' else '100', refund))
        if scenario == 'ambiguous':
            board.conn.execute("INSERT INTO transactions SELECT " + ','.join(
                "'synthetic-other'" if c[1] == 'transaction_id' else c[1]
                for c in board.conn.execute('PRAGMA table_info(transactions)')) + ' FROM transactions WHERE transaction_id=?', (original,))
        if scenario == 'conflict':
            board.conn.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (original,))
        if scenario == 'recorded':
            for row in (original, refund):
                board.conn.execute("INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) SELECT transaction_id,batch_id,'숙박비','','refunds','',amount_krw,merchant,approval_date,transaction_direction,source_hash,'2026-10-24' FROM transactions WHERE transaction_id=?", (row,))
        board.conn.commit()
        before = board.conn.total_changes
        link = refund_links(board.conn, [refund]).get(refund)
        markup = _render_refund_evidence(board, refund, link)
        assert expected in markup
        assert original not in markup
        assert board.conn.total_changes == before
        assert '<li><li>' not in markup
    finally:
        board.close()
