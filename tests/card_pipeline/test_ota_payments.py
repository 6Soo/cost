import datetime
import hashlib
import json

import pytest
from tests.card_pipeline.test_booking_mail import message

from app.ota_payments import build_ota_payment_events, match_ota_payment_events, same_date_cards


JP_PAID_SUBJECT = '\u304a\u652f\u6255\u3044\u304c\u5b8c\u4e86\u3044\u305f\u3057\u307e\u3057\u305f-NoReply'
JP_CHARGED = '\u5186\u3092\u3054\u6307\u5b9a\u306e\u304a\u652f\u6255\u65b9\u6cd5\u306b\u8acb\u6c42\u3055\u305b\u3066\u3044\u305f\u3060\u304d\u307e\u3057\u305f'
JP_PAID_BODY = ('\u4e88\u7d04\u756a\u53f7: 1400830000000001\n9,737' + JP_CHARGED + '\n'
                'VISA\uff08\u30af\u30ec\u30b8\u30c3\u30c8\u30ab\u30fc\u30c9\uff09 9,737\u5186\n'
                '\u30c1\u30a7\u30c3\u30af\u30a4\u30f3 2026\u5e749\u670830\u65e5\n'
                '\u30c1\u30a7\u30c3\u30af\u30a2\u30a6\u30c8 2026\u5e7410\u67081\u65e5\n'
                'Hotel tax JPY 150\n78 Trip Coins earned (KRW 1,034)')


