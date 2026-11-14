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
AREAS = ('classify', 'plan', 'refund_pairing', 'refund_groups', 'ota_links', 'ota_mn', 'ota_candidates', 'trips', 'period')

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


def _case(area, case_id, command, request, note='', covers=()):
    case = {'case_id': f'{area}-{case_id}', 'area': area, 'command': command, 'note': note, 'covers': list(covers),
            'input': request, 'expected': _run(command, request)}
    text = json.dumps(case['expected'], ensure_ascii=False, sort_keys=True)
    missing = [token for token in covers if token not in text]
    if missing:  # a named boundary must really run; otherwise the case is misnamed
        raise RuntimeError(f"{case['case_id']} ({note}) did not reach its branch: {missing}")
    return case


# --- classify (app.classify.classify_transaction) -----------------------------------------

def _txn(tid, merchant, **changes):
    row = {'transaction_id': tid, 'source_hash': 'syn-hash-' + tid, 'issuer': 'SYN-BANK', 'card_tail': '0001',
           'card_kind': '국내', 'transaction_direction': 'purchase', 'transaction_kind': 'purchase',
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

    def add(note, covers=(), **case):
        nonlocal n
        n += 1
        out.append(_case('classify', f'{n:03d}', 'classify', {'cases': [case]}, note, covers))

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
            'start': '2026-10-01', 'end': '2026-10-05'}})], covers=['syn-rule-p', '기간 일치'])
    add('date window miss', transaction=_txn('syn-c1', 'SYN CAFE', approval_date='2026-11-03'),
        rules=[_rule('syn-rule-p', 'syn cafe', '식비', optional={'date_or_service_period': {
            'start': '2026-10-01', 'end': '2026-10-05'}})], covers=['적용할 규칙과 분명한 가맹점 이름이 없어'])
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
    from app import reconciliation as rc
    inferred = lambda origin, trip='T-A', conf='높음', rid='syn-rule-i': _rule(  # noqa: E731
        rid, 'syn cafe', '식비', origin=origin,
        optional={'inferred_assignment': {'trip_id': trip, 'confidence': conf, 'basis': '합성 근거'}})
    expect = {rc.OWNER_BOOKING_ORIGIN: 'owner_booking', rc.GUIDE_AIRFARE_ORIGIN: 'guide_airfare_evidence',
              rc.OWNER_COUNTRY_EXCEPTION_ORIGIN: '"classification_source": "user_exception"',
              'automatic-trip-priority': 'provisional_assignment'}
    for origin in (rc.OWNER_BOOKING_ORIGIN, rc.OWNER_AUTHORIZED_INFERENCE_ORIGIN, rc.OWNER_COUNTRY_EXCEPTION_ORIGIN,
                   rc.PERIOD_OTA_ORIGIN, rc.OTA_MAIL_ORIGIN, rc.OTA_PORTAL_ORIGIN, rc.GUIDE_AIRFARE_ORIGIN,
                   'automatic-trip-priority', 'history-recovery-20261003', 'syn-origin'):
        add(f'inferred assignment origin {origin}', transaction=_txn('syn-c1', 'SYN CAFE'),
            rules=[inferred(origin)], trip_ids=['T-A'], covers=[expect[origin]] if origin in expect else [])
        add(f'inferred assignment origin {origin}, trip not verified', transaction=_txn('syn-c1', 'SYN CAFE'),
            rules=[inferred(origin)])
    for rival in (rc.PERIOD_OTA_ORIGIN, 'syn-origin'):
        add(f'owner booking outranks {rival}', transaction=_txn('syn-c1', 'SYN CAFE'),
            rules=[inferred(rc.OWNER_BOOKING_ORIGIN, 'T-A', rid='syn-rule-i1'), inferred(rival, 'T-B', rid='syn-rule-i2')],
            trip_ids=['T-A', 'T-B'], covers=['owner_booking'])
    add('period-bound OTA rule outranks a plain inference', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[inferred(rc.PERIOD_OTA_ORIGIN, 'T-A', rid='syn-rule-i1'), inferred('syn-origin', 'T-B', rid='syn-rule-i2')],
        trip_ids=['T-A', 'T-B'], covers=['"classification_source": "inference"'])
    bound = lambda origin, item, version=1: dict(  # noqa: E731
        _rule('syn-rule-' + ('lodging' if item == '숙박비' else 'meal') + str(len(origin)), 'syn cafe', item, origin=origin, version=version),
        optional={'source_hash': 'syn-hash-syn-c1'} if origin != 'history-recovery-20261003' else {})
    add('source-bound OTA rule outranks history recovery v1', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[bound(rc.OTA_MAIL_ORIGIN, '숙박비'), bound('history-recovery-20261003', '식비')],
        covers=['"classification_source": "rule"', '"item": "숙박비"'])
    add('history recovery v1 alone conflicts with another item', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[bound('syn-origin', '숙박비'), bound('history-recovery-20261003', '식비')], covers=['rule_conflict'])
    add('inferred assignments disagree', transaction=_txn('syn-c1', 'SYN CAFE'),
        rules=[inferred('syn-origin', 'T-A', rid='syn-rule-i1'), inferred('syn-origin', 'T-B', rid='syn-rule-i2')],
        trip_ids=['T-A', 'T-B'])
    for day, tail, kind in (('2026-10-03', '3820', '국내'), ('2026-10-03', '3820', '해외'), ('2026-09-21', '3820', '해외'),
                            ('2026-10-03', '0001', '국내'), ('', '3820', '국내')):
        cover = {('2026-10-03', '3820', '국내'): ['owner_card_residual'],
                 ('2026-09-21', '3820', '해외'): ['"classification_source": "user_exception"', 'T-SG']}.get((day, tail, kind), [])
        add(f'card 3820 residual {day} {kind}', transaction=_txn('syn-c1', 'SYN UNKNOWN', card_tail=tail, card_kind=kind,
                                                                  approval_date=day, posting_date=day or ''),
            residual_policy=True, trip_ids=['T-SG'], covers=cover)
    add('fukutake with trip', transaction=_txn('syn-c1', 'FUKUTAKE FOUNDATION', card_kind='해외', foreign_currency='JPY'),
        trip_ids=['T-A'])
    add('fukutake without trip resolver', transaction=_txn('syn-c1', 'FUKUTAKE FOUNDATION', card_kind='해외',
                                                            foreign_currency='JPY'))
    return out


# --- plan (app.automatic_classification.plan) ---------------------------------------------

def _row(tid, merchant, **changes):
    row = {'transaction_id': tid, 'merchant': merchant, 'approval_date': '2026-10-03', 'posting_date': '2026-10-05',
           'amount_krw': 15000, 'approval_number': 'SYN-AP-' + tid[4:], 'card_kind': '국내',
           'transaction_kind': 'purchase'}
    row.update(changes)
    return row


def _plan_links(request):
    """The refund links Python hands to plan, reduced to what plan reads (original, kind of link, status)."""
    found = _run('links', {'kind': 'refund', 'scenario': request['scenario'],
                           'transaction_ids': request.get('transaction_ids')})['links']
    return {tid: {'original_id': link['original_id'], 'inferred': bool(link.get('inferred')),
                  'link_state': link.get('status', '')} for tid, link in found.items()}


def plan_cases():
    out, n = [], 0

    def add(note, scenario, covers=(), **options):
        nonlocal n
        n += 1
        request = dict({'scenario': scenario, 'trips': options.pop('trips', TRIPS)}, **options)
        links = _plan_links(request)
        if links:
            request['links'] = links
        out.append(_case('plan', f'{n:03d}', 'plan', request, note, covers))

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
    overseas = dict(card_kind='해외', foreign_currency='JPY', foreign_amount='1500')
    twin = [TRIP_A, dict(TRIP_A, trip_id='T-A2', display_key='SYN-A2')]
    add('overseas card, two overlapping overseas trips: fixed-order tie', base(**overseas), trips=twin, covers=['동률 2개 중'])
    add('overseas tie, reconsider', base(**overseas), trips=twin, reconsider=True)
    add('overseas tie broken by nets', base(**overseas), trips=twin, nets={'T-A2': 100}, covers=['T-A2'])
    add('card 3820 residual quarter', base(card_tail='3820'), covers=['owner_card_residual'])
    add('card 3820 Singapore exception', base(card_tail='3820', approval_date='2026-09-21', posting_date='2026-09-22',
                                              **overseas), trips=TRIPS + [TRIP_SG], covers=['user_exception', 'T-SG'])
    add('card 3820 Singapore window but no Singapore trip', base(card_tail='3820', approval_date='2026-09-21',
                                                               posting_date='2026-09-22', **overseas), covers=['"trip_id"'] if False else [])
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

    def add(note, rows, covers=()):
        nonlocal n
        n += 1
        out.append(_case('refund_pairing', f'{n:03d}', 'links', {'kind': 'refund', 'scenario': {'rows': rows}}, note, covers))

    P = lambda tid='syn-r1', amount=10000, **c: _pair_row(tid, 'purchase', amount, **{'approval_number': 'SYN-A-' + tid[4:], **c})  # noqa: E731
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
    add('two purchases with the same approval number: no link', [P(), P('syn-r9', approval_number='SYN-A-r1'),
                                                                  C('syn-r2', -10000, 'SYN-A-r1')],
        covers=['"links": {}', 'syn-r9'])
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


# --- refund group judgement (app.ledger._apply_refund_pairs and friends) -------------------

