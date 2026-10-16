"""기존 OTA 대사 결과를 코어의 정확 매칭 규칙으로 한 번 더 확인한다.

새로 자동 배정될 수 있는 거래만 검사한다. 장부에 기록된 거래, 보존 거래, 사용자·소유자가 정한 거래는
건드리지 않는다. 코어 규칙을 통과하지 못한 연결은 자동 배정하지 않고 사유와 함께 미연결로 남긴다.
"""
import os
from collections import Counter, defaultdict

from app import ota_payments

ENV = 'WEBLEDGER_OTA_EXACT_GATE'
PROTECTED_SOURCES = ('user_decision', 'user_exception', 'user_completed_period', 'owner_card_residual',
                     'refund_original')
# 카드 끝자리가 없는 이벤트는 승인된 업체 별칭이 있어야 한다. 트립닷컴은 코어가 날짜·금액·유일 후보로 판단한다.
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


def _match_reason(match, row, charges, rules):
    if charges is None:
        return 'evidence_unavailable'
    if row is None:
        return 'row_missing'
    candidates = charges.get((str(match.get('provider') or ''), str(match.get('booking_ref') or '')), [])
    if not candidates:
        return 'no_core_event'
    reasons = []
    for event in candidates:
        reason = ota_payments.pair_check(event, row, rules)
        if reason is None:
            return None
        reasons.append(reason)
    return reasons[0]


def apply_gate(report, transactions, *, events, rules, open_ids):
    """열린 거래의 연결만 확인해 막힌 것을 빼고, 빠진 근거를 미연결 사유로 남긴다.

    `events`가 None이면 OTA 근거를 읽지 못한 것이므로 열린 거래의 연결을 모두 막는다(닫힌 쪽으로 실패).
    """
    if not enabled():
        return report
    rows = {str(row.get('transaction_id')): row for row in transactions}
    charges = None if events is None else _paid_charges(events)
    dropped = {}
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
    report['exact_matches'] = len(kept)
    report['type_only_matches'] = len(kept_type)
    report['unmatched_reason_counts'] = dict(Counter(row['reason'] for row in report['unmatched_transactions']))
    report['evidence_gate'] = dict(checked=checked, dropped=list(dropped.values()))
    return report
