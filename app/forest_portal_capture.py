"""Parse saved forest portal observations without inventing payment dates."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


def day(value):
    value = str(value).strip().replace('.', '-')
    return date.fromisoformat(value).isoformat()


def money(value, *, allow_zero=False):
    try:
        amount = Decimal(str(value).replace(',', '').replace('원', '').strip())
    except InvalidOperation as exc:
        raise ValueError('FOREST_AMOUNT_INVALID') from exc
    if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero) or amount != amount.to_integral_value():
        raise ValueError('FOREST_AMOUNT_INVALID')
    return int(amount)


def base(ref, start, end, label, status, observed_at):
    if not ref or not label or day(start) >= day(end):
        raise ValueError('FOREST_RESERVATION_INVALID')
    if datetime.fromisoformat(observed_at.replace('Z', '+00:00')).utcoffset() is None:
        raise ValueError('FOREST_OBSERVATION_TIME_REQUIRED')
    return dict(provider='forest', booking_number=ref, label=label,
                service_start_on=day(start), service_end_on=day(end),
                reservation_status=status, payment_status='unknown', paid_on=None,
                card_last4=None, price_components=[], product_type='lodging',
                evidence_format='forest-portal-v1', parser_version=1, observed_at=observed_at)


def foresttrip_row(row, kind, observed_at):
    cells = row['cells']
    cancelled = kind == 'cancel'
    if len(cells) != (5 if cancelled else 6):
        raise ValueError('FOREST_TABLE_SHAPE_INVALID')
    payment, product, period = (cells[0], cells[1], cells[3]) if cancelled else (cells[1], cells[2], cells[4])
    ref = re.search(r'\[([A-Za-z0-9_-]+)\]', product)
    dates = re.fullmatch(r'(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})', period.strip())
    if not ref or not dates:
        raise ValueError('FOREST_RESERVATION_INVALID')
    if '자연휴양림' not in product:
        raise ValueError('FOREST_FACILITY_MISSING')
    label = re.sub(r'^\[[^]]+\]\s*(?:공|국|사)\s+', '', product).split('자연휴양림')[0] + '자연휴양림'
    fact = base('foresttrip:' + ref[1], *dates.groups(), label,
                'cancelled' if cancelled else 'completed' if kind == 'use' else 'confirmed', observed_at)
    fact['portal'] = 'foresttrip'
    order = re.match(r'([A-Za-z0-9_-]{6,64})(?:\s|$)', cells[0]) if not cancelled else None
    fact['order_number'] = order[1] if order else None
    # Cancellation tables contain cancellation amounts/dates, never a charge.
    if not cancelled:
        paid = re.search(r'^(\d{4}-\d{2}-\d{2})\s*결제금액\s*([\d,]+)\s*원', payment)
        if kind == 'pay' and not paid:
            raise ValueError('FOREST_PAYMENT_INVALID')
        if paid:
            fact.update(paid_on=day(paid[1]), payment_status='paid', amount_krw=money(paid[2]))
            fact['price_components'] = [dict(kind='paid_today', currency='KRW', decimal_text=str(fact['amount_krw']))]
    return fact


def reservation_total(lines):
    """The portal repeats daily prices, category subtotals and the grand total.

    Only the explicit grand-total row is a reservation amount. Adding every
    rsrvtAmt counts the same money repeatedly.
    """
    # Older flat captures contain components only, without the summary axes.
    if lines and all('goodsClsscCd' not in line and 'useDt' not in line for line in lines):
        return sum(money(line['rsrvtAmt'],allow_zero=True) for line in lines)
    totals = [money(line['rsrvtAmt'],allow_zero=True) for line in lines
              if not line.get('goodsClsscCd') and not line.get('useDt')]
    return totals[0] if len(totals) == 1 else None


def sooperang_records(listing, details, observed_at):
    # The list explicitly binds each reservation ID to its facility and stay.
    blocks = re.split(r'(?=AD\d{8,})', listing['text'])
    by_ref, raw_blocks = {}, {}
    for block in blocks:
        ref = re.match(r'(AD\d{8,})([^\n]+)', block)
        period = re.search(r'이용날짜\s*:\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})', block)
        status = re.search(r'예약상태\s*:\s*([^\n]+)', block)
        if ref and period and status:
            fact = base('sooperang:' + ref[1], *period.groups(), ref[2].strip(),
                        'cancelled' if status[1].strip() == '취소' else
                        'completed' if status[1].strip() == '이용완료' else 'unknown', observed_at)
            fact['portal'] = 'sooperang'
            booked = re.search(r'신청날짜\s*:\s*(\d{4}-\d{2}-\d{2})', block)
            fact['booked_on'] = day(booked[1]) if booked else None
            if ref[1] in by_ref and by_ref[ref[1]] != fact:
                raise ValueError('FOREST_LIST_IDENTITY_CONFLICT')
            by_ref[ref[1]] = fact
            raw_blocks[ref[1]] = block
    for record in details:
        if not record.get('ok') or record['id'] not in by_ref:
            raise ValueError('FOREST_DETAIL_IDENTITY_MISSING')
        fact = dict(by_ref[record['id']])
        lines = record['data'].get('useAmtSmmarList') or []
        if lines:
            fact['reservation_amount_krw'] = reservation_total(lines)
        # Application date, payment deadline and daily room prices are not paid facts.
        yield {'list_text': raw_blocks[record['id']], 'detail': record}, fact


def records(directory, observed_at):
    root = Path(directory)
    for path in sorted(root.glob('*.json')):
        if path.stem.startswith(('pay-', 'use-', 'cancel-')):
            kind = path.stem.split('-')[0]
            capture = json.loads(path.read_text(encoding='utf-8-sig'))
            for row in capture['rows']:
                if not any('[' in cell for cell in row['cells']):
                    continue  # empty-table placeholder
                yield {'capture': path.name, 'url': capture['url'], 'head':capture.get('head'), 'row': row}, foresttrip_row(row, kind, observed_at)
    listing = root / 'sooperang-list-default.json'
    details = root / 'sooperang-details.json'
    if listing.exists() or details.exists():
        yield from sooperang_records(json.loads(listing.read_text(encoding='utf-8-sig')),
                                    json.loads(details.read_text(encoding='utf-8-sig')), observed_at)
