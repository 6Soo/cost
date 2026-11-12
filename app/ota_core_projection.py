"""검증된 코어 연결을 카드 검토와 장부에 같은 근거로 전달한다."""
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


def project_canonical_candidate_period_assignments(
    *,
    cards: Dict[str, Dict[str, Any]],
    choices: List[Tuple[str, str, str, str, str]],
) -> List[Dict[str, Any]]:
    """순수하게 이미 판정된 선택을 기존 규칙 형태로 만든다."""
    from collections import defaultdict
    from app.classify import PERIOD_OTA_ORIGIN
    from app.normalize import normalize_merchant

    grouped: Dict[str, Set[Tuple[str, str, str, str]]] = defaultdict(set)
    for source, trip_id, item, starts_on, ends_on in choices:
        grouped[str(source)].add((str(trip_id), str(item), str(starts_on), str(ends_on)))
    rules = []
    for source, options in grouped.items():
        if len(options) != 1:
            continue
        trip_id, item, starts_on, ends_on = next(iter(options))
        card = next((card for card in cards.values() if str(card.get('source_hash') or '') == source), None)
        if not card:
            continue
        basis = (f"결제일 미상 OTA 후보의 검증된 이용기간 {starts_on}~{ends_on}이 "
                 "기존 여행과 겹칩니다. 예약 연결과 예약번호는 확정하지 않았습니다.")
        rules.append({
            'conditions': {'merchant_normalized': normalize_merchant(
                card.get('merchant_normalized') or card.get('merchant') or ''),
                'transaction_direction': 'purchase'},
            'optional': {'source_hash': source, 'inferred_assignment': {
                'trip_id': trip_id, 'confidence': '낮음', 'basis': basis}},
            'effects': {'item': item}, 'origin': PERIOD_OTA_ORIGIN, 'note': '',
            'rule_id': f"auto-ota-undated-candidate-{source[:16]}",
        })
    return rules


# OTA 상태/사유 라벨은 ota_payment_review와 동일하게 유지한다.
from app.ota_labels import OTA_STATUS as _OTA_STATUS
from app.ota_labels import OTA_REASON as _OTA_REASON
from app.ota_status_read_contract import OtaStatusSnapshotRead


def project_card_ota_statuses(current: Optional[OtaStatusSnapshotRead]) -> Tuple[Dict[str, str], Optional[int], Dict[str, Any]]:
    """Pure helper: project OTA link statuses from the caller-gated snapshot.

    Args:
        current: Canonical status-read shape with optional 'generation', 'results',
                 and 'data.results'. Callers apply their freshness gate; this helper
                 does not inspect freshness. If None, returns empty statuses.

    Returns:
        Tuple of (statuses_by_transaction_id, generation, reconciliation_dict).
        reconciliation_dict contains: enabled, fresh, status, generation.
    """
    if current is None:
        return {}, None, {'enabled': True, 'fresh': False, 'status': 'stale', 'generation': None}

    generation = current.get('generation')
    results = current.get('results') or ()

    states: Dict[str, str] = {}
    for result in results:
        reservation = result.get('reservation_link') or {}
        reservation_id = str(reservation.get('transaction_id') or '')
        reservation_state = str(reservation.get('status') or '')
        reservation_projection = {'INFERRED': 'RESERVATION_INFERRED',
                                  'USER_CONFIRMED': 'RESERVATION_CONFIRMED',
                                  'NEEDS_REVIEW': 'RESERVATION_NEEDS_REVIEW',
                                  'STALE': 'RESERVATION_STALE'}.get(reservation_state)
        if reservation_id and reservation_projection:
            states[reservation_id] = reservation_projection
        transaction_id = str(result.get('transaction_id') or '')
        group_only = (result.get('allocation_basis') in
                      ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                      and result.get('individual_payment_evidence') is False)
        state = ('GROUP_RECONCILED' if group_only else
                 'USER_CONFIRMED' if result.get('status') == 'MATCHED_USER' else
                 'INFERRED' if result.get('inferred_link') else
                 'EXACT' if result.get('status') == 'MATCHED_AUTO' else None)
        if transaction_id and state:
            states[transaction_id] = state
        for reserved in result.get('reserved_card_ids') or ():
            states[str(reserved)] = 'REVIEW_REQUIRED'

    # Relation cardinality is independent from the legacy financial allocator.
    for result in results:
        relation = result.get('payment_relation') or {}
        if relation.get('status') == 'LINKED':
            for identity in relation.get('transaction_ids') or ():
                states[str(identity)] = ('GROUP_RECONCILED' if relation.get('balance') == 'BALANCED'
                                         and relation.get('event_count') != 1 else
                                         'EXACT' if relation.get('individual_payment_verified') else 'GROUP_LINKED')

    # Reservation-only candidates from data.results
    for result in (current.get('data') or {}).get('results') or ():
        trace = result.get('candidate_search') or {}
        if not trace.get('reservation_only'):
            continue
        for candidate in trace.get('candidates') or ():
            identity = str(candidate.get('transaction_id') or '')
            if identity:
                states.setdefault(identity, 'CANDIDATE')

    reconciliation = {
        'enabled': True,
        'fresh': True,
        'status': 'ready',
        'generation': generation,
    }
    return states, generation, reconciliation


