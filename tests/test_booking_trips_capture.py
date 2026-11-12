"""Synthetic Booking.com trip ingestion, display-fare boundary and LINK-002 non-broadening checks."""
import datetime
import json
from pathlib import Path

import pytest

from app.booking_trips_capture import FORMAT, parse_trip, records
from app.ota_store import OtaStore
from app.ota_payments import _booking_trip_events
from tools.import_booking_trips import main, plan
from webapp.ledger_stay_evidence import _build_index

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

# Two identical blocks, a same-name/period/status block at another fare, and a distinct hotel:
# exercises both the occurrence disambiguation and the singleton content hash, with no snapshot.
MULTI_BLOCKS = [
    ['가상호텔', '10월 23일 ~ 10월 24일₩123,456', '객실 1개도쿠시마', '완료'],
    ['가상호텔', '10월 23일 ~ 10월 24일₩123,456', '객실 1개도쿠시마', '완료'],
    ['가상호텔', '10월 23일 ~ 10월 24일₩200,000', '도쿠시마', '완료'],
    ['다른호텔', '10월 24일 ~ 10월 25일₩150,000', '객실 1개교토', '완료'],
]


def _blocks_text(blocks):
    return '예약 찾기\n' + '\n'.join(line for block in blocks for line in block) + '\n국가'


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


def isolated_store(tmp_path, name='ota-evidence.sqlite'):
    """A store laid out as <host>/data/<name> so the isolated-copy gate accepts it."""
    db = tmp_path / 'host' / 'data' / name
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


def isolated_apply_args(db):
    """Fresh isolated-copy backup evidence for the store's CURRENT state, plus gated --apply args.

    Re-prepared before each apply so the gate's state comparison still matches after prior writes.
    """
    from tools.verify_operational_backup_restore import backup_database, database_state
    db = Path(db)
    if not db.exists():
        OtaStore(db).close()
    host = db.parent.parent
    bundle = host / 'data' / 'backups' / 'bundle'
    (bundle / 'databases').mkdir(parents=True, exist_ok=True)
    backup_database(db, bundle / 'databases' / db.name)
    state = database_state(db)
    (bundle / 'manifest.json').write_text(json.dumps({'databases': {db.name: state}}), encoding='utf8')
    evidence = host / 'data' / 'backups' / 'evidence.json'
    evidence.write_text(json.dumps({
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'backup_directory': str(bundle), 'live_state_unchanged': True,
        'all_database_tables_and_columns_compared': True, 'restored_review_binding_equal': True,
    }), encoding='utf8')
    return ['--apply', '--isolated-copy', '--host-root', str(host), '--backup-evidence', str(evidence)]


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


def test_inconsistent_snapshot_falls_back_to_content_identity():
    mismatched = LODGING_SNAPSHOT.replace('가상호텔', '다른호텔')
    fact, = parse_trip(trip_record(LODGING_TEXT, mismatched))
    assert fact['identity_kind'] == 'content_hash'
    assert fact['booking_number'].startswith('bkg-')
    empty, = parse_trip(trip_record(LODGING_TEXT, ''))
    assert empty['identity_kind'] == 'content_hash'
    # Content identity ignores the trip id and screen order, unlike the old block ordinal.
    other, = parse_trip(trip_record(LODGING_TEXT, '', trip_id='trip-other'))
    assert fact['booking_number'] == empty['booking_number'] == other['booking_number']


def test_content_identity_is_order_independent():
    base = parse_trip(trip_record(_blocks_text(MULTI_BLOCKS)))
    assert len(base) == 4 and all(f['identity_kind'] == 'content_hash' for f in base)
    base_ids = {f['booking_number'] for f in base}
    assert len(base_ids) == 4  # identical-content blocks keep distinct occurrences
    for reordered in (list(reversed(MULTI_BLOCKS)), MULTI_BLOCKS[2:] + MULTI_BLOCKS[:2],
                      [MULTI_BLOCKS[3], MULTI_BLOCKS[0], MULTI_BLOCKS[2], MULTI_BLOCKS[1]]):
        again = parse_trip(trip_record(_blocks_text(reordered)))
        assert {f['booking_number'] for f in again} == base_ids


