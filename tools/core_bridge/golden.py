"""Generate synthetic golden cases by running the current Python through the bridge.

Expected values are whatever Python outputs; they are never edited by hand.
Regenerate: ``python -m tools.core_bridge.golden write`` (or ``check`` to detect drift).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / 'core' / 'golden' / 'synthetic'
AREAS = ('classify', 'plan', 'refund_pairing', 'ota_links')

TRIP_A = dict(trip_id='T-A', display_key='SYN-A', destination='도쿄', starts_on='2026-10-01', ends_on='2026-10-05')
TRIP_B = dict(trip_id='T-B', display_key='SYN-B', destination='도쿄', starts_on='2026-11-10', ends_on='2026-11-15')
TRIP_KR = dict(trip_id='T-KR', display_key='SYN-KR', destination='제주', starts_on='2026-12-01', ends_on='2026-12-03')
TRIP_SG = dict(trip_id='T-SG', display_key='SYN-SG', destination='싱가포르', starts_on='2026-09-19', ends_on='2026-09-24')
TRIPS = [TRIP_A, TRIP_B, TRIP_KR]


def _run(command, request):
    from tools.core_bridge.cli import handle
    response = handle(command, request, sha='')
    if not response['ok']:
        raise RuntimeError(f"golden generation failed: {command} {response['error']}")
    return response['result']


def _case(area, case_id, command, request, note=''):
    return {'case_id': f'{area}-{case_id}', 'area': area, 'command': command, 'note': note,
            'input': request, 'expected': _run(command, request)}


# --- classify (app.classify.classify_transaction) -----------------------------------------

def _txn(tid, merchant, **changes):
    row = {'transaction_id': tid, 'source_hash': 'syn-hash-' + tid, 'issuer': 'SYN-BANK', 'card_tail': '0001',
           'card_kind': '국내', 'transaction_direction': 'purchase', 'transaction_kind': '승인',
           'merchant': merchant, 'approval_date': '2026-10-03', 'posting_date': '2026-10-05',
           'amount_krw': 12000, 'description_raw': '', 'foreign_currency': '', 'parse_error': ''}
    row.update(changes)
    return row


def _rule(rule_id, merchant, item, *, description='', optional=None, origin='', conditions=None, version=1):
    effects = {'item': item}
    if description:
        effects['description'] = description
    return {'rule_id': rule_id, 'version': version, 'status': 'active',
            'conditions': dict({'merchant_normalized': merchant}, **(conditions or {})),
            'effects': effects, 'optional': optional or {}, 'origin': origin}


def classify_cases():
    from app.classify import CLEAR_PATTERNS
    from tools.core_bridge.golden_guard import CATEGORY_INDUSTRIES, FAMILY_MERCHANTS
    out, n = [], 0

    def add(note, **case):
        nonlocal n
        n += 1
        out.append(_case('classify', f'{n:03d}', 'classify', {'cases': [case]}, note))

    for needle, *_ in CLEAR_PATTERNS:
        add('pattern exact', transaction=_txn('syn-c1', needle))
        add('pattern prefix', transaction=_txn('syn-c1', needle + ' syn'))
        add('pattern inside word is not a match', transaction=_txn('syn-c1', 'syn' + needle))
    for merchant in FAMILY_MERCHANTS:
        add('named merchant family', transaction=_txn('syn-c1', merchant))
    for industry in CATEGORY_INDUSTRIES:
        add('card category', transaction=_txn('syn-c1', 'SYN SHOP', description_raw='card-category:' + industry))
    for industry in ('편의점', '택시', '호텔', '항공사'):
        add('card category with verified overseas trip', transaction=_txn(
            'syn-c1', 'SYN SHOP', description_raw='card-category:' + industry, card_kind='해외',
            foreign_currency='JPY'), trip_ids=['T-A'])
    add('unreadable amount', transaction=_txn('syn-c1', 'gs25', parse_error='AMOUNT_UNREADABLE', amount_krw=None))
    add('prior decision wins', transaction=_txn('syn-c1', 'gs25'),
        prior_decision={'item': '수동항목', 'description': 'syn', 'display_tab_id': 'T-A', 'trip_id': 'T-A'})
    add('no rule, no pattern', transaction=_txn('syn-c1', 'SYN UNKNOWN'))
    add('booking evidence needed', transaction=_txn('syn-c1', 'AGODA'))
    add('skyticket provider default', transaction=_txn('syn-c1', '어드벤처코리아'))
    rule = _rule('syn-rule-1', 'syn cafe', '식비', description='합성 카페')
    add('rule match', transaction=_txn('syn-c1', 'SYN CAFE'), rules=[rule])
    add('rule needs exact merchant', transaction=_txn('syn-c1', 'SYN CAFE 2'), rules=[rule])
    add('two rules, same effect', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[rule, _rule('syn-rule-2', 'syn cafe', '식비', description='합성 카페')])
    add('rule conflict', transaction=_txn('syn-c1', 'SYN CAFE'), rules=[rule, _rule('syn-rule-2', 'syn cafe', '기타경비')])
    for lo, hi, expect_amount in ((None, 10000, 12000), (10000, None, 12000), (13000, None, 12000), (None, 11000, 12000)):
        window = {k: v for k, v in (('min', lo), ('max', hi)) if v is not None}
        add(f'amount range {window}', transaction=_txn('syn-c1', 'SYN CAFE', amount_krw=expect_amount),
            rules=[_rule('syn-rule-r', 'syn cafe', '식비', optional={'amount_range': window})])
    add('card kind condition hit', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[_rule('syn-rule-k', 'syn cafe', '식비', conditions={'card_kind': '국내'})])
    add('card kind condition miss', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[_rule('syn-rule-k', 'syn cafe', '식비', conditions={'card_kind': '해외'})])
    add('direction condition', transaction=_txn('syn-c1', 'SYN CAFE', transaction_direction='cancellation'),
        rules=[_rule('syn-rule-d', 'syn cafe', '식비', conditions={'transaction_direction': 'purchase'})])
    add('date window hit', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[_rule('syn-rule-p', 'syn cafe', '식비', optional={'date_or_service_period': {
            'starts_on': '2026-10-01', 'ends_on': '2026-10-05'}})])
    add('date window miss', transaction=_txn('syn-c1', 'SYN CAFE', approval_date='2026-11-03'),
        rules=[_rule('syn-rule-p', 'syn cafe', '식비', optional={'date_or_service_period': {
            'starts_on': '2026-10-01', 'ends_on': '2026-10-05'}})])
    add('travel country rule, trip verified', transaction=_txn('syn-c1', 'SYN CAFE JP'),
        rules=[_rule('syn-rule-t', 'syn cafe jp', '식비', optional={'travel_country': 'JP'})], trip_ids=['T-A'])
    add('travel country rule, no trip', transaction=_txn('syn-c1', 'SYN CAFE JP'),
        rules=[_rule('syn-rule-t', 'syn cafe jp', '식비', optional={'travel_country': 'JP'})])
    add('booking period rule, trip verified', transaction=_txn('syn-c1', 'AGODA'),
        rules=[_rule('syn-rule-b', 'agoda', '숙박비', optional={'booking_period': True})], trip_ids=['T-A'])
    add('booking period rule, no trip', transaction=_txn('syn-c1', 'AGODA'),
        rules=[_rule('syn-rule-b', 'agoda', '숙박비', optional={'booking_period': True})])
    add('default local rule', transaction=_txn('syn-c1', 'SYN LOCAL SHOP', card_kind='해외', foreign_currency='JPY'),
        rules=[_rule('syn-rule-star', '*', '현지경비')])
    add('default rule skipped for booking merchant', transaction=_txn('syn-c1', 'AGODA'),
        rules=[_rule('syn-rule-star', '*', '현지경비')])
    add('merchant family agoda', transaction=_txn('syn-c1', 'agoda syn'),
        rules=[_rule('syn-rule-f', 'agoda', '숙박비', optional={'merchant_family': 'agoda'})])
    inferred = lambda origin, trip='T-A', conf='높음', rid='syn-rule-i': _rule(  # noqa: E731
        rid, 'syn cafe', '식비', origin=origin,
        optional={'inferred_assignment': {'trip_id': trip, 'confidence': conf, 'basis': '합성 근거'}})
    for origin in ('owner-booking', 'ota-mail-live', 'ota-portal-live', 'automatic-trip-priority', 'owner-country-exception',
                   'guide-airfare', 'history-recovery-20261003', 'syn-origin'):
        add(f'inferred assignment origin {origin}', transaction=_txn('syn-c1', 'SYN CAFE'),
            rules=[inferred(origin)], trip_ids=['T-A'])
        add(f'inferred assignment origin {origin}, trip not verified', transaction=_txn('syn-c1', 'SYN CAFE'),
            rules=[inferred(origin)])
    add('inferred assignments disagree', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[inferred('syn-origin', 'T-A', rid='syn-rule-i1'), inferred('syn-origin', 'T-B', rid='syn-rule-i2')],
        trip_ids=['T-A', 'T-B'])
    for day, tail, kind in (('2026-10-03', '3820', '국내'), ('2026-10-03', '3820', '해외'), ('2026-09-21', '3820', '해외'),
                            ('2026-10-03', '0001', '국내'), ('', '3820', '국내')):
        add(f'card 3820 residual {day} {kind}', transaction=_txn('syn-c1', 'SYN UNKNOWN', card_tail=tail, card_kind=kind,
                                                                  approval_date=day, posting_date=day or ''),
            residual_policy=True, trip_ids=['T-SG'])
    add('fukutake with trip', transaction=_txn('syn-c1', 'FUKUTAKE FOUNDATION', card_kind='해외', foreign_currency='JPY'),
        trip_ids=['T-A'])
    add('fukutake without trip resolver', transaction=_txn('syn-c1', 'FUKUTAKE FOUNDATION', card_kind='해외',
                                                            foreign_currency='JPY'))
    return out


# --- plan (app.automatic_classification.plan) ---------------------------------------------

def _row(tid, merchant, **changes):
    row = {'transaction_id': tid, 'merchant': merchant, 'approval_date': '2026-10-03', 'posting_date': '2026-10-05',
           'amount_krw': 15000, 'approval_number': 'SYN-AP-' + tid[4:], 'card_kind': '국내'}
    row.update(changes)
    return row


def plan_cases():
    out, n = [], 0

    def add(note, scenario, **options):
        nonlocal n
        n += 1
        request = dict({'scenario': scenario, 'trips': options.pop('trips', TRIPS)}, **options)
        out.append(_case('plan', f'{n:03d}', 'plan', request, note))

    first = 'syn-p1'
    base = lambda **c: {'rows': [dict(_row(first, 'SYN SHOP'), **c)]}  # noqa: E731
    for reconsider in (False, True):
        for selected in (False, True):
            tag = f'reconsider={reconsider} selected={selected}'
            opts = dict(reconsider=reconsider, **({'transaction_ids': [first]} if selected else {}))
            scenario = {'rows': [_row(first, 'SYN SHOP'), _row('syn-p2', 'gs25'), _row('syn-p3', 'SYN HOTEL', amount_krw=90000)]}
            add('three fresh rows ' + tag, scenario, **opts)
            add('history: review decision ' + tag, dict(scenario, decisions=[
                {'transaction_id': first, 'item': '수동항목', 'display_tab_id': 'T-A'}]), **opts)
            add('history: manual override ' + tag, dict(scenario, overrides=[first]), **opts)
            add('hold, exclusion, conflict ' + tag, dict(scenario, holds=[{'transaction_id': first}],
                exclusions=[{'transaction_id': 'syn-p2'}]), **opts)
    for note, change in (
            ('parse error', {'parse_error': 'AMOUNT_UNREADABLE', 'amount_krw': None}),
            ('duplicate', {'duplicate_of': 'syn-p0'}), ('conflict', {'conflict_reason': 'syn conflict'}),
            ('recorded P2 judgement', {'classification_source': 'ai_inference', 'classification_state': 'classified',
                                       'item': '식비', 'trip_id': 'T-A', 'display_tab_id': 'T-A'}),
            ('already classified, valid trip', {'classification_source': 'inference', 'classification_state': 'classified',
                                                'item': '식비', 'trip_id': 'T-A', 'display_tab_id': 'T-A'}),
            ('already classified, stale trip', {'classification_source': 'inference', 'classification_state': 'classified',
                                                'item': '식비', 'trip_id': 'T-GONE', 'display_tab_id': 'T-GONE'}),
            ('user exception source', {'classification_source': 'user_exception', 'classification_state': 'classified',
                                       'item': '식비'}),
            ('decided_at set', {'decided_at': '2026-10-04T00:00:00Z', 'item': '식비', 'classification_state': 'classified'}),
            ('rule_conflict source', {'classification_source': 'rule_conflict'}),
            ('no use date', {'approval_date': '', 'posting_date': '2026-10-05'}),
            ('bad use date', {'approval_date': '1900-01-01', 'posting_date': '1900-01-01'}),
            ('no dates at all', {'approval_date': '', 'posting_date': ''}),
            ('before all trips', {'approval_date': '2026-08-01', 'posting_date': '2026-08-02'}),
            ('after all trips', {'approval_date': '2027-01-20', 'posting_date': '2027-01-21'}),
            ('completed period 2025', {'approval_date': '2025-10-03', 'posting_date': '2025-10-04'}),
            ('closed quarter 2026Q1', {'approval_date': '2026-02-03', 'posting_date': '2026-02-04'}),
            ('boundary 2026-06-30', {'approval_date': '2026-06-30', 'posting_date': '2026-06-30'}),
            ('overseas purchase', {'card_kind': '해외', 'foreign_currency': 'JPY', 'foreign_amount': '1500'}),
            ('domestic during overseas trip', {'card_kind': '국내'}),
            ('domestic during domestic trip', {'approval_date': '2026-12-02', 'posting_date': '2026-12-03'}),
            ('same day, two trips, tie', {'approval_date': '2026-10-03'}),
            ('card 3820 domestic', {'card_tail': '3820'}),
            ('card 3820 overseas', {'card_tail': '3820', 'card_kind': '해외', 'foreign_currency': 'JPY'}),
            ('card 3820 decided', {'card_tail': '3820', 'classification_source': 'user_decision',
                                   'classification_state': 'classified', 'item': '식비'}),
            ('card 3820 online purchase', {'card_tail': '3820', 'card_kind': '해외', 'foreign_currency': 'USD',
                                           'merchant': 'AMAZON.COM'}),
            ('fukutake', {'merchant': 'FUKUTAKE FOUNDATION', 'card_kind': '해외', 'foreign_currency': 'JPY'}),
            ('fukutake already generic', {'merchant': 'FUKUTAKE FOUNDATION', 'item': '현지경비',
                                          'classification_state': 'classified', 'classification_source': 'code_inference',
                                          'trip_id': 'T-A', 'display_tab_id': 'T-A'}),
            ('booking merchant', {'merchant': 'AGODA'}),
            ('card category hotel', {'description_raw': 'card-category:호텔'}),
            ('card category taxi', {'description_raw': 'card-category:택시', 'merchant': 'SYN TAXI'}),
            ('cancellation direction', {'transaction_direction': 'cancellation', 'amount_krw': -15000,
                                        'transaction_kind': '취소'}),
            ('zero amount', {'amount_krw': 0})):
        add(note, base(**change))
        add(note + ' (reconsider)', base(**change), reconsider=True)
    nets = {'T-B': 100}
    add('nets break a tie', base(), nets=nets)
    add('trips: none', base(), trips=[])
    add('trips: only invalid', base(), trips=[dict(TRIP_A, ends_on='2026-09-01')])
    add('trips: archived', base(), trips=[dict(TRIP_A, archived=1)])
    add('trips: overlapping same start', base(), trips=[TRIP_A, dict(TRIP_A, trip_id='T-A2', display_key='SYN-A2')])
    add('restored from ledger entry', {'rows': [_row(first, 'SYN SHOP', item='식비', decided_at='2026-10-04T00:00:00Z',
                                                      classification_state='classified')],
                                       'ledger': [{'transaction_id': first, 'item': '식비', 'display_tab_id': 'T-B', 'trip_id': 'T-B'}]})
    add('restored from board row', {'rows': [_row(first, 'SYN SHOP', item='식비', decided_at='2026-10-04T00:00:00Z',
                                                   classification_state='classified')],
                                    'boards': [{'transaction_id': first, 'display_tab_id': 'T-B',
                                                'payload': {'item': '식비', 'confirmed_by': 'automatic'}}]})
    add('ledger entry item overrides', {'rows': [_row(first, 'SYN SHOP')],
                                        'ledger': [{'transaction_id': first, 'item': '입장료', 'display_tab_id': '', 'trip_id': ''}]})
    add('recorded trip kept from ledger', {'rows': [_row(first, 'SYN SHOP')],
                                          'ledger': [{'transaction_id': first, 'item': '식비', 'display_tab_id': 'T-B', 'trip_id': 'T-B'}]})
    evidence = {first: {'source_hash': 'syn-hash-' + first, 'trip_id': 'T-B', 'item': '숙박비', 'basis': '합성 예약기간'}}
    for reconsider in (False, True):
        add(f'booking evidence reconsider={reconsider}', base(), evidence=evidence, reconsider=reconsider)
        add(f'booking evidence for another source hash reconsider={reconsider}', base(),
            evidence={first: dict(evidence[first], source_hash='syn-other')}, reconsider=reconsider)
        add(f'booking evidence on recorded inference reconsider={reconsider}', {
            'rows': [_row(first, 'SYN SHOP', classification_source='inference', classification_state='classified',
                          item='숙박비', trip_id='T-A', display_tab_id='T-A')],
            'ledger': [{'transaction_id': first, 'item': '숙박비', 'display_tab_id': 'T-A', 'trip_id': 'T-A'}],
            'boards': [{'transaction_id': first, 'display_tab_id': 'T-A',
                        'payload': {'item': '숙박비', 'confirmed_by': 'automatic'}}]}, evidence=evidence, reconsider=reconsider)
    # refund inheritance
    refund_rows = [_row('syn-p1', 'SYN SHOP', approval_number='SYN-AP-1', item='식비', classification_state='classified',
                        classification_source='inference', trip_id='T-A', display_tab_id='T-A'),
                   _row('syn-p2', 'SYN SHOP', transaction_direction='cancellation', transaction_kind='취소',
                        amount_krw=-15000, approval_number='SYN-CX-2', original_approval_number='SYN-AP-1')]
    add('refund inherits original', {'rows': refund_rows})
    add('refund inherits original (reconsider)', {'rows': refund_rows}, reconsider=True)
    add('partial refund', {'rows': [dict(refund_rows[0]), dict(refund_rows[1], amount_krw=-5000)]})
    add('excess refund', {'rows': [dict(refund_rows[0]), dict(refund_rows[1], amount_krw=-20000)]})
    add('refund, original outside selection', {'rows': refund_rows}, transaction_ids=['syn-p2'])
    add('refund already refund_original', {'rows': [refund_rows[0], dict(
        refund_rows[1], classification_source='refund_original', classification_state='classified',
        item='식비', trip_id='T-A', display_tab_id='T-A')]})
    add('refund without original', {'rows': [dict(refund_rows[1], original_approval_number='SYN-AP-9')]})
    add('original of a refund keeps ledger tab', {'rows': [dict(refund_rows[0], item='', classification_state='needs_review',
                                                                trip_id='', display_tab_id='', classification_source='')]
                                                   + [refund_rows[1]],
                                                   'ledger': [{'transaction_id': 'syn-p1', 'item': '식비',
                                                               'display_tab_id': 'T-A', 'trip_id': 'T-A'}]})
    return out


# --- refund pairing (app.partial_refund) ---------------------------------------------------

def _pair_row(tid, direction, amount, **changes):
    row = {'transaction_id': tid, 'transaction_direction': direction, 'amount_krw': amount,
           'transaction_kind': '취소' if direction == 'cancellation' else '승인', 'merchant': 'SYN SHOP',
           'approval_date': '2026-10-03', 'posting_date': '2026-10-05', 'card_tail': '0001', 'issuer': 'SYN-BANK'}
    row.update(changes)
    return row


def refund_cases():
    out, n = [], 0

    def add(note, rows):
        nonlocal n
        n += 1
        out.append(_case('refund_pairing', f'{n:03d}', 'links', {'kind': 'refund', 'scenario': {'rows': rows}}, note))

    P = lambda tid='syn-r1', amount=10000, **c: _pair_row(tid, 'purchase', amount, approval_number='SYN-A-' + tid[4:], **c)  # noqa: E731
    C = lambda tid, amount, ref, **c: _pair_row(tid, 'cancellation', amount, original_approval_number=ref,  # noqa: E731
                                                 approval_number='SYN-X-' + tid[4:], **c)
    add('no refunds', [P()])
    add('full refund by approval number', [P(), C('syn-r2', -10000, 'SYN-A-r1')])
    add('partial refund', [P(), C('syn-r2', -4000, 'SYN-A-r1')])
    add('two partials make a full refund', [P(), C('syn-r2', -4000, 'SYN-A-r1'), C('syn-r3', -6000, 'SYN-A-r1')])
    add('two partials, still partial', [P(), C('syn-r2', -2000, 'SYN-A-r1'), C('syn-r3', -3000, 'SYN-A-r1')])
    add('excess refund', [P(), C('syn-r2', -12000, 'SYN-A-r1')])
    add('excess through two cancellations', [P(), C('syn-r2', -6000, 'SYN-A-r1'), C('syn-r3', -6000, 'SYN-A-r1')])
    add('whitespace-padded reference', [P(), C('syn-r2', -10000, ' SYN-A-r1 ')])
    add('digit change is no match', [P(), C('syn-r2', -10000, 'SYN-A-r2')])
    add('other card tail', [P(), C('syn-r2', -10000, 'SYN-A-r1', card_tail='0002')])
    add('other issuer', [P(), C('syn-r2', -10000, 'SYN-A-r1', issuer='SYN-BANK-B')])
    add('two purchases with the same approval number', [P(), P('syn-r9'), C('syn-r2', -10000, 'SYN-A-r1')])
    add('original is a duplicate', [P(duplicate_of='syn-r0'), C('syn-r2', -10000, 'SYN-A-r1')])
    add('original has a conflict', [P(conflict_reason='syn conflict'), C('syn-r2', -10000, 'SYN-A-r1')])
    add('cancellation has a parse error', [P(), C('syn-r2', -10000, 'SYN-A-r1', parse_error='AMOUNT_UNREADABLE')])
    add('one sibling cancellation is a duplicate', [P(), C('syn-r2', -4000, 'SYN-A-r1'),
                                                    C('syn-r3', -4000, 'SYN-A-r1', duplicate_of='syn-r2')])
    add('one sibling cancellation has a conflict', [P(), C('syn-r2', -4000, 'SYN-A-r1'),
                                                    C('syn-r3', -4000, 'SYN-A-r1', conflict_reason='syn conflict')])
    add('completed period group', [P(approval_date='2025-10-03', posting_date='2025-10-04'),
                                   C('syn-r2', -4000, 'SYN-A-r1', approval_date='2025-10-05', posting_date='2025-10-06')])
    add('positive amount cancellation is ignored', [P(), C('syn-r2', 10000, 'SYN-A-r1')])
    add('cancellation without a purchase', [C('syn-r2', -10000, 'SYN-A-NONE')])
    add('two originals, two refunds', [P(), P('syn-r5', 7000), C('syn-r2', -10000, 'SYN-A-r1'), C('syn-r6', -7000, 'SYN-A-r5')])
    foreign = lambda tid, direction, amount, day, foreign_amount='1500', **c: _pair_row(  # noqa: E731
        tid, direction, amount, **dict(dict(card_kind='해외', foreign_currency='JPY', foreign_amount=foreign_amount,
        approval_date=day, posting_date=day, merchant_normalized='syn shop'), **c))
    add('foreign amount pair', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                foreign('syn-r2', 'cancellation', -14100, '2026-10-20')])
    add('foreign amount, different amount', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                             foreign('syn-r2', 'cancellation', -14100, '2026-10-20', '1600')])
    add('foreign amount, refund before purchase', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                                   foreign('syn-r2', 'cancellation', -14000, '2026-10-01')])
    add('foreign amount, beyond window', [foreign('syn-r1', 'purchase', 14000, '2024-10-03'),
                                          foreign('syn-r2', 'cancellation', -14000, '2026-10-20')])
    add('foreign amount, two purchases, one refund', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                                      foreign('syn-r3', 'purchase', 14000, '2026-10-04'),
                                                      foreign('syn-r2', 'cancellation', -14000, '2026-10-20')])
    add('foreign amount, one purchase, two refunds', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                                      foreign('syn-r2', 'cancellation', -14000, '2026-10-20'),
                                                      foreign('syn-r3', 'cancellation', -14000, '2026-10-21')])
    add('foreign amount, two and two', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                        foreign('syn-r3', 'purchase', 14000, '2026-10-04'),
                                        foreign('syn-r2', 'cancellation', -14000, '2026-10-20'),
                                        foreign('syn-r4', 'cancellation', -14000, '2026-10-21')])
    add('foreign amount, other merchant', [foreign('syn-r1', 'purchase', 14000, '2026-10-03'),
                                           foreign('syn-r2', 'cancellation', -14000, '2026-10-20', merchant_normalized='syn other')])
    add('foreign amount, purchase taken by approval number', [
        foreign('syn-r1', 'purchase', 14000, '2026-10-03', approval_number='SYN-A-1'),
        _pair_row('syn-r5', 'cancellation', -14000, card_kind='해외', foreign_currency='JPY', foreign_amount='1500',
                  approval_date='2026-10-10', posting_date='2026-10-10', merchant_normalized='syn shop',
                  original_approval_number='SYN-A-1'),
        foreign('syn-r2', 'cancellation', -14000, '2026-10-20')])
    add('same-day exact amount, same merchant', [P(), _pair_row('syn-r2', 'cancellation', -10000)])
    add('exact amount, other day', [P(), _pair_row('syn-r2', 'cancellation', -10000, approval_date='2026-10-04')])
    add('exact amount, other merchant', [P(), _pair_row('syn-r2', 'cancellation', -10000, merchant='SYN OTHER')])
    add('exact amount, two purchases collide', [P(), P('syn-r3'), _pair_row('syn-r2', 'cancellation', -10000)])
    add('exact amount, dirty competitor', [P(), P('syn-r3', conflict_reason='syn conflict'),
                                           _pair_row('syn-r2', 'cancellation', -10000)])
    add('exact amount, two refunds for one purchase', [P(), _pair_row('syn-r2', 'cancellation', -10000),
                                                       _pair_row('syn-r4', 'cancellation', -10000)])
    kakao = lambda tid, direction, amount, day, merchant='카카오T SYN', **c: _pair_row(  # noqa: E731
        tid, direction, amount, merchant=merchant, merchant_normalized=merchant.lower(), approval_date=day,
        posting_date=day, **c)
    add('kakao taxi within window', [kakao('syn-r1', 'purchase', 9000, '2026-10-01'),
                                     kakao('syn-r2', 'cancellation', -9000, '2026-10-10')])
    add('kakao taxi beyond window', [kakao('syn-r1', 'purchase', 9000, '2026-10-01'),
                                     kakao('syn-r2', 'cancellation', -9000, '2026-10-20')])
    add('kakao taxi spelling variant', [kakao('syn-r1', 'purchase', 9000, '2026-10-01'),
                                        kakao('syn-r2', 'cancellation', -9000, '2026-10-05', '카카오택시 SYN')])
    add('kakao different services', [kakao('syn-r1', 'purchase', 9000, '2026-10-01', '카카오T 대리 SYN'),
                                     kakao('syn-r2', 'cancellation', -9000, '2026-10-05')])
    add('kakao refund before purchase', [kakao('syn-r1', 'purchase', 9000, '2026-10-05'),
                                         kakao('syn-r2', 'cancellation', -9000, '2026-10-01')])
    add('refund direction row with amount < 0', [P(), _pair_row('syn-r2', 'refund', -10000, original_approval_number='SYN-A-r1')])
    return out


# --- OTA to card links (app.ota_payments.match_ota_payment_events) ------------------------

def _event(identity, **changes):
    row = {'ota_event_id': identity, 'provider': 'trip', 'booking_ref': 'SYN-BOOK-1', 'event_type': 'charge',
           'paid_on': '2026-09-04', 'amount': '30000', 'currency': 'KRW', 'amount_krw': 30000, 'card_last4': '2042',
           'item': '항공권', 'evidence_status': 'paid_verified', 'payment_status': 'paid', 'source_digest': identity,
           'source_ids': [f'mail:{identity}'], 'service_period': {'starts_on': '2026-10-01', 'ends_on': '2026-10-03'}}
    row.update(changes)
    return row


def _card(identity, **changes):
    row = {'transaction_id': identity, 'merchant': 'TRIP.COM', 'merchant_normalized': 'trip.com', 'issuer': 'SYN-BANK',
           'card_tail': '2042', 'approval_date': '2026-09-04', 'amount_krw': 30000, 'transaction_direction': 'purchase'}
    row.update(changes)
    return row


def ota_cases():
    out, n = [], 0

    def add(note, events, cards, **extra):
        nonlocal n
        n += 1
        out.append(_case('ota_links', f'{n:03d}', 'links', dict(
            {'kind': 'ota', 'events': events, 'transactions': cards}, **extra), note))

    E, C = _event, _card
    add('exact match', [E('syn-e1')], [C('syn-t1')])
    add('missing payment date', [E('syn-e1', paid_on=None)], [C('syn-t1')])
    add('no card', [E('syn-e1')], [])
    add('amount differs', [E('syn-e1')], [C('syn-t1', amount_krw=30001)])
    add('card tail differs', [E('syn-e1')], [C('syn-t1', card_tail='9999')])
    add('issuer differs when event names the issuer', [E('syn-e1', card_issuer='SYN-BANK')], [C('syn-t1', issuer='SYN-BANK-B')])
    add('date differs by one day', [E('syn-e1')], [C('syn-t1', approval_date='2026-09-05')])
    add('date differs by a month', [E('syn-e1')], [C('syn-t1', approval_date='2026-10-05')])
    add('merchant is another provider', [E('syn-e1')], [C('syn-t1', merchant='SYN OTHER', merchant_normalized='syn other')])
    add('partial merchant token', [E('syn-e1', provider='agoda', card_last4=None)],
        [C('syn-t1', merchant='nottrip.commercial', merchant_normalized='nottrip.commercial')])
    for provider, merchant in (('trip', 'TRIP.COM'), ('trip', '트립닷컴_이니시스'), ('agoda', 'AGODA_NICE-Agoda'),
                               ('booking', 'BOOKING.COM'), ('klook', 'KLOOK')):
        add(f'provider alias {provider} {merchant}', [E('syn-e1', provider=provider, paid_on=None)],
            [C('syn-t1', merchant=merchant, merchant_normalized=merchant.lower())])
    add('card has a duplicate marker', [E('syn-e1')], [C('syn-t1', duplicate_of='syn-t0')])
    add('card has a parse error', [E('syn-e1')], [C('syn-t1', parse_error='AMOUNT_UNREADABLE')])
    add('card has a conflict', [E('syn-e1')], [C('syn-t1', conflict_reason='syn conflict')])
    add('card is a refund row', [E('syn-e1')], [C('syn-t1', transaction_direction='refund')])
    add('foreign currency card', [E('syn-e1')], [C('syn-t1', foreign_currency='JPY', foreign_amount='30000', amount_krw=None)])
    add('authorization numbers conflict', [E('syn-e1', authorization_number='SYN-AUTH-1', authorization_scheme='scheme-a')],
        [C('syn-t1', authorization_number='SYN-AUTH-2', authorization_scheme='scheme-a')])
    add('authorization numbers agree', [E('syn-e1', authorization_number='SYN-AUTH-1', authorization_scheme='scheme-a')],
        [C('syn-t1', authorization_number='SYN-AUTH-1', authorization_scheme='scheme-a')])
    add('event not paid', [E('syn-e1', payment_status='pending')], [C('syn-t1')])
    add('event evidence not verified', [E('syn-e1', evidence_status='booking_only')], [C('syn-t1')])
    add('refund event', [E('syn-e1', event_type='refund', evidence_status='refund_verified', refund_status='refunded')],
        [C('syn-t1', amount_krw=-30000, transaction_direction='cancellation')])
    add('two events, two cards', [E('syn-e1', booking_ref='SYN-BOOK-1'), E('syn-e2', booking_ref='SYN-BOOK-2')],
        [C('syn-t1'), C('syn-t2', approval_number='SYN-AP-2')])
    add('two events, one card', [E('syn-e1', booking_ref='SYN-BOOK-1'), E('syn-e2', booking_ref='SYN-BOOK-2')], [C('syn-t1')])
    add('one event, two identical cards', [E('syn-e1')], [C('syn-t1'), C('syn-t2', approval_number='SYN-AP-2')])
    add('one event, two cards on different days', [E('syn-e1', paid_on=None)],
        [C('syn-t1'), C('syn-t2', approval_date='2026-09-06')])
    for m, k in ((1, 2), (2, 1), (2, 2), (2, 3), (3, 2)):
        for missing in (False, True):
            events = [E(f'syn-e{i}', booking_ref=f'SYN-BOOK-{i}', paid_on=None if missing else '2026-09-04') for i in range(m)]
            cards = [C(f'syn-t{i}', merchant='Agoda', merchant_normalized='agoda', approval_number=f'SYN-AP-{i}') for i in range(k)]
            events = [dict(e, provider='agoda') for e in events]
            add(f'M:N {m}:{k} missing_date={missing}', events, cards)
            add(f'M:N {m}:{k} missing_date={missing} (input reversed)', events[::-1], cards[::-1])
    add('same booking, different amounts', [E('syn-e1'), E('syn-e2', amount='25000', amount_krw=25000)],
        [C('syn-t1'), C('syn-t2', amount_krw=25000, approval_number='SYN-AP-2')])
    add('existing link pins an event', [E('syn-e1')], [C('syn-t1'), C('syn-t2', approval_number='SYN-AP-2')],
        existing_links={'syn-e1': {'transaction_id': 'syn-t2', 'status': 'MATCHED_AUTO'}})
    add('existing link to an absent card', [E('syn-e1')], [C('syn-t1')],
        existing_links={'syn-e9': {'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}})
    add('trip discount step is not accepted without a rule', [E('syn-e1', amount='28500', amount_krw=28500)], [C('syn-t1')])
    add('event without amount', [E('syn-e1', amount=None, amount_krw=None)], [C('syn-t1')])
    add('event amount zero', [E('syn-e1', amount='0', amount_krw=0)], [C('syn-t1', amount_krw=0)])
    return out


GENERATORS = {'classify': classify_cases, 'plan': plan_cases, 'refund_pairing': refund_cases, 'ota_links': ota_cases}


def render(area):
    """The exact text of one golden file."""
    return ''.join(json.dumps(case, ensure_ascii=False, sort_keys=True) + '\n' for case in GENERATORS[area]())


def manifest(texts):
    return json.dumps({'protocol': 'core-bridge/1', 'files': {
        f'{area}.jsonl': {'cases': text.count('\n'), 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
        for area, text in texts.items()}}, indent=2, sort_keys=True) + '\n'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ('write', 'check'):
        sys.stderr.write('usage: python -m tools.core_bridge.golden write|check\n')
        return 2
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.core_bridge.golden_guard import validate_text
    texts = {area: render(area) for area in AREAS}
    for area, text in texts.items():
        validate_text(area, text)
    texts_out = {f'{area}.jsonl': text for area, text in texts.items()}
    texts_out['manifest.json'] = manifest(texts)
    if argv[0] == 'write':
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in texts_out.items():
            (GOLDEN_DIR / name).write_bytes(text.encode('utf-8'))
        sys.stdout.write(json.dumps({a: t.count('\n') for a, t in texts.items()}, sort_keys=True) + '\n')
        return 0
    drift = [name for name, text in texts_out.items()
             if not (GOLDEN_DIR / name).is_file() or (GOLDEN_DIR / name).read_bytes() != text.encode('utf-8')]
    sys.stdout.write(json.dumps({'drift': drift}) + '\n')
    return 1 if drift else 0


if __name__ == '__main__':
    raise SystemExit(main())