def project_card_ota_candidate_notes(
    current: Optional[Dict[str, Any]],
    wanted_transaction_ids: Set[str],
    rows: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, List[str]]:
    """Pure helper: extract unresolved canonical OTA candidate notes for given transactions.

    Args:
        current: The canonical snapshot dict with keys 'generation', 'results', 'data'.
        wanted_transaction_ids: Set of transaction_ids we want notes for.
        rows: Optional list of row dicts with 'transaction_id', 'merchant', 'foreign_currency',
              'foreign_amount' for Toyoko fallback note.

    Returns:
        Dict mapping transaction_id -> sorted list of notes (max 2 per transaction).
        Input `current` is not mutated.
    """
    import re
    if current is None:
        return {}

    data = current.get('data') or {}
    events = {str(event.get('ota_event_id')): event for event in data.get('events', [])}
    notes: Dict[str, Set[str]] = {}

    for result in data.get('results', []):
        relation = result.get('payment_relation') or {}
        if relation.get('status') == 'LINKED':
            note = (f"OTA M:N 연결 · 결제 근거 {relation.get('event_count')}개 ↔ 카드 {relation.get('card_count')}건"
                    + (' · 그룹 금액 차이' if relation.get('balance') == 'AMOUNT_DIFFERENCE' else '')
                    + (' · 원문 결제일 미기록' if not relation.get('payment_date_verified') else ''))
            for identity in relation.get('transaction_ids') or ():
                if str(identity) in wanted_transaction_ids:
                    notes.setdefault(str(identity), set()).add(note)
            if not relation.get('individual_payment_verified'):
                continue
        group_only = (result.get('allocation_basis') in
                      ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                      and result.get('individual_payment_evidence') is False)
        if group_only:
            event = events.get(str(result.get('ota_event_id') or ''), {})
            note = ('OTA 반복 결제 그룹은 대응됐지만 이 카드와 예약의 개별 연결 근거는 확인되지 않았습니다.'
                    if event else 'OTA 반복 결제 그룹 대응이며 개별 예약 연결은 미확정입니다.')
            identity = str(result.get('transaction_id') or '')
            if identity in wanted_transaction_ids:
                notes.setdefault(identity, set()).add(note)
            continue

        reservation = result.get('reservation_link') or {}
        reservation_id = str(reservation.get('transaction_id') or '')
        reservation_status = str(reservation.get('status') or '')
        event = events.get(str(result.get('ota_event_id') or ''), {})
        period = event.get('service_period') or {}
        stay = (f" · 숙박 {period.get('starts_on', '?')}~{period.get('ends_on', '?')}"
                if isinstance(period, dict) and period else '')
        booking = str(event.get('booking_ref') or '예약 번호 미확인')
        if reservation_id in wanted_transaction_ids and reservation_status:
            amount_status = reservation.get('amount_status')
            reason = {'INFERRED': '예약 추론 연결 · 결제는 검증되지 않았습니다.' +
                      (' 원문 금액은 확인되지 않았습니다.' if amount_status == 'UNKNOWN' else
                       ' 원문 금액이 다릅니다.' if amount_status == 'MISMATCH' else ''),
                      'USER_CONFIRMED': '사용자가 예약 관계만 확인했습니다 · 결제는 검증되지 않았습니다.',
                      'NEEDS_REVIEW': '예약 후보가 여러 개이거나 근거가 충돌해 사용자 확인이 필요합니다.',
                      'STALE': '저장한 예약 관계의 근거가 바뀌었습니다 · 기존 선택 이력은 유지되며 재확인이 필요합니다.'}.get(reservation_status)
            if reason:
                notes.setdefault(reservation_id, set()).add(f'{reason} · {booking}{stay}')
        if reservation_status == 'NEEDS_REVIEW':
            search = result.get('candidate_search') or {}
            mismatch = any(candidate.get('amount_status') == 'MISMATCH'
                           for candidate in search.get('candidates') or ())
            reason = ('예약 원문 금액 차이 · 예약 관계만 사용자가 확인할 수 있습니다.' if mismatch else
                      '예약 후보가 경합하거나 묶음 합계라 개별 관계가 미확정입니다.')
            for candidate in search.get('candidates') or ():
                identity = str(candidate.get('transaction_id') or '')
                if identity in wanted_transaction_ids:
                    notes.setdefault(identity, set()).add(f'{reason} · {booking}{stay}')
        if result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER'):
            continue

        event = events.get(str(result.get('ota_event_id') or ''), {})
        provider = str(event.get('provider') or 'OTA')
        booking_ref = str(event.get('booking_ref') or '')
        status = _OTA_STATUS.get(str(result.get('status') or ''), str(result.get('status') or '확인 필요'))
        reason = _OTA_REASON.get(str(result.get('reason') or ''),
                                 str(result.get('reason') or '추가 근거 확인 필요').replace('_', ' '))
        note = f"OTA 후보(미확정): {provider} {booking_ref} · {status} · {reason}".strip()
        if provider == 'toyoko':
            period = event.get('service_period') or {}
            basis = ('묶음 합계 · 객실별 결제 미확정' if event.get('reservation_group_only')
                     else '객실 소계 · 결제 완료 근거 미확인')
            note = (f"호텔 예약 후보(미확정): {booking_ref} · "
                    f"숙박 {period.get('starts_on', '?')}~{period.get('ends_on', '?')} · {basis}")

        search_candidates = [candidate.get('transaction_id')
                             for candidate in (result.get('candidate_search') or {}).get('candidates') or ()]
        search_rejections = (result.get('candidate_search') or {}).get('rejected') or ()
        rejected_ids = [candidate.get('transaction_id') for candidate in search_rejections]

        for transaction_id in [*(result.get('candidates') or ()), *search_candidates, *rejected_ids]:
            identity = str(transaction_id or '')
            if provider == 'toyoko' and identity in rejected_ids and identity not in search_candidates:
                continue
            if identity and identity in wanted_transaction_ids:
                candidate_note = note
                if provider == 'toyoko' and any(
                        str(candidate.get('transaction_id')) == identity
                        and candidate.get('basis') == 'HOTEL_BRANCH_AND_STAY_ONLY'
                        for candidate in (result.get('candidate_search') or {}).get('candidates') or ()):
                    candidate_note = (f"호텔 일정 후보(금액 불일치): {booking_ref} · "
                                      f"숙박 {period.get('starts_on', '?')}~{period.get('ends_on', '?')} · "
                                      "같은 지점·숙박기간만 확인 · 결제 미확정")
                if provider == 'toyoko' and any(
                        str(candidate.get('transaction_id')) == identity
                        and candidate.get('amount_status') == 'MISMATCH'
                        for candidate in (result.get('candidate_search') or {}).get('candidates') or ()):
                    candidate_note = (f"호텔 예약 후보(원문 금액 차이): {booking_ref} · "
                                      "금액 차이를 확인하고 예약 관계만 검토하세요 · 결제 미확정")
                notes.setdefault(identity, set()).add(candidate_note)

        for rejected in search_rejections:
            identity = str(rejected.get('transaction_id') or '')
            if identity not in wanted_transaction_ids:
                continue
            rejected_reason = _OTA_REASON.get(
                str(rejected.get('reason') or ''), '같은 카드 조건에서 금액 또는 통화가 다릅니다.')
            if provider == 'toyoko':
                notes.setdefault(identity, set()).add(f'호텔 후보 제외: {booking_ref} · {rejected_reason}')
            else:
                notes.setdefault(identity, set()).add(f'OTA 후보 제외 사유: {rejected_reason}')

    # Toyoko fallback: cards with toyokoinn merchant but no foreign currency/amount
    if rows:
        for row in rows:
            identity = str(row.get('transaction_id') or '')
            merchant = re.sub(r'[^a-z0-9]', '', str(row.get('merchant') or '').casefold())
            if (identity and identity not in notes and merchant.startswith('toyokoinn')
                    and (not row.get('foreign_currency') or not row.get('foreign_amount'))):
                notes[identity] = {'호텔 예약 연결 보류: 카드 원본의 현지 금액·통화 확인이 필요합니다.'}

    # Deduplicate and limit to top 2 per transaction, sorted for determinism
    return {identity: sorted(values, key=lambda note: (
                not note.startswith(('예약 추론 연결', '사용자가 예약 관계', '예약 원문 금액 차이',
                                     '예약 후보가', '저장한 예약 관계')),
                note.startswith('호텔 후보 제외:'), note.startswith('호텔 일정 후보'), note))[:2]
            for identity, values in notes.items()}