def test_japanese_paid_stay_keeps_original_currency_and_two_distinct_payments(tmp_path):
    directory = tmp_path / 'jp-mail'
    directory.mkdir()
    mails = [message(JP_PAID_BODY.replace('1400830000000001', ref), subject=JP_PAID_SUBJECT,
                     identity='jp-' + ref, sent='2026-09-25')
             for ref in ('1400830000000001', '1400830000000002')]
    (directory / 'gmail-jp.json').write_text(json.dumps({'responses': mails}), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories': [directory]})
    assert len(events) == 2 and len({e['ota_event_id'] for e in events}) == 2
    for e in events:
        assert e['amount'] == '9737' and e['currency'] == 'JPY' and e['amount_krw'] is None
        assert e['item'] == '숙박비' and e['paid_on'] == '2026-09-25'
        assert e['paid_on_semantics'] == 'mail_sent_proxy'
        assert e['payment_event_id'] is None
        assert e['service_period'] == {'starts_on': '2026-09-30', 'ends_on': '2026-10-01'}
        assert e['card_last4'] is None and e['evidence_status'] == 'paid_verified'
    results = match_ota_payment_events(events, [card('krw-a', amount_krw=85621,
        approval_date='2026-09-25'), card('krw-b', amount_krw=85621, approval_date='2026-09-25')])
    assert all(not r.get('transaction_id') for r in results)


@pytest.mark.parametrize('body', [
    JP_PAID_BODY.replace('9,737' + JP_CHARGED, 'Total JPY 9,737'),
    JP_PAID_BODY + '\n9,738' + JP_CHARGED,
    JP_PAID_BODY + '\n\u4e88\u7d04\u756a\u53f7: 1400830000000002',
    JP_PAID_BODY.replace('2026\u5e749\u670830\u65e5', '2026\u5e7410\u67082\u65e5'),
    JP_PAID_BODY.replace('2026\u5e7410\u67081\u65e5', '2026\u5e7413\u67081\u65e5'),
    JP_PAID_BODY.replace('\u30af\u30ec\u30b8\u30c3\u30c8\u30ab\u30fc\u30c9', 'Trip Coins'),
])
def test_japanese_paid_stay_rejects_ambiguous_or_unpaid_layouts(body):
    from app.ota_payments import _extract_signed_payment_message
    assert _extract_signed_payment_message(message(body, subject=JP_PAID_SUBJECT)) is None


def test_japanese_paid_stay_requires_verified_trip_sender():
    from app.ota_payments import _extract_signed_payment_message
    mail = message(JP_PAID_BODY, subject=JP_PAID_SUBJECT)
    mail['payload']['headers'][-1]['value'] = 'mx.google.com; dkim=fail header.i=@trip.com'
    assert _extract_signed_payment_message(mail) is None
    assert _extract_signed_payment_message(message(JP_PAID_BODY, subject=JP_PAID_SUBJECT,
                                                   domain='booking.com')) is None


def event(identity='event-a', **changes):
    value = dict(ota_event_id=identity, provider='agoda', booking_ref='BOOK12345',
                 item='숙박비',
                 event_type='charge', paid_on='2026-08-01', amount=30000,
                 currency='KRW', amount_krw=30000, card_last4='1234',
                 evidence_status='paid_verified', payment_status='paid',
                 source_digest='a' * 64, source_ids=['mail:1'])
    value.update(changes)
    return value


def card(identity='card-a', **changes):
    value = dict(transaction_id=identity, source_hash=(identity.encode().hex() * 32)[:64],
                 merchant='UNRELATED MERCHANT', merchant_normalized='unrelated merchant',
                 issuer='issuer-x',
                 card_kind='credit', approval_date='2026-08-01', posting_date='2026-08-02',
                 transaction_direction='purchase', amount_krw=30000, card_tail='1234',
                 foreign_currency='', foreign_amount=None)
    value.update(changes)
    return value


def test_a_card_discovery_searches_all_merchants_and_returns_every_same_date_row():
    rows = [card('x', merchant='GROCERY'), card('y', merchant='AIRLINE', amount_krw=100),
            card('z', merchant='UNKNOWN')]
    found = same_date_cards(event(), rows)
    assert [row['transaction_id'] for row in found] == ['y', 'x', 'z']
    assert all('already_linked_event_id' in row for row in found)


def test_candidate_search_marks_rejection_visibility_from_payment_date_only():
    from app.ota_payments import search_card_candidates

    fact = event(paid_on='2026-08-01', currency='KRW', amount=30000, amount_krw=30000)
    same_day = card('same-day', amount_krw=31000, approval_date='2026-08-01')
    other_day = card('other-day', amount_krw=31000, approval_date='2026-08-15')
    result = search_card_candidates(fact, [same_day, other_day])
    visibility = {row['transaction_id']: row['display_relevant'] for row in result['rejected']}
    assert visibility == {'same-day': True, 'other-day': False}

    undated = search_card_candidates(dict(fact, paid_on=None), [same_day])
    assert undated['rejected'][0]['display_relevant'] is False


def test_b_one_booking_can_have_multiple_distinct_paid_events():
    first, second = event('one'), event('two', source_ids=['mail:2'], amount=12000,
                                        amount_krw=12000, paid_on='2026-08-04')
    results = match_ota_payment_events([first, second], [card(), card('card-b', amount_krw=12000,
        approval_date='2026-08-04')])
    assert len(results) == 2
    assert {row['ota_event_id'] for row in results} == {'one', 'two'}


def test_c_reservation_and_scheduled_evidence_never_becomes_charge():
    pending = event('pending', evidence_status='pending', payment_status='scheduled',
                    event_type='reservation', amount_krw=None)
    results = match_ota_payment_events([pending], [card()])
    assert results[0]['status'] == 'PENDING_PAYMENT'
    assert results[0]['transaction_id'] is None


def test_d_refund_requires_explicit_refund_evidence_and_matches_refund_direction():
    refund = event('refund', event_type='refund', refund_status='refunded',
                   evidence_status='refund_verified')
    results = match_ota_payment_events([refund], [card('purchase'), card('refund',
        transaction_direction='refund')])
    assert results[0]['transaction_id'] == 'refund'
    assert results[0]['status'] == 'MATCHED_AUTO'


def test_e_same_mail_identity_and_digest_is_deduplicated_stably(tmp_path):
    mail = message('예약번호: BOOK12345\n총 금액 30,000원', subject='[Trip.com] 결제 완료 안내',
                   identity='stable-message')
    import json
    for directory in (tmp_path / 'one', tmp_path / 'two'):
        directory.mkdir()
        (directory / 'gmail-test.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    first = build_ota_payment_events({'mail_directories': [tmp_path / 'one']})
    duplicate = build_ota_payment_events({'mail_directories': [tmp_path / 'one', tmp_path / 'two']})
    assert len(first) == len(duplicate) == 1
    assert first[0]['ota_event_id'] == duplicate[0]['ota_event_id']


def test_f_two_distinct_payment_ids_for_same_booking_are_not_merged():
    one, two = event('payment-1'), event('payment-2', source_ids=['portal:2'])
    results = match_ota_payment_events([one, two], [card()])
    assert len(results) == 2
    assert sum(result['status'] == 'MATCHED_AUTO' for result in results) <= 1
    assert any(result['status'] == 'HOLD_AMBIGUOUS' for result in results)


def test_g_legacy_exact_link_is_pinned_even_if_a_better_card_appears():
    results = match_ota_payment_events([event()], [card('old'), card('better')],
        existing_links={'event-a': {'transaction_id':'old', 'status':'MATCHED_USER'}})
    assert results[0]['transaction_id'] == 'old'
    assert results[0]['status'] == 'MATCHED_USER'


def test_h_card_only_never_creates_a_payment_event():
    assert build_ota_payment_events({'mail_directories': [], 'portal_databases': [],
                                     'reference_documents': []}) == []


def test_partial_registered_source_inventory_blocks_new_automatic_candidate(tmp_path):
    import json
    from app.ota_payments import OtaSourcesError
    good = tmp_path / 'available-mail'
    good.mkdir()
    mail = message('Booking ID: BOOK12345\nTotal price USD 123.45',
                   subject='Payment confirmation', identity='partial-source-candidate',
                   domain='booking.com')
    (good / 'gmail-test.json').write_text(json.dumps({'responses':[mail]}), encoding='utf-8')
    missing = tmp_path / 'registered-mail-missing'
    with pytest.raises(OtaSourcesError, match='OTA_SOURCES_INCOMPLETE'):
        build_ota_payment_events({'mail_directories':[good, missing]})


def test_source_registry_missing_diagnostics_block_partial_event_inventory(tmp_path):
    from app.ota_payments import OtaSourcesError
    with pytest.raises(OtaSourcesError, match='OTA_SOURCES_INCOMPLETE'):
        build_ota_payment_events({
            'mail_directories':[], 'portal_databases':[], 'reference_documents':[],
            'missing':[{'kind':'portal_database', 'path':'synthetic-missing'}],
            'diagnostics':['registered portal database missing']})


@pytest.mark.parametrize('loader', ['mail', 'portal', 'reference'])
def test_registered_source_loader_errors_block_event_authority(tmp_path, loader):
    from app.ota_payments import OtaSourcesError
    if loader == 'mail':
        source = tmp_path / 'mail'
        source.mkdir()
        (source / 'gmail-broken.json').write_text('{broken', encoding='utf-8')
        sources = {'mail_directories':[source]}
    elif loader == 'portal':
        source = tmp_path / 'broken-portal.sqlite'
        source.write_text('not a database', encoding='utf-8')
        sources = {'portal_databases':[source]}
    else:
        source = tmp_path / 'broken-reference.json'
        source.write_text('{broken', encoding='utf-8')
        sources = {'reference_documents':[source]}
    with pytest.raises(OtaSourcesError, match='OTA_SOURCES_INCOMPLETE'):
        build_ota_payment_events(sources)


def test_portal_payment_without_paid_date_stays_unmatched():
    portal_event = event('portal', provider='agoda', paid_on=None,
                         evidence_kind='portal_payment_claim')
    result = match_ota_payment_events([portal_event], [card()])[0]
    assert result['status'] == 'HOLD_DATE_UNKNOWN'
    assert result['transaction_id'] is None


def test_legacy_exact_portal_link_binds_by_source_booking_card_and_amount():
    from app.ota_payments import bind_legacy_portal_links
    portal_event = event('portal', provider='agoda', paid_on=None,
                         source_digest='d'*64, source_digests=['e'*64], card_last4='1234',
                         amount='30000', currency='KRW')
    bound = bind_legacy_portal_links([portal_event], [{
        'verified_exact': True, 'evidence_kind': 'portal_payment_claim',
        'booking_ref': 'BOOK12345', 'source_digest': 'd'*64, 'source_digests':['e'*64],
        'card_last4': '1234', 'amount': '30000', 'currency': 'KRW',
        'transaction_id': 'legacy-card'}])
    result = match_ota_payment_events([portal_event], [card('legacy-card')], existing_links=bound)
    assert result[0]['status'] == 'MATCHED_AUTO'
    assert result[0]['transaction_id'] == 'legacy-card'


def test_legacy_binding_with_changed_amount_is_rejected():
    portal_event = event('portal', source_digest='d'*64, source_digests=['e'*64])
    binding = {'transaction_id':'card-a', 'status':'MATCHED_AUTO', 'legacy_exact':True,
               'source_digest':'d'*64, 'source_digests':['e'*64]}
    result = match_ota_payment_events([portal_event], [card(amount_krw=31000)],
                                      existing_links={'portal': binding})[0]
    assert result['status'] == 'HOLD_EVIDENCE_CONFLICT'
    assert result['transaction_id'] is None


def test_amount_and_date_without_a_second_identity_signal_auto_matches():
    fact = event(card_last4=None, provider='unknown-provider')
    result = match_ota_payment_events([fact], [card(card_tail=None)])[0]
    assert result['status'] == 'MATCHED_AUTO'
    assert result['transaction_id'] == 'card-a'


def test_paid_charge_is_preserved_when_later_source_reports_refund():
    fact = event(refund_status='refunded')
    result = match_ota_payment_events([fact], [card()])[0]
    assert result['transaction_id'] == 'card-a'
    assert result['status'] == 'MATCHED_AUTO'


def test_changed_source_keeps_event_identity_and_changes_source_digest(tmp_path):
    import json
    mail = message('예약번호: BOOK12345\n총 금액 30,000원', subject='[Trip.com] 결제 완료 안내',
                   identity='stable-source')
    path = tmp_path / 'mail'
    path.mkdir()
    source = path / 'gmail-test.json'
    source.write_text(json.dumps({'responses':[mail]}), encoding='utf-8')
    before = build_ota_payment_events({'mail_directories':[path]})[0]
    mail['payload']['body']['content'] = '예약번호: CHANGED123\n총 금액 31,000원'
    source.write_text(json.dumps({'responses':[mail]}), encoding='utf-8')
    after = build_ota_payment_events({'mail_directories':[path]})[0]
    assert before['ota_event_id'] == after['ota_event_id']
    assert before['source_digest'] != after['source_digest']
    assert before['booking_ref'] != after['booking_ref']
    assert before['amount_krw'] != after['amount_krw']


def test_paid_charge_survives_a_later_booking_cancellation():
    fact = event(reservation_status='cancelled')
    result = match_ota_payment_events([fact], [card()])[0]
    assert result['status'] == 'MATCHED_AUTO'
    assert result['transaction_id'] == 'card-a'


def test_existing_duplicate_pins_are_both_held_for_review():
    first, second = event('one'), event('two', source_ids=['mail:2'])
    links = {identity:{'transaction_id':'card-a','status':'MATCHED_AUTO'} for identity in ('one','two')}
    results = match_ota_payment_events([first, second], [card()], existing_links=links)
    assert [result['status'] for result in results] == ['HOLD_AMBIGUOUS', 'HOLD_AMBIGUOUS']


def test_verified_refund_matches_signed_negative_row_by_absolute_amount_and_direction():
    refund = event('refund', event_type='refund', refund_status='refunded',
                   evidence_status='refund_verified')
    row = card('negative-refund', transaction_direction='refund', amount_krw=-30000)
    result = match_ota_payment_events([refund], [row])[0]
    assert result['status'] == 'MATCHED_AUTO'
    assert result['transaction_id'] == 'negative-refund'


def test_foreign_payment_matches_exact_foreign_amount_and_currency():
    foreign = event(amount='123.45', currency='USD', amount_krw=None)
    row = card('foreign-card', amount_krw=None, foreign_amount='123.45', foreign_currency='USD')
    result = match_ota_payment_events([foreign], [row])[0]
    assert result['status'] == 'MATCHED_AUTO'


@pytest.mark.parametrize('amount,raw,currency,direction,matched', [
    ('52560', '52,560.000', 'JPY', 'purchase', True),
    ('52,560.00', '52560', 'JPY', 'purchase', True),
    ('52560', '-52,560.000', 'JPY', 'refund', True),
    ('52560', '-52,560.000', 'JPY', 'purchase', False),
    ('52560', '52,560.001', 'JPY', 'purchase', False),
    ('52560', '52,560.000', 'USD', 'purchase', False),
    ('52560', '5,2560.000', 'JPY', 'purchase', False),
    ('52560', '52,,560', 'JPY', 'purchase', False),
    ('52560', 'NaN', 'JPY', 'purchase', False),
    ('52560', 'Infinity', 'JPY', 'purchase', False),
    ('52560', '5.256e4', 'JPY', 'purchase', False),
])
def test_foreign_card_format_does_not_change_amount_currency_or_direction(amount, raw, currency, direction, matched):
    fact = event(amount=amount, currency='JPY', amount_krw=None,
                 event_type='refund' if direction == 'refund' else 'charge',
                 evidence_status='refund_verified' if direction == 'refund' else 'paid_verified',
                 refund_status='refunded' if direction == 'refund' else None)
    row = card('foreign-formatted', foreign_amount=raw, foreign_currency=currency,
               transaction_direction=direction, amount_krw=-30000 if direction == 'refund' else 30000)
    result = match_ota_payment_events([fact], [row])[0]
    assert (result['status'] == 'MATCHED_AUTO') is matched
    assert row['foreign_amount'] == raw


def test_signed_approved_amount_delta_matches_but_absolute_or_unapproved_delta_does_not():
    fact = event(amount=279013, amount_krw=279013)
    row = card(amount_krw=275013)
    conditions = {'provider':'agoda','item':'숙박비','issuer':'issuer-x','card_last4':'1234',
                  'amount_delta_krw':-4000,'date_lag_days':0}
    unapproved = {'conditions':conditions, 'status':'pending'}
    approved = {'conditions':conditions, 'status':'active', 'approved_by':'owner'}
    inactive_approved = {'conditions':conditions, 'active':False, 'approved_by':'owner'}
    assert match_ota_payment_events([fact], [row], rules=[unapproved])[0]['status'] == 'HOLD_AMOUNT_MISMATCH'
    assert match_ota_payment_events([fact], [row], rules=[inactive_approved])[0]['status'] == 'HOLD_AMOUNT_MISMATCH'
    assert match_ota_payment_events([fact], [row], rules=[approved])[0]['status'] == 'MATCHED_AUTO'


def test_active_status_without_explicit_user_approval_cannot_apply_delta_rule():
    fact = event(amount=279013, amount_krw=279013)
    row = card(amount_krw=275013)
    active_only = {'conditions':{'provider':'agoda','item':'숙박비','issuer':'issuer-x',
        'card_last4':'1234','amount_delta_krw':-4000}, 'status':'active'}
    assert match_ota_payment_events([fact], [row], rules=[active_only])[0]['status'] == 'HOLD_AMOUNT_MISMATCH'


def test_approved_provider_item_only_rule_is_rejected_as_too_broad():
    fact = event(amount=279013, amount_krw=279013)
    row = card(amount_krw=275013)
    broad = {'conditions':{'provider':'agoda','item':'숙박비','amount_delta_krw':-4000},
             'status':'active','approved_by':'owner'}
    assert match_ota_payment_events([fact], [row], rules=[broad])[0]['status'] == 'HOLD_AMOUNT_MISMATCH'


def test_missing_manual_event_link_still_reserves_its_card():
    current = event('other')
    missing_pin = {'removed-event': {'transaction_id':'card-a','status':'MATCHED_USER'}}
    result = match_ota_payment_events([current], [card()], existing_links=missing_pin)[0]
    assert result['status'] == 'HOLD_AMBIGUOUS'
    assert result['transaction_id'] is None


def test_portal_source_extract_keeps_two_same_amount_payment_ids(tmp_path):
    import hashlib
    import json
    import shutil
    import sqlite3
    from tests.card_pipeline.test_ota_portal import portal_database
    path = portal_database(tmp_path / 'portal.sqlite')
    with sqlite3.connect(path) as conn:
        record = conn.execute('SELECT id,payload_json FROM direct_source_records').fetchone()
        fact = json.loads(record[1])
        fact['booking_number'] = 'BOOK12345'
        fact['price_components'] = [
            {'kind':'paid_today','currency':'KRW','decimal_text':'30000','minor_units':30000,'scale':0,'payment_id':'pay-a'},
            {'kind':'paid_today','currency':'KRW','decimal_text':'30000','minor_units':30000,'scale':0,'payment_id':'pay-b'}]
        raw = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        conn.execute('UPDATE direct_source_records SET payload_json=?,source_sha256=? WHERE id=?',
                     (raw, hashlib.sha256(raw.encode()).hexdigest(), record[0]))
        conn.execute("UPDATE bookings SET booking_number='BOOK12345'")
    events = build_ota_payment_events({'portal_databases':[path]})
    assert len(events) == 2
    assert {event['payment_id'] for event in events} == {'pay-a','pay-b'}
    assert len({event['payment_event_id'] for event in events}) == 2
    assert all(event['paid_on'] is None for event in events)


def test_portal_jpy_does_not_invent_krw_amount(tmp_path):
    import hashlib
    import json
    import sqlite3
    from tests.card_pipeline.test_ota_portal import portal_database
    path = portal_database(tmp_path / 'portal-jpy.sqlite')
    with sqlite3.connect(path) as conn:
        record = conn.execute('SELECT id,payload_json FROM direct_source_records').fetchone()
        fact = json.loads(record[1])
        fact['price_components'] = [{'kind':'paid_today','currency':'JPY','decimal_text':'12000',
                                     'minor_units':12000,'scale':0,'payment_id':'jpy-payment'}]
        raw = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        conn.execute('UPDATE direct_source_records SET payload_json=?,source_sha256=? WHERE id=?',
                     (raw, hashlib.sha256(raw.encode()).hexdigest(), record[0]))
    built = build_ota_payment_events({'portal_databases':[path]})[0]
    assert built['currency'] == 'JPY'
    assert built['amount'] == '12000'
    assert built['amount_krw'] is None


def test_mail_and_portal_same_payment_id_merge_source_digests_once(tmp_path):
    import hashlib
    import json
    import sqlite3
    from tests.card_pipeline.test_ota_portal import portal_database
    mail = message('Booking reference: BOOK12345\nPayment ID: pay-1234\nPaid amount: KRW 30000\nCard ending 1234',
                   subject='Payment confirmation', identity='mail-pay', domain='agoda.com')
    directory = tmp_path / 'mail'
    directory.mkdir()
    (directory / 'gmail-test.json').write_text(json.dumps({'responses':[mail]}), encoding='utf-8')
    path = portal_database(tmp_path / 'portal.sqlite')
    with sqlite3.connect(path) as conn:
        record = conn.execute('SELECT id,payload_json FROM direct_source_records').fetchone()
        fact = json.loads(record[1])
        fact['booking_number'] = 'BOOK12345'
        fact['payment_id'] = 'pay-1234'
        fact['price_components'][0]['payment_id'] = 'pay-1234'
        raw = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        conn.execute('UPDATE direct_source_records SET payload_json=?,source_sha256=? WHERE id=?',
                     (raw, hashlib.sha256(raw.encode()).hexdigest(), record[0]))
        conn.execute("UPDATE bookings SET booking_number='BOOK12345'")
    events = build_ota_payment_events({'mail_directories':[directory], 'portal_databases':[path]})
    assert len(events) == 1
    assert len(events[0]['source_digests']) == 2
    assert len(events[0]['source_ids']) == 2


def test_same_date_and_amount_mail_portal_claims_without_identity_proof_stay_separate():
    from app.ota_payments import _merge_proven_duplicate_payments
    mail_event = event('mail-event', provider='agoda', paid_on='2026-08-01',
                       amount='30000', amount_krw=30000, currency='KRW', card_last4='1234',
                       source_ids=['mail:mail-event'], payment_id=None, source_binding_ids=[])
    portal_event = event('portal-event', provider='agoda', paid_on='2026-08-01',
                         amount='30000', amount_krw=30000, currency='KRW', card_last4='1234',
                         source_ids=['portal:record:source-7:payment:row-7-part-0'],
                         payment_id=None, source_binding_ids=[])
    merged = _merge_proven_duplicate_payments([mail_event, portal_event])
    assert {item['ota_event_id'] for item in merged} == {'mail-event', 'portal-event'}
    contested = match_ota_payment_events(merged, [card()])
    assert [item['status'] for item in contested] == ['HOLD_AMBIGUOUS', 'HOLD_AMBIGUOUS']


def test_portal_explicit_completed_refund_becomes_separate_event(tmp_path):
    import hashlib
    import json
    import sqlite3
    from tests.card_pipeline.test_ota_portal import portal_database
    path = portal_database(tmp_path / 'portal-refund.sqlite')
    with sqlite3.connect(path) as conn:
        record = conn.execute('SELECT id,payload_json FROM direct_source_records').fetchone()
        fact = json.loads(record[1])
        fact['refund_status'] = 'refunded'
        fact['price_components'].append({'kind':'refund_completed','currency':'KRW',
            'decimal_text':'5000','minor_units':5000,'scale':0,'payment_id':'refund-1',
            'refunded_on':'2026-08-03'})
        raw = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        conn.execute('UPDATE direct_source_records SET payload_json=?,source_sha256=? WHERE id=?',
                     (raw, hashlib.sha256(raw.encode()).hexdigest(), record[0]))
    events = build_ota_payment_events({'portal_databases':[path]})
    assert [event['event_type'] for event in events].count('charge') == 1
    refunds = [event for event in events if event['event_type'] == 'refund']
    assert len(refunds) == 1
    assert refunds[0]['paid_on'] == '2026-08-03'


def test_completed_aside_stay_supplies_missing_item_without_changing_payment(tmp_path):
    from tests.card_pipeline.test_ota_portal import portal_database
    path = portal_database(tmp_path / 'completed-aside.sqlite', facts=[{
        'evidence_format': 'agoda-aside-v1', 'reservation_status': 'completed'}])
    original = path.read_bytes()
    event = build_ota_payment_events({'portal_databases': [path]})[0]
    assert event['item'] == '숙박비'
    assert event['paid_on'] is None
    assert event['service_period'] == {'starts_on': '2026-08-02', 'ends_on': '2026-08-03'}
    assert event['amount_krw'] == 30000 and event['card_last4'] == '1234'
    assert event['booking_ref'] == 'synthetic-booking'
    from app.ota_payments import _event_id
    assert event['ota_event_id'] == _event_id(event['identity_source_ids'])
    assert path.read_bytes() == original


def test_portal_observation_keeps_reason_when_paid_event_is_not_created(tmp_path):
    import json
    import sqlite3
    from app.reconcile.observations import inspect_observations
    from tests.card_pipeline.test_ota_portal import portal_database

    path = portal_database(tmp_path / 'missing-paid-component.sqlite')
    with sqlite3.connect(path) as conn:
        record = conn.execute('SELECT id,payload_json FROM direct_source_records').fetchone()
        fact = json.loads(record[1])
        fact['price_components'] = [{**item, 'kind': 'gross_total'}
                                    for item in fact['price_components']]
        raw = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        conn.execute('UPDATE direct_source_records SET payload_json=?,source_sha256=? WHERE id=?',
                     (raw, hashlib.sha256(raw.encode()).hexdigest(), record[0]))

    sources = {'portal_databases': [path]}
    outcomes = []
    events = build_ota_payment_events(sources, extraction_outcomes=outcomes)
    report = inspect_observations(sources, events, outcomes)
    assert events == []
    assert report['skipped_reason_counts']['PAID_TODAY_COMPONENT_MISSING'] == 5


def test_missing_item_is_not_inferred_from_agoda_name_or_unverified_stay(tmp_path):
    from tests.card_pipeline.test_ota_portal import portal_database
    cases = [
        ({}, None),
        ({'evidence_format': 'agoda-aside-v1', 'reservation_status': 'confirmed'}, None),
        ({'evidence_format': 'agoda-aside-v1', 'service_start_on': None}, None),
        ({'evidence_format': 'agoda-aside-v1', 'item': '항공료'}, '항공료'),
        ({'product_type': 'lodging'}, '숙박비'),
        ({'product_type': 'flight'}, None),
    ]
    for index, (changes, expected) in enumerate(cases):
        path = portal_database(tmp_path / f'item-guard-{index}.sqlite', facts=[changes])
        event = build_ota_payment_events({'portal_databases': [path]})[0]
        assert event['item'] == expected


def test_later_cancel_notice_does_not_replace_verified_charge(tmp_path):
    import json
    paid = message('예약번호: BOOK12345\n총 금액 30,000원',
                   subject='[Trip.com] 결제 완료 안내', identity='paid-before-cancel')
    cancel = message('예약번호: BOOK12345', subject='[Trip.com] 예약이 취소되었습니다',
                     identity='cancel-after-paid')
    directory = tmp_path / 'mail-cancel'
    directory.mkdir()
    (directory / 'gmail-test.json').write_text(json.dumps({'responses':[paid,cancel]}), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[directory]})
    charges = [event for event in events if event['event_type'] == 'charge' and
               event['evidence_status'] == 'paid_verified']
    assert len(charges) == 1
    assert charges[0]['booking_ref'] == 'BOOK12345'


def test_signed_booking_id_total_price_payment_receipt_extracts_without_cards(tmp_path):
    import json
    mail = message('Booking ID: BOOK12345\nTotal price USD 123.45\nCheck-in: August 1, 2026\nCheck-out: August 3, 2026',
                   subject='Payment completed', identity='booking-payment', domain='booking.com')
    directory = tmp_path / 'booking-mail'
    directory.mkdir()
    (directory / 'gmail-test.json').write_text(json.dumps({'responses':[mail]}), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[directory]})
    assert len(events) == 1
    assert events[0]['booking_ref'] == 'BOOK12345'
    assert events[0]['currency'] == 'USD'
    assert events[0]['amount'] == '123.45'
    assert events[0]['service_period'] == {'starts_on':'2026-08-01','ends_on':'2026-08-03'}


