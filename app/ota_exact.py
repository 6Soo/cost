"""기존 OTA 대사 결과를 코어의 정확 매칭 규칙으로 한 번 더 확인한다.

새로 자동 배정될 수 있는 거래만 검사한다. 장부에 기록된 거래, 보존 거래, 사용자·소유자가 정한 거래는
건드리지 않는다. 코어 규칙을 통과하지 못한 연결은 자동 배정하지 않고 사유와 함께 미연결로 남긴다.
"""
import os
from collections import Counter, defaultdict

from app import ota_payments
from app.ota_portal import SCHEDULED_CARD_DATE_EVIDENCE

ENV = 'WEBLEDGER_OTA_EXACT_GATE'
PROTECTED_SOURCES = ('user_decision', 'user_exception', 'user_completed_period', 'owner_card_residual',
                     'refund_original')
# 카드 끝자리가 없는 이벤트는 승인된 업체 별칭이 있어야 한다. 제공자 경계는 코어와 공유한다.
ALIAS_REQUIRED_PROVIDERS = ('agoda', 'booking', 'klook')


def enabled():
    return os.environ.get(ENV, '1').strip() != '0'


def open_transaction_ids(conn):
    """새 자동 배정 대상이 될 수 있는 거래 ID. 기록된 거래, 보존 거래, 사용자·소유자 결정은 뺀다."""
    recorded = {row[0][len('card-'):] for row in conn.execute(
        "SELECT row_id FROM board_rows WHERE row_kind='expense' AND row_id LIKE 'card-%'")}
    return {str(tid) for tid, state, source in conn.execute(
        "SELECT transaction_id, classification_state, classification_source FROM transactions")
        if str(tid) not in recorded and state != 'preserved' and source not in PROTECTED_SOURCES}


def _paid_charges(events):
    index = defaultdict(list)
    for event in events:
        if event.get('event_type') == 'charge' and ota_payments._event_is_paid(event):
            index[(str(event.get('provider') or ''), str(event.get('booking_ref') or ''))].append(event)
    return index


def _scheduled_card_reason(match, row):
    """자동결제 예정일 연결은 카드 원행의 이용일·금액·카드 끝자리가 그대로 맞아야 한다."""
    if row.get('duplicate_of') or row.get('parse_error') or row.get('conflict_reason'):
        return 'row_flagged'
    if row.get('transaction_direction') != 'purchase':
        return 'direction'
    if row.get('approval_date') != match.get('scheduled_on'):
        return 'date'
    try:
        if int(row.get('amount_krw') or 0) != int(match.get('amount_krw') or 0):
            return 'amount'
    except (TypeError, ValueError):
        return 'amount'
    if str(row.get('card_tail') or '') != str(match.get('card_last4') or ''):
        return 'card_identity'
    return None


def _match_reason(match, row, charges, rules):
    if charges is None:
        return 'evidence_unavailable'
    if row is None:
        return 'row_missing'
    if not ota_payments.provider_compatible(match, row, rules):
        return 'provider'
    if match.get('evidence_kind') == SCHEDULED_CARD_DATE_EVIDENCE:
        return _scheduled_card_reason(match, row)
    candidates =charges.get((str(match.get('provider') or ''), str(match.get('booking_ref') or '')), [])
    if not candidates:
        return 'no_core_event'
    reasons = []
    for event in candidates:
        reason = ota_payments.pair_check(event, row, rules)
        if reason is None:
            return None
        reasons.append(reason)
    return reasons[0]


def apply_gate(report, transactions, *, events, rules, open_ids, inference_excluded_ids=()):
    """열린 거래의 연결만 확인해 막힌 것을 빼고, 빠진 근거를 미연결 사유로 남긴다.

    `events`가 None이면 OTA 근거를 읽지 못한 것이므로 열린 거래의 연결을 모두 막는다(닫힌 쪽으로 실패).
    """
    if not enabled():
        return report
    rows = {str(row.get('transaction_id')): row for row in transactions}
    charges = None if events is None else _paid_charges(events)
    dropped = {}
    # 이용기간을 아는 예약은 결제 월로 다른 여행을 고르지 않는다. 막힌 연결의 추론 배정도 함께 막는다.
    blocked_inference = set()
    kept = []
    checked = 0
    for match in report.get('matches', []):
        tid = str(match.get('transaction_id'))
        if tid not in open_ids:
            kept.append(match)
            continue
        checked += 1
        reason = _match_reason(match, rows.get(tid), charges, rules)
        if reason is None:
            kept.append(match)
        else:
            dropped.setdefault(match.get('source_hash'), dict(transaction_id=tid, source_hash=match.get('source_hash'),
                                                              provider=match.get('provider'), reason=reason))
            if match.get('period'):
                blocked_inference.add(match.get('source_hash'))
    kept_type = []
    for candidate in report.get('type_only_candidates', []):
        tid = str(candidate.get('transaction_id'))
        provider = candidate.get('provider')
        if tid in open_ids and provider in ALIAS_REQUIRED_PROVIDERS and candidate.get('shared_period'):
            checked += 1
            if charges is None:
                reason = 'evidence_unavailable'
            elif ota_payments._descriptor_matches({'provider': provider}, rows.get(tid, {}), rules):
                reason = None
            else:
                reason = 'corroboration'
            if reason:
                dropped.setdefault(candidate.get('source_hash'), dict(transaction_id=tid,
                                   source_hash=candidate.get('source_hash'), provider=provider, reason=reason))
                blocked_inference.add(candidate.get('source_hash'))
                continue
        kept_type.append(candidate)
    report['matches'] = kept
    report['type_only_candidates'] = kept_type
    report['rules'] = [rule for rule in report.get('rules', [])
                       if rule.get('optional', {}).get('source_hash') not in dropped]
    report.setdefault('unmatched_transactions', []).extend(
        dict(transaction_id=item['transaction_id'], source_hash=item['source_hash'], reason=item['reason'])
        for item in dropped.values())
    diagnoses = report.setdefault('portal_diagnoses', [])
    for item in dropped.values():
        entry = next((d for d in diagnoses if d.get('source_hash') == item['source_hash']), None)
        if entry is None:
            diagnoses.append(dict(source_hash=item['source_hash'], reason=item['reason'], booking_ref_count=0))
        else:
            entry['reason'] = item['reason']
    from app import ota_inference
    if events is not None:
        report = ota_inference.extend_report(report, events, transactions, open_ids=open_ids,
                                             excluded_ids=inference_excluded_ids, rules=rules)
    else:
        report['exact_matches'] = len(kept)
    inferred_sources = {f['source_hash'] for f in report['matches'] if f.get('inferred_link')}
    blocked_inference.difference_update(inferred_sources)
    dropped = {source: value for source, value in dropped.items() if source not in inferred_sources}
    for diagnosis in diagnoses:
        if diagnosis.get('source_hash') in inferred_sources:
            diagnosis.update(reason=ota_inference.BASIS, inferred_link=True)
    report['type_only_matches'] = len(report['type_only_candidates'])
    report['unmatched_reason_counts'] = dict(Counter(row['reason'] for row in report['unmatched_transactions']))
    report['evidence_gate'] = dict(checked=checked, dropped=list(dropped.values()),
                                   blocked_inference_sources=sorted(blocked_inference))
    return report
