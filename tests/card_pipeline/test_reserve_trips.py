import copy
import datetime as dt
import hashlib
import json
import os
from unittest.mock import patch

import pytest
from app.reserve_trips import (sync_records, encoded, registrations, validate_record, SCHEMA,
                               initialize_sync_schedule, sync_if_due, sync_status, KST)
from ledger.domain.direct_trip_schedule_authority import SCHEMA_VERSION, END_SEMANTICS, load_document
from webapp.ledger_store import LedgerStore


def record(comments=5, start='2026-10-10', end='2026-10-13', status='scheduled', fldid='test'):
    r = dict(source_key=f'reserve:{fldid}:{start[:4]}',fldid=fldid,post_id='1',title='합성 여행',
             trip_code='1010_도쿠시마',region='도쿠시마',country='일본',starts_on=start,ends_on=end,
             event_year=int(start[:4]),end_semantics=END_SEMANTICS,authority_kind='explicit_trip_registry',
             authority_status='authoritative',comment_count=comments,comment_threshold=5,
             departure_status=status,source_url=f'https://cafe.daum.net/sixsungwon/{fldid}/1')
    r['record_sha256'] = hashlib.sha256(encoded(r)).hexdigest()
    return r


@pytest.fixture
def setup(tmp_path):
    with patch.dict(os.environ,{'WEBLEDGER_UNIFIED_DB':'1'}):
        board = LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
        from app import Pipeline
        Pipeline(board.conn)
        authority = tmp_path/'authority.json'
        authority.write_bytes(encoded({'schema_version':SCHEMA_VERSION,'records':[]}))
        yield board,authority,tmp_path/'evidence'
        board.close()


def run(setup, rows):
    return sync_records(*setup[:1],rows,*setup[1:],day='2026-10-03')


def test_five_comments_create_one_trip_and_retries_never_create_costs(setup):
    first = run(setup,[record()])
    board,authority,evidence = setup
    before = board.conn.execute('SELECT * FROM trip_tabs').fetchall()
    events = board.conn.execute('SELECT * FROM decision_events').fetchall()
    second = run(setup,[record(8)])
    assert first['created'] == 1 and second['unchanged'] == 1
    assert before == board.conn.execute('SELECT * FROM trip_tabs').fetchall()
    assert events == board.conn.execute('SELECT * FROM decision_events').fetchall()
    assert len(registrations(board)) == len(load_document(authority)[0]) == 1
    assert len(list(evidence.glob('reserve-*.json'))) == 1
    for table in ('transactions','ledger_entries','board_rows'):
        assert board.conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0


def test_below_threshold_past_and_unavailable_do_not_register(setup):
    result = run(setup,[record(4,status='below_threshold'),record(20,start='2026-10-01',fldid='old'),
                         record(None,status='comments_unavailable',fldid='unknown')])
    assert result['created'] == 0 and not setup[0].list_trips()
    with pytest.raises(ValueError,match='ELIGIBILITY'):
        run(setup,[record(4)])


def test_existing_trip_and_user_metadata_are_preserved(setup):
    board = setup[0]
    trip = board.create_trip(starts_on='2026-10-10',ends_on='2026-10-13',destination='도쿠시마',
        display_key='1010_도쿠시마',source_sha256='a'*64,client_request_id='manual')
    before = board.conn.execute('SELECT * FROM trip_tabs').fetchall()
    assert run(setup,[record()])['linked'] == 1
    assert before == board.conn.execute('SELECT * FROM trip_tabs').fetchall()
    assert not load_document(setup[1])[0]
    assert next(iter(registrations(board))) == trip['tab_id']


def test_changed_period_and_declining_comments_do_not_erase_registered_trip(setup):
    run(setup,[record()])
    before = setup[0].conn.execute('SELECT * FROM trip_tabs').fetchall()
    assert run(setup,[record(end='2026-10-14')])['held'] == 1
    assert next(iter(registrations(setup[0]).values()))['departure_status'] == 'schedule_conflict'
    run(setup,[record(4,status='below_threshold')])
    assert next(iter(registrations(setup[0]).values()))['departure_status'] == 'below_threshold'
    assert before == setup[0].conn.execute('SELECT * FROM trip_tabs').fetchall()


def test_same_named_trip_in_a_later_year_is_separate(setup):
    run(setup,[record()])
    run(setup,[record(start='2027-10-10',end='2027-10-13')])
    assert {t['display_key'] for t in setup[0].list_trips()} == {'1010_도쿠시마','2027_1010_도쿠시마'}
    assert len(load_document(setup[1])[0]) == 2


def test_source_hash_and_duplicate_keys_are_rejected_before_writing(setup):
    r = record();r['comment_count'] = 99
    with pytest.raises(ValueError,match='HASH'):
        run(setup,[r])
    with pytest.raises(ValueError,match='DUPLICATED'):
        run(setup,[record(),record()])
    assert not setup[0].list_trips()