def test_trip_prepaid_confirmation_captures_only_actual_online_payment_without_inventing_date(tmp_path):
    import json
    mail = message(
        '예약 번호: 1400830177908672\n체크인: 2026년 10월 23일\n체크아웃: 2026년 10월 24일\n'
        '온라인 사전 결제\n결제 완료\nKB국민카드(신용카드) 199,173원\n'
        '총 예약 요금 202,000원\n온라인 사전 결제 199,173원',
        subject='[예약 확정 안내] 합성 숙소 예약이 확정되었습니다', identity='trip-prepaid')
    # 실제 Gmail 원본의 필드명도 확인한다. 이 필드는 결제일의 증거가 아니다.
    mail['internalDate'] = mail.pop('internal_date')
    path = tmp_path / 'gmail-trip.json'
    path.write_text(json.dumps({'responses':[mail]}, ensure_ascii=False), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[tmp_path]})
    assert len(events) == 1
    actual = events[0]
    assert (actual['booking_ref'], actual['event_type'], actual['evidence_status']) == (
        '1400830177908672', 'charge', 'paid_verified')
    assert (actual['amount'],actual['currency'],actual['amount_krw'],actual['paid_on']) == (
        '199173','KRW',199173,None)
    assert actual['service_period'] == {'starts_on':'2026-10-23','ends_on':'2026-10-24'}
    assert actual['source_ids'] == ['mail:trip-prepaid']
    # A paid reservation without an explicit payment date must not bind to an
    # otherwise same-amount/same-card transaction.
    candidate = card('possible-trip-payment', amount_krw=199173,
                     approval_date='2026-10-21', card_tail='1234')
    linked = match_ota_payment_events([actual], [candidate])
    assert linked[0]['transaction_id'] is None


