"""Synthetic Booking.com trip ingestion, display-fare boundary and LINK-002 non-broadening checks."""
import json

import pytest

from app.booking_trips_capture import FORMAT, parse_trip, records
from app.ota_store import OtaStore
from app.ota_payments import _booking_trip_events
from tools.import_booking_trips import main, plan
from webapp.ledger_stay_evidence import _booking_candidate_periods

OBSERVED = '2031-02-10T12:00:00+09:00'
TRIP_START = '2031-10-20'
TRIP_END = '2031-10-25'

LODGING_TEXT = '\n'.join(['예약 찾기', '가상호텔', '10월 23일 ~ 10월 24일₩123,456',
                          '객실 1개도쿠시마', '완료', '국가'])
LODGING_SNAPSHOT = '\n'.join([
    '  anchor [ref=1, url=https://secure.booking.com/confirmation.ko.html?auth_key=abcdef1234567890]',
    '    text "가상호텔"'])
FLIGHT_TEXT = '\n'.join(['예약 찾기', 'ICN → NRT', '10월 23일 09:00 - 10월 23일 11:30',
                         '완료승객 1명', '직항Eastar Jet', '₩111,222', '국가'])
FLIGHT_SNAPSHOT = '\n'.join([
    '  anchor [ref=1, url=https://flights.booking.com/confirmation/0123456789abcdef0123456789abcdef]',
    '    text "ICN → NRT"'])
ROUNDTRIP_TEXT = '\n'.join(['예약 찾기', 'ICN → NRT', '10월 23일 09:00 - 10월 23일 11:30',
                            'NRT → ICN', '10월 27일 12:00 - 10월 27일 14:30',
                            '완료승객 1명', '직항Eastar Jet', '₩222,333', '국가'])
CANCELLED_TEXT = '\n'.join(['예약 찾기', '가상호텔', '10월 23일 ~ 10월 24일₩123,456',
                            '취소됨', '국가'])
CANCELLED_FLIGHT_TEXT = '\n'.join(['예약 찾기', 'ICN → NRT', '10월 23일 09:00 - 10월 23일 11:30',
                                   '취소됨승객 1명', '직항Eastar Jet', '₩111,222', '국가'])


def trip_record(text, snapshot='', trip_id='trip-demo', start=TRIP_START, end=TRIP_END):
    return {'observed_at': OBSERVED,
            'trip': {'id': trip_id, 'startDate': start, 'endDate': end, 'itemCount': 1,
                     'status': 'CONFIRMED', 'stage': 'PAST'},
            'text': text, 'snapshot': snapshot}


def write_capture(root, recs):
    details = root / 'booking' / 'details'
    details.mkdir(parents=True, exist_ok=True)
    edges = []
    for i, rec in enumerate(recs, 1):
        (details / f'trip-{i}.json').write_text(json.dumps(rec, ensure_ascii=False), encoding='utf8')
        edges.append({'node': rec['trip']})
    (root / 'booking-list-PAST.json').write_text(
        json.dumps({'data': {'userTrips': {'edges': edges}}}, ensure_ascii=False), encoding='utf8')


def booking_card(**over):
    card = dict(transaction_id='card-1', source_hash='src-1', merchant='Booking.com99999999999',
                amount_krw=113333, foreign_currency='KRW', foreign_amount=111222,
                approval_date='2031-10-08', transaction_direction='purchase', item='항공료')
    card.update(over)
    return card


def test_lodging_block_parses_period_status_rooms_and_display_fare():
    fact, = parse_trip(trip_record(LODGING_TEXT, LODGING_SNAPSHOT))
    assert fact['provider'] == 'booking' and fact['evidence_format'] == FORMAT
    assert fact['product_type'] == 'lodging' and fact['item'] == '숙박비'
    assert fact['label'] == '가상호텔' and fact['rooms'] == 1 and fact['city'] == '도쿠시마'
    assert fact['service_start_on'] == '2031-10-23' and fact['service_end_on'] == '2031-10-24'
    assert fact['reservation_status'] == 'completed'
    assert fact['display_amount_krw'] == 123456 and fact['display_currency'] == 'KRW'
    assert fact['identity_kind'] == 'confirmation_token'


def test_flight_block_parses_route_leg_airline_and_period():
    fact, = parse_trip(trip_record(FLIGHT_TEXT, FLIGHT_SNAPSHOT))
    assert fact['product_type'] == 'flight' and fact['item'] == '항공료'
    assert fact['routes'] == ['ICN → NRT'] and fact['airline'] == 'Eastar Jet'
    assert fact['passengers'] == 1
    assert fact['service_start_on'] == '2031-10-23' and fact['service_end_on'] == '2031-10-23'
    assert fact['display_amount_krw'] == 111222
    assert fact['identity_kind'] == 'confirmation_token'


def test_round_trip_is_one_booking_spanning_both_legs():
    fact, = parse_trip(trip_record(ROUNDTRIP_TEXT, FLIGHT_SNAPSHOT))
    assert fact['product_type'] == 'flight'
    assert fact['routes'] == ['ICN → NRT', 'NRT → ICN']
    assert fact['service_start_on'] == '2031-10-23' and fact['service_end_on'] == '2031-10-27'
    assert fact['display_amount_krw'] == 222333