def refund_group_cases():
    out, n = [], 0
    trips, tabs = ['T-A', 'T-B'], ['T-A', 'T-B', 'refunds', 'unclassified', 'quarter:2026:4']

    def add(note, rows, by_id=None, covers=(), entries=True, **extra):
        nonlocal n
        n += 1
        by_id = by_id or {}
        scenario = {'rows': rows, **{k: extra.pop(k) for k in ('ledger', 'batch_rows') if k in extra}}
        request = {'kind': 'refund_group', 'scenario': scenario, **extra}
        if entries:
            request['entries'] = [dict({'transaction_id': r['transaction_id']},
                                       **dict({'item': '식비', 'display_tab_id': 'T-A', 'trip_id': 'T-A'}
                                              if r['transaction_direction'] == 'purchase' else {},
                                              **by_id.get(r['transaction_id'], {})))
                                  for r in rows if by_id.get(r['transaction_id']) != 'absent']
        for key, default in (('valid_trips', trips), ('valid_tabs', tabs)):
            if key in request and request[key] is None:
                del request[key]
            else:
                request.setdefault(key, default)
        out.append(_case('refund_groups', f'{n:03d}', 'links', request, note, covers))

    P = lambda tid='syn-r1', amount=10000, **c: _pair_row(tid, 'purchase', amount, **{'approval_number': 'SYN-A-' + tid[4:], **c})  # noqa: E731
    C = lambda tid, amount, ref='SYN-A-r1', **c: _pair_row(tid, 'cancellation', amount, original_approval_number=ref,  # noqa: E731
                                                            approval_number='SYN-X-' + tid[4:], **c)
    full, part = [P(), C('syn-r2', -10000)], [P(), C('syn-r2', -4000)]
    old = dict(approval_date='2025-10-03', posting_date='2025-10-04')
    add('full pair: refund inherits and both go to the refund tab (RFND-022)', full,
        covers=['"display_tab_id": "refunds"', '"status": "full"'])
    add('partial pair: refund inherits attribution', part, covers=['"status": "partial"'])
    add('excess refund holds both (RFND-018)', [P(), C('syn-r2', -12000)], covers=['refund_exceeds_original'])
    add('excess through two cancellations holds all', [P(), C('syn-r2', -6000), C('syn-r3', -6000)],
        covers=['refund_exceeds_original'])
    add('same-day exact amount pair is judged like a numbered pair', [P(), _pair_row('syn-r2', 'cancellation', -10000)],
        covers=['same_card_merchant_day_exact_amount'])
    add('foreign amount partial pair', [P(amount=14000, foreign_currency='JPY', foreign_amount='1500', approval_number='',
                                          merchant_normalized='syn shop'),
                                        _pair_row('syn-r2', 'cancellation', -13000, foreign_currency='JPY',
                                                  foreign_amount='1500', merchant_normalized='syn shop')],
        covers=['merchant_card_foreign_amount'])
    add('original held for source conflict holds the refund', full, {'syn-r1': {'blocked': 'source_conflict'}},
        covers=['refund_pair_incomplete'])
    add('original held for review lets the refund wait too', full, {'syn-r1': {'blocked': 'needs_review'}},
        covers=['refund_pair_incomplete'])
    add('refund held for a duplicate holds the original', full, {'syn-r2': {'blocked': 'duplicate_possible'}},
        covers=['환불 거래가 보류 중'])
    add('refund held only for a missing item still inherits', full, {'syn-r2': {'blocked': 'item_missing'}})
    add('partial pair with conflicting item (RFND-020)', part, {'syn-r2': {'item': '교통비'}},
        covers=['refund_pair_mismatch'])
    add('partial pair with conflicting trip (RFND-020)', part, {'syn-r2': {'item': '식비', 'trip_id': 'T-B'}},
        covers=['refund_pair_mismatch'])
    add('full pair with conflicting item is allowed (RFND-022)', full, {'syn-r2': {'item': '교통비'}})
    add('refund not in the batch holds the original (RFND-025)', part, {'syn-r2': 'absent'},
        covers=['refund_group_incomplete'])
    add('original not in the batch holds the refund', part, {'syn-r1': 'absent'}, covers=['refund_original_missing'])
    add('neither in the batch', part, {'syn-r1': 'absent', 'syn-r2': 'absent'})
    booked = {'ledger': [{'transaction_id': 'syn-r1', 'item': '식비', 'display_tab_id': 'T-A', 'trip_id': 'T-A'}]}
    add('original booked earlier: refund completes it (RFND-026)', part, **booked)
    add('refund booked earlier: original completes it', part,
        ledger=[{'transaction_id': 'syn-r2', 'item': '식비', 'display_tab_id': 'T-A', 'trip_id': 'T-A'}])
    add('booked original and a held refund', part, {'syn-r2': {'blocked': 'duplicate_possible'}}, **booked)
    add('refund booked earlier, original held', part, {'syn-r1': {'blocked': 'source_conflict'}},
        ledger=[{'transaction_id': 'syn-r2', 'item': '식비', 'display_tab_id': 'T-A', 'trip_id': 'T-A'}])
    add('inherited trip no longer valid', part, valid_trips=['T-B'], covers=['trip_no_longer_valid'])
    add('inherited tab no longer valid', part, valid_tabs=['T-B'], covers=['tab_no_longer_valid'])
    add('no trip validator', part, valid_trips=None, covers=['trip_unverified'])
    add('original without an item cannot be inherited', part, {'syn-r1': {'item': ''}}, covers=['이어받을 항목'])
    add('refund with its own full attribution keeps it', part,
        {'syn-r2': {'item': '식비', 'display_tab_id': 'T-A', 'trip_id': 'T-A', 'description': 'syn'}})
    add('two partials make a full refund', [P(), C('syn-r2', -4000), C('syn-r3', -6000)])
    add('two partials, one conflicting', [P(), C('syn-r2', -2000), C('syn-r3', -3000)], {'syn-r3': {'item': '교통비'}},
        covers=['refund_pair_mismatch'])
    add('second refund missing from the batch leaves a half group', [P(), C('syn-r2', -4000), C('syn-r3', -6000)],
        {'syn-r3': 'absent'}, covers=['REFUND_GROUP_INCOMPLETE'])
    # cross-file (RFND-029): the original or a refund comes from another import batch
    ext = {'source_batch_id': 'syn-batch-b'}
    add('cross-file partial: original with a real trip', part, {'syn-r1': ext}, covers=['"status": "partial"'])
    add('cross-file partial: refund from another file', part, {'syn-r2': ext})
    add('cross-file partial: original without attribution (RFND-029)', part,
        {'syn-r1': dict(ext, display_tab_id='unclassified', trip_id='')}, covers=['refund_original_unattributed'])
    add('cross-file partial: original on the refund tab', part,
        {'syn-r1': dict(ext, display_tab_id='refunds', trip_id='')}, covers=['refund_original_unattributed'])
    add('cross-file partial: original with empty tab', part, {'syn-r1': dict(ext, display_tab_id='', trip_id='')},
        covers=['refund_original_unattributed'])
    add('cross-file partial: quarter cost original', part,
        {'syn-r1': dict(ext, display_tab_id='quarter:2026:4', trip_id='')}, covers=['"status": "partial"'])
    add('cross-file partial: completed period first (PROC-072)',
        [P(**old), C('syn-r2', -4000, **old)], {'syn-r1': ext, 'syn-r2': {}}, covers=['refund_completed_period'])
    add('cross-file partial: one member in a completed period',
        [P(), C('syn-r2', -4000, **old)], {'syn-r1': ext}, covers=['refund_completed_period'])
    add('cross-file partial: duplicate cancellation of the original',
        [P(), C('syn-r2', -4000), C('syn-r3', -4000, duplicate_of='syn-r2')], {'syn-r1': ext},
        covers=['refund_unclean_member'])
    add('cross-file partial: conflicted cancellation of the original',
        [P(), C('syn-r2', -4000), C('syn-r3', -4000, conflict_reason='syn conflict')], {'syn-r1': ext},
        covers=['refund_unclean_member'])
    add('cross-file partial: cancellation with a parse error',
        [P(), C('syn-r2', -4000), C('syn-r3', -4000, parse_error='AMOUNT_UNREADABLE')], {'syn-r1': ext},
        covers=['refund_unclean_member'])
    add('in-file partial in a completed period is not excluded', [P(**old), C('syn-r2', -4000, **old)])
    add('cross-file full refund keeps the refund tab', full, {'syn-r1': dict(ext, display_tab_id='', trip_id='')},
        covers=['"display_tab_id": "refunds"'])
    add('cross-file full refund in a completed period', [P(**old), C('syn-r2', -10000, **old)], {'syn-r1': ext})
    add('cross-file excess', [P(), C('syn-r2', -12000)], {'syn-r1': ext}, covers=['refund_exceeds_original'])
    # batch selection (_ready_rows) with and without the verified-group extension
    two = {'batch_rows': [{'batch_id': 'syn-batch', 'transaction_id': 'syn-r2'},
                          {'batch_id': 'syn-batch-b', 'transaction_id': 'syn-r1'}]}
    sel = dict(batch_id='syn-batch', entries=False, **two)
    add('selection: no extension keeps the file scope', full, covers=['"selected": ["syn-r2"]'], extension=False, **{
        k: v for k, v in sel.items()})
    add('selection: verified full refund pulls the original', full, covers=['"selected": ["syn-r1", "syn-r2"]'],
        extension=True, **sel)
    add('selection: numbered partial pulls the original', part, covers=['"selected": ["syn-r1", "syn-r2"]'],
        extension=True, **sel)
    add('selection: partial in a completed period is not pulled', [P(**old), C('syn-r2', -4000, **old)],
        covers=['"selected": ["syn-r2"]'], extension=True, **sel)
    add('selection: partial with a duplicate cancellation is not pulled',
        [P(), C('syn-r2', -4000), C('syn-r3', -4000, duplicate_of='syn-r2')],
        covers=['"selected": ["syn-r2"]'], extension=True, **sel)
    add('selection: excess is not pulled', [P(), C('syn-r2', -12000)], covers=['"selected": ["syn-r2"]'],
        extension=True, **sel)
    add('selection: foreign partial is not pulled', [
        P(amount=14000, foreign_currency='JPY', foreign_amount='1500', approval_number='', merchant_normalized='syn shop'),
        _pair_row('syn-r2', 'cancellation', -13000, foreign_currency='JPY', foreign_amount='1500',
                  merchant_normalized='syn shop')], covers=['"selected": ["syn-r2"]'], extension=True, **sel)
    add('selection: exact-amount full pair is pulled', [P(), _pair_row('syn-r2', 'cancellation', -10000)],
        covers=['"selected": ["syn-r1", "syn-r2"]'], extension=True, **sel)
    add('selection: full refund in a completed period is pulled', [P(**old), C('syn-r2', -10000, **old)],
        covers=['"selected": ["syn-r1", "syn-r2"]'], extension=True, **sel)
    add('selection: unrelated rows stay out', [P(), C('syn-r2', -4000), P('syn-r5', 7000)],
        covers=['"selected": ["syn-r1", "syn-r2"]'], extension=True,
        **dict(sel, batch_rows=two['batch_rows'] + [{'batch_id': 'syn-batch-b', 'transaction_id': 'syn-r5'}]))
    return out


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