def test_booking_receipt_uses_explicit_paid_date_and_excludes_onsite_tax(tmp_path):
    import json
    receipt = message(
        '예약 번호 5374676720\n결제일 2026년 10월 21일\n'
        '체크인: 2026년 10월 23일\n체크아웃: 2026년 10월 24일\n'
        '2026년 10월 21일에 결제된 금액 ¥24,200',
        subject='고객님의 영수증입니다', identity='booking-receipt',domain='booking.com')
    confirmation = message(
        '예약 번호 5374676720\n체크인: 2026년 10월 23일\n체크아웃: 2026년 10월 24일\n'
        '합계 ¥24,500\n총 지불 금액 ¥24,200\n현장 온천세 ¥300',
        subject='예약이 확정되었습니다', identity='booking-confirmation', domain='booking.com')
    for mail in (receipt, confirmation):
        mail['internalDate'] = mail.pop('internal_date')
    (tmp_path / 'gmail-booking.json').write_text(
        json.dumps({'responses':[receipt,confirmation]}, ensure_ascii=False), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[tmp_path]})
    paid = [e for e in events if e['evidence_status'] == 'paid_verified']
    assert len(events) == 2 and len(paid) == 1
    assert (paid[0]['amount'],paid[0]['currency'],paid[0]['paid_on']) == (
        '24200','JPY','2026-10-21')
    assert paid[0]['paid_on_semantics'] == 'explicit_charge_date'
    assert paid[0]['source_ids'] == ['mail:booking-receipt']
    assert paid[0]['service_period'] == {'starts_on':'2026-10-23','ends_on':'2026-10-24'}
    assert any(e['event_type'] == 'reservation' for e in events)
    # The separately due onsite tax is not a second online charge.
    onsite_tax = card('onsite-tax', approval_date='2026-10-21',
                     foreign_currency='JPY', foreign_amount='300', amount_krw=3000)
    assert match_ota_payment_events(paid, [onsite_tax])[0]['transaction_id'] is None


