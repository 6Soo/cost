"""Shared read-only classification destination and provenance decisions."""
from __future__ import annotations

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
    """Resolve display destination precedence and report its shared status."""
    display = str(row.get('display_tab_id') or '').strip()
    trip = str(row.get('trip_id') or '').strip()
    destination = display if display not in ('', 'unclassified') else trip
    status = destination_status(destination, valid_trip_ids)
    if (display not in ('', 'unclassified') and trip not in ('', 'unclassified')
            and display != trip
            and (destination_status(display, valid_trip_ids) != 'ASSIGNED'
                 or destination_status(trip, valid_trip_ids) != 'ASSIGNED')):
        status = 'UNASSIGNED'
    return destination, status


def classification_source_label(source):
    """Map internal classification provenance to safe user facing text."""
    value = str(source or '').strip()
    labels = {
        'owner_card_residual': '자동 분류 · 카드 잔여 비용 규칙',
        'owner_booking': '예약 근거 자동 배정',
        'guide_airfare_evidence': '항공권 자료 근거',
        'refund_original': '원결제 연결 근거',
        'manual': '사용자 직접 지정', 'user_decision': '사용자 직접 지정',
        'user_exception': '사용자 예외 규칙', 'auto_inferred': '자동 추론',
        'auto': '자동 분류', 'inference': '자동 추론',
        'rule': '자동 분류 · 등록 규칙', 'pattern': '자동 분류 · 가맹점 규칙',
        'card_category': '자동 분류 · 카드 항목',
        'booking_evidence_needed': '예약 근거 확인 필요',
        'travel_location_hold': '여행 지역 확인 필요',
        'rule_conflict': '분류 규칙 충돌', 'inference_conflict': '자동 추론 충돌',
        'previous_decision': '기존 분류 유지',
    }
    return labels.get(value, '자동 분류 · 기타 근거' if value else '분류 근거 미확인')
