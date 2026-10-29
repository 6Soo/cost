import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import forest_mail, ota_payments, ota_store
from tests.card_pipeline.test_forest_mail import body_notice
from webapp import ota_catalog
from webapp.ledger_store import LedgerStore


def mail(identity, *, cancelled=False, numbered=False):
    body='2026-10-05 합성자연휴양림 가상실 객실 예약완료'
    if numbered:
        body+='\n예약번호: SYN-REF-1234'
    return body_notice(body,identity=identity,
        subject='숲나들e 예약취소 안내' if cancelled else '숲나들e 예약완료 안내')


def write_mail(folder,messages):
    folder.mkdir(exist_ok=True)
    (folder/'gmail-synthetic.json').write_text(json.dumps({'responses':messages}),encoding='utf-8')
    return folder


def test_import_persists_separate_observations_without_inventing_booking_or_payment(tmp_path):
    messages=[mail('one'),mail('two',cancelled=True)]
    directory=write_mail(tmp_path/'mail',messages)
    store=ota_store.OtaStore(tmp_path/'ota.sqlite')
    try:
        assert store.import_mail(directory)
        facts=[json.loads(r[0]) for r in store.conn.execute('SELECT fact_json FROM ota_reservation_observations')]
        assert len(facts)==2 and {e['reservation_status'] for e in facts}=={'observed','cancelled'}
        assert all(e['booking_ref'] is None and e['paid_on'] is None and e['payment_event_id'] is None for e in facts)
        assert all(e['service_period']['ends_on'] is None for e in facts)
        assert store.conn.execute('SELECT count(*) FROM ota_bookings').fetchone()[0]==0
        events=ota_payments.build_ota_payment_events({'mail_directories':[store.path]})
        assert events==ota_payments.build_ota_payment_events({'mail_directories':[directory]})
        assert all(r['status']=='RESERVATION_ONLY' for r in ota_payments.match_ota_payment_events(events,[]))
        changes=store.conn.total_changes
        assert not store.import_mail(directory)
        assert store.rebuild_reservation_observations()==0
        assert store.conn.total_changes==changes
    finally:
        store.close()


def test_existing_raw_revision_backfills_without_rewriting_raw_or_other_providers(tmp_path):
    directory=write_mail(tmp_path/'mail',[mail('one')])
    store=ota_store.OtaStore(tmp_path/'ota.sqlite')
    try:
        store.import_mail(directory)
        tables=['ota_messages','ota_sources','ota_source_revisions','ota_raw_entries','ota_raw_blobs','ota_bookings','ota_booking_evidence']
        before={t:[tuple(r) for r in store.conn.execute('SELECT * FROM '+t)] for t in tables}
        store.conn.execute('DELETE FROM ota_reservation_observations');store.conn.commit()
        assert store.rebuild_reservation_observations()==1
        assert before=={t:[tuple(r) for r in store.conn.execute('SELECT * FROM '+t)] for t in tables}
        store.conn.execute('DELETE FROM ota_reservation_observations');store.conn.commit()
        assert store.import_mail(directory)  # unchanged source can gain a missing derived row
        assert before=={t:[tuple(r) for r in store.conn.execute('SELECT * FROM '+t)] for t in tables}
    finally:
        store.close()


def test_backfill_failure_rolls_back_all_observations(tmp_path):
    directory=write_mail(tmp_path/'mail',[mail('one'),mail('two')])
    store=ota_store.OtaStore(tmp_path/'ota.sqlite')
    try:
        store.import_mail(directory)
        store.conn.execute('DELETE FROM ota_reservation_observations');store.conn.commit()
        store.conn.execute("CREATE TEMP TRIGGER refuse_second BEFORE INSERT ON ota_reservation_observations WHEN (SELECT count(*) FROM ota_reservation_observations)>0 BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with pytest.raises(sqlite3.IntegrityError,match='synthetic failure'):
            store.rebuild_reservation_observations()
        assert store.conn.execute('SELECT count(*) FROM ota_reservation_observations').fetchone()[0]==0
    finally:
        store.close()


def test_catalog_lists_persisted_and_live_notices_once_and_shows_actual_ref_only(tmp_path,monkeypatch):
    monkeypatch.delenv('WEBLEDGER_REVIEW_CONFIG',raising=False)
    directory=write_mail(tmp_path/'mail',[mail('one'),mail('two',cancelled=True),mail('three',numbered=True)])
    store=ota_store.OtaStore(tmp_path/'ota.sqlite')
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        store.import_mail(directory)
        sources=dict(portal_databases=[store.path],mail_directories=[store.path],missing=[])
        changes=board.conn.total_changes,store.conn.total_changes
        result=ota_catalog.catalog(board,{'provider':['forest']},sources=sources)
        assert result['total']==3 and result['providers']==['forest']
        assert len({r['booking_ref'] for r in result['rows']})==3
        assert sorted(r['booking_ref_display'] for r in result['rows'])==sorted(['원문 미제공','원문 미제공','SYN-REF-1234'])
        assert all(r['identity_kind']=='reservation_observation' and r['card_count']==0 for r in result['rows'])
        html=ota_catalog.render_html(result,{})
        assert '숲나들e' in html and '원문 미제공' in html and 'SYN-REF-1234' in html
        assert '>forest-notice:' not in html
        for r in result['rows']:
            entry=ota_catalog._entry(board,sources,'forest',r['booking_ref'])
            detail=ota_catalog.render_detail(board,entry,csrf='synthetic')
            assert '<h1>숲나들e · '+r['booking_ref_display']+'</h1>' in detail
            assert '2026-10-05 ~ 미확인' in detail
        assert (board.conn.total_changes,store.conn.total_changes)==changes
    finally:
        board.close();store.close()


def test_candidate_and_reservation_relations_do_not_mix_numberless_notices(monkeypatch):
    events=forest_mail.collect({m['id']:m for m in [mail('one'),mail('two')]})
    ids=[e['ota_event_id'] for e in events]
    current={'data':dict(events=events,transactions=[],results=[
        dict(ota_event_id=ids[0],candidate_search=dict(reservation_only=True,candidates=[dict(transaction_id='card-one')])),
        dict(ota_event_id=ids[1],candidate_search=dict(reservation_only=True,candidates=[dict(transaction_id='card-two')]))])}
    flow=SimpleNamespace(_held_ota_snapshot=lambda:(current,True))
    from webapp import ota_payment_review
    monkeypatch.setattr(ota_payment_review,'enabled',lambda:True)
    result=ota_catalog._reservation_card_candidates(flow)
    assert result[('forest',forest_mail.catalog_reference(events[0]))]==['card-one']
    assert result[('forest',forest_mail.catalog_reference(events[1]))]==['card-two']


def test_catalog_observations_follow_current_revision_without_deleting_history(tmp_path):
    directory=write_mail(tmp_path/'mail',[mail('one')])
    store=ota_store.OtaStore(tmp_path/'ota.sqlite')
    try:
        store.import_mail(directory)
        write_mail(directory,[mail('two',cancelled=True)])
        store.import_mail(directory)
        rows=[r for r in ota_store.catalog_rows(store.conn) if r['provider']=='forest']
        assert len(rows)==1 and rows[0]['status']=='cancelled'
        assert store.conn.execute('SELECT count(*) FROM ota_reservation_observations').fetchone()[0]==2
    finally:
        store.close()
