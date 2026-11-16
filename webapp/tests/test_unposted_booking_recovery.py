import pytest

from app import automatic_classification as policy
from app.closed_period import recoverable_unrecorded_booking, excluded_ids
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def prepare(board, row):
    board.conn.execute("UPDATE transactions SET approval_date='2026-02-10',posting_date='2026-02-11',"
                       "classification_source='inference',classification_state='classified',"
                       "item='항공료',trip_id='OLD',display_tab_id='OLD' WHERE transaction_id=?",(row['transaction_id'],))
    trips = TRIPS + [dict(trip_id='OLD',starts_on='2026-02-09',ends_on='2026-02-14')]
    fact = dict(source_hash=row['source_hash'],trip_id='A',item='항공료',basis='synthetic original booking',
                formal_link=True,service_period=dict(starts_on='2026-10-01',ends_on='2026-10-05'))
    return trips, fact


def test_unposted_calendar_guess_recovers_with_formal_open_booking(setup):
    board,_,_,rows=setup
    row=rows[0];tid=row['transaction_id'];trips,fact=prepare(board,row)
    facts={tid:fact}
    assert tid not in excluded_ids(board.conn,trips,evidence=facts)
    plan=policy.plan(board.conn,trips,transaction_ids=[tid],evidence=facts)
    assert plan['summary']['to_classify']==1
    before=board.conn.execute('SELECT source_hash,amount_krw,raw_row_json FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    policy.apply(board.conn,plan,trips,transaction_ids=[tid],evidence=facts)
    assert board.conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?',(tid,)).fetchone()==('A',)
    assert board.conn.execute('SELECT source_hash,amount_krw,raw_row_json FROM transactions WHERE transaction_id=?',(tid,)).fetchone()==before
    assert not board.conn.execute('SELECT 1 FROM ledger_entries WHERE transaction_id=?',(tid,)).fetchone()


@pytest.mark.parametrize('guard',['posted','manual','source','informal','period','refund','conflict','duplicate'])
def test_recovery_does_not_weaken_financial_or_original_protections(setup, guard):
    board,_,_,rows=setup
    row=rows[0];trips,fact=prepare(board,row)
    current=policy._read(board.conn,{row['transaction_id']})[0]
    options=dict(recorded=False,manual=False,evidence=fact)
    if guard=='posted':options['recorded']=True
    elif guard=='manual':options['manual']=True
    elif guard=='source':fact['source_hash']='changed'
    elif guard=='informal':fact['formal_link']=False
    elif guard=='period':fact['service_period']['ends_on']='2026-10-99'
    elif guard=='refund':current['transaction_direction']='cancellation'
    elif guard=='conflict':current['conflict_reason']='source conflict'
    elif guard=='duplicate':current['duplicate_of']='other'
    assert not recoverable_unrecorded_booking(current,trips,**options)