def test_booking_receipt_with_conflicting_paid_dates_does_not_create_charge(tmp_path):
    import json
    receipt = message('예약 번호 5374676720\n결제일 2026년 10월 20일\n'
                      '2026년 10월 21일에 결제된 금액 ¥24,200',
                      subject='고객님의 영수증입니다',identity='conflict',domain='booking.com')
    receipt['internalDate'] = receipt.pop('internal_date')
    (tmp_path/'gmail-conflict.json').write_text(
        json.dumps({'responses':[receipt]}, ensure_ascii=False),encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[tmp_path]})
    assert len(events) == 1
    assert events[0]['evidence_status'] == 'not_card_charge'


def test_booking_payment_receipt_subject_and_amount_label_variants_are_extracted(tmp_path):
    import json
    labels = ['총 금액', '총 지불 금액', '총 요금']
    subjects = [
        '결제가 완료되었습니다', '결제 완료 안내', 'Payment confirmation',
        'Your payment was successfully received', 'Payment for your booking was received',
        'Your reservation payment is successful', '결제 완료 알림', 'Payment successfully completed',
        'Booking payment received',
    ]
    messages = []
    for index in range(16):
        label = labels[index % len(labels)] if index < 9 else '결제 완료'
        subject = subjects[index % len(subjects)]
        messages.append(message(
            f'Booking ID: BOOK{index:08d}\n{label} USD {100 + index}.25',
            subject=subject, identity=f'booking-receipt-{index}', domain='booking.com'))
    directory = tmp_path / 'booking-receipt-variants'
    directory.mkdir()
    (directory / 'gmail-test.json').write_text(json.dumps({'responses':messages}), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[directory]})
    assert len(events) == 16
    assert all(item['evidence_status'] == 'paid_verified' for item in events)
    assert all(item['currency'] == 'USD' for item in events)


