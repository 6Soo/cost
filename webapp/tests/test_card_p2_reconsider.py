"""Explicit P2 reruns revisit automatic results without changing financial facts."""
import json
import sqlite3

import pytest

from app import automatic_classification as policy
from tools import complete_card_classification as tool
from webapp.tests.test_automatic_classification_completion import setup, TRIPS


def test_historical_completion_note_does_not_exempt_an_unassigned_purchase(setup):
    board, _, _, rows = setup
    board.conn.execute("UPDATE transactions SET classification_state='classified',item='expense',"
                       "classification_basis='등록된 유효 여행 없음 · 비용 항목 분류 완료'")
    preview = policy.plan(board.conn, TRIPS)
    assert preview['summary']['to_classify'] == len(rows)
    policy.apply(board.conn, preview, TRIPS)
    assert all(r[0] in {'A', 'B'} for r in board.conn.execute('SELECT trip_id FROM transactions'))


def test_reconsider_new_assignment_has_stable_reason_on_repeat(setup):
    board, _, _, _ = setup
    options = dict(reconsider=True)
    preview = policy.plan(board.conn,TRIPS,**options)
    policy.apply(board.conn,preview,TRIPS,**options)
    assert policy.plan(board.conn,TRIPS,**options)['summary']['to_classify'] == 0


def test_reconsider_prefers_booking_period_and_refines_generic_item_with_no_financial_writes(setup):
    board, _, _, rows = setup
    tid = rows[0]['transaction_id']
    board.conn.execute("UPDATE transactions SET classification_state='classified',classification_source='inference',"
                       "item='synthetic expense',trip_id='A',display_tab_id='A'")
    board.conn.execute("UPDATE transactions SET item='기타경비' WHERE transaction_id=?", (tid,))
    evidence = {tid: dict(source_hash=rows[0]['source_hash'],trip_id='B',item='숙박비',basis='synthetic service period')}
    before = tool.protected_state(board.conn)
    preview = policy.plan(board.conn, TRIPS, reconsider=True, evidence=evidence)
    policy.apply(board.conn, preview, TRIPS, reconsider=True, evidence=evidence)
    assert board.conn.execute('SELECT item,trip_id,classification_source FROM transactions WHERE transaction_id=?',(tid,)).fetchone() == ('숙박비','B','inference')
    assert tool.protected_state(board.conn) == before
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0
    assert policy.plan(board.conn, TRIPS, reconsider=True, evidence=evidence)['summary']['to_classify'] == 0


def test_reconsider_keeps_manual_trip_category_and_recorded_trip(setup):
    board, flow, _, rows = setup
    manual, recorded = rows[:2]
    flow.pipeline.save_decision(manual['transaction_id'],manual['revision'],item='manual item',
        display_tab_id='A',trip_id='A',tab_validator=lambda _:True,trip_validator=lambda _:True,request_id='p2-manual')
    board.conn.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','A',1,?)",
        ('card-'+recorded['transaction_id'],json.dumps(dict(item='recorded item',display_tab_id='A'))))
    evidence = {r['transaction_id']:dict(source_hash=r['source_hash'],trip_id='B',item='synthetic lodging',basis='synthetic') for r in (manual,recorded)}
    before = tool.protected_state(board.conn)
    options = dict(reconsider=True,evidence=evidence)
    policy.apply(board.conn,policy.plan(board.conn,TRIPS,**options),TRIPS,**options)
    assert board.conn.execute('SELECT item,trip_id FROM transactions WHERE transaction_id=?',(manual['transaction_id'],)).fetchone() == ('manual item','A')
    assert board.conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?',(recorded['transaction_id'],)).fetchone()[0] == 'A'
    assert tool.protected_state(board.conn) == before


def test_reconsider_evidence_and_mode_are_bound_to_preview_digest(setup):
    board, _, _, rows = setup
    tid = rows[0]['transaction_id']
    evidence = {tid:dict(source_hash=rows[0]['source_hash'],trip_id='A',item='item',basis='one')}
    preview = policy.plan(board.conn,TRIPS,reconsider=True,evidence=evidence)
    with pytest.raises(ValueError,match='CLASSIFICATION_PREVIEW_STALE'):
        policy.apply(board.conn,preview,TRIPS)
    changed = {tid:dict(evidence[tid],trip_id='B')}
    with pytest.raises(ValueError,match='CLASSIFICATION_PREVIEW_STALE'):
        policy.apply(board.conn,preview,TRIPS,reconsider=True,evidence=changed)