def test_cancelled_status_invents_no_charge_or_refund():
    fact, = parse_trip(trip_record(CANCELLED_TEXT, LODGING_SNAPSHOT))
    assert fact['reservation_status'] == 'cancelled'
    assert fact['amount_krw'] is None and fact['payment_status'] == 'unknown'
    assert fact['paid_on'] is None and fact['card_last4'] is None
    assert fact['display_amount_krw'] == 123456


@pytest.mark.parametrize('text,snapshot', [(LODGING_TEXT, LODGING_SNAPSHOT),
                                           (FLIGHT_TEXT, FLIGHT_SNAPSHOT)])
def test_display_fare_is_never_exact_payment_evidence(text, snapshot):
    fact, = parse_trip(trip_record(text, snapshot))
    assert fact['display_amount_is_converted'] is True
    assert fact['amount_krw'] is None and fact['payment_status'] == 'unknown'
    assert fact['paid_on'] is None and fact['card_last4'] is None
    assert [part['kind'] for part in fact['price_components']] == ['display_total']
    assert not any(part['kind'] == 'paid_today' for part in fact['price_components'])


def test_inconsistent_snapshot_falls_back_to_trip_ordinal_identity():
    mismatched = LODGING_SNAPSHOT.replace('가상호텔', '다른호텔')
    fact, = parse_trip(trip_record(LODGING_TEXT, mismatched))
    assert fact['identity_kind'] == 'trip_ordinal'
    assert fact['booking_number'] == 'bkg-trip-trip-demo-1'
    empty, = parse_trip(trip_record(LODGING_TEXT, ''))
    assert empty['identity_kind'] == 'trip_ordinal'


def test_confirmation_token_identity_is_stable_across_observations():
    first, = parse_trip(trip_record(LODGING_TEXT, LODGING_SNAPSHOT))
    again, = parse_trip(trip_record(LODGING_TEXT, LODGING_SNAPSHOT, trip_id='trip-other'))
    assert first['booking_number'] == again['booking_number']


def test_records_require_bound_list_identity_and_period(tmp_path):
    write_capture(tmp_path, [trip_record(LODGING_TEXT, LODGING_SNAPSHOT)])
    assert len(list(records(tmp_path))) == 1
    stray = trip_record(LODGING_TEXT, LODGING_SNAPSHOT, trip_id='trip-not-listed')
    (tmp_path / 'booking' / 'details' / 'trip-9.json').write_text(
        json.dumps(stray, ensure_ascii=False), encoding='utf8')
    with pytest.raises(ValueError, match='IDENTITY'):
        list(records(tmp_path))


def test_import_preview_append_replay_and_conflict_never_overwrite(tmp_path, capsys):
    captures = tmp_path / 'capture'
    write_capture(captures, [trip_record(LODGING_TEXT, LODGING_SNAPSHOT)])
    db = tmp_path / 'ota.sqlite'
    args = ['--directory', str(captures), '--store', str(db)]
    assert main(args) == 0
    assert not db.exists()
    preview = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert preview['additional'] == 1 and preview['inserted'] == 0 and preview['conflict'] == 0
    assert main(args + ['--apply']) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['inserted'] == 1
    before = db.read_bytes()
    assert main(args + ['--apply']) == 0
    replay = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert replay['duplicate'] == 1 and replay['inserted'] == 0 and replay['additional'] == 0
    assert before == db.read_bytes()
    changed = trip_record(LODGING_TEXT.replace('10월 24일', '10월 25일'), LODGING_SNAPSHOT)
    write_capture(captures, [changed])
    assert main(args + ['--apply']) == 0
    conflict = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert conflict['conflict'] == 1 and conflict['inserted'] == 0
    assert before == db.read_bytes()


def test_append_only_preserves_existing_source_rows(tmp_path, capsys):
    captures = tmp_path / 'capture'
    lodging = trip_record(LODGING_TEXT, LODGING_SNAPSHOT, trip_id='trip-a')
    write_capture(captures, [lodging])
    db = tmp_path / 'ota.sqlite'
    args = ['--directory', str(captures), '--store', str(db), '--apply']
    assert main(args) == 0
    capsys.readouterr()
    store = OtaStore(db)
    before = {tuple(r) for r in store.conn.execute(
        'SELECT booking_id, fact_json FROM ota_booking_evidence')}
    store.close()
    flight = trip_record(FLIGHT_TEXT, FLIGHT_SNAPSHOT, trip_id='trip-b')
    write_capture(captures, [lodging, flight])
    assert main(args) == 0
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary['inserted'] == 1 and summary['duplicate'] == 1 and summary['conflict'] == 0
    store = OtaStore(db)
    after = {tuple(r) for r in store.conn.execute(
        'SELECT booking_id, fact_json FROM ota_booking_evidence')}
    store.close()
    assert len(after) == len(before) + 1
    assert before <= after