def test_scheduled_booking_receipt_never_becomes_paid_event(tmp_path):
    import json
    mail = message('Booking ID: BOOK12345\nTotal price USD 123.45\nYour card will be charged on August 1, 2026',
                   subject='Payment scheduled', identity='booking-scheduled', domain='booking.com')
    directory = tmp_path / 'scheduled-mail'
    directory.mkdir()
    (directory / 'gmail-test.json').write_text(json.dumps({'responses':[mail]}), encoding='utf-8')
    events = build_ota_payment_events({'mail_directories':[directory]})
    assert len(events) == 1
    assert events[0]['event_type'] == 'scheduled_charge'
    assert events[0]['evidence_status'] == 'scheduled'
    assert match_ota_payment_events(events, [card()])[0]['status'] == 'PENDING_PAYMENT'


def test_portal_snapshot_copies_with_only_observed_at_change_deduplicate(tmp_path):
    from tests.card_pipeline.test_ota_portal import portal_database
    first = portal_database(tmp_path / 'portal-copy-a.sqlite')
    second = portal_database(tmp_path / 'portal-copy-b.sqlite')
    events = build_ota_payment_events({'portal_databases':[first,second]})
    assert len(events) == 1
    assert len(events[0]['source_digests']) == 1
    assert events[0]['paid_on'] is None
    assert len(events[0]['source_lineage_ids']) == 2
    assert len(events[0]['observation_ids']) == 2
    assert events[0]['payment_event_id'] is None


