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
        unassigned_row(board)
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
        assert {k:v for k,v in after.items() if k not in ('display_tab_id','revision')}=={k:v for k,v in record.items() if k not in ('display_tab_id','revision')}
        assert after['display_tab_id']==(trip['tab_id'] if expected else None)
        assert assign_existing_local_expenses(flow)==0
    finally:
        ledger_board.bind_store(None)
        board.close()
