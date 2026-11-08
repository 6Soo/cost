"""P1/P2 termination preserves money and does not create or consume P3 questions."""
import json

from webapp.tests.test_autonomous_cleanup import setup, receive, create_trip, make_weak_rows, financial_snapshot
from webapp.autonomous_cleanup_worker import AutonomousCleanupWorker, JOB_SCOPE, load_job


def task_history(conn):
    return conn.execute("SELECT * FROM requests WHERE scope='user_action_task_v1'").fetchall()


def test_no_actual_trip_finishes_in_source_quarter_without_ai_or_question(setup):
    board = setup
    batch, rows = receive(board,1)
    source = board.conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions').fetchall()
    def no_candidate_provider(_):
        raise AssertionError('AI cannot invent a trip when there are no actual candidates')
    worker = AutonomousCleanupWorker(board,board._lock,provider=no_candidate_provider)
    assert worker.sweep_once()
    result = board.conn.execute('SELECT classification_state,item,display_tab_id,trip_id FROM transactions').fetchone()
    assert result[0] == 'classified' and result[1]
    assert result[2] == 'quarter:2026:4' and not result[3]
    assert board.conn.execute('SELECT transaction_id,source_hash,amount_krw FROM transactions').fetchall() == source
    assert not task_history(board.conn)
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_p2_exhaustion_keeps_p1_destination_and_never_asks_or_applies_old_answers(setup):
    board = setup
    trip = create_trip(board)
    batch, rows = receive(board,1)
    identities = make_weak_rows(board,batch,rows,trip)
    board.conn.execute('INSERT INTO requests VALUES(?,?,?,?,?)',
        ('historical-answer','user_action_task_v1','history',json.dumps({
            'state':'ANSWERED','answer_effect':{'kind':'card_item','transaction_id':identities[0]},
            'answer':{'value':'사무용품'}}),'historical'))
    board.conn.commit()
    history = task_history(board.conn)
    before = financial_snapshot(board)
    def unavailable(_):
        raise RuntimeError('synthetic provider outage')
    worker = AutonomousCleanupWorker(board,board._lock,provider=unavailable)
    for _ in range(3):
        assert worker.sweep_once()
        board.conn.execute("UPDATE requests SET response_json=json_set(response_json,'$.not_before',0) WHERE scope=?",(JOB_SCOPE,))
        board.conn.commit()
    assert load_job(board.conn,identities[0])['status'] == 'ai_dead'
    state,item,target = board.conn.execute('SELECT classification_state,item,display_tab_id FROM transactions').fetchone()
    assert state == 'classified' and item == '현지경비' and target == trip
    assert financial_snapshot(board) == before
    assert task_history(board.conn) == history