def test_portal_source_lineage_can_use_registered_stable_id(tmp_path):
    from tests.card_pipeline.test_ota_portal import portal_database
    path = portal_database(tmp_path / 'portal-lineage.sqlite')
    events = build_ota_payment_events({
        'portal_databases': [path],
        'source_lineage_ids': {str(path.resolve()): 'agoda-primary-source'},
    })
    assert events[0]['source_lineage_ids'] == ['agoda-primary-source']
    assert len(events[0]['observation_ids']) == 1


def test_portal_local_record_id_collision_does_not_merge_distinct_bookings(tmp_path):
    import hashlib
    import shutil
    import sqlite3
    from tests.card_pipeline.test_ota_portal import portal_database
    first = portal_database(tmp_path / 'portal-a.sqlite')
    second = portal_database(tmp_path / 'portal-b.sqlite')
    with sqlite3.connect(first) as conn:
        conn.execute("UPDATE direct_source_records SET payload_json=replace(payload_json,'synthetic-booking','booking-a')")
        raw = conn.execute('SELECT payload_json FROM direct_source_records').fetchone()[0]
        conn.execute('UPDATE direct_source_records SET source_sha256=?', (hashlib.sha256(raw.encode()).hexdigest(),))
        conn.execute("UPDATE bookings SET booking_number='booking-a'")
    first_copy = tmp_path / 'portal-a-copy.sqlite'
    shutil.copyfile(first, first_copy)
    with sqlite3.connect(second) as conn:
        conn.execute("UPDATE direct_source_records SET payload_json=replace(replace(payload_json,'synthetic-booking','booking-b'),'30000','70000')")
        raw = conn.execute('SELECT payload_json FROM direct_source_records').fetchone()[0]
        conn.execute('UPDATE direct_source_records SET source_sha256=?', (hashlib.sha256(raw.encode()).hexdigest(),))
        conn.execute("UPDATE bookings SET booking_number='booking-b'")
    events = build_ota_payment_events({'portal_databases':[first, first_copy, second]})
    assert len(events) == 2
    assert {(item['booking_ref'], item['amount_krw']) for item in events} == {
        ('booking-a', 30000), ('booking-b', 70000)}
    assert len({item['ota_event_id'] for item in events}) == 2
    copied = next(item for item in events if item['booking_ref'] == 'booking-a')
    assert len(copied['source_lineage_ids']) == 2