def test_reordered_recapture_adds_no_duplicates(tmp_path, capsys):
    captures = tmp_path / 'capture'
    write_capture(captures, [trip_record(_blocks_text(MULTI_BLOCKS))])
    db = isolated_store(tmp_path)
    args = ['--directory', str(captures), '--store', str(db)]
    assert main(args + isolated_apply_args(db)) == 0
    first = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert first['inserted'] == 4 and first['additional'] == 4 and first['duplicate_input'] == 0
    before = db.read_bytes()
    write_capture(captures, [trip_record(_blocks_text(list(reversed(MULTI_BLOCKS))))])
    assert main(args + isolated_apply_args(db)) == 0
    again = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert again['additional'] == 0 and again['duplicate'] == 4
    assert again['inserted'] == 0 and again['conflict'] == 0
    assert before == db.read_bytes()


def test_apply_gate_refuses_missing_stale_or_changed_backup(tmp_path, capsys):
    captures = tmp_path / 'capture'
    write_capture(captures, [trip_record(LODGING_TEXT, LODGING_SNAPSHOT)])
    db = isolated_store(tmp_path)
    base = ['--directory', str(captures), '--store', str(db)]
    with pytest.raises(SystemExit):  # no --backup-evidence: refused before any write
        main(base + ['--apply'])
    args = base + isolated_apply_args(db)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['inserted'] == 1
    # The evidence now describes the pre-append state; reusing it must be refused, not applied.
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['error'] == 'BACKUP_SOURCE_CHANGED'
    evidence = Path(args[args.index('--backup-evidence') + 1])
    saved = json.loads(evidence.read_text(encoding='utf8'))
    saved['recorded_at'] = (datetime.datetime.now(datetime.timezone.utc)
                            - datetime.timedelta(hours=2)).isoformat()
    evidence.write_text(json.dumps(saved), encoding='utf8')
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['error'] == 'BACKUP_NOT_FRESH'


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
    db = isolated_store(tmp_path)
    args = ['--directory', str(captures), '--store', str(db)]
    assert main(args) == 0
    assert not db.exists()
    preview = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert preview['additional'] == 1 and preview['inserted'] == 0 and preview['conflict'] == 0
    assert main(args + isolated_apply_args(db)) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['inserted'] == 1
    before = db.read_bytes()
    assert main(args + isolated_apply_args(db)) == 0
    replay = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert replay['duplicate'] == 1 and replay['inserted'] == 0 and replay['additional'] == 0
    assert before == db.read_bytes()
    changed = trip_record(LODGING_TEXT.replace('10월 24일', '10월 25일'), LODGING_SNAPSHOT)
    write_capture(captures, [changed])
    assert main(args + isolated_apply_args(db)) == 0
    conflict = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert conflict['conflict'] == 1 and conflict['inserted'] == 0
    assert before == db.read_bytes()


def test_append_only_preserves_existing_source_rows(tmp_path, capsys):
    captures = tmp_path / 'capture'
    lodging = trip_record(LODGING_TEXT, LODGING_SNAPSHOT, trip_id='trip-a')
    write_capture(captures, [lodging])
    db = isolated_store(tmp_path)
    args = ['--directory', str(captures), '--store', str(db)]
    assert main(args + isolated_apply_args(db)) == 0
    capsys.readouterr()
    store = OtaStore(db)
    before = {tuple(r) for r in store.conn.execute(
        'SELECT booking_id, fact_json FROM ota_booking_evidence')}
    store.close()
    flight = trip_record(FLIGHT_TEXT, FLIGHT_SNAPSHOT, trip_id='trip-b')
    write_capture(captures, [lodging, flight])
    assert main(args + isolated_apply_args(db)) == 0
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
    db = isolated_store(tmp_path)
    assert main(['--directory', str(captures), '--store', str(db)] + isolated_apply_args(db)) == 0
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
    db = isolated_store(tmp_path)
    assert main(['--directory', str(captures), '--store', str(db)] + isolated_apply_args(db)) == 0
    capsys.readouterr()
    return _booking_trip_events([str(db)])


def test_booking_reservation_never_attaches_card_period(tmp_path, capsys):
    # LINK-002 is the only path that gives a card row a usage period. A Booking trip screen has no
    # card tail or payment date and only a display fare, so even an exact foreign-fare match must
    # not attach a period (the removed display-inference path).
    events = _flight_events(tmp_path, capsys)
    card = booking_card(amount_krw=113333, foreign_amount=111222)  # foreign total == display fare
    data = dict(events=events, transactions=[card], results=[], links={})
    assert 'card-1' not in _build_index(data, set())