def card_matches(facts, data):
    """검증된 코어 연결을 화면에 보완하며 기존 연결과 카드 점유는 유지한다."""
    facts = list(facts)
    occupied = {str(fact.get('transaction_id')): index for index, fact in enumerate(facts)
                if fact.get('transaction_id')}
    existing_counts = Counter(str(fact.get('transaction_id')) for fact in facts if fact.get('transaction_id'))
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    claims = defaultdict(list)
    for result in data.get('results', []):
        if result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER') and result.get('transaction_id'):
            if (result.get('allocation_basis') in
                    ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order') and
                    result.get('individual_payment_evidence') is False):
                # A group-level ordering is not proof that this card paid this booking.
                # Keep it out of per-card booking metadata, travel dates, and ledger fields.
                continue
            claims[str(result['transaction_id'])].append(result)
    for tid, results in claims.items():
        if len(results) != 1:
            continue
        result = results[0]
        event = events.get(str(result.get('ota_event_id')))
        card = cards.get(tid)
        link = (data.get('links') or {}).get(str(result.get('ota_event_id'))) or {}
        if not event or not card or any(result.get(k) or event.get(k) for k in
                ('evidence_changed', 'evidence_missing', 'service_period_conflict')):
            continue
        if isinstance(link, dict) and (link.get('evidence_changed') or link.get('evidence_missing') or
                (link.get('source_digest') and link.get('source_digest') != event.get('source_digest'))):
            continue
        shared = event.get('service_period_basis') == 'LINK-108'
        if not event.get('provider') or (not event.get('booking_ref') and not shared):
            continue
        if card.get('duplicate_of') or card.get('parse_error') or card.get('conflict_reason'):
            continue
        if tid in occupied:
            # 같은 카드와 같은 예약의 결제 영수증에 이용기간만 빠졌다면,
            # 코어가 검증한 해당 예약의 이용기간을 보완한다. 기존 연결은 바꾸지 않는다.
            old = facts[occupied[tid]]
            period = event.get('service_period') or {}
            from app import ota_payments
            if (existing_counts[tid] != 1 or old.get('period') or old.get('period_conflict')
                    or old.get('reservation_status') in ('cancelled', 'refunded')
                    or event.get('reservation_status') in ('cancelled', 'refunded')
                    or str(old.get('provider')) != str(event['provider'])
                    or str(old.get('booking_ref')) != str(event['booking_ref'])
                    or old.get('source_hash') != card.get('source_hash')
                    or not period.get('starts_on') or not period.get('ends_on')
                    or not ota_payments._event_is_paid(event)):
                continue
            digests = set(old.get('source_digests') or old.get('evidence_digests') or [])
            digests.update(event.get('source_digests') or [])
            digests.update(d for d in (old.get('source_sha256'), event.get('source_digest')) if d)
            facts[occupied[tid]] = dict(old, period=dict(period), core_link=True,
                                       source_digests=sorted(digests), ota_event_id=event['ota_event_id'])
            continue
        facts.append({
            'provider': event['provider'], 'booking_ref': event.get('booking_ref') or '',
            'transaction_id': tid, 'source_hash': card.get('source_hash'),
            'merchant': card.get('merchant_normalized') or card.get('merchant'), 'paid_on': event.get('paid_on'),
            'paid_amount_krw': card.get('amount_krw'), 'item': event.get('item'),
            'direction': card.get('transaction_direction'),
            'reservation_status': event.get('reservation_status'),
            'inferred_link': bool(result.get('inferred_link')),
            'allocation_basis': result.get('allocation_basis'),
            'core_link': True, 'ota_event_id': event.get('ota_event_id'),
            'period': event.get('service_period'),
            'service_period_basis': event.get('service_period_basis'),
            'source_sha256': event.get('source_digest'),
            'source_digests': event.get('source_digests') or [event.get('source_digest')],
            'evidence_kind': event.get('evidence_kind'),
            'inference_basis': result.get('inference_basis'),
            'payment_date_verified': result.get('payment_date_verified'),
        })
        occupied[tid] = len(facts) - 1
    # LINK-108 permits a common period without selecting a room, including
    # repeated payment groups. Keep the financial allocation untouched and
    # independently recheck each receipt/card pair before projecting dates.
    from app import ota_payments
    shared_claims = defaultdict(list)
    for result in data.get('results', []):
        tid = str(result.get('transaction_id') or '')
        event = events.get(str(result.get('ota_event_id')), {})
        card = cards.get(tid)
        link = (data.get('links') or {}).get(str(result.get('ota_event_id'))) or {}
        if (tid in occupied or not card or event.get('service_period_basis') != 'LINK-108'
                or result.get('status') not in ('MATCHED_AUTO','MATCHED_USER')
                or any(result.get(k) or event.get(k) for k in
                       ('evidence_changed','evidence_missing','service_period_conflict','period_conflict'))
                or event.get('reservation_status') not in ('observed','completed','confirmed')
                or not ota_payments._event_is_paid(event)
                or ota_payments.pair_check(event,card) is not None):
            continue
        if isinstance(link,dict) and (link.get('evidence_changed') or link.get('evidence_missing')
                or link.get('source_digest') and link['source_digest'] != event.get('source_digest')):
            continue
        shared_claims[tid].append(event)
    for tid, options in shared_claims.items():
        periods = {tuple(sorted((event.get('service_period') or {}).items())) for event in options}
        competing = [events.get(str(result.get('ota_event_id')), {}) for result in claims.get(tid, [])]
        if (len(periods) != 1 or any(other.get('service_period') and
                other['service_period'] != options[0]['service_period'] for other in competing)):
            continue
        event, card = options[0], cards[tid]
        facts.append(dict(provider='forest',booking_ref='',transaction_id=tid,source_hash=card.get('source_hash'),
            merchant=card.get('merchant_normalized') or card.get('merchant'),paid_on=event.get('paid_on'),
            paid_amount_krw=card.get('amount_krw'),item='숙박비',direction='purchase',
            reservation_status='observed',core_link=False,ota_event_id=event['ota_event_id'],
            period=event['service_period'],service_period_basis='LINK-108',
            source_sha256=event.get('source_digest'),
            source_digests=sorted({d for option in options for d in option.get('source_digests',[])}),
            evidence_kind=event.get('evidence_kind')))
    return facts



def extend_report(report, data):
    """열린 원행에 묶인 규칙만 추가한다. 점유·결정·원문과 기존 규칙은 바꾸지 않는다."""
    from app import ota_payments
    from app.normalize import normalize_merchant
    facts = card_matches(report.get('matches', []), data)
    existing = report.get('matches', [])
    existing_count = len(existing)
    updated = [fact for index, fact in enumerate(facts)
               if index >= existing_count or fact != existing[index]]
    if not updated:
        return report
    result = dict(report, matches=facts, rules=list(report.get('rules', [])))
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    for fact in updated:
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