def test_undated_payment_candidate_search_is_separate_from_exact_matching():
    from app.ota_payments import search_card_candidates
    fact = event('undated-event', paid_on=None)
    row = card('candidate-card')
    trace = search_card_candidates(fact, [row])
    assert trace['status'] == 'CANDIDATES_FOUND'
    assert trace['date_status'] == 'UNKNOWN'
    assert trace['candidates'] == [{
        'transaction_id': 'candidate-card', 'date_status': 'UNKNOWN',
        'resolution_allowed': False, 'basis': 'EXACT_AMOUNT_AND_CARD_EVIDENCE'}]
    assert match_ota_payment_events([fact], [row])[0]['status'] == 'HOLD_DATE_UNKNOWN'


def test_undated_candidate_search_keeps_hard_card_identity_exclusion():
    from app.ota_payments import search_card_candidates
    fact = event('undated-event', paid_on=None)
    row = card('wrong-card', card_tail='9999')
    assert search_card_candidates(fact, [row])['status'] == 'NO_CANDIDATE'


def test_candidate_search_reports_known_date_mismatch_without_allowing_resolution():
    from app.ota_payments import search_card_candidates
    fact = event('dated-event', paid_on='2026-08-01')
    row = card('later-card', approval_date='2026-08-03')
    result = search_card_candidates(fact, [row])
    assert result['candidates'][0]['date_status'] == 'MISMATCH'
    assert result['candidates'][0]['resolution_allowed'] is False


def test_candidate_search_reports_amount_and_currency_mismatch_reasons():
    from app.ota_payments import search_card_candidates
    fact = event('amount-event', paid_on=None)
    wrong_amount = card('wrong-amount', amount_krw=31000)
    amount_result = search_card_candidates(fact, [wrong_amount])
    assert amount_result['rejection_counts']['AMOUNT_MISMATCH'] == 1

    foreign_fact = event('currency-event', paid_on=None, currency='JPY', amount='30000', amount_krw=None)
    wrong_currency = card('wrong-currency', foreign_amount='30000', foreign_currency='USD')
    currency_result = search_card_candidates(foreign_fact, [wrong_currency])
    assert currency_result['rejection_counts']['CURRENCY_MISMATCH'] == 1


def test_candidate_search_uses_approved_provider_alias_defaults():
    from app.ota_payments import search_card_candidates
    fact = event('agoda-alias', paid_on=None, card_last4=None)
    row = card('agoda-nice', card_tail='1234', merchant_normalized='agoda nice-agoda')
    result = search_card_candidates(fact, [row])
    assert result['status'] == 'CANDIDATES_FOUND'
    assert result['candidates'][0]['date_status'] == 'UNKNOWN'


def test_same_payload_under_distinct_portal_source_ids_is_not_collapsed(tmp_path):
    from tests.card_pipeline.test_ota_portal import portal_database
    path = portal_database(tmp_path / 'distinct-records.sqlite', [{},{}])
    events = build_ota_payment_events({'portal_databases':[path]})
    assert len(events) == 2
    assert events[0]['source_ids'] != events[1]['source_ids']


def test_repeated_nm_payments_normalize_equal_decimal_formats_without_inventing_identity():
    """Two verified reservations + two real card payments are a count-balanced N:M group.

    A card belongs to the group, not to an individually proven booking number.
    Sorting is deterministic, but no individual payment evidence is asserted.
    """
    bookings = [
        event('nm-1', booking_ref='BOOK-A', amount=30000, amount_krw=30000,
              source_digest='1' * 64, source_ids=['mail:nm-1']),
        event('nm-2', booking_ref='BOOK-B', amount='30000.00', amount_krw='30000.00',
              source_digest='2' * 64, source_ids=['mail:nm-2']),
    ]
    cards = [
        card('nm-card-1', approval_number='1001', amount_krw=30000),
        card('nm-card-2', approval_number='1002', amount_krw=30000),
    ]
    first = match_ota_payment_events(bookings, cards)
    second = match_ota_payment_events(list(reversed(bookings)), list(reversed(cards)))
    def summarized(results):
        return {row['ota_event_id']: (row['status'], row.get('transaction_id'))
                for row in results}
    assert summarized(first) == summarized(second)
    assert {row['transaction_id'] for row in first} == {'nm-card-1', 'nm-card-2'}
    assert all(row['status'] == 'MATCHED_AUTO'
               and row['group_count'] == {'ota': 2, 'cards': 2}
               and row['allocation_basis'] == 'auto_stable_order'
               and row['individual_payment_evidence'] is False
               for row in first)


def test_repeated_nm_payments_hold_when_extra_equal_amount_card_exists():
    bookings = [
        event('over-1', booking_ref='B-A', amount=30000, amount_krw=30000),
        event('over-2', booking_ref='B-B', amount='30000.0', amount_krw='30000.00'),
    ]
    cards = [card('over-c1'), card('over-c2'), card('over-c3')]
    results = match_ota_payment_events(bookings, cards)
    assert len(results) == 2
    assert all(row['status'] == 'HOLD_PARTIAL_GROUP'
               and row['transaction_id'] is None
               and row['group_count'] == {'ota': 2, 'cards': 3}
               for row in results)


def test_repeated_nm_payment_rejects_invalid_numeric_group_identity():
    from app.ota_payments import _canonical_group_amount
    assert _canonical_group_amount('30000.00') == '30000'
    assert _canonical_group_amount(30000) == '30000'
    assert _canonical_group_amount('30000.001') == '30000.001'
    for invalid in ('NaN', 'Infinity', '-30000', '0', '', None):
        assert _canonical_group_amount(invalid) is None
