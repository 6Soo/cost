"""Shared read-only classification destination and provenance decisions."""
from __future__ import annotations

import json
from .quarter_tab import parse_tab


def destination_status(destination, valid_trip_ids=()):
    """Return ASSIGNED for a valid trip or quarter bucket; otherwise UNASSIGNED."""
    value = str(destination or '').strip()
    if value in ('', 'unclassified', 'refunds'):
        return 'UNASSIGNED'
    if is_quarter_destination(value):
        return 'ASSIGNED'
    return 'ASSIGNED' if value in set(valid_trip_ids or ()) else 'UNASSIGNED'


def is_quarter_destination(destination):
    return parse_tab(str(destination or '').strip()) is not None


def row_destination(row, valid_trip_ids=()):
    """Compatibility tuple; legacy completion callers block any stored-ID conflict."""
    verdict = row_assignment(row, valid_trip_ids)
    status = 'UNASSIGNED' if verdict['conflicts'] else verdict['status']
    return verdict['destination'], status


def row_assignment(row, valid_trip_ids=()):
    """Resolve an effective destination while keeping conflicting IDs separate."""
    display = str(row.get('display_tab_id') or '').strip()
    trip = str(row.get('trip_id') or '').strip()
    valid = set(valid_trip_ids or ())
    display_status = destination_status(display, valid)
    trip_status = destination_status(trip, valid)
    display_present = display not in ('', 'unclassified')
    trip_present = trip not in ('', 'unclassified')
    conflicts = []
    if display_present and trip_present and display != trip:
        conflicts.append('DESTINATION_CONFLICT')
    if display_present and display_status != 'ASSIGNED' and trip_present and trip_status == 'ASSIGNED':
        conflicts.append('STALE_DISPLAY_DESTINATION')
    if trip_present and trip_status != 'ASSIGNED' and display_present and display_status == 'ASSIGNED':
        conflicts.append('STALE_TRIP_DESTINATION')
    if display_present and display_status == 'ASSIGNED':
        destination = display
    elif trip_present and trip_status == 'ASSIGNED':
        destination = trip
    else:
        destination = display if display_present else trip
    return {'destination': destination,
            'status': destination_status(destination, valid),
            'conflicts': conflicts}


def sql_assignment_status(display, trip, valid_trip_ids_json):
    try:
        valid_trip_ids = json.loads(valid_trip_ids_json or '[]')
    except (TypeError, ValueError):
        valid_trip_ids = []
    return row_assignment({'display_tab_id': display, 'trip_id': trip}, valid_trip_ids)['status']


def classification_source_detail(source):
    """Map internal classification provenance to safe user facing text."""
    value = str(source or '').strip()
    labels = {
        'owner_card_residual': '자동 분류 · 카드 잔여 비용 규칙',
        'owner_booking': '예약 근거 자동 배정',
        'guide_airfare_evidence': '항공권 자료 근거',
        'refund_original': '원결제 연결 근거',
        'manual': '사용자 직접 지정', 'user_decision': '사용자 직접 지정',
        'user_exception': '사용자 예외 규칙', 'auto_inferred': '코드 추론',
        'auto': '자동', 'inference': '코드 추론',
        'code_inference': '코드 추론', 'ai_inference': 'AI 추론',
        'rule': '자동 분류 · 등록 규칙', 'pattern': '자동 분류 · 가맹점 규칙',
        'card_category': '자동 분류 · 카드 항목',
        'booking_evidence_needed': '예약 근거 확인 필요',
        'travel_location_hold': '여행 지역 확인 필요',
        'rule_conflict': '분류 규칙 충돌', 'inference_conflict': '자동 추론 충돌',
        'previous_decision': '기존 분류 유지',
    }
    return labels.get(value, '자동 분류 · 기타 근거' if value else '분류 근거 미확인')


def classification_source_label(source):
    from .classification_provenance import label
    return label({'classification_source': source})


def assignment_conflict_label(reasons):
    labels = {
        'DESTINATION_CONFLICT': '여행 배정 값이 서로 다릅니다',
        'STALE_DISPLAY_DESTINATION': '화면 배정 목적지를 확인해야 합니다',
        'STALE_TRIP_DESTINATION': '저장된 여행 배정을 확인해야 합니다',
    }
    return ' · '.join(labels.get(str(reason), '배정 충돌 확인 필요') for reason in reasons or ())
