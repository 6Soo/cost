"""검증된 코어 연결을 카드 검토와 장부에 같은 근거로 전달한다."""
from collections import defaultdict

def card_matches(facts, data):
    """검증된 코어 연결을 화면에 보완하며 기존 연결과 카드 점유는 유지한다."""
    facts = list(facts)
    occupied = {str(fact.get('transaction_id')) for fact in facts if fact.get('transaction_id')}
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    claims = defaultdict(list)
    for result in data.get('results', []):
        if result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER') and result.get('transaction_id'):
            claims[str(result['transaction_id'])].append(result)
    for tid, results in claims.items():
        if tid in occupied or len(results) != 1:
            continue
        result = results[0]
        event = events.get(str(result.get('ota_event_id')))
        card = cards.get(tid)
        link = (data.get('links') or {}).get(str(result.get('ota_event_id'))) or {}
        if not event or not card or any(result.get(k) or event.get(k) for k in
                ('evidence_changed', 'evidence_missing', 'service_period_conflict')):
            continue
        if isinstance(link, dict) and (link.get('evidence_changed') or
                (link.get('source_digest') and link.get('source_digest') != event.get('source_digest'))):
            continue
        if not event.get('provider') or not event.get('booking_ref'):
            continue
        if card.get('duplicate_of') or card.get('parse_error') or card.get('conflict_reason'):
            continue
        facts.append({
            'provider': event['provider'], 'booking_ref': event['booking_ref'],
            'transaction_id': tid, 'source_hash': card.get('source_hash'),
            'merchant': card.get('merchant_normalized') or card.get('merchant'), 'paid_on': event.get('paid_on'),
            'paid_amount_krw': card.get('amount_krw'), 'item': event.get('item'),
            'direction': card.get('transaction_direction'),
            'reservation_status': event.get('reservation_status'),
            'inferred_link': bool(result.get('inferred_link')),
            'allocation_basis': result.get('allocation_basis'),
            'core_link': True, 'ota_event_id': event.get('ota_event_id'),
            'period': event.get('service_period'),
            'source_sha256': event.get('source_digest'),
            'source_digests': event.get('source_digests') or [event.get('source_digest')],
            'evidence_kind': event.get('evidence_kind'),
            'inference_basis': result.get('inference_basis'),
            'payment_date_verified': result.get('payment_date_verified'),
        })
        occupied.add(tid)
    return facts



def extend_report(report, data):
    """열린 원행에 묶인 규칙만 추가한다. 점유·결정·원문과 기존 규칙은 바꾸지 않는다."""
    from app import ota_payments
    from app.normalize import normalize_merchant
    facts = card_matches(report.get('matches', []), data)
    existing_count = len(report.get('matches', []))
    if len(facts) == existing_count:
        return report
    result = dict(report, matches=facts, rules=list(report.get('rules', [])))
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    for fact in facts[existing_count:]:
        card = cards[fact['transaction_id']]
        event = events[str(fact['ota_event_id'])]
        period = fact.get('period') or {}
        if (card.get('ota_inference_eligible') is not True or fact.get('direction') != 'purchase'
                or not ota_payments._event_is_paid(event)
                or fact.get('reservation_status') not in ('confirmed', 'completed', 'observed')
                or not period.get('starts_on') or not period.get('ends_on')
                or not fact.get('source_sha256') or not fact.get('source_hash') or not fact.get('item')):
            continue
        basis = fact.get('allocation_basis')
        label = ('반복 거래 순서 배정 · 개별 결제 근거 미확인' if basis in
                 ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                 else '검증된 OTA 결제 연결')
        result['rules'] = [rule for rule in result['rules']
                           if rule.get('optional', {}).get('source_hash') != fact['source_hash']]
        result['rules'].append({
            'conditions': {'merchant_normalized': normalize_merchant(fact['merchant']),
                           'transaction_direction': 'purchase'},
            'optional': {'source_hash': fact['source_hash']},
            'effects': {'item': fact['item'], 'description': '예약 ' + fact['booking_ref'] + ' · ' + label},
            'origin': 'ota-mail-live', 'note': label,
        })
    return result
