"""Authenticated mail groups must not modify payment events or financial decisions."""
from copy import deepcopy
import json
import pytest

from app import ota_payments
from app.ota_mail_reservation_identity import attest
from app.ota_reservation_groups import project_reservation_groups
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_payments import JP_PAID_BODY, JP_PAID_SUBJECT
from webapp import ota_payment_review, ota_snapshot


def test_two_authenticated_payment_notices_group_but_keep_distinct_event_ids_and_amounts(tmp_path):
    mails = [message(JP_PAID_BODY, subject=JP_PAID_SUBJECT, identity='synthetic-charge-a', sent='2026-09-25'),
             message(JP_PAID_BODY.replace('9,737', '9,738'), subject=JP_PAID_SUBJECT,
                     identity='synthetic-charge-b', sent='2026-09-26')]
    (tmp_path / 'gmail-test.json').write_text(json.dumps({'responses': mails}), encoding='utf-8')
    events = ota_payments.build_ota_payment_events({'mail_directories': [tmp_path]})
    original = deepcopy(events)
    assert len(events) == 2 and len({e['ota_event_id'] for e in events}) == 2
    projected = project_reservation_groups(events)
    group, = projected['groups']
    assert group['verified'] and group['member_count'] == 2
    assert {e['amount'] for e in events} == {'9737', '9738'}
    assert events == original
    assert all(e['payment_event_id'] is None for e in events)
    results = ota_payments.match_ota_payment_events(events, [])
    assert all(r['transaction_id'] is None for r in results)
    assert all(r['status'] != 'MATCHED_AUTO' for r in results)
    public = ota_payment_review.public_snapshot({'events': events})
    assert '_mail_reservation_provenance' not in json.dumps(public)
    persisted = ota_snapshot._public_results(results)
    assert all('reservation_identity_attestation' not in r and '_mail_reservation_provenance' not in r for r in persisted)


def test_producer_rejects_untrusted_domain_and_ambiguous_or_different_binding():
    mail = message('예약번호: SYN123456', identity='synthetic')
    base = {'provider': 'trip', 'booking_ref': 'SYN123456', 'source_ids': ['mail:synthetic'], 'source_digest': 'digest'}
    for text, domain in [('예약번호: OTHER1234', None),
                         ('예약번호: SYN123456 예약번호: OTHER1234', None),
                         ('예약번호: SYN123456', 'dkim=fail header.i=@trip.com')]:
        candidate = deepcopy(base)
        raw = deepcopy(mail)
        if domain:
            raw['payload']['headers'][-1]['value'] = domain
        attest(candidate, raw, text)
        assert 'reservation_identity_attestation' not in candidate
    local_hotel = dict(base, provider='toyoko')
    attest(local_hotel, mail, '예약번호: SYN123456')
    assert 'reservation_identity_attestation' not in local_hotel


@pytest.mark.parametrize('change', [
    {'booking_ref': 'OTHER1234'}, {'source_digest': 'changed'}, {'source_ids': []},
    {'source_ids': 1}, {'evidence_missing': True},
])
def test_grouping_refuses_changed_or_missing_mail_binding(change):
    mail = message('예약번호: SYN123456', identity='synthetic')
    event = {'ota_event_id': 'evt', 'provider': 'trip', 'booking_ref': 'SYN123456',
             'source_ids': ['mail:synthetic'], 'source_digest': 'digest'}
    attest(event, mail, '예약번호: SYN123456')
    event.update(change)
    group, = project_reservation_groups([event])['groups']
    assert not group['verified']