def _ota_inputs():
    """(note, events, cards, extra) of every OTA matching scenario; shared by ota_links and ota_candidates."""
    out = []

    def add(note, events, cards, **extra):
        out.append((note, events, cards, extra))

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


def ota_cases():
    return [_case('ota_links', f'{n:03d}', 'links', dict({'kind': 'ota', 'events': events, 'transactions': cards}, **extra),
                  note) for n, (note, events, cards, extra) in enumerate(_ota_inputs(), 1)]


def ota_mn_cases():
    """Final OTA links beyond ota_links: frozen groups, pinned and legacy links, occupancy, ambiguity, undated inference."""
    out = []

    def add(note, events, cards, covers=(), **extra):
        out.append(_case('ota_mn', f'{len(out) + 1:03d}', 'links',
                         dict({'kind': 'ota', 'events': events, 'transactions': cards}, **extra), note, covers))

    E, C = _event, _card
    two_events = [E('syn-e1', booking_ref='SYN-BOOK-1'), E('syn-e2', booking_ref='SYN-BOOK-2')]
    two_cards = [C('syn-t1', approval_number='SYN-AP-1'), C('syn-t2', approval_number='SYN-AP-2')]
    first = _run('links', {'kind': 'ota', 'events': two_events, 'transactions': two_cards})['results'][0]
    snapshot = first['group_order_snapshot']
    pin = {'event_ids': ['syn-e1', 'syn-e2'], 'card_ids': ['syn-t1', 'syn-t2'],
           'mapping': {'syn-e1': 'syn-t2', 'syn-e2': 'syn-t1'}, 'order_snapshot': snapshot}
    add('frozen group keeps the confirmed order', two_events, two_cards, frozen_groups=[pin],
        covers=['frozen_user_confirmed_order'])
    add('frozen group keeps the confirmed order (input reversed)', two_events[::-1], two_cards[::-1], frozen_groups=[pin],
        covers=['frozen_user_confirmed_order'])
    add('frozen group without a snapshot', two_events, two_cards,
        frozen_groups=[{k: v for k, v in pin.items() if k != 'order_snapshot'}], covers=['frozen_user_confirmed_order'])
    add('frozen group with an empty snapshot', two_events, two_cards, frozen_groups=[dict(pin, order_snapshot={})],
        covers=['frozen_user_confirmed_order'])
    add('frozen group, card evidence changed', two_events, [two_cards[0], C('syn-t2', approval_number='SYN-AP-2', issuer='SYN-BANK',
        merchant='TRIP.COM', merchant_normalized='trip.com', card_kind='해외')],
        frozen_groups=[pin], covers=['frozen_group_evidence_changed'])
    add('frozen group, event evidence changed', [two_events[0], dict(two_events[1], source_ids=['mail:syn-e9'])], two_cards,
        frozen_groups=[pin], covers=['frozen_group_evidence_changed'])
    add('frozen group, approval order changed', two_events,
        [C('syn-t1', approval_number='SYN-AP-9'), two_cards[1]], frozen_groups=[pin], covers=['HOLD_GROUP_CHANGED'])
    add('frozen group, mapping names a card that is no option', two_events, two_cards,
        frozen_groups=[dict(pin, mapping={'syn-e1': 'syn-t9', 'syn-e2': 'syn-t1'})], covers=['HOLD_GROUP_CHANGED'])
    add('frozen group, signature change holds members and spares unrelated events',
        [E('syn-e1', item='숙박비', booking_ref='SYN-BOOK-1'), two_events[1], E('syn-e3', booking_ref='SYN-BOOK-3')],
        two_cards + [C('syn-t3', approval_number='SYN-AP-3')], frozen_groups=[pin], covers=['HOLD_GROUP_CHANGED'])
    add('frozen group, a new event joins the signature',
        two_events + [E('syn-e3', booking_ref='SYN-BOOK-3')], two_cards + [C('syn-t3', approval_number='SYN-AP-3')],
        frozen_groups=[pin], covers=['frozen_group_membership_changed'])
    add('frozen group, source events are gone', [E('syn-e9', amount='25000', amount_krw=25000, booking_ref='SYN-BOOK-9')],
        [C('syn-t1'), C('syn-t2', approval_number='SYN-AP-2'), C('syn-t3', amount_krw=25000, approval_number='SYN-AP-3')],
        frozen_groups=[pin], covers=['"transaction_id": "syn-t3"'])
    add('frozen group member has a manual link', two_events, two_cards, frozen_groups=[pin],
        existing_links={'syn-e1': {'transaction_id': 'syn-t2', 'status': 'MATCHED_USER'}})
    add('manual link pins one event, the other takes the free card',
        [E('syn-e1'), E('syn-e2', source_ids=['mail:syn-e2'], amount='25000', amount_krw=25000)],
        [C('syn-t1'), C('syn-t2', amount_krw=25000, approval_number='SYN-AP-2')],
        existing_links={'syn-e1': {'transaction_id': 'syn-t1', 'status': 'MATCHED_USER'}},
        covers=['pinned_existing_link', 'unique_exact_evidence'])
    add('card claimed by an absent linked event stays reserved', two_events, two_cards,
        existing_links={'syn-e9': {'transaction_id': 'syn-t1', 'status': 'MATCHED_USER'}}, covers=['MATCHED_GROUP'])
    add('two links claim one card', [E('syn-e1'), E('syn-e2', booking_ref='SYN-BOOK-2')], [C('syn-t1')],
        existing_links={'syn-e1': {'transaction_id': 'syn-t1', 'status': 'MATCHED_USER'},
                        'syn-e2': {'transaction_id': 'syn-t1', 'status': 'MATCHED_USER'}},
        covers=['pinned_global_one_to_one_collision'])
    add('link status is not a match status', [E('syn-e1')], [C('syn-t1')],
        existing_links={'syn-e1': {'transaction_id': 'syn-t1', 'status': 'inactive'}}, covers=['invalid_existing_link_status'])
    legacy = {'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO', 'legacy_exact': True, 'source_digest': 'syn-e1',
              'source_digests': ['syn-d1']}
    add('legacy exact link that still validates', [E('syn-e1', source_digests=['syn-d1', 'syn-d2'])], [C('syn-t1')],
        existing_links={'syn-e1': legacy}, covers=['pinned_existing_link'])
    add('legacy exact link, source digest moved', [E('syn-e1', source_digest='syn-e2', source_digests=['syn-d1'])], [C('syn-t1')],
        existing_links={'syn-e1': legacy}, covers=['legacy_exact_binding_validation_failed'])
    add('legacy exact link, no shared source digest', [E('syn-e1', source_digests=['syn-d3'])], [C('syn-t1')],
        existing_links={'syn-e1': legacy}, covers=['legacy_exact_binding_validation_failed'])
    add('legacy exact link, card amount changed', [E('syn-e1', source_digests=['syn-d1'])], [C('syn-t1', amount_krw=30001)],
        existing_links={'syn-e1': legacy}, covers=['legacy_exact_binding_validation_failed'])
    add('legacy exact link, card is gone', [E('syn-e1', source_digests=['syn-d1'])], [],
        existing_links={'syn-e1': legacy}, covers=['legacy_exact_binding_validation_failed'])
    add('same amount in two number formats forms one group',
        [E('syn-e1', booking_ref='SYN-BOOK-1'), E('syn-e2', booking_ref='SYN-BOOK-2', amount='30000.00', amount_krw='30000.00')],
        two_cards, covers=['auto_stable_order'])
    add('approval order beats booking order only after booking order',
        [E('syn-e1', booking_ref='SYN-BOOK-1'), E('syn-e2', booking_ref='SYN-BOOK-2')],
        [C('syn-t1', approval_number='SYN-AP-9'), C('syn-t2', approval_number='SYN-AP-1')], covers=['auto_stable_order'])
    add('group cards without an issuer', two_events, [C('syn-t1', issuer='', approval_number='SYN-AP-1'),
        C('syn-t2', issuer='', approval_number='SYN-AP-2')], covers=['MATCHED_GROUP'])
    add('group events with two card issuers', two_events, [C('syn-t1', approval_number='SYN-AP-1'),
        C('syn-t2', issuer='SYN-BANK-B', approval_number='SYN-AP-2')], covers=['MATCHED_GROUP'])
    add('events on distinct known cards form separate groups',
        [E('syn-e1', booking_ref='SYN-BOOK-1', card_last4='2042'), E('syn-e2', booking_ref='SYN-BOOK-2', card_last4='9999')],
        [C('syn-t1', card_tail='2042'), C('syn-t2', card_tail='9999')], covers=['"transaction_id": "syn-t2"'])
    add('different items with identical cards are an equal optimum',
        [E('syn-e1', booking_ref='SYN-BOOK-1', item='항공권'), E('syn-e2', booking_ref='SYN-BOOK-2', item='숙박비')],
        two_cards, covers=['MATCHED_GROUP'])
    add('group overlaps a singleton with another signature',
        two_events + [E('syn-e3', booking_ref='SYN-BOOK-3', item='숙박비')], two_cards, covers=['MATCHED_GROUP'])
    add('one event, an exact card and a flight-delta card', [E('syn-e1')],
        [C('syn-t1'), C('syn-t2', amount_krw=29000, approval_number='SYN-AP-2')], covers=['MATCHED_GROUP'])
    add('one event, one card, a second event on another day', [E('syn-e1'), E('syn-e2', paid_on='2026-09-05', booking_ref='SYN-BOOK-2')],
        [C('syn-t1'), C('syn-t2', approval_date='2026-09-05', approval_number='SYN-AP-2')],
        covers=['"transaction_id": "syn-t2"'])
    add('two events, one flagged duplicate card', two_events, [two_cards[0], dict(two_cards[1], duplicate_of='syn-t1')],
        covers=['MATCHED_GROUP'])
    add('refund events share one refund card',
        [E('syn-e1', event_type='refund', evidence_status='refund_verified', refund_status='refunded', booking_ref='SYN-BOOK-1'),
         E('syn-e2', event_type='refund', evidence_status='refund_verified', refund_status='refunded', booking_ref='SYN-BOOK-2')],
        [C('syn-t1', amount_krw=-30000, transaction_direction='refund')], covers=['MATCHED_GROUP'])
    portal = dict(provider='agoda', paid_on=None, verified_portal_snapshot=True, reservation_status='confirmed',
                  booking_ref='SYN-BOOK-1')
    agoda_card = dict(merchant='Agoda', merchant_normalized='agoda', ota_inference_eligible=True)
    add('undated agoda event, mutually unique card', [E('syn-e1', **portal)], [C('syn-t1', **agoda_card)],
        covers=['mutually_unique_undated_agoda', '"inferred_link": true'])
    add('undated agoda event, card not marked eligible', [E('syn-e1', **portal)],
        [C('syn-t1', merchant='Agoda', merchant_normalized='agoda')], covers=['merchant_amount_card_tail_without_payment_date'])
    add('undated agoda event, card already linked elsewhere', [E('syn-e1', **portal)], [C('syn-t1', **agoda_card)],
        existing_links={'syn-e9': {'transaction_id': 'syn-t1', 'status': 'MATCHED_USER'}})
    add('undated agoda event, two candidate cards', [E('syn-e1', **portal)],
        [C('syn-t1', **agoda_card), C('syn-t2', approval_number='SYN-AP-2', **agoda_card)])
    add('undated agoda event, one-day stay', [E('syn-e1', service_period={'starts_on': '2026-10-01', 'ends_on': '2026-10-01'}, **portal)],
        [C('syn-t1', **agoda_card)])
    add('undated agoda event, cancelled booking sibling',
        [E('syn-e1', **portal), E('syn-e2', **dict(portal, reservation_status='cancelled'), source_ids=['mail:syn-e2'])],
        [C('syn-t1', **agoda_card)])
    add('undated agoda event, a dated event also fits the card',
        [E('syn-e1', **portal), E('syn-e2', provider='agoda', booking_ref='SYN-BOOK-2', source_ids=['mail:syn-e2'])],
        [C('syn-t1', **agoda_card)])
    # shadow overlay: production returns dict(event, **link), so event fields the link omits stay in the result
    unpaid = dict(event_type='reservation', evidence_status='booking_only', payment_status='pending', paid_on=None,
                  amount=None, amount_krw=None)
    flag = dict(individual_payment_evidence=False)
    add('shadow overlay: unpaid toyoko reservation keeps the payment evidence flag',
        [E('syn-e1', provider='toyoko', reservation_group_only=True, **unpaid, **flag)], [C('syn-t1')],
        covers=['RESERVATION_ONLY', '"individual_payment_evidence": false'])
    add('shadow overlay: unpaid forest reservation keeps the payment evidence flag',
        [E('syn-e1', provider='forest', **unpaid, **flag)], [C('syn-t1')],
        covers=['RESERVATION_ONLY', '"individual_payment_evidence": false'])
    add('shadow overlay: conflicted toyoko reservation keeps the payment evidence flag',
        [E('syn-e1', provider='toyoko', **dict(unpaid, evidence_status='conflict'), **flag)], [C('syn-t1')],
        covers=['HOLD_EVIDENCE_CONFLICT', '"individual_payment_evidence": false'])
    add('shadow overlay: unpaid rakuten reservation without the flag',
        [E('syn-e1', provider='rakuten', **unpaid)], [C('syn-t1')], covers=['RESERVATION_ONLY'])
    add('shadow overlay: preauthorized reservation without the flag',
        [E('syn-e1', **dict(unpaid, evidence_status='preauthorized', preauthorized_on='2026-09-04',
                            preauthorized_amount_krw=30000))], [C('syn-t1', amount_krw=30500)], covers=['RESERVATION_ONLY'])
    add('shadow overlay: reservation with a price change amount without the flag',
        [E('syn-e1', **dict(unpaid, price_change_amount_krw=5000, price_change_on='2026-09-04'))],
        [C('syn-t1', amount_krw=5001)], covers=['RESERVATION_ONLY'])
    add('shadow overlay: paid forest event linked to one card, input flag false',
        [E('syn-e1', provider='forest', item='숙박비', card_last4=None, evidence_kind='authenticated_forest_pg_card_receipt',
           authorization_scheme='issuer_card_approval', approval_number='SYN-AP-1', **flag)],
        [C('syn-t1', merchant='SYN SHOP', merchant_normalized='syn shop', approval_number='SYN-AP-1')],
        covers=['MATCHED_AUTO', 'individual_payment_evidence'])
    return out


