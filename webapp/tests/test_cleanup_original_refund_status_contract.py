"""Protect the distinction between OTA evidence and settled refund linkage."""
from webapp import card_flow
from webapp.tests.test_refund_inference_runtime import context


def test_cleanup_original_shows_refund_offset_even_if_ota_refreshing(context, monkeypatch):
    store, flow, batch, original, refund = context
    store.conn.execute('UPDATE transactions SET original_approval_number=? WHERE transaction_id=?',
                       ('100', refund))
    store.conn.commit()
    # A downstream review hold can carry a legacy trip/item prompt onto a
    # refund row even though this page renders the refund group read-only.
    monkeypatch.setattr(type(flow), 'automatic_holds', lambda self, _batch_id: {
        refund: {'kind': 'review_hold', 'reason': '비용 항목과 배정 내용을 확인해 주세요.'}
    })
    before = list(store.conn.iterdump())
    markup = card_flow.render_expense_cleanup(store, 'synthetic-csrf')
    assert markup.count(f"data-transaction='{original}'") == 1
    assert markup.count(f"data-transaction='{refund}'") == 1
    assert '환불 상쇄 확인' in markup
    assert '원승인번호 기준 원결제 확정 연결' in markup
    assert '여행·항목을 확인하고 변경 저장을 눌러 주세요.' not in markup
    assert '금융 관계 원행은 이 목록에서 여행·항목을 변경하지 않습니다.' in markup
    assert store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    assert list(store.conn.iterdump()) == before