def test_consumed_as_reservation_only_without_payment(tmp_path, capsys):
    captures = tmp_path / 'capture'
    write_capture(captures, [trip_record(FLIGHT_TEXT, FLIGHT_SNAPSHOT)])
    db = tmp_path / 'ota.sqlite'
    assert main(['--directory', str(captures), '--store', str(db), '--apply']) == 0
    capsys.readouterr()
    event, = _booking_trip_events([str(db)])
    assert event['event_type'] == 'reservation' and event['evidence_status'] == 'reservation_only'
    assert event['payment_status'] == 'not_card_charge' and event['evidence_kind'] == 'portal_reservation'
    assert event['amount'] is None and event['amount_krw'] is None
    assert event['paid_on'] is None and event['card_last4'] is None
    assert event['display_amount_krw'] == 111222 and event['item'] == '항공료'
    assert event['service_period'] == {'starts_on': '2031-10-23', 'ends_on': '2031-10-23'}


def _flight_events(tmp_path, capsys, text=FLIGHT_TEXT):
    captures = tmp_path / 'capture'
    write_capture(captures, [trip_record(text, FLIGHT_SNAPSHOT)])
    db = tmp_path / 'ota.sqlite'
    assert main(['--directory', str(captures), '--store', str(db), '--apply']) == 0
    capsys.readouterr()
    return _booking_trip_events([str(db)])


def test_display_inference_names_period_without_payment_link(tmp_path, capsys):
    events = _flight_events(tmp_path, capsys)
    card = booking_card()
    data = dict(events=events, transactions=[card], results=[], links={})
    found = _booking_candidate_periods(data, set())
    assert found['card-1']['service_period'] == '2031-10-23~2031-10-23'
    assert found['card-1']['item'] == '항공료'
    assert found['card-1']['ota_evidence'] == {'kind': 'reservation_period_inferred',
                                               'payment_verified': False}
    from app.ota_core_projection import card_matches
    assert card_matches([], data) == []


def test_display_inference_matches_foreign_krw_total_not_billed_krw(tmp_path, capsys):
    events = _flight_events(tmp_path, capsys)
    # The screen fare equals the card's foreign KRW total, not its billed amount_krw.
    card = booking_card(amount_krw=113333, foreign_amount=111222)
    found = _booking_candidate_periods(dict(events=events, transactions=[card], results=[], links={}), set())
    assert 'card-1' in found
    billed_only = booking_card(amount_krw=111222, foreign_currency='USD', foreign_amount=100)
    found = _booking_candidate_periods(dict(events=events, transactions=[billed_only], results=[], links={}), set())
    assert 'card-1' in found


def test_converted_lodging_fare_does_not_match_billed_card(tmp_path, capsys):
    captures = tmp_path / 'capture'
    write_capture(captures, [trip_record(LODGING_TEXT, LODGING_SNAPSHOT)])
    db = tmp_path / 'ota.sqlite'
    assert main(['--directory', str(captures), '--store', str(db), '--apply']) == 0
    capsys.readouterr()
    events = _booking_trip_events([str(db)])
    card = booking_card(amount_krw=130000, foreign_currency='JPY', foreign_amount=15000,
                        item='숙박비', approval_date='2031-10-08')
    found = _booking_candidate_periods(dict(events=events, transactions=[card], results=[], links={}), set())
    assert found == {}


def test_display_inference_rejects_ambiguous_cancelled_and_late_cards(tmp_path, capsys):
    events = _flight_events(tmp_path, capsys)
    twin = booking_card(transaction_id='card-2', source_hash='src-2')
    data = dict(events=events, transactions=[booking_card(), twin], results=[], links={})
    assert _booking_candidate_periods(data, set()) == {}
    late = booking_card(approval_date='2031-10-24')
    assert _booking_candidate_periods(dict(events=events, transactions=[late], results=[], links={}), set()) == {}
    cancelled = _flight_events(tmp_path / 'c', capsys, text=CANCELLED_FLIGHT_TEXT)
    assert _booking_candidate_periods(dict(events=cancelled, transactions=[booking_card()],
                                           results=[], links={}), set()) == {}


def test_display_inference_skips_occupied_and_manual_cards(tmp_path, capsys):
    events = _flight_events(tmp_path, capsys)
    card = booking_card()
    occupied = dict(events=events, transactions=[card],
                    results=[dict(transaction_id='card-1', ota_event_id='other', status='MATCHED_AUTO')],
                    links={})
    assert _booking_candidate_periods(occupied, set()) == {}
    assert _booking_candidate_periods(dict(events=events, transactions=[card], results=[], links={}),
                                      {'card-card-1'}) == {}


def test_build_index_wires_booking_display_inference(tmp_path, capsys):
    from webapp.ledger_stay_evidence import _build_index
    events = _flight_events(tmp_path, capsys)
    data = dict(events=events, transactions=[booking_card()], results=[], links={})
    index = _build_index(data, set())
    assert index['card-1']['service_period'] == '2031-10-23~2031-10-23'
    assert index['card-1']['ota_evidence'] == {'kind': 'reservation_period_inferred',
                                               'payment_verified': False}
