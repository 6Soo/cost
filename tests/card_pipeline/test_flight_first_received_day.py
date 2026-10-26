"""User-approved first received date policy; every message is synthetic."""
import datetime
import json

from app import flight_evidence as flight
from tests.card_pipeline.test_booking_mail import message


def _flight(ref='123456789'):
    return f'예약번호: {ref}\nKIM\n(성)\nALPHA\n(이름)'


def _save(root, messages):
    path = root / 'gmail-synthetic.json'
    path.write_text(json.dumps({'responses': messages}), encoding='utf-8')
    return path


def test_first_receipt_is_per_booking_authenticated_mailbox_time_in_korea(tmp_path):
    latest = message(_flight(), identity='flight', sent='2026-10-06')
    earliest = message('예약번호: 123456789', identity='first', sent='2026-09-15')
    earliest['internal_date'] = str(int(datetime.datetime.fromisoformat('2026-10-01T23:30:00+00:00').timestamp() * 1000))
    unrelated = message(_flight('987654321'), identity='other', sent='2026-09-01')
    forged = message('예약번호: 123456789', identity='untrusted', sent='2026-08-01', domain='untrusted.invalid')
    path = _save(tmp_path, [latest, unrelated, forged, earliest])
    before = path.read_bytes()
    result = flight.collect_flight_evidence([tmp_path])
    got = result[('trip', '123456789')]
    assert got['booking_date_status'] == 'FIRST_RECEIVED'
    assert got['reserved_on'] == got['booking_card_day'] == '2026-10-02'
    assert got['booking_date_evidence'][0]['timestamp'] == '2026-10-01T23:30:00+00:00'
    assert got['booking_date_evidence'][0]['source_kind'] == 'mailbox_internal_date'
    assert result[('trip', '987654321')]['reserved_on'] == '2026-09-01'
    assert len(result) == 2 and path.read_bytes() == before


def test_explicit_date_and_conflict_take_precedence_over_mail_fallback(tmp_path):
    explicit = message(_flight() + '\n예약일: 2026-10-04', identity='explicit', sent='2026-10-06')
    early = message('예약번호: 123456789', identity='first', sent='2026-10-02')
    _save(tmp_path, [explicit, early])
    got = flight.collect_flight_evidence([tmp_path])[('trip', '123456789')]
    assert got['booking_date_status'] == 'EXPLICIT_LABEL' and got['reserved_on'] == '2026-10-04'
    conflicting = message(_flight() + '\n예약일: 2026-10-05', identity='conflict')
    _save(tmp_path, [explicit, early, conflicting])
    got = flight.collect_flight_evidence([tmp_path])[('trip', '123456789')]
    assert got['booking_date_status'] == 'CONFLICT' and not got['booking_card_day']


def test_new_earlier_receipt_changes_date_and_revision_without_creating_flights(tmp_path):
    current = message(_flight(), identity='later', sent='2026-10-06')
    generic_other = message('예약번호: 555555555', identity='generic-only', sent='2026-08-01')
    _save(tmp_path, [current, generic_other])
    first = flight.collect_flight_evidence([tmp_path])
    assert len(first) == 1
    prior = first[('trip', '123456789')]
    earlier = message('예약번호: 123456789', identity='earlier', sent='2026-10-02')
    _save(tmp_path, [current, generic_other, earlier])
    changed = flight.collect_flight_evidence([tmp_path])[('trip', '123456789')]
    assert changed['reserved_on'] == '2026-10-02' and changed['digest'] != prior['digest']
    assert len(changed['source_digests']) == 2
    assert prior['reserved_on'] == '2026-10-06'


def test_invalid_reception_and_multiple_booking_messages_do_not_supply_fallback(tmp_path):
    invalid = message(_flight(), identity='invalid')
    invalid['internal_date'] = 'not-a-mailbox-time'
    generic = message('예약번호: 123456789\n예약번호: 987654321', identity='ambiguous')
    _save(tmp_path, [invalid, generic])
    got = flight.collect_flight_evidence([tmp_path])[('trip', '123456789')]
    assert got['booking_date_status'] == 'UNKNOWN' and not got['reserved_on']
    for bad in (None, '-1', '1790000000', '99999999999999'):
        assert flight._received_fact({'internal_date': bad}, 'synthetic') is None


def test_receipt_date_can_be_shown_with_itinerary_conflict_without_clearing_it():
    booking = flight.merge_booking_evidence([{'booking_ref': '123456789', 'source_digest': 'synthetic',
        'booking_date_status': 'UNKNOWN', 'passengers': [], 'legs': []}])
    booking['conflict'] = True
    receipt = flight._received_fact(message('', identity='synthetic'), 'synthetic')
    projected = flight._with_first_received_day(booking, [receipt])
    assert projected['conflict'] and projected['booking_date_status'] == 'FIRST_RECEIVED'
    assert not booking.get('reserved_on')  # Projection never changes the original object.
