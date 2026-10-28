"""결제일이 없는 아고다 관측의 엄격한 일대일 추론 규칙."""
import re
from datetime import date

from app.ota_matching_defaults import load_defaults
from app.provisional_assignment import ota_service_period_candidate, rank_trip_candidates

BASIS = 'mutually_unique_undated_agoda'
NOTE = '추론 연결: 카드 끝자리·원문 금액·전체 자료의 일대일 대응과 이용기간 확인. 실제 결제일은 미확인'


def provisional_trip_decisions(events, trips, *, manual_decisions=None):
    """Rank verified OTA service-period trip candidates independently of payment matching."""
    manual_decisions = manual_decisions or {}
    result = {}
    for event in events:
        identity = str(event.get('ota_event_id') or '')
        authenticated_mail = (event.get('evidence_kind') == 'authenticated_payment_mail'
                              and re.fullmatch(r'[0-9a-f]{64}', str(event.get('source_digest') or '')))
        verified_period_source = (event.get('verified_portal_snapshot') is True
                                  or authenticated_mail)
        # Only verified reservation periods can create a trip candidate. This
        # path never modifies payment status, booking links, or settlement IDs.
        if (not identity or not verified_period_source
                or event.get('reservation_status') not in (
                    ('confirmed', 'completed', 'observed') if authenticated_mail else ('confirmed', 'completed'))
                or event.get('service_period_conflict') or event.get('period_conflict')):
            continue
        candidates = ota_service_period_candidate(event, trips)
        refund = event.get('event_type') == 'refund' or event.get('refund_status') in (
            'refund_pending', 'refund_requested', 'refunded', 'refund_completed')
        manual = manual_decisions.get(identity)
        manual_status = manual.get('status') if isinstance(manual, dict) else manual
        manual_trip_id = manual.get('trip_id') if isinstance(manual, dict) else None
        result[identity] = rank_trip_candidates(
            candidates, trips=trips,
            manual_status=manual_status, manual_trip_id=manual_trip_id,
            financial_hold=refund or event.get('financial_hold') is True
                or bool(event.get('evidence_changed') or event.get('evidence_missing')))
    return result


def unique_pairs(events, transactions, *, occupied=(), rules=()):
    from app import ota_payments as payments
    policy = load_defaults().get('agoda_undated_unique_match', {})
    if policy.get('enabled') is not True or not policy.get('approval_source'):
        return {}
    occupied = set(occupied)
    result = {}
    for event in events:
        if (event.get('provider') != 'agoda' or event.get('paid_on') or
                event.get('event_type') != 'charge' or not payments._event_is_paid(event) or
                event.get('verified_portal_snapshot') is not True or
                event.get('reservation_status') not in ('confirmed', 'completed') or
                event.get('refund_status') not in (None, '', 'none_displayed') or
                not re.fullmatch(r'[0-9]{4}', str(event.get('card_last4') or ''))):
            continue
        period = event.get('service_period') or {}
        try:
            if date.fromisoformat(period['ends_on']) <= date.fromisoformat(period['starts_on']):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        related = [e for e in events if (e.get('provider'), e.get('booking_ref')) ==
                   (event.get('provider'), event.get('booking_ref'))]
        if any(e.get('reservation_status') == 'cancelled' or e.get('service_period_conflict')
               or e.get('event_type') == 'refund' or e.get('refund_status') in
               ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')
               or (e.get('service_period') and e['service_period'] != period) for e in related):
            continue

        def exact(e, row):
            return (e.get('card_last4') == event['card_last4'] and
                    payments.provider_compatible(e, row, rules) and
                    payments._strict_card_identity(e, row) and payments._amount_matches(e, row, []))

        # 이미 기장했거나 원문 오류가 있는 경쟁 원행도 유일성 검사에는 포함한다.
        # 확인된 중복 사본만 제외하고, 남는 정상 후보만 골라 연결하지 않는다.
        cards = [row for row in transactions if payments._direction(row) == 'purchase' and
                 not row.get('duplicate_of') and exact(event, row)]
        if len(cards) != 1:
            continue
        row = cards[0]
        if (row.get('parse_error') or row.get('conflict_reason') or
                row.get('ota_inference_eligible') is not True or row['transaction_id'] in occupied):
            continue
        claims = [e for e in events if e.get('provider') == 'agoda' and
                  e.get('event_type') == 'charge' and payments._event_is_paid(e) and exact(e, row)]
        if len(claims) != 1:
            continue
        if any(e.get('paid_on') and payments._event_is_paid(e) and
               payments.pair_check(e, row, rules) is None for e in events):
            continue
        result[event['ota_event_id']] = row
    return result


def extend_report(report, events, transactions, *, open_ids, excluded_ids=(), rules=()):
    existing = {str(f['transaction_id']) for f in report.get('matches', [])}
    eligible = set(open_ids) - set(excluded_ids)
    cards = [dict(row, ota_inference_eligible=str(row.get('transaction_id')) in eligible) for row in transactions]
    pairs = unique_pairs(events, cards, occupied=existing, rules=rules)
    indexed = {e['ota_event_id']: e for e in events}
    sources = {row['source_hash'] for row in pairs.values()}
    report['rules'] = [r for r in report.get('rules', []) if r.get('optional', {}).get('source_hash') not in sources]
    for identity, row in pairs.items():
        event = indexed[identity]
        fact = dict(provider='agoda', booking_ref=event['booking_ref'], transaction_id=row['transaction_id'],
                    source_hash=row['source_hash'], source_sha256=event['source_digest'],
                    source_digests=event.get('source_digests') or [event['source_digest']],
                    merchant=row.get('merchant_normalized') or row['merchant'], card_kind=row.get('card_kind', ''),
                    item='숙박비', period=event['service_period'], reservation_status=event['reservation_status'],
                    paid_on=None, paid_amount_krw=row.get('amount_krw'),
                    direction='purchase', evidence_kind='portal_payment_claim', basis=NOTE,
                    inferred_link=True, inference_basis=NOTE, payment_date_verified=False)
        report.setdefault('matches', []).append(fact)
        report.setdefault('rules', []).append({
            'conditions': {'merchant_normalized': fact['merchant'], 'transaction_direction': 'purchase'},
            'optional': {'source_hash': fact['source_hash']},
            'effects': {'item': '숙박비', 'description': '예약 ' + event['booking_ref'] + ' · 추론 연결'},
            'origin': 'ota-portal-live', 'note': NOTE})
    report['type_only_candidates'] = [r for r in report.get('type_only_candidates', []) if r.get('source_hash') not in sources]
    report['unmatched_transactions'] = [r for r in report.get('unmatched_transactions', []) if r.get('source_hash') not in sources]
    report['inferred_matches'] = sum(bool(f.get('inferred_link')) for f in report.get('matches', []))
    report['exact_matches'] = sum(not f.get('inferred_link') for f in report.get('matches', []))
    return report
