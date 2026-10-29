"""Trip authority and assignment services used by the card flow facade.

The functions deliberately receive the facade and its loaders as callbacks.  This
keeps existing instance monkeypatches and card_flow module global overrides
observable while moving the authority boundary out of the facade.
"""
import hashlib
import json
import os
from pathlib import Path

def trip_valid(flow, trip_id, *, google_periods, trip_authority, unchanged_workbook_schedule):
    """화면용 여행 탭의 기간이 원본 일정과 일치해야 한다.

    원본은 연결된 구글 여행 탭의 시트 기간이다. 구글 기간과 맞지 않으면 기존 일정 권한 파일로 확인한다."""
    from ledger.domain.direct_trip_schedule_authority import load_document
    from . import real_review
    trip = flow.board.get_trip(trip_id)
    if not trip or trip['deleted'] or trip['archived']:
        return False
    google = google_periods().get(trip_id, set())
    if trip['ends_on'] and any((start, end) == (trip['starts_on'], trip['ends_on']) for start, end, _ in google):
        return True
    path = os.environ.get('WEBLEDGER_TRIP_AUTHORITY')
    if not path:
        return False
    records, _ = trip_authority(Path(path))
    matches = [r for r in records if r.trip_code == trip['display_key']]
    if len(matches)!=1:
        return False
    record=matches[0]
    locator=record.source_locator.partition('#')[0]
    if record.trip_code=='5월_유럽' or Path(locator).name.startswith(('reserve-', 'owner-schedule-')):
        source=Path(record.source_locator.partition('#')[0])
        evidence=Path(os.environ.get('WEBLEDGER_EVIDENCE_ROOT','D:/WebLedgerHost/data/evidence'))
        if not source.resolve().is_relative_to(evidence.resolve()):
            return False
        try:
            raw=source.read_bytes()
            digest=hashlib.sha256(raw).hexdigest()
            if source.name.startswith('owner-schedule-'):
                snapshot=json.loads(raw)
                expected=record.as_dict()
                expected.pop('source_locator')
                expected.pop('source_sha256')
                if snapshot.get('schema_version')!='owner-trip-schedule-v1' or snapshot.get('schedule')!=expected:
                    return False
            if source.name.startswith('reserve-'):
                from app.reserve_trips import validate_record, SCHEMA
                snapshot=json.loads(raw)
                validate_record(snapshot['record'])
                if (snapshot['schema_version']!=SCHEMA or snapshot['registered_trip_code']!=record.trip_code
                        or snapshot['record']['starts_on']!=record.starts_on.isoformat()
                        or snapshot['record']['ends_on']!=record.ends_on.isoformat()
                        or snapshot['record']['departure_status']!='scheduled'):
                    return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
    else:
        service = real_review.active_service()
        if service is None:
            return False
        source=Path(service.manifest['snapshot_path'])
        current_bytes=source.read_bytes()
        digest=hashlib.sha256(current_bytes).hexdigest()
        if digest!=service.manifest['snapshot_sha256']:
            return False
        if digest!=record.source_sha256:
            if not hasattr(flow,'_schedule_title_cache'):
                flow._schedule_title_cache={}
            # 장부를 옮기며 제목이 빈 구글 탭은 해시로 확인한 원본 제목을 쓴다. 구글에 명시된 다른 기간이 있으면 쓰지 않는다.
            moved = (google and all(guessed for _, _, guessed in google)
                     and any(start == record.starts_on.isoformat() for start, _, _ in google))
            if not (unchanged_workbook_schedule(record,current_bytes,flow._schedule_title_cache)
                    or (moved and unchanged_workbook_schedule(record,None,flow._schedule_title_cache))):
                return False
            digest=record.source_sha256
    return len(matches) == 1 and all((
        matches[0].is_authoritative,
        matches[0].source_sha256 == digest == trip['source_sha256'],
        matches[0].starts_on.isoformat() == trip['starts_on'],
        matches[0].ends_on.isoformat() == trip['ends_on'],
        matches[0].event_year == trip['event_year'],
    ))


def retail_trip(flow, transaction, country, *, google_nets):
    from app.rules import merchant_country, trip_countries
    if isinstance(country,dict):
        if country.get('owner_card3820_singapore'):
            candidates = [t for t in flow.board.list_trips()
                          if t['destination'] == '싱가포르'
                          and (t['starts_on'], t['ends_on']) == ('2026-09-19', '2026-09-24')
                          and flow.trip_valid(t['tab_id'])]
            return candidates[0]['tab_id'] if len(candidates) == 1 else ''
        if 'inferred_trip_id' in country:
            target=country['inferred_trip_id']
            if not flow.trip_valid(target):
                return ''
            return target
        return flow.booking_trip(transaction,country)
    if merchant_country(transaction) != country or not transaction.get('approval_date'):
        return ''
    if not hasattr(flow, '_retail_trips'):
        # 명시된 일정의 지역만 사용한다. 새 지역은 자동으로 국가를 만들어 붙이지 않는다.
        flow._retail_trips = []
        for trip in flow.board.list_trips():
            if flow.trip_valid(trip['tab_id']):
                flow._retail_trips.extend((code,trip) for code in trip_countries(trip))
    occurred = transaction['approval_date']
    candidates = [trip for code,trip in flow._retail_trips if code == country
                  and trip['starts_on'] <= occurred <= trip['ends_on']]
    if not candidates:
        return ''
    # 한 여행이 끝나고 다음 여행이 시작하는 날이면 수입-비용 차액이 큰 여행으로 보낸다.
    handover = len(candidates)>1 and all(occurred in (t['starts_on'], t['ends_on']) for t in candidates)
    nets = google_nets() if handover else {}
    candidates.sort(key=lambda t:(nets.get(t['tab_id'], float('-inf')),t['starts_on']==occurred,t['starts_on'],t['ends_on']),reverse=True)
    top = candidates[0]
    if len(candidates)>1 and (nets.get(top['tab_id']), top['starts_on'],top['ends_on']) == (
            nets.get(candidates[1]['tab_id']), candidates[1]['starts_on'],candidates[1]['ends_on']):
        return ''
    return top['tab_id']


def booking_trip(flow, transaction, period, *, google_nets, handover_days, overlaps_stay, stay_trip):
    # 이용기간에 맞는 검증된 여행이다. 저장된 여행 이름이 그 기간과 겹치는 여행이면 그 여행을 쓴다.
    verified = [t for t in flow.board.list_trips() if flow.trip_valid(t['tab_id'])]
    service = period.get('service', False)
    handover = handover_days(verified)
    named = [t for t in verified if t['display_key']==period.get('target_code')
             and overlaps_stay(t['starts_on'], t['ends_on'], period['starts_on'], period['ends_on'], service=service,
                               handover=handover)]
    if len(named)==1:
        return named[0]['tab_id']
    chosen = stay_trip(verified, period['starts_on'], period['ends_on'], service=service, nets=google_nets())
    return chosen['tab_id'] if chosen else ''