def test_reconsider_failure_rolls_back_source_and_ledger_projection(setup):
    board, _, _, rows = setup
    tid = rows[0]['transaction_id']
    board.conn.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense','',1,'{}')",('card-'+tid,))
    board.conn.commit()
    before = '\n'.join(board.conn.iterdump())
    board.conn.execute("CREATE TEMP TRIGGER reject_p2 BEFORE UPDATE ON board_rows BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError,match='synthetic failure'):
        policy.apply(board.conn,policy.plan(board.conn,TRIPS,reconsider=True),TRIPS,reconsider=True)
    assert '\n'.join(board.conn.iterdump()) == before


def test_reconsider_retains_p1_source_when_result_is_unchanged(setup):
    board, _, _, _ = setup
    board.conn.execute("UPDATE transactions SET classification_state='classified',classification_source='rule',item='specific',trip_id='A',display_tab_id='A'")
    options = dict(reconsider=True)
    policy.apply(board.conn,policy.plan(board.conn,TRIPS,**options),TRIPS,**options)
    assert set(board.conn.execute('SELECT classification_source FROM transactions')) == {('rule',)}
    assert policy.plan(board.conn,TRIPS,**options)['summary']['to_classify'] == 0


def test_reconsider_does_not_replace_inherited_refund_with_a_weak_date_guess(setup):
    board, _, _, rows = setup
    tid = rows[0]['transaction_id']
    board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',classification_state='classified',"
                       "classification_source='refund_original',item='inherited',trip_id='',display_tab_id='' WHERE transaction_id=?",(tid,))
    before = board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    options = dict(reconsider=True)
    policy.apply(board.conn,policy.plan(board.conn,TRIPS,**options),TRIPS,**options)
    assert board.conn.execute('SELECT * FROM transactions WHERE transaction_id=?',(tid,)).fetchone() == before


def test_booking_evidence_is_bound_to_transaction_identity_and_rejects_cancelled_and_conflicting_periods(setup, monkeypatch, tmp_path):
    board, _, _, rows = setup
    trips = [dict(trip_id='A',starts_on='2026-10-01',ends_on='2026-10-05'),
             dict(trip_id='B',starts_on='2026-11-01',ends_on='2026-11-05')]
    def fact(index, **extra):
        return dict(transaction_id=rows[index]['transaction_id'],source_hash=rows[index]['source_hash'],
                    period=dict(starts_on='2026-10-02',ends_on='2026-10-04'),item='synthetic',**extra)
    facts = [fact(0),fact(1,reservation_status='cancelled'),fact(2,period_conflict=True),
             fact(3),dict(fact(3),period=dict(starts_on='2026-11-02',ends_on='2026-11-04')),
             dict(fact(4),source_hash='wrong source')]
    class Flow:
        def _compute_ota_report(self):
            return dict(matches=facts)
    monkeypatch.setattr(tool,'read_flow',lambda *_:Flow())
    evidence, summary = tool.load_review_evidence(board.conn,tmp_path,trips)
    assert set(evidence) == {rows[0]['transaction_id']}
    assert summary['conflicting_periods'] == 1


def test_evidence_cache_rejects_changed_source_before_reusing_a_review(setup, monkeypatch, tmp_path):
    board, _, _, _ = setup
    cache = tmp_path/'data/backups/review.json'
    cache.parent.mkdir(parents=True)
    document = tmp_path/'synthetic.txt'
    document.write_text('version one',encoding='utf-8')
    calls = []
    class Flow:
        def _ota_sources(self):
            return dict(manifest_path=None,reference_documents=[document],mail_directories=[],portal_databases=[],missing=[])
        def _compute_ota_report(self):
            calls.append(True)
            return dict(matches=[])
    monkeypatch.setattr(tool,'read_flow',lambda *_:Flow())
    assert tool.load_review_evidence(board.conn,tmp_path,TRIPS,cache)[0] == {}
    tool.load_review_evidence(board.conn,tmp_path,TRIPS,cache)
    assert len(calls) == 1
    document.write_text('version two',encoding='utf-8')
    with pytest.raises(ValueError,match='EVIDENCE_CACHE_STALE'):
        tool.load_review_evidence(board.conn,tmp_path,TRIPS,cache)
