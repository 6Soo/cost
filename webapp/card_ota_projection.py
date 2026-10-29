"""Card-side OTA display candidate indexing and projections.

Extracts presentation projection responsibilities from webapp.card_flow:
- index_ota_display_candidates: screen-specific inverted index collecting OTA candidates,
  rejection reasons, service periods, and amounts per card transaction.

This module is strictly read-only and presentation-only:
- NO database connections or SQL queries
- NO mutations to snapshot data or financial records
- NO reverse dependencies on card_flow or UI renderers
"""
from __future__ import annotations

from typing import Callable


def index_ota_display_candidates(
    current: dict,
    *,
    transaction_ids=None,
    link_diagnosis_label_fn: Callable[[object], str],
) -> dict:
    """카드 ID별 OTA 후보와 거절 이유를 전부 모으는 화면 전용 역색인."""
    data = current.get('data') or {}
    events = {str(row.get('ota_event_id') or ''): row for row in data.get('events') or ()}
    from app.ota_labels import OTA_REASON
    from decimal import Decimal, InvalidOperation
    cards = {str(row.get('transaction_id') or ''): row for row in data.get('transactions') or ()}

    def amount_text(amount, currency):
        if amount in (None, ''):
            return '금액 미확인'
        try:
            number = Decimal(str(amount))
            if not number.is_finite():
                return '금액 미확인'
            value = f'{number:,f}'
        except (InvalidOperation, ValueError):
            return '금액 미확인'
        return value + ('원' if currency == 'KRW' else ' ' + (currency or '통화 미확인'))

    indexed = {}
    seen = set()
    wanted = None if transaction_ids is None else set(map(str, transaction_ids))
    for result in [*(current.get('results') or ()), *(data.get('results') or ())]:
        if not isinstance(result, dict):
            continue
        event = events.get(str(result.get('ota_event_id') or ''), {})
        booking = str(event.get('booking_ref') or '예약 번호 미확인')
        provider = str(event.get('provider') or 'OTA')
        trace = result.get('candidate_search') or {}
        group_only = (result.get('individual_payment_evidence') is False and
                      result.get('allocation_basis') in
                      ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order'))
        result_kind = ('묶음 대응' if group_only else
                       '확정 연결' if result.get('status') in ('MATCHED_AUTO', 'MATCHED_USER') else
                       '금액 대조 보류' if result.get('status') == 'HOLD_AMOUNT_UNVERIFIED' else
                       '금액 비교' if result.get('status') == 'HOLD_AMOUNT_MISMATCH' else '후보')
        for kind, values in ((result_kind, result.get('candidates') or ()),
                             ('후보', trace.get('candidates') or ()),
                             ('제외', trace.get('rejected') or ())):
            for value in values:
                if isinstance(value, dict):
                    identity = str(value.get('transaction_id') or '')
                    why = value.get('reason') or result.get('reason')
                    if value.get('date_status') == 'UNKNOWN':
                        why = 'payment_date_unknown'
                else:
                    identity, why = str(value or ''), result.get('reason')
                if wanted is not None and identity not in wanted:
                    continue
                if identity:
                    card = cards.get(identity)
                    # Rejection visibility and temporal relevance belong to the core
                    # candidate trace; the screen only consumes that decision.
                    if kind == '제외' and not (isinstance(value, dict) and
                                               value.get('display_relevant') is True):
                        continue
                    reason = ('결제일 확인 필요' if why == 'payment_date_unknown' else
                              OTA_REASON.get(str(why), link_diagnosis_label_fn(why)) if why else '')
                    period = event.get('service_period') or {}
                    date_note = (event.get('paid_on') or
                                 (f"{period.get('starts_on', '?')}~{period.get('ends_on', '?')}"
                                  if isinstance(period, dict) and period else ''))
                    item = (identity, booking, provider, kind, str(reason or ''), str(date_note or ''))
                    if item not in seen:
                        seen.add(item)
                        currency = str(event.get('currency') or '').upper()
                        native = event.get('amount')
                        if native in (None, '') and currency == 'KRW':
                            native = event.get('amount_krw')
                        label = '예약 결제액 ' if event.get('event_type') in ('charge', 'refund') else '예약 원문 금액 '
                        amounts = label + amount_text(native, currency)
                        if card:
                            amounts += ' · 카드 청구액 ' + amount_text(card.get('amount_krw'), 'KRW')
                            if card.get('foreign_amount') not in (None, ''):
                                amounts += ' · 카드 외화 ' + amount_text(card['foreign_amount'], card.get('foreign_currency'))
                        indexed.setdefault(identity, []).append(
                            f"{provider} 예약 {booking} · {kind}"
                            + f' · {amounts}'
                            + (f" · 근거 {reason}" if reason else '')
                            + (f" · 이용/결제일 {date_note}" if date_note else ''))
        reserved_ids = result.get('reserved_card_ids') or ()
        reservation = result.get('reservation_link') or {}
        reserved_ids = [*reserved_ids, reservation.get('transaction_id')]
        for value in reserved_ids:
            identity = str(value or '')
            if identity and (wanted is None or identity in wanted):
                indexed.setdefault(identity, [])
    return indexed
