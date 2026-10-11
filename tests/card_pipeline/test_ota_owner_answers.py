from app.ota_mail import shared_lodging_period


def fact(ref, status='observed', end='2026-08-25'):
    return dict(provider='trip', paid_on='2026-06-10', paid_amount_krw=442055,
                item='숙박비', booking_ref=ref, reservation_status=status,
                period=dict(starts_on='2026-08-24', ends_on=end), source_sha256=ref*64)


def test_shared_period_does_not_select_a_booking_number():
    result=shared_lodging_period([fact('a'),fact('b')],paid_on='2026-06-10',amount_krw=442055)
    assert result['booking_count']==2
    assert result['period']['ends_on']=='2026-08-25'
    assert 'booking_ref' not in result


def test_cancelled_or_disagreeing_candidates_cannot_supply_shared_period():
    for second in (fact('b','cancelled'),fact('b',end='2026-08-26')):
        assert shared_lodging_period([fact('a'),second],paid_on='2026-06-10',amount_krw=442055) is None


def test_cancellation_on_another_date_still_blocks_candidate():
    cancel=fact('a','cancelled');cancel['paid_on']='2026-07-01';cancel['paid_amount_krw']=None
    assert shared_lodging_period([fact('a'),cancel],paid_on='2026-06-10',amount_krw=442055) is None


def test_owner_schedule_is_verified_against_its_preserved_source(tmp_path, monkeypatch):
    import hashlib
    import json
    from unittest.mock import patch
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    from ledger.domain.direct_trip_schedule_authority import SCHEMA_VERSION, END_SEMANTICS
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB','1')
    schedule=dict(trip_code='0823_합성여행',event_year=2026,starts_on='2026-08-23',ends_on='2026-08-25',
                  region='합성여행',authority_kind='user_confirmed_schedule',authority_status='authoritative',
                  end_semantics=END_SEMANTICS)
    source=tmp_path/'owner-schedule-synthetic.json'
    source.write_text(json.dumps(dict(schema_version='owner-trip-schedule-v1',schedule=schedule)),encoding='utf-8')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    record=dict(schedule,source_locator=str(source)+'#schedule',source_sha256=digest)
    authority=tmp_path/'authority.json'
    authority.write_text(json.dumps(dict(schema_version=SCHEMA_VERSION,records=[record])),encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_TRIP_AUTHORITY',str(authority))
    monkeypatch.setenv('WEBLEDGER_EVIDENCE_ROOT',str(tmp_path))
    board=LedgerStore(tmp_path/'board.sqlite',seed_demo=False)
    try:
        trip=board.create_trip(starts_on=schedule['starts_on'],ends_on=schedule['ends_on'],
                              destination='합성여행',display_key=schedule['trip_code'],source_sha256=digest,
                              client_request_id='synthetic')
        with patch('webapp.real_review.active_service',return_value=object()):
            flow=CardFlow(board)
            assert flow.trip_valid(trip['tab_id'])
        # 명시적으로 확정한 일정 원본은 과거 XLSX 검토 서비스가 없어도 검증한다.
        with patch('webapp.real_review.active_service',return_value=None):
            assert flow.trip_valid(trip['tab_id'])
            source.write_text('{}',encoding='utf-8')
            assert not flow.trip_valid(trip['tab_id'])
    finally:board.close()
