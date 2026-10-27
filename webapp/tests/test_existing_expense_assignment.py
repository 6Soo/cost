import json
import pytest
from webapp.card_flow import assign_existing_local_expenses
from webapp.ledger_store import LedgerStore
from webapp import ledger_board
from webapp.tests.test_expense_cleanup import card_rows, unassigned_row


@pytest.mark.parametrize('mode,expected', [('local',1),('hotel',0),('manual',0),('decision',0)])
def test_existing_expense_only_gets_a_verified_missing_trip_without_changing_money(tmp_path, monkeypatch, mode, expected):
    board=LedgerStore(tmp_path/'existing.sqlite',seed_demo=False)
    try:
        ledger_board.bind_store(board)
        flow,batch,rows=card_rows(board,1)
        tid=rows[0]['transaction_id']
        trip=board.create_trip(starts_on='2026-10-01',ends_on='2026-10-05',destination='합성',client_request_id='existing-trip')
        unassigned_row(board,confirmed=True)
        record=json.loads(board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0])
        record.update(source_event_id=tid,item='숙박비' if mode=='hotel' else '식비')
        board.conn.execute('UPDATE board_rows SET payload_json=?',(json.dumps(record),))
        board.conn.execute("UPDATE transactions SET card_kind='국내',merchant='식당'")
        if mode=='manual':
            board.conn.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,?,?)",
                               (record['row_id'],'display_tab_id','synthetic-owner'))
        if mode=='decision':
            flow.pipeline.save_decision(tid,rows[0]['revision'],item='식비',description='',display_tab_id='unclassified',
                trip_id='',request_id='existing-owner',trip_validator=lambda _:True,tab_validator=lambda _:True)
        board.conn.commit()
        monkeypatch.setattr(flow,'retail_trip',lambda *_:trip['tab_id'])
        monkeypatch.setattr(flow,'trip_valid',lambda _:True)
        assert assign_existing_local_expenses(flow)==expected
        after=json.loads(board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0])
        assert {k:v for k,v in after.items() if k not in ('display_tab_id','revision','operator_note')}=={k:v for k,v in record.items() if k not in ('display_tab_id','revision','operator_note')}
        assert after['display_tab_id']==(trip['tab_id'] if expected else None)
        if expected:
            assert '자동 추론' in after['operator_note']
            assert board.conn.execute('SELECT COUNT(*) FROM board_manual_overrides').fetchone()[0]==0
            assert board.conn.execute('SELECT COUNT(*) FROM board_learning_cases').fetchone()[0]==0
        assert assign_existing_local_expenses(flow)==0
    finally:
        ledger_board.bind_store(None)
        board.close()


def test_confirmed_unassigned_expense_is_complete_without_inventing_a_trip(tmp_path):
    from webapp.card_flow import CardFlow,cleanup_total
    board=LedgerStore(tmp_path/'complete.sqlite',seed_demo=False)
    try:
        CardFlow(board)
        unassigned_row(board,confirmed=True)
        before=board.conn.execute('SELECT * FROM board_rows').fetchall()
        assert cleanup_total(board)==0
        assert board.conn.execute('SELECT * FROM board_rows').fetchall()==before
    finally:
        board.close()


@pytest.mark.parametrize('item,merchant,expected', [('식비','식당',1),('숙박비','숙소',0),('교통비','철도승차권 발매',0)])
def test_clear_local_cost_can_be_recorded_unassigned_but_reservations_need_service_evidence(tmp_path,monkeypatch,item,merchant,expected):
    from webapp.card_flow import CardFlow,reclassify_cleanup,cleanup_total
    board=LedgerStore(tmp_path/'unassigned-card.sqlite',seed_demo=False)
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    try:
        flow,batch,rows=card_rows(board,1)
        board.conn.execute("UPDATE transactions SET item=?,merchant=?,merchant_normalized=?,display_tab_id='unclassified'",(item,merchant,merchant))
        board.conn.commit()
        monkeypatch.setattr(CardFlow,'_classify',lambda *args,**kwargs: {})
        monkeypatch.setattr(CardFlow,'_ota_report',lambda _:None)
        monkeypatch.setattr(CardFlow,'_guide_airfare_rules',lambda *args:[])
        result=reclassify_cleanup(board)
        assert result['recorded']==expected
        assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]==expected
        assert cleanup_total(board)==(0 if expected else 1)
        if expected:
            saved=json.loads(board.conn.execute('SELECT payload_json FROM board_rows').fetchone()[0])
            assert saved['display_tab_id'] is None and saved['amount_krw']==5000
            assert reclassify_cleanup(board)['recorded']==0
    finally:
        board.close()


def test_cancelled_charge_is_a_reconciliation_case_not_a_category_question(tmp_path,monkeypatch):
    from webapp import card_flow
    board=LedgerStore(tmp_path/'cancelled.sqlite',seed_demo=False)
    try:
        ledger_board.bind_store(board)
        flow,batch,rows=card_rows(board,1)
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-5000,item='' ")
        board.conn.commit()
        before=board.conn.execute('SELECT * FROM transactions').fetchall()
        monkeypatch.setattr(card_flow,'_ota_entries_by_card',lambda _, **kw: {})
        assert card_flow._cleanup_card_breakdown(board)=={'protected':1}
        html=card_flow.render_expense_cleanup(board,'token')
        assert '취소·환불 확인' in html and '원결제 근거가 필요' in html
        assert '가맹점을 하나씩 입력할 목록이 아닙니다' in html
        assert "<input name='item'" not in html
        assert board.conn.execute('SELECT * FROM transactions').fetchall()==before
    finally:
        ledger_board.bind_store(None)
        board.close()
