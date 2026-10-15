"""Identical payments and identical bookings pair one to one even though the amount alone cannot tell them apart."""
from decimal import Decimal

from app.ota_portal import portal_matches

PERIOD = {'starts_on': '2026-04-12', 'ends_on': '2026-04-13'}


def fact(ref, amount=Decimal('50804'), period=PERIOD, card='8835'):
    return {ref: {'v': dict(booking_ref=ref, card_last4=card, currency='KRW', amount=amount, period=period,
                            source_sha256='hash-' + ref, payment_format='canonical_paid')}}


def row(tid, amount=50804, card='8835'):
    return dict(transaction_id=tid, source_hash='src-' + tid, merchant='AGODA_NICE-Agoda', merchant_normalized='agoda',
                card_kind='일시불', card_tail=card, transaction_direction='purchase', duplicate_of='', parse_error='',
                conflict_reason='', amount_krw=amount, foreign_amount='', foreign_currency='')


def analysis(*facts):
    merged = {}
    for item in facts:
        merged.update(item)
    return {'facts': merged, 'blocked': {}, 'rejected': {}}


def test_three_identical_payments_pair_with_three_identical_bookings():
    facts = analysis(fact('B1'), fact('B2'), fact('B3'))
    rows = [row('T1'), row('T2'), row('T3')]
    matches = portal_matches([], rows, analysis=facts)
    assert sorted(m['booking_ref'] for m in matches) == ['B1', 'B2', 'B3']
    assert sorted(m['transaction_id'] for m in matches) == ['T1', 'T2', 'T3']


def test_fewer_payments_than_bookings_stays_unmatched():
    facts = analysis(fact('B1'), fact('B2'), fact('B3'))
    assert portal_matches([], [row('T1'), row('T2')], analysis=facts) == []


def test_bookings_with_different_stays_are_not_paired_by_guess():
    other = {'starts_on': '2026-04-20', 'ends_on': '2026-04-21'}
    facts = analysis(fact('B1'), fact('B2', period=other))
    assert portal_matches([], [row('T1'), row('T2')], analysis=facts) == []