def ota_candidate_cases():
    """ota_links inputs plus rule, foreign-currency, pair-check, preauthorization, price-change and forest scenarios."""
    out = []

    def add(note, events, cards, covers=(), **extra):
        out.append(_case('ota_candidates', f'{len(out) + 1:03d}', 'candidates',
                         dict({'events': events, 'transactions': cards}, **extra), note, covers))

    for note, events, cards, extra in _ota_inputs():
        add(note, events, cards, **extra)
    E, C = _event, _card
    rule = lambda rule_id, **conditions: {  # noqa: E731
        'rule_id': rule_id, 'status': 'active', 'approved_by': 'syn-owner',
        'conditions': dict({'provider': 'trip', 'item': '항공권', 'merchant_normalized': 'trip.com'}, **conditions)}
    for amount in (29000, 27000, 20000, 19000, 29500, 31000):
        add(f'trip flight discount step, card {amount}', [E('syn-e1')], [C('syn-t1', amount_krw=amount)])
    add('trip flight step does not apply to another item', [E('syn-e1', item='숙박비')], [C('syn-t1', amount_krw=29000)])
    add('approved delta rule', [E('syn-e1')], [C('syn-t1', amount_krw=31500)],
        rules=[rule('syn-rule-1', amount_delta_krw=1500)])
    add('approved delta rule, wrong delta', [E('syn-e1')], [C('syn-t1', amount_krw=31600)],
        rules=[rule('syn-rule-1', amount_delta_krw=1500)])
    add('delta rule without an approver', [E('syn-e1')], [C('syn-t1', amount_krw=31500)],
        rules=[{'rule_id': 'syn-rule-1', 'status': 'active',
                'conditions': rule('syn-rule-1', amount_delta_krw=1500)['conditions']}])
    add('inactive delta rule', [E('syn-e1')], [C('syn-t1', amount_krw=31500)],
        rules=[dict(rule('syn-rule-1', amount_delta_krw=1500), status='inactive')])
    percent = dict(discount_rate_bps=500, discount_cap_krw=3000, minimum_amount_krw=10000, rounding_mode='floor',
                   payment_method='syn-pay', valid_from='2026-09-01', valid_to='2026-09-30')
    for amount in (28500, 28501, 27000):
        add(f'percent discount rule, card {amount}', [E('syn-e1')],
            [C('syn-t1', amount_krw=amount, payment_method='syn-pay')], rules=[rule('syn-rule-1', **percent)])
    add('percent discount rule, other payment method', [E('syn-e1')],
        [C('syn-t1', amount_krw=28500, payment_method='syn-other')], rules=[rule('syn-rule-1', **percent)])
    add('percent discount rule, rounding up', [E('syn-e1', amount='30030', amount_krw=30030)],
        [C('syn-t1', amount_krw=28529, payment_method='syn-pay')],
        rules=[rule('syn-rule-1', **dict(percent, rounding_mode='half_up'))])
    add('date lag rule, one day', [E('syn-e1')], [C('syn-t1', approval_date='2026-09-05')],
        rules=[rule('syn-rule-1', date_lag_days=1)])
    add('date lag rule, two days', [E('syn-e1')], [C('syn-t1', approval_date='2026-09-06')],
        rules=[rule('syn-rule-1', date_lag_days=1)])
    add('date lag rule, negative range', [E('syn-e1')], [C('syn-t1', approval_date='2026-09-03')],
        rules=[rule('syn-rule-1', date_lag_min_days=-2, date_lag_max_days=-1)])
    add('date lag rule, invalid scope (range with days)', [E('syn-e1')], [C('syn-t1', approval_date='2026-09-05')],
        rules=[rule('syn-rule-1', date_lag_min_days=0, date_lag_max_days=2, date_lag_days=1)])
    add('rule valid window excludes the payment date', [E('syn-e1')], [C('syn-t1', approval_date='2026-09-05')],
        rules=[rule('syn-rule-1', date_lag_days=1, valid_from='2026-10-01', valid_to='2026-10-31')])
    add('provider alias rule', [E('syn-e1', provider='booking', paid_on=None)],
        [C('syn-t1', merchant='SYN ALIAS', merchant_normalized='syn alias')],
        rules=[{'rule_id': 'syn-rule-1', 'status': 'active', 'approved_by': 'syn-owner', 'conditions': {
            'rule_kind': 'provider_alias', 'provider': 'booking', 'alias': 'syn alias', 'alias_version': 1,
            'approval_source': 'syn-source'}}])
    add('provider alias without a rule', [E('syn-e1', provider='booking', paid_on=None)],
        [C('syn-t1', merchant='SYN ALIAS', merchant_normalized='syn alias')])
    add('issuer alias rule', [E('syn-e1', card_issuer='SYN-BANK-ALIAS')], [C('syn-t1')],
        rules=[{'rule_id': 'syn-rule-1', 'status': 'active', 'approved_by': 'syn-owner', 'conditions': {
            'rule_kind': 'issuer_alias', 'provider': 'trip', 'event_issuer_alias': 'SYN-BANK-ALIAS',
            'issuer': 'SYN-BANK', 'alias_version': 1, 'approval_source': 'syn-source'}}])
    add('issuer name differs without an alias rule', [E('syn-e1', card_issuer='SYN-BANK-ALIAS')], [C('syn-t1')])
    jp = dict(currency='JPY', amount='30000', amount_krw=None)
    add('foreign payment, same day', [E('syn-e1', **jp)],
        [C('syn-t1', foreign_currency='JPY', foreign_amount='30000', amount_krw=270000)])
    add('foreign payment, card one day later', [E('syn-e1', **jp)],
        [C('syn-t1', foreign_currency='JPY', foreign_amount='30000', amount_krw=270000, approval_date='2026-09-05')])
    add('foreign payment, card two days later', [E('syn-e1', **jp)],
        [C('syn-t1', foreign_currency='JPY', foreign_amount='30000', amount_krw=270000, approval_date='2026-09-06')])
    add('foreign payment, other currency', [E('syn-e1', **jp)],
        [C('syn-t1', foreign_currency='USD', foreign_amount='30000', amount_krw=270000)])
    add('foreign payment, amount differs', [E('syn-e1', **jp)],
        [C('syn-t1', foreign_currency='JPY', foreign_amount='29000', amount_krw=270000)])
    add('foreign payment, card has no foreign amount', [E('syn-e1', **jp)], [C('syn-t1', amount_krw=270000)])
    add('foreign payment without a date', [E('syn-e1', paid_on=None, **jp)],
        [C('syn-t1', foreign_currency='JPY', foreign_amount='30000', amount_krw=270000)])
    add('foreign refund',
        [E('syn-e1', event_type='refund', evidence_status='refund_verified', refund_status='refunded', **jp)],
        [C('syn-t1', foreign_currency='JPY', foreign_amount='-30000', amount_krw=-270000,
           transaction_direction='refund')])
    add('refund without a refund status', [E('syn-e1', event_type='refund', evidence_status='refund_verified')],
        [C('syn-t1', amount_krw=-30000, transaction_direction='refund')])
    add('refund, exact', [E('syn-e1', event_type='refund', evidence_status='refund_verified', refund_status='refunded')],
        [C('syn-t1', amount_krw=-30000, transaction_direction='refund')])
    add('pair check reasons', [E('syn-e1')], [
        C('syn-t1'), C('syn-t2', duplicate_of='syn-t1'), C('syn-t3', merchant='AGODA', merchant_normalized='agoda'),
        C('syn-t4', transaction_direction='refund'), C('syn-t5', amount_krw=31000),
        C('syn-t6', approval_date='2026-09-07'), C('syn-t7', card_tail='9999'), C('syn-t8', parse_error='AMOUNT_UNREADABLE')])
    add('pair check, missing payment date', [E('syn-e1', paid_on=None)],
        [C('syn-t1'), C('syn-t2', merchant='SYN OTHER', merchant_normalized='syn other')])
    add('pair check, no card tail hint and no corroborator',
        [E('syn-e1', provider='agoda', card_last4=None, paid_on='2026-09-04')],
        [C('syn-t1', merchant='SYN OTHER', merchant_normalized='syn other', approval_date='2026-09-04')])
    add('payment id corroborates', [E('syn-e1', provider='booking', card_last4=None, payment_id='syn-pay-1',
                                      payment_id_scheme='scheme-p', paid_on='2026-09-04')],
        [C('syn-t1', merchant='SYN SHOP', merchant_normalized='syn shop', approval_date='2026-09-05',
           payment_id='syn-pay-1', payment_id_scheme='scheme-p')])
    add('skyticket merchant', [E('syn-e1', provider='skyticket', item='항공권')],
        [C('syn-t1', merchant='어드벤처코리아', merchant_normalized='어드벤처코리아')])
    add('skyticket event, card of another brand', [E('syn-e1', provider='skyticket', item='항공권')],
        [C('syn-t1', merchant='AGODA', merchant_normalized='agoda')])
    forest = dict(provider='forest', item='숙박비', card_last4=None)
    add('forest portal event, facility on the card',
        [E('syn-e1', evidence_kind='forest_portal', hotel_name='SYN HOTEL', **forest)],
        [C('syn-t1', merchant='SYN HOTEL', merchant_normalized='syn hotel')])
    add('forest portal event, other facility',
        [E('syn-e1', evidence_kind='forest_portal', hotel_name='SYN HOTEL', **forest)],
        [C('syn-t1', merchant='SYN SHOP', merchant_normalized='syn shop')])
    receipt = dict(evidence_kind='authenticated_forest_pg_card_receipt', authorization_scheme='issuer_card_approval',
                   approval_number='SYN-AP-1', **forest)
    add('forest receipt, approval numbers agree', [E('syn-e1', **receipt)],
        [C('syn-t1', merchant='SYN SHOP', merchant_normalized='syn shop', approval_number='SYN-AP-1')])
    add('forest receipt, approval numbers differ', [E('syn-e1', **receipt)],
        [C('syn-t1', merchant='SYN SHOP', merchant_normalized='syn shop', approval_number='SYN-AP-2')])
    pre = dict(event_type='reservation', evidence_status='preauthorized', preauthorized_on='2026-09-04',
               preauthorized_amount_krw=30000, paid_on=None, amount=None, amount_krw=None)
    add('preauthorization, same day and amount', [E('syn-e1', **pre)], [C('syn-t1')])
    add('preauthorization, amount differs', [E('syn-e1', **pre)], [C('syn-t1', amount_krw=30500)])
    add('preauthorization, card already linked', [E('syn-e1', **pre)],
        [C('syn-t1'), C('syn-t2', approval_number='SYN-AP-2')],
        existing_links={'syn-e9': {'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}})
    add('preauthorization, card of another brand', [E('syn-e1', **pre)],
        [C('syn-t1', merchant='AGODA', merchant_normalized='agoda')])
    add('preauthorization, card held for review', [E('syn-e1', **pre)], [C('syn-t1', ota_review_held=True)])
    add('preauthorization without a date', [E('syn-e1', **dict(pre, preauthorized_on=None))], [C('syn-t1')])
    change = dict(event_type='reservation', evidence_status='booking_only', price_change_amount_krw=5000,
                  price_change_on='2026-09-04', paid_on=None, amount=None, amount_krw=None)
    add('price change, rise charged that day', [E('syn-e1', **change)],
        [C('syn-t1', amount_krw=5000, source_hash='syn-hash-t1')])
    add('price change, card without a source hash', [E('syn-e1', **change)], [C('syn-t1', amount_krw=5000)])
    add('price change, cancelled reservation', [E('syn-e1', reservation_status='cancelled', **change)],
        [C('syn-t1', amount_krw=5000, source_hash='syn-hash-t1')])
    add('price change, another amount', [E('syn-e1', **change)],
        [C('syn-t1', amount_krw=5001, source_hash='syn-hash-t1')])
    add('existing link keeps an event out of the search', [E('syn-e1')], [C('syn-t1')],
        existing_links={'syn-e1': {'transaction_id': 'syn-t1', 'status': 'MATCHED_USER'}})
    return out


# --- trips (app.trip_selection, provisional_assignment, reconciliation.stay_trip, 3820 policy) -------

def _tr(trip_id, destination, starts_on, ends_on=None, **changes):
    trip = {'trip_id': trip_id, 'tab_id': trip_id, 'display_key': 'SYN-' + trip_id[2:], 'destination': destination,
            'starts_on': starts_on}
    if ends_on:
        trip['ends_on'] = ends_on
    trip.update(changes)
    return trip


def trips_cases():
    out, n = [], 0

    def add(note, op, covers=(), **request):
        nonlocal n
        n += 1
        out.append(_case('trips', f'{n:03d}', 'trips', dict(request, op=op), note, covers))

    jp = dict(card_kind='해외', foreign_currency='JPY')
    A, B, KR, SG = (dict(t, tab_id=t['trip_id']) for t in (TRIP_A, TRIP_B, TRIP_KR, TRIP_SG))
    two = [A, _tr('T-A2', '도쿄', '2026-10-01', '2026-10-05')]
    osaka = [A, _tr('T-OS', '오사카', '2026-10-02', '2026-10-06')]
    jeju = _tr('T-J', '제주', '2026-09-09', '2026-09-12', display_key='0909_제주')
    seto = [_tr('T-S1', '세토우치', '2026-10-10', '2026-10-12')]
    days = ('2026-09-30', '2026-10-01', '2026-10-03', '2026-10-05', '2026-10-06', '2026-11-12', '2026-12-02', '2027-01-20')
    for op in ('infer_trip', 'candidates'):
        for day in days:
            add(f'overseas card on {day}', op, row=_txn('syn-c1', 'SYN SHOP', approval_date=day, **jp), trips=[A, B, KR])
            add(f'domestic card on {day}', op, row=_txn('syn-c1', 'SYN SHOP', approval_date=day), trips=[A, B, KR])
        add(f'booking merchant ignores region ({op})', op, row=_txn('syn-c1', 'AGODA'), trips=[A, KR])
        add(f'country suffix JP on a domestic-kind card ({op})', op,
            row=_txn('syn-c1', 'SYN SHOP JP', approval_date='2026-10-02'), trips=[A, KR])
        add(f'country suffix KR on an overseas-kind card ({op})', op,
            row=_txn('syn-c1', 'SYN SHOP KR', approval_date='2026-12-02', **jp), trips=[A, KR])
        add(f'raw row country JPN ({op})', op,
            row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-02', raw_row={'country': 'JPN'}), trips=[A, KR])
        add(f'no region clue ({op})', op, row=_txn('syn-c1', 'SYN SHOP', card_kind='', approval_date='2026-10-02'), trips=[A, KR])
        add(f'fixed-order tie, same start ({op})', op, row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp),
            trips=two, covers=['동률 2개 중'] if op == 'infer_trip' else [])
        add(f'nets break a tie ({op})', op, row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp), trips=two,
            nets={'T-A2': 100}, covers=['T-A2'])
        add(f'nets tie again ({op})', op, row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp), trips=two,
            nets={'T-A': 100, 'T-A2': 100})
        add(f'merchant names the destination ({op})', op,
            row=_txn('syn-c1', 'SYN 도쿄 SHOP', approval_date='2026-10-03', **jp), trips=osaka, covers=['가맹점 지역명 일치'])
        add(f'merchant names the other destination ({op})', op,
            row=_txn('syn-c1', 'SYN 오사카 SHOP', approval_date='2026-10-03', **jp), trips=osaka)
        add(f'named beats nets ({op})', op, row=_txn('syn-c1', 'SYN 오사카 SHOP', approval_date='2026-10-03', **jp),
            trips=osaka, nets={'T-A': 500})
        add(f'input order does not matter ({op})', op, row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp),
            trips=[osaka[1], osaka[0]])
        fuku = lambda day, **c: _txn('syn-c1', 'FUKUTAKE FOUNDATION', approval_date=day, **dict(jp, **c))  # noqa: E731
        add(f'fukutake before a Setouchi trip ({op})', op, row=fuku('2026-10-03'),
            trips=[A] + seto + [_tr('T-S2', '세토우치', '2026-11-01', '2026-11-03')], covers=['세토우치'])
        add(f'fukutake on the start day ({op})', op, row=fuku('2026-10-10'), trips=seto)
        add(f'fukutake, two trips start together ({op})', op, row=fuku('2026-10-03'),
            trips=[_tr('T-S2', '세토우치', '2026-10-10', '2026-10-12'), _tr('T-S1', '세토우치', '2026-10-10', '2026-10-11')])
        add(f'fukutake after every Setouchi trip ({op})', op, row=fuku('2026-12-03'), trips=seto + [A])
        add(f'fukutake without a use date ({op})', op, row=fuku(''), trips=seto)
        add(f'fukutake refund is an ordinary row ({op})', op, row=fuku('2026-10-03', transaction_direction='cancellation'),
            trips=[A] + seto)
        add(f'fukutake with a parse error ({op})', op, row=fuku('2026-10-03', parse_error='AMOUNT_UNREADABLE'), trips=[A] + seto)
        add(f'restricted Jeju trip, other card ({op})', op, row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-09-10'), trips=[jeju])
        add(f'Jeju key on another start day ({op})', op, row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-09-10'),
            trips=[dict(jeju, starts_on='2026-09-08')])
    for reconsider in (False, True):
        tag = f'reconsider={reconsider}'
        add('recorded trip is valid, ' + tag, 'infer_trip',
            row=_txn('syn-c1', 'SYN SHOP', trip_id='T-B', display_tab_id='T-B', **jp), trips=[A, B], reconsider=reconsider)
        add('recorded display tab is valid, ' + tag, 'infer_trip',
            row=_txn('syn-c1', 'SYN SHOP', display_tab_id='T-B', **jp), trips=[A, B], reconsider=reconsider)
        add('recorded trip is gone, ' + tag, 'infer_trip',
            row=_txn('syn-c1', 'SYN SHOP', trip_id='T-GONE', **jp), trips=[A, B], reconsider=reconsider)
        add('recorded trip is restricted, ' + tag, 'infer_trip',
            row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-09-10', trip_id='T-J'), trips=[jeju], reconsider=reconsider)
    add('no use date picks the latest start', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date='', **jp),
        trips=[A, B], covers=['이용일 단서 없음'])
    add('no use date, region filters trips', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date=''), trips=[A, KR])
    add('no use date, same start picks the larger id', 'infer_trip',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='', **jp), trips=two)
    add('no use date, no trips', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date='', **jp), trips=[])
    add('no trips at all', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', **jp), trips=[], covers=['PROC-004'])
    add('only an invalid trip (ends before it starts)', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', **jp),
        trips=[dict(A, ends_on='2026-09-01')])
    for label, change in (('archived', {'archived': 1}), ('deleted', {'deleted': 1}), ('disabled', {'enabled': False}),
                          ('valid false', {'valid': False}), ('conflict', {'conflict': 1}),
                          ('period conflict', {'period_conflict': 1}), ('period order flag', {'flags': ['PERIOD_ORDER']}),
                          ('start missing flag', {'flags': ['PERIOD_START_MISSING']})):
        add(f'trip {label} is not authoritative', 'infer_trip',
            row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp), trips=[dict(A, **change), B])
    add('trip without an id', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp),
        trips=[dict(A, trip_id='')])
    add('open-ended trip ends before the next start', 'infer_trip',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-11-05', **jp), trips=[_tr('T-O', '도쿄', '2026-10-01'), B])
    add('open-ended trip without a following trip', 'infer_trip',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp), trips=[_tr('T-O', '도쿄', '2026-10-01')])
    add('open-ended trips with the same start', 'infer_trip',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-30', **jp),
        trips=[_tr('T-O', '도쿄', '2026-10-01'), _tr('T-O2', '도쿄', '2026-10-01'), B])
    add('three open-ended trips in a row', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-11-12', **jp),
        trips=[_tr('T-O3', '도쿄', '2026-12-01'), _tr('T-O2', '도쿄', '2026-11-10'), _tr('T-O', '도쿄', '2026-10-01')])
    add('trip ids repeat: the later row wins', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp),
        trips=[A, dict(A, destination='오사카', ends_on='2026-10-04')])
    add('trip start is empty', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **jp),
        trips=[dict(A, starts_on='')])
    evidence = {'trip_id': 'T-A', 'service_period': {'starts_on': '2026-10-01', 'ends_on': '2026-10-02'},
                'formal_link': True, 'source_hash': 'syn-hash-syn-c1'}
    for day in ('2025-10-03', '2026-02-03', '2026-03-31', '2026-04-01'):
        add(f'completed period check {day}', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', approval_date=day, **jp), trips=[A, B])
    closed = dict(approval_date='2026-02-03', **jp)
    add('completed period with a formal booking fact', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', **closed),
        trips=[A, B], completed_evidence=evidence)
    add('completed period, fact for another source', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', **closed),
        trips=[A, B], completed_evidence=dict(evidence, source_hash='syn-other'))
    add('completed period, fact outside the trip', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', **closed), trips=[A, B],
        completed_evidence=dict(evidence, service_period={'starts_on': '2026-10-04', 'ends_on': '2026-10-09'}))
    add('completed period, fact without a formal link', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', **closed),
        trips=[A, B], completed_evidence=dict(evidence, formal_link=False))
    add('completed period, recorded closed quarter', 'infer_trip',
        row=_txn('syn-c1', 'SYN SHOP', display_tab_id='quarter:2026:1', **closed), trips=[A, B], completed_evidence=evidence)
    add('completed period, recorded closed trip', 'infer_trip', row=_txn('syn-c1', 'SYN SHOP', trip_id='T-C', **closed),
        trips=[A, _tr('T-C', '도쿄', '2026-02-01', '2026-02-05')], completed_evidence=evidence)
    add('posting date decides the closed period', 'infer_trip',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='', posting_date='2026-02-04', **jp), trips=[A, B])

    # stay_trip: lodging nights (TRIP-039) and the preparation stay (TRIP-042)
    stays = ((('2026-10-02', '2026-10-04'), 'inside'), (('2026-10-04', '2026-10-06'), 'ends the day after the trip'),
             (('2026-10-05', '2026-10-06'), 'last night of the trip'), (('2026-09-28', '2026-10-02'), 'starts before'),
             (('2026-09-28', '2026-09-30'), 'before the trip'), (('2026-09-30', '2026-10-01'), 'night before the start day'),
             (('2026-10-06', '2026-10-08'), 'after the trip'), (('2026-11-08', '2026-11-10'), 'before the next trip'),
             (('2026-10-04', '2026-11-12'), 'spans two trips'), (('2026-10-01', '2026-10-01'), 'zero nights'))
    neighbours = {'plain': [A, B], 'handover': [A, _tr('T-N', '도쿄', '2026-10-05', '2026-10-08')],
                  'next-day handover': [A, _tr('T-N', '도쿄', '2026-10-06', '2026-10-08')],
                  'same start': [B, _tr('T-B2', '도쿄', '2026-11-10', '2026-11-12')]}
    for service in (False, True):
        for (check_in, check_out), what in stays:
            for label, trips_ in neighbours.items():
                add(f'stay {what}, {label}, service={service}', 'stay_trip', check_in=check_in, check_out=check_out,
                    service=service, trips=trips_)
    for nets in ({'T-A': 5, 'T-B': 9}, {'T-A': 9, 'T-B': 9}, {'T-B': 1}):
        add(f'stay shared evenly, nets {nets}', 'stay_trip', check_in='2026-10-04', check_out='2026-11-12',
            trips=[A, B], nets=nets)
        add(f'stay covered by two trips, nets {nets}', 'stay_trip', check_in='2026-10-02', check_out='2026-10-04',
            trips=[A, dict(A, trip_id='T-A2', tab_id='T-B')], nets=nets)

    # booking_trip (TRIP-036): a named trip that overlaps wins, else stay_trip
    for code in ('SYN-A', 'SYN-B', 'SYN-X'):
        for check_in, check_out in (('2026-10-02', '2026-10-04'), ('2026-10-04', '2026-11-12'), ('2026-11-08', '2026-11-10')):
            add(f'booking period for {code}', 'booking_trip', row=_txn('syn-c1', 'AGODA'), check_in=check_in,
                check_out=check_out, target_code=code, trips=[A, B])
    add('booking period, restricted trip hidden', 'booking_trip', row=_txn('syn-c1', 'AGODA'),
        check_in='2026-09-10', check_out='2026-09-11', target_code='0909_제주', trips=[jeju])
    add('booking period, two named trips overlap', 'booking_trip', row=_txn('syn-c1', 'AGODA'), check_in='2026-10-02',
        check_out='2026-10-04', target_code='SYN-A', trips=[A, dict(A, trip_id='T-A2', tab_id='T-A2')])
    add('booking period, flight arrival day', 'booking_trip', row=_txn('syn-c1', 'AGODA'), check_in='2026-10-05',
        check_out='2026-10-06', target_code='SYN-A', service=True, trips=[A, B])

    # card 3820 owner policy
    o3820 = dict(card_tail='3820', **jp)
    sg_sets = (('no trips', []), ('Singapore trip', [SG]), ('Singapore and Tokyo', [SG, A, B]),
               ('two Singapore trips', [SG, dict(SG, trip_id='T-SG2', tab_id='T-SG2')]))
    for day in ('2026-09-18', '2026-09-19', '2026-09-21', '2026-09-24', '2026-09-25', '2026-10-03', '2026-10-06',
                '2026-11-12', '2026-07-04'):
        for label, trips_ in sg_sets:
            add(f'card 3820 overseas on {day}, {label}', 'card3820',
                row=_txn('syn-c1', 'SYN SHOP', approval_date=day, posting_date=day, **o3820), trips=trips_)
        add(f'card 3820 domestic on {day}', 'card3820',
            row=_txn('syn-c1', 'SYN SHOP', approval_date=day, posting_date=day, card_tail='3820'), trips=[A, B, SG])
    add('card 3820 residual quarter name', 'card3820', row=_txn('syn-c1', 'SYN SHOP', card_tail='3820'), trips=[A],
        covers=['owner_card_residual'])
    add('card 3820 Singapore exception', 'card3820', row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-09-21', **o3820),
        trips=[SG], covers=['user_exception'])
    add('card 3820 overseas in an overseas trip', 'card3820',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **o3820), trips=[A], covers=['해외 사용 · 국가 일치 불필요'])
    add('card 3820 overseas in a trip, item recorded', 'card3820', row=_txn(
        'syn-c1', 'SYN SHOP', approval_date='2026-10-03', item='식비', description='syn', **o3820), trips=[A])
    add('card 3820 overseas in two overlapping trips', 'card3820',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-10-03', **o3820), trips=two)
    add('card 3820 overseas, named destination', 'card3820',
        row=_txn('syn-c1', 'SYN 오사카 SHOP', approval_date='2026-10-03', **o3820), trips=osaka)
    add('card 3820 overseas, domestic trip only', 'card3820',
        row=_txn('syn-c1', 'SYN SHOP', approval_date='2026-12-02', **o3820), trips=[KR])
    for merchant, currency in (('AMAZON.COM', 'USD'), ('TRIP.COM', 'JPY'), ('AGODA', 'JPY'), ('SYN SHOP', 'USD'),
                               ('FUKUTAKE FOUNDATION', 'JPY')):
        for industry in ('', '인터넷상거래', '결제대행', '호텔'):
            add(f'card 3820 overseas {merchant} {currency} category {industry or "none"}', 'card3820', row=_txn(
                'syn-c1', merchant, approval_date='2026-10-03', card_tail='3820', card_kind='해외', foreign_currency=currency,
                description_raw='card-category:' + industry if industry else ''), trips=[A])
    for day, trips_ in (('2026-10-03', [A]), ('2026-12-02', [KR])):
        add(f'card 3820 online category, local currency, trips {day}', 'card3820', row=_txn(
            'syn-c1', 'SYN SHOP JP', approval_date=day, card_tail='3820', card_kind='해외', foreign_currency='JPY',
            description_raw='card-category:인터넷상거래'), trips=trips_)
    for label, change in (('other card', {'card_tail': '0001'}), ('cancellation', {'transaction_direction': 'cancellation'}),
                          ('refund kind', {'transaction_kind': '취소'}), ('approval kind', {'transaction_kind': '승인'}),
                          ('parse error', {'parse_error': 'AMOUNT_UNREADABLE'}), ('zero amount', {'amount_krw': 0}),
                          ('negative amount', {'amount_krw': -10}), ('no amount', {'amount_krw': None}),
                          ('no dates', {'approval_date': '', 'posting_date': ''}),
                          ('posting date only', {'approval_date': '', 'posting_date': '2026-10-03'})):
        add(f'card 3820 {label}', 'card3820', row=_txn('syn-c1', 'SYN SHOP', **dict(o3820, **change)), trips=[A, SG])

    # infer_item vocabulary
    from tools.core_bridge.golden_guard import CATEGORY_INDUSTRIES, FAMILY_MERCHANTS
    for industry in CATEGORY_INDUSTRIES:
        add('item from card category', 'infer_item', row=_txn('syn-c1', 'SYN SHOP', description_raw='card-category:' + industry))
    for merchant in FAMILY_MERCHANTS + ('AGODA', 'TRIP.COM', 'KLOOK', 'BOOKING.COM', '어드벤처코리아', 'AMAZON.COM', '카카오T SYN'):
        add('item from merchant', 'infer_item', row=_txn('syn-c1', merchant))
    add('item kept', 'infer_item', row=_txn('syn-c1', 'SYN SHOP', item='식비'))
    add('item of a cancellation', 'infer_item', row=_txn('syn-c1', 'SYN SHOP', transaction_direction='cancellation'))
    add('item of an overseas purchase', 'infer_item', row=_txn('syn-c1', 'SYN SHOP', **jp), covers=['현지경비'])
    add('item of a domestic purchase', 'infer_item', row=_txn('syn-c1', 'SYN SHOP'), covers=['기타경비'])
    for source in ('', 'user_decision', 'user_exception', 'inference'):
        add(f'fukutake item, source {source!r}', 'infer_item', row=_txn(
            'syn-c1', 'FUKUTAKE FOUNDATION', item='식비', classification_source=source, **jp))
    return out


# --- period (webapp.ledger_stay_evidence.verified_period_for; Rust applies the rule to the bridge facts) -----

def period_cases():
    out, n = [], 0

    def add(note, events, cards=None, *, results=None, rows=None, manual=(), links=None, covers=(), p2=None,
            passengers=None, inference=False):
        nonlocal n
        n += 1
        cards = [C()] if cards is None else cards
        if results is None:
            results = [{'ota_event_id': e['ota_event_id'], 'transaction_id': c['transaction_id'], 'status': 'MATCHED_AUTO'}
                       for e, c in zip(events, cards)]
        if rows is None:
            rows = [{'row_id': 'card-' + c['transaction_id'], 'service_period': '', 'reservation_no': ''} for c in cards]
        request = {'data': {'events': events, 'transactions': cards, 'results': results, 'links': links or {}},
                   'manual': list(manual), 'rows': rows}
        if inference:
            request['inference'] = True
            request['p2'] = p2 or []
            if passengers:
                request['data']['passengers'] = passengers
        out.append(_case('period', f'{n:03d}', 'periods', request, note, covers))

    def E(identity='syn-e1', **changes):
        return _event(identity, **dict({'item': '숙박비', 'reservation_status': 'confirmed'}, **changes))

    def C(identity='syn-t1', **changes):
        return _card(identity, source_hash='syn-hash-' + identity, **changes)

    def R(tid='syn-t1', period='', reservation_no='', **changes):
        return dict({'row_id': 'card-' + tid, 'service_period': period, 'reservation_no': reservation_no}, **changes)

    def link(**changes):
        return [dict({'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}, **changes)]

    verified = '2026-10-01~2026-10-03'
    add('verified lodging link fills a blank period', [E()], covers=[verified])
    add('stored period wins over evidence', [E()], rows=[R(period='2026-09-01~2026-09-02')], covers=['2026-09-01~2026-09-02'])
    add('whitespace-only stored period counts as blank', [E()], rows=[R(period='  ')], covers=[verified])
    add('manual period override leaves the row blank', [E()], manual=['card-syn-t1'])
    add('reservation number equal to the booking', [E()], rows=[R(reservation_no='SYN-BOOK-1')], covers=[verified])
    add('reservation number of another booking', [E()], rows=[R(reservation_no='SYN-BOOK-2')])
    for status in ('observed', 'completed'):
        add(f'reservation status {status}', [E(reservation_status=status)], covers=[verified])
    for status in ('cancelled', 'refunded', 'refund_pending', 'evidence_pending'):
        add(f'reservation status {status}', [E(reservation_status=status)])
    add('event without a period', [E(service_period=None)])
    add('event without a source digest', [E(source_digest=None)])
    add('event not linked to any card', [E()], results=[])
    add('link is only a candidate', [E()], results=link(status='HOLD_DATE_UNKNOWN'))
    add('period conflict on the result', [E()], results=link(period_conflict=True))
    add('period conflict on the event', [E(period_conflict=True)])
    add('evidence changed on the event', [E(evidence_changed=True)])
    add('evidence missing on the event', [E(evidence_missing=True)])
    add('service period conflict on the event', [E(service_period_conflict=True)])
    add('two events claim one card', [E('syn-e1'), E('syn-e2', booking_ref='SYN-BOOK-2')], [C()],
        results=link() + [{'ota_event_id': 'syn-e2', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}])
    add('user-confirmed link', [E()], results=link(status='MATCHED_USER'), covers=[verified])
    add('card is a refund row', [E()], [C(transaction_direction='refund')])
    add('card is a duplicate', [E()], [C(duplicate_of='syn-t0')])
    add('card has a parse error', [E()], [C(parse_error='AMOUNT_UNREADABLE')])
    card_without_hash = C()
    del card_without_hash['source_hash']
    add('card without a source hash', [E()], [card_without_hash])
    add('inferred link keeps the period without a booking number', [E()], results=link(inferred_link=True),
        covers=[verified])
    add('inferred link with a reservation number', [E()], rows=[R(reservation_no='SYN-BOOK-1')],
        results=link(inferred_link=True))
    add('ordered group with individual evidence', [E()],
        results=link(allocation_basis='auto_stable_order', individual_payment_evidence=True), covers=[verified])
    add('ordered group without individual evidence', [E()],
        results=link(allocation_basis='auto_stable_order', individual_payment_evidence=False))
    add('shared period by LINK-108', [E(booking_ref=None, service_period_basis='LINK-108')], covers=[verified])
    add('item outside lodging, flight and rental', [E(item='식비')])
    for item in ('항공료', '렌터카'):
        add(f'paid {item} charge', [E(item=item)], covers=[verified])
        add(f'unpaid {item}', [E(item=item, payment_status='pending')])
        add(f'{item} evidence not verified', [E(item=item, evidence_status='booking_only')])
        add(f'{item} event already refunded', [E(item=item, refund_status='refunded')])
        add(f'{item} card refunded', [E(item=item)], [C(refund_status='refunded')])
        add(f'{item} card held for review', [E(item=item)], [C(ota_review_held=True)])
        add(f'{item} card blocked by a refund', [E(item=item)], [C(reservation_refund_blocked=True)])
    add('lodging card with a refunded flag still counts', [E()], [C(refund_status='refunded')], covers=[verified])
    add('row is not a card row', [E()], rows=[{'row_id': 'ledger-syn-t1', 'service_period': '', 'reservation_no': ''}])
    add('row names another source event', [E()], rows=[R(source_event_id='syn-t9')])
    add('row names its own source event', [E()], rows=[R(source_event_id='syn-t1')], covers=[verified])
    add('two cards with the same source hash', [E('syn-e1'), E('syn-e2', booking_ref='SYN-BOOK-2')],
        [C('syn-t1'), dict(C('syn-t2'), source_hash='syn-hash-syn-t1')], rows=[R('syn-t1'), R('syn-t2')])
    add('two cards with different periods', [E('syn-e1'), E('syn-e2', booking_ref='SYN-BOOK-2',
        service_period={'starts_on': '2026-11-01', 'ends_on': '2026-11-02'})], [C('syn-t1'), C('syn-t2')],
        rows=[R('syn-t1'), R('syn-t2')], covers=[verified, '2026-11-01~2026-11-02'])

    # --- inferred periods (DATE-080, DATE-101), P2 period metadata and saved flight bookings (found = kind/period/basis) ---
    def stated(identity='syn-e2', **changes):
        return E(identity, item='', event_type='reservation', evidence_status='booking_only', payment_status='pending',
                 **changes)

    receipt = E('syn-e1', item='', service_period=None)
    pair = [receipt, stated()]
    only_receipt = [{'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}]
    inferred = '2026-10-01~2026-10-03'
    add('reservation-only period is an inference, not a verified period', pair, results=only_receipt, inference=True,
        covers=[inferred, 'reservation_only', '"inferred"'])
    add('reservation-only inference with the same reservation number', pair, results=only_receipt, inference=True,
        rows=[R(reservation_no='SYN-BOOK-1', item='숙박비')], covers=['reservation_only'])
    add('reservation-only inference with another reservation number', pair, results=only_receipt, inference=True,
        rows=[R(reservation_no='SYN-BOOK-2')], covers=['"none"'])
    add('stored period wins over a reservation-only inference', pair, results=only_receipt, inference=True,
        rows=[R(period='2026-09-01~2026-09-02')], covers=['2026-09-01~2026-09-02', '"verified"'])
    add('manual override blocks a reservation-only inference', pair, results=only_receipt, inference=True,
        manual=['card-syn-t1'], covers=['"none"'])
    add('cancelled reservation withholds the inference', [receipt, stated(reservation_status='cancelled')],
        results=only_receipt, inference=True, covers=['"none"'])
    toyoko = [_event('syn-e1', provider='toyoko', item='숙박비', event_type='reservation', evidence_status='reservation_only',
                     payment_status='pending', source_trust='sender_domain', reservation_status='confirmed')]
    candidates = {'status': 'CANDIDATES_FOUND', 'candidates': [
        {'transaction_id': 'syn-t1', 'branch_status': 'MATCH', 'stay_date_status': 'MATCH'}]}
    toyoko_result = [{'ota_event_id': 'syn-e1', 'status': 'RESERVATION_ONLY', 'candidate_search': candidates}]
    add('candidate-agreement period (DATE-101)', toyoko, results=toyoko_result, inference=True,
        covers=['candidate_agreement', inferred])
    add('candidate-agreement period with a manual blank', toyoko, results=toyoko_result, inference=True,
        manual=['card-syn-t1'], covers=['"none"'])
    p2 = [{'transaction_id': 'syn-t1', 'service_period': '2026-10-04~2026-10-06', 'run_id': 'syn-run-1',
           'model': 'syn-model', 'source_hash': 'syn-hash-syn-t1', 'item': '숙박비', 'decision_revision': 1}]
    p2_row = R(item='숙박비', source_fact_digest='syn-hash-syn-t1')
    add('P2 run period without any booking evidence', [], results=[], p2=p2, inference=True, rows=[p2_row],
        covers=['p2_run', '2026-10-04~2026-10-06'])
    add('P2 period of another source is not used', [], results=[], p2=p2, inference=True,
        rows=[R(item='숙박비', source_fact_digest='syn-hash-syn-t9')], covers=['"none"'])
    add('P2 period of another item is not used', [], results=[], p2=p2, inference=True,
        rows=[R(item='항공료', source_fact_digest='syn-hash-syn-t1')], covers=['"none"'])
    add('P2 period yields to a verified link', [E()], p2=p2, inference=True, rows=[p2_row], covers=[verified, '"verified"'])
    add('P2 period of a card held for review is not used', [], [C(ota_review_held=True)], results=[], p2=p2,
        inference=True, rows=[p2_row], covers=['"none"'])
    legs = [{'departure_on': '2026-10-05'}, {'departure_on': '2026-10-01'}]

    def booking(**changes):
        return {'SYN-BOOK-1': dict({'legs': legs, 'source_digests': ['syn-d1'], 'cancellation_status': 'NONE'}, **changes)}

    flight = R(reservation_no='SYN-BOOK-1', item='항공료')
    add('flight booking legs give a verified period', [], results=[], passengers=booking(), inference=True, rows=[flight],
        covers=['2026-10-01~2026-10-05', 'SYN-BOOK-1'])
    add('flight booking of another reservation number', [], results=[], passengers=booking(), inference=True,
        rows=[R(reservation_no='SYN-BOOK-2', item='항공료')], covers=['"none"'])
    add('flight row without a reservation number', [], results=[], passengers=booking(), inference=True,
        rows=[R(item='항공료')], covers=['"none"'])
    add('flight evidence only applies to flight rows', [], results=[], passengers=booking(), inference=True,
        rows=[R(reservation_no='SYN-BOOK-1', item='숙박비')], covers=['"none"'])
    add('cancelled flight booking', [], results=[], passengers=booking(cancellation_status='CANCELLED'), inference=True,
        rows=[flight], covers=['"none"'])
    add('flight booking in conflict', [], results=[], passengers=booking(conflict=True), inference=True,
        rows=[flight], covers=['"none"'])
    add('flight booking without a source digest', [], results=[], passengers=booking(source_digests=[]), inference=True,
        rows=[flight], covers=['"none"'])
    add('flight booking with an unreadable leg day', [], results=[],
        passengers=booking(legs=[{'departure_on': ''}]), inference=True, rows=[flight], covers=['"none"'])
    add('manual override blocks flight evidence', [], results=[], passengers=booking(), inference=True, manual=['card-syn-t1'],
        rows=[flight], covers=['"none"'])
    add('stored period wins over flight evidence', [], results=[], passengers=booking(), inference=True,
        rows=[R(period='2026-09-01~2026-09-02', reservation_no='SYN-BOOK-1', item='항공료')],
        covers=['2026-09-01~2026-09-02'])
    return out


GENERATORS = {'classify': classify_cases, 'plan': plan_cases, 'refund_pairing': refund_cases, 'refund_groups': refund_group_cases, 'ota_links': ota_cases,
              'ota_mn': ota_mn_cases, 'ota_candidates': ota_candidate_cases,
              'trips': trips_cases, 'period': period_cases}


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