def test_midnight_schedule_runs_once_and_survives_reinitialization(setup):
    board, authority, evidence = setup
    # UTC 15시는 한국 시간으로 다음 날 0시다.
    before = dt.datetime(2026, 10, 3, 14, 59, 59, tzinfo=dt.timezone.utc)
    midnight = before + dt.timedelta(seconds=1)
    initialize_sync_schedule(board, before)
    with patch('app.reserve_trips.fetch_records', return_value=[record()]) as fetch:
        assert not sync_if_due(board, authority, evidence, now=before)
        assert sync_if_due(board, authority, evidence, now=midnight)
        board.reserve_trip_sync_status = {}
        initialize_sync_schedule(board, midnight + dt.timedelta(minutes=1))
        assert not sync_if_due(board, authority, evidence, now=midnight + dt.timedelta(minutes=1))
        assert fetch.call_count == 1
        assert sync_status(board)['next_run_at'] == '2026-10-05T00:00:00+09:00'
        # 다음 한국 날짜에만 다시 조회하며 같은 여행은 추가하지 않는다.
        assert sync_if_due(board, authority, evidence, now=midnight + dt.timedelta(days=1))
        assert fetch.call_count == 2
    assert len(board.list_trips()) == 1
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_failed_daily_query_is_not_retried_on_the_same_day(setup):
    board, authority, evidence = setup
    initialize_sync_schedule(board, dt.datetime(2026, 10, 3, 18, tzinfo=KST))
    midnight = dt.datetime(2026, 10, 4, tzinfo=KST)
    with patch('app.reserve_trips.fetch_records', side_effect=TimeoutError('synthetic')) as fetch:
        assert sync_if_due(board, authority, evidence, now=midnight)
        initialize_sync_schedule(board, midnight + dt.timedelta(hours=2))
        assert not sync_if_due(board, authority, evidence, now=midnight + dt.timedelta(hours=2))
        assert fetch.call_count == 1
    assert sync_status(board)['status'] == 'failed'
    assert sync_status(board)['next_run_at'] == '2026-10-05T00:00:00+09:00'
    assert not board.list_trips()


def test_interrupted_query_keeps_its_daily_claim_after_restart(setup):
    board, authority, evidence = setup
    initialize_sync_schedule(board, dt.datetime(2026, 10, 3, 18, tzinfo=KST))
    with patch('app.reserve_trips.fetch_records', side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            sync_if_due(board, authority, evidence, now=dt.datetime(2026, 10, 4, tzinfo=KST))
    board.reserve_trip_sync_status = {}
    state = initialize_sync_schedule(board, dt.datetime(2026, 10, 4, 1, tzinfo=KST))
    assert state['status'] == 'failed' and state['error'] == 'RESERVE_SYNC_INTERRUPTED'
    with patch('app.reserve_trips.fetch_records') as fetch:
        assert not sync_if_due(board, authority, evidence, now=dt.datetime(2026, 10, 4, 1, tzinfo=KST))
        fetch.assert_not_called()


def test_registered_trip_and_imported_card_are_shown_before_cost_commit(setup):
    from app import Pipeline
    from webapp import ledger_board
    from webapp.tests.test_card_flow import CARD
    board, authority, evidence = setup
    Pipeline(board.conn).receive(CARD, 'synthetic.csv')
    run(setup, [record()])
    initialize_sync_schedule(board, dt.datetime(2026, 10, 3, 18, tzinfo=KST))
    previous = ledger_board._STORE
    try:
        ledger_board.bind_store(board)
        with patch.dict(os.environ, {'WEBLEDGER_RESERVE_TRIP_SYNC':'1'}), \
                patch('app.reserve_trips.today', return_value='2026-10-03'):
            html = ledger_board.trips_page(role='owner')
        assert '여행 1개 · 카드 자료 1건 · 장부 기록 0건' in html
        assert '저장된 데이터 없음' not in html
        from webapp.card_flow import home_page
        home = home_page(board)
        assert '여행글은 한국 시간 매일 0시에 조회합니다.' in home
        assert '다음 조회: 2026-10-04 00:00' in home
        assert '1010_도쿠시마' in html and '출발 예정' in html
        assert "href='/import" in html
    finally:
        ledger_board.bind_store(previous)
    assert board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 0


def test_interrupted_registration_recovers_the_same_trip(setup):
    from app import reserve_trips
    board,authority,evidence = setup
    create = board.create_trip
    def interrupted(**kwargs):
        create(**kwargs)
        raise RuntimeError('simulated interruption')
    with patch.object(board,'create_trip',side_effect=interrupted),pytest.raises(RuntimeError):
        run(setup,[record()])
    before = board.conn.execute('SELECT * FROM trip_tabs').fetchall()
    run(setup,[record(8)])
    assert before == board.conn.execute('SELECT * FROM trip_tabs').fetchall()
    assert len(registrations(board)) == 1


def test_deployment_guard_allows_only_the_new_trip_history(setup, tmp_path):
    from tools.verify_operational_backup_restore import backup_database
    from tools.deploy_reserve_trips import verify_delta
    board = setup[0]
    board.save_owner_profile(expected_revision=0,client_request_id='synthetic-owner-profile',
                             company_name='합성 회사',assignee_name='합성 담당자')
    before = tmp_path/'before.sqlite'
    backup_database(board.path,before)
    run(setup,[record()])
    verify_delta(before,board.path)
    board.conn.execute("UPDATE owner_profile SET company_name='changed'")
    board.conn.commit()
    with pytest.raises(RuntimeError,match='EXISTING_DATA_CHANGED'):
        verify_delta(before,board.path)


def test_registered_source_is_revalidated_before_card_assignment(setup):
    from types import SimpleNamespace
    from webapp.card_flow import CardFlow
    from webapp import real_review
    run(setup,[record()])
    board,authority,evidence = setup
    trip=board.list_trips()[0]
    with patch.dict(os.environ,{'WEBLEDGER_TRIP_AUTHORITY':str(authority),'WEBLEDGER_EVIDENCE_ROOT':str(evidence)}), \
            patch.object(real_review,'active_service',return_value=SimpleNamespace(manifest={})):
        flow=CardFlow(board)
        assert flow.trip_valid(trip['tab_id'])
        source=next(evidence.glob('reserve-*.json'))
        snapshot=json.loads(source.read_text(encoding='utf-8'))
        snapshot['record']['ends_on']='2026-10-14'
        source.write_bytes(encoded(snapshot))
        assert not flow.trip_valid(trip['tab_id'])
