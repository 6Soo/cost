"""Legacy export conflicts do not become duplicate work or weaken source guards."""
from unittest.mock import patch

import pytest

from app.card_export_profiles import redundant_purchase_conflicts
from tests.card_pipeline.test_export_downloads import legacy_domestic, domestic_usage
from webapp import ledger_board
from webapp.card_flow import CardFlow, cleanup_total, _cleanup_card_items, _cleanup_card_breakdown, render_expense_cleanup
from webapp.ledger_store import LedgerStore


@pytest.fixture
def context(tmp_path):
    board=LedgerStore(tmp_path/'source-conflicts.sqlite',seed_demo=False)
    ledger_board.bind_store(board)
    pipe=CardFlow(board).pipeline
    pipe.receive(legacy_domestic(),'legacy.csv')
    original=board.conn.execute('SELECT transaction_id FROM transactions').fetchone()[0]
    with patch('app.card_export_profiles.existing_purchase',return_value=(original,False)):
        batch=pipe.receive(domestic_usage(merchant='합성상점 서울'),'usage.csv')['batch_id']
    conflict=pipe.get_batch(batch)['rows'][0]['transaction_id']
    board.conn.execute("UPDATE transactions SET classification_state='classified',item='현지경비',classification_basis='complete-card-inference-v1' WHERE transaction_id=?",(original,))
    board.conn.commit()
    try:
        yield board,pipe,original,conflict
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_cleanup_count_rows_breakdown_and_render_share_readonly_verified_duplicate_projection(context):
    board,pipe,original,conflict=context
    changed=pipe.receive(domestic_usage(amount=11000),'actual-amount-change.csv')['batch_id']
    actual=pipe.get_batch(changed)['rows'][0]['transaction_id']
    before=list(board.conn.iterdump())
    assert redundant_purchase_conflicts(board.conn)==[conflict]
    assert cleanup_total(board)==1
    assert {row[0] for row in _cleanup_card_items(board)}=={actual}
    assert _cleanup_card_breakdown(board)=={'evidence':1}
    markup=render_expense_cleanup(board,'synthetic')
    assert f"data-transaction='{actual}'" in markup
    assert f"data-transaction='{conflict}'" not in markup
    assert list(board.conn.iterdump())==before


@pytest.mark.parametrize('guard',['manual','hold','parse','source-change','missing-source','corrupt-blob','ambiguous-original'])
def test_duplicate_projection_preserves_manual_dirty_missing_and_ambiguous_source_guards(context,guard):
    board,pipe,original,conflict=context
    if guard=='manual':
        board.conn.execute("UPDATE transactions SET classification_source='user_decision' WHERE transaction_id=?",(conflict,))
    elif guard=='hold':
        board.conn.execute("INSERT INTO transaction_review_holds SELECT transaction_id,source_hash,'user_hold','synthetic' FROM transactions WHERE transaction_id=?",(conflict,))
    elif guard=='parse':
        board.conn.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?",(conflict,))
    elif guard=='source-change':
        board.conn.execute("UPDATE transactions SET source_hash='changed-source' WHERE transaction_id=?",(conflict,))
    elif guard=='missing-source':
        board.conn.execute("UPDATE import_batches SET content_bytes=X'' WHERE batch_id=(SELECT batch_id FROM transactions WHERE transaction_id=?)",(original,))
    elif guard=='corrupt-blob':
        batch=board.conn.execute('SELECT batch_id FROM transactions WHERE transaction_id=?',(original,)).fetchone()[0]
        content=board.conn.execute('SELECT content_bytes FROM import_batches WHERE batch_id=?',(batch,)).fetchone()[0]
        board.conn.execute('UPDATE import_batches SET content_bytes=? WHERE batch_id=?',(content+b'\n',batch))
    elif guard=='ambiguous-original':
        from tests.card_pipeline.test_export_downloads import make_csv,HANA_USAGE,hana_usage
        extra=hana_usage(amount=12000,fee=0);extra[6]='00002222'
        batch=pipe.receive(make_csv([extra],headers=HANA_USAGE),'competitor.csv')['batch_id']
        board.conn.execute("UPDATE transactions SET approval_number='00001111' WHERE batch_id=?",(batch,))
    board.conn.commit()
    before=list(board.conn.iterdump())
    assert redundant_purchase_conflicts(board.conn)==[]
    assert list(board.conn.iterdump())==before
