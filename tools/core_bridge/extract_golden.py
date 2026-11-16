"""Synthetic-only M6 vectors. Expected outputs come from the unchanged Python extractor.

Run ``python -m tools.core_bridge.extract_golden`` to create the new golden file.
No source locations or customer originals are accepted by this generator.
"""
import copy
import hashlib
import json
from pathlib import Path

from app import ota_payments as op
from .commands import canonical
from .extract_sources import forest_name_keys


def event(source, **changes):
    base = dict(provider='agoda', booking_ref='SYNTHETIC123', event_type='charge',
                paid_on='2026-06-01', amount='30000', currency='KRW', amount_krw=30000,
                payment_status='paid', evidence_status='paid_verified', refund_status='none_displayed',
                card_last4='1234', service_period=None, payment_id=None,
                source_ids=[source], identity_source_ids=[source], source_digest=op._digest(source),
                source_digests=[op._digest(source)], source_binding_ids=[], source_lineage_ids=[source],
                observation_ids=['obs_' + op._digest(source)], ota_event_id=op._event_id([source]))
    return dict(base, **changes)


def stages(mail=(), portal=(), trip=(), booking=(), forest=()):
    result = dict(schema_version='ota-extract-stages/1', mail_events=list(mail), portal_events=list(portal),
                trip_reservation_events=list(trip), booking_trip_events=list(booking), forest_portal_events=list(forest))
    return dict(result, forest_name_keys=forest_name_keys(result))


def inputs():
    yield 'empty', stages()
    first, second = event('mail:synthetic-a'), event('portal:synthetic-b')
    yield 'same-amount-is-not-proof', stages([first], [second])
    yield 'all-source-order-and-unicode', stages([first], [second],
        [event('trip:synthetic', provider='trip')],
        [event('booking:synthetic', provider='booking', item='숙박비 🏡\n"인용"')])
    linked = dict(second, source_binding_ids=first['source_ids'])
    yield 'explicit-binding', stages([first], [linked])
    yield 'reverse-binding', stages([dict(first, source_binding_ids=second['source_ids'])], [second])
    yield 'payment-id', stages([dict(first, payment_id='SYNTH-PAY')], [dict(second, payment_id='SYNTH-PAY')])
    yield 'different-payment-ids-override-binding', stages([dict(first, payment_id='SYNTH-1')], [dict(linked, payment_id='SYNTH-2')])
    yield 'ambiguous-three-same-payment', stages([
        event('mail:one', payment_id='SYNTH-PAY'), event('mail:two', payment_id='SYNTH-PAY'),
        event('mail:three', payment_id='SYNTH-PAY')])
    yield 'ambiguous-binding-star', stages([first], [linked, dict(linked, ota_event_id=op._event_id(['third']))])
    for key, value in [('provider', 'trip'), ('booking_ref', 'SYNTH-OTHER'), ('event_type', 'refund')]:
        yield 'separate-' + key, stages([first], [dict(linked, **{key: value})])
    for key, value in [('currency', 'USD'), ('card_last4', '9876'),
                       ('service_period', {'starts_on': '2026-07-01', 'ends_on': '2026-07-03'}),
                       ('paid_on', '2026-06-02'), ('amount', '31000')]:
        left = first
        if key == 'service_period':
            left = dict(first, service_period={'starts_on': '2026-07-02', 'ends_on': '2026-07-03'})
        yield 'conflict-' + key, stages([left], [dict(linked, **{key: value})])
    for index, amount in enumerate(['30000.00', '3E+4', 'NaN', 'not-money']):
        yield 'decimal-' + str(index), stages([first], [dict(linked, amount=amount)])
    yield 'null-is-not-conflict', stages([dict(first, currency=None, paid_on=None)], [linked])
    yield 'digest-fallback-empty-lineage', stages([dict(first, source_digests=[], source_lineage_ids=[''])], [linked])
    proof = dict(provider='agoda', identity='synthetic-reservation', source_digest='synthetic-digest')
    attestation = dict(provider='agoda', identity='synthetic-reservation', identity_status='verified',
                       evidence_status='verified', source_status='verified', evidence_link_ids=['synthetic:proof'])
    a = dict(first, _portal_reservation_provenance=proof, reservation_identity_attestation=attestation)
    b = dict(linked, _portal_reservation_provenance=proof, reservation_identity_attestation=attestation)
    yield 'portal-provenance-retained', stages([a], [b])
    yield 'portal-provenance-conflict-stripped', stages([a], [dict(b, amount='999')])
    yield 'portal-attestation-disagrees', stages([a], [dict(b, reservation_identity_attestation=dict(attestation, identity='other'))])
    mail_proof = dict(kind='authenticated_provider_booking', provider='agoda', identity='synthetic-mail-proof',
                      booking_ref='SYNTHETIC123', source_lineage_id='synthetic-mail-provider')
    a = dict(first, _mail_reservation_provenance=dict(mail_proof, source_digest=first['source_digest']),
             reservation_identity_attestation=dict(attestation, identity=mail_proof['identity'], evidence_link_ids=['mail:a']))
    b = dict(linked, _mail_reservation_provenance=dict(mail_proof, source_digest=linked['source_digest']),
             reservation_identity_attestation=dict(attestation, identity=mail_proof['identity'], evidence_link_ids=['mail:b']))
    yield 'mail-provenance-retained', stages([a], [b])
    yield 'mail-provenance-conflict-stripped', stages([a], [dict(b, card_last4='9999')])
    yield 'mail-proof-missing', stages([a], [linked])
    receipt = event('mail:forest-synthetic', provider='forest', booking_ref='PG-SYNTH', order_number='ORDER-SYNTH',
                    evidence_kind='authenticated_forest_pg_card_receipt', merchant_name='합성 휴양림', item=None)
    period = {'starts_on': '2026-07-01', 'ends_on': '2026-07-03'}
    portal = event('forest:synthetic', provider='forest', booking_ref='FOREST-SYNTH', order_number='ORDER-SYNTH',
                   evidence_kind='forest_portal', service_period=period, reservation_status='confirmed', item='숙박비')
    yield 'forest-exact-order', stages([receipt], forest=[portal])
    yield 'forest-exact-conflicting-period', stages([dict(receipt, service_period=dict(period, ends_on='2026-07-04'))], forest=[portal])
    yield 'forest-exact-no-order', stages([receipt], forest=[dict(portal, order_number=None)])
    yield 'forest-exact-refund', stages([dict(receipt, event_type='refund', evidence_status='refund_verified', refund_status='refunded')],
        forest=[dict(portal, event_type='refund', evidence_status='refund_verified', refund_status='refunded')])
    reservation = dict(portal, paid_on=None, amount=None, amount_krw=None, reservation_amount_krw=30000,
                       booked_on='2026-05-28', hotel_name='합성휴양림', payment_status='not_card_charge',
                       evidence_status='reservation_only', event_type='reservation')
    yield 'forest-shared-period', stages([receipt], forest=[reservation])
    for key, value in [('booked_on', '2026-05-20'), ('booked_on', None), ('booked_on', 'invalid'),
                       ('booked_on', '2026-06-02'), ('reservation_status', 'cancelled'),
                       ('evidence_status', 'conflict'), ('reservation_amount_krw', 29999),
                       ('reservation_amount_krw', 0), ('card_last4', '9999'), ('hotel_name', '다른휴양림')]:
        yield 'forest-refusal-' + key + '-' + str(value), stages([receipt], forest=[dict(reservation, **{key: value})])
    yield 'forest-multiple-same-period', stages([receipt], forest=[reservation, dict(reservation, source_ids=['forest:second'])])
    yield 'forest-ambiguous-period', stages([receipt], forest=[reservation, dict(reservation, service_period=dict(period, ends_on='2026-07-04'))])
    yield 'forest-unknown-application-veto', stages([receipt], forest=[reservation, dict(reservation, booked_on=None)])
    yield 'forest-invalid-period', stages([receipt], forest=[dict(reservation, service_period=dict(period, ends_on='2026-06-01'))])
    yield 'forest-existing-period-preserved', stages([dict(receipt, service_period=period)], forest=[reservation])
    yield 'forest-exact-before-shared', stages([receipt], forest=[portal, reservation])


def expected(data):
    data = copy.deepcopy(data)
    events = data['mail_events'] + data['portal_events'] + data['trip_reservation_events'] + data['booking_trip_events']
    events = op._attach_forest_portal_periods(events, data['forest_portal_events'])
    events = op._merge_proven_duplicate_payments(events)
    events.sort(key=lambda event: event['ota_event_id'])
    return canonical({'events': events})


def records():
    for name, data in inputs():
        result = expected(data)
        raw = json.dumps(result, ensure_ascii=False, sort_keys=True)
        yield dict(case_id=name, input=data, expected=result,
                   sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(), bytes=len(raw.encode('utf-8')))


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[2] / 'core/golden/synthetic/extract.jsonl'
    # This is a new unit's golden file. Never silently overwrite established expectations.
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        for record in records():
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
