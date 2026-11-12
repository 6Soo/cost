"""Parse saved Booking.com trip screens into per-booking reservation facts.

A record is {observed_at, trip: UserTrips node, text: rendered screen, snapshot: accessibility
tree}. The rendered text names each booking's property or route, its stay or departure dates,
its status (완료/취소됨) and a KRW display fare. Blocks are read from the text so a capture whose
accessibility tree came from another tab still parses.

Each booking's confirmation anchor in the accessibility tree (lodging ``confirmation.ko.html`` /
``mybooking_archivedsummary.ko.html`` with an ``auth_key``; flights ``flights.booking.com/
confirmation/<token>``) supplies a stable opaque identity when the tree lines up with the text
block for block. Otherwise the trip id and block ordinal identify the booking.

The screen fare is a display amount: Booking shows lodging in the viewer's currency, so a KRW
figure may be a conversion of the property's own currency and is never exact card-payment
evidence. It is kept only as period/status evidence (and for read-only display matching). No
payment, charge date or card tail is invented here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

FORMAT = 'booking-trips-v1'
PARSER_VERSION = 1

_LODGING_URL = re.compile(r'secure\.booking\.com/(?:confirmation|mybooking_archivedsummary)\.ko\.html')
_FLIGHT_URL = re.compile(r'flights\.booking\.com/confirmation/([0-9a-f]{32,})')
_AUTH_KEY = re.compile(r'[?&]auth_key=([^&\s\]]+)')
_TEXT = re.compile(r'^\s*text "((?:[^"\\]|\\.)*)"')
_ANCHOR = re.compile(r'^(\s*)anchor \[ref=\d+, url=([^\]]+)\]')
_PRICE = re.compile(r'₩\s*([\d,]+)')
_LODGING_RANGE = re.compile(r'(\d{1,2})월\s*(\d{1,2})일\s*~\s*(\d{1,2})월\s*(\d{1,2})일')
_FLIGHT_LEG = re.compile(r'(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}:\d{2})')
_ROOMS = re.compile(r'객실\s*(\d+)개\s*(.*)')
_PASSENGERS = re.compile(r'승객\s*(\d+)명')
_ROUTE = re.compile(r'(.+?)\s*→\s*(.+)')
_AIRLINE = re.compile(r'^(?:직항|경유)\s*(.*)')
_STATUS = {'완료': 'completed', '취소됨': 'cancelled', '취소': 'cancelled'}
_IGNORE = {'·', '파트너사 요금', '인보이스 요청', '숙박 경험 평가하기', '닫기', '직항', '경유'}


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('BOOKING_OBSERVATION_TIME_REQUIRED')
    return parsed.astimezone(timezone.utc).isoformat()


def _money(text):
    found = _PRICE.search(text)
    return int(found[1].replace(',', '')) if found else None


def _infer_date(month, day, anchor):
    """The screen omits the year; place each date in the year nearest the trip start."""
    month, day = int(month), int(day)
    candidates = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        raise ValueError('BOOKING_DATE_INVALID')
    return min(candidates, key=lambda value: (abs((value - anchor).days), value.year < anchor.year))


def _lodging_period(text, anchor):
    found = _LODGING_RANGE.search(text)
    if not found:
        return None, None
    start = _infer_date(found[1], found[2], anchor)
    end = _infer_date(found[3], found[4], anchor)
    if end < start:
        end = date(end.year + 1, end.month, end.day)
    return start.isoformat(), end.isoformat()


def _flight_period(texts, anchor):
    """Departure through arrival across every leg of the booking."""
    days = []
    for text in texts:
        found = _FLIGHT_LEG.search(text)
        if found:
            days.append(_infer_date(found[1], found[2], anchor))
            days.append(_infer_date(found[4], found[5], anchor))
    if not days:
        return None, None
    return min(days).isoformat(), max(days).isoformat()


def _identity(product_type, token):
    return 'bkg-' + hashlib.sha256(f'{product_type}:{token}'.encode('utf-8')).hexdigest()[:20]


def _booking_area(text):
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    try:
        start = lines.index('예약 찾기') + 1
    except ValueError:
        raise ValueError('BOOKING_SCREEN_HEADER_MISSING')
    end = next((i for i in range(start, len(lines)) if lines[i] == '국가'), len(lines))
    return lines[start:end]


def _text_blocks(lines):
    """Split the booking area into blocks; a label before a date line opens a block once the
    previous one has closed with its status. A round trip's second route stays in its block."""
    def opens(i):
        return i + 1 < len(lines) and (_LODGING_RANGE.search(lines[i + 1]) or _FLIGHT_LEG.search(lines[i + 1]))

    blocks, current, closed = [], [], True
    for i, line in enumerate(lines):
        if opens(i) and (closed or not current):
            if current:
                blocks.append(current)
            current, closed = [line], False
        else:
            current.append(line)
        if line.startswith('완료') or line.startswith('취소됨') or line.startswith('취소'):
            closed = True
    if current:
        blocks.append(current)
    return blocks


def _snapshot_identities(snapshot):
    """Confirmation anchors in document order as (product_type, token, heading)."""
    lines = snapshot.splitlines()
    result = []
    for index, line in enumerate(lines):
        found = _ANCHOR.match(line)
        if not found:
            continue
        indent, url = len(found[1]), found[2]
        flight = _FLIGHT_URL.search(url)
        lodging = _LODGING_URL.search(url)
        if flight:
            product, token = 'flight', flight[1]
        elif lodging:
            auth = _AUTH_KEY.search(url)
            if not auth:
                continue
            product, token = 'lodging', auth[1]
        else:
            continue
        heading = None
        for sub in lines[index + 1:]:
            if not sub.strip():
                continue
            if len(sub) - len(sub.lstrip(' ')) <= indent:
                break
            text = _TEXT.match(sub)
            if text:
                heading = text[1].replace('\\"', '"').strip()
                break
        result.append((product, token, heading))
    return result


def _common_fields(trip_id, anchor, observed_at, block, product_type, item, label, start, end,
                   status, amount, rooms, city, airline, passengers, routes):
    if not start or not end or not label or status is None:
        raise ValueError('BOOKING_BLOCK_INVALID')
    return {
        'provider': 'booking', 'evidence_format': FORMAT, 'parser_version': PARSER_VERSION,
        'product_type': product_type, 'item': item, 'label': label, 'city': city, 'rooms': rooms,
        'airline': airline, 'passengers': passengers, 'routes': routes,
        'service_start_on': start, 'service_end_on': end, 'reservation_status': status,
        'display_amount_krw': amount, 'display_currency': 'KRW', 'display_amount_is_converted': True,
        'price_components': ([{'kind': 'display_total', 'currency': 'KRW', 'decimal_text': str(amount)}]
                             if amount is not None else []),
        'amount_krw': None, 'payment_status': 'unknown', 'paid_on': None, 'card_last4': None,
        'trip_id': trip_id, 'observed_at': observed_at,
    }


def _parse_block(block, trip_id, anchor, observed_at):
    label = block[0]
    joined = ' '.join(block)
    routes = [line for line in block if _ROUTE.search(line)]
    is_flight = bool(routes) or any(_FLIGHT_LEG.search(line) for line in block)
    status = None
    for line in block:
        for token, value in _STATUS.items():
            if line.startswith(token):
                status = value
                break
        if status:
            break
    amount = next((_money(line) for line in block if _money(line) is not None), None)
    passengers = next((int(_PASSENGERS.search(line)[1]) for line in block if _PASSENGERS.search(line)), None)
    rooms, city = None, None
    for line in block[1:]:
        found = _ROOMS.search(line)
        if found:
            rooms = int(found[1])
            if found[2].strip():
                city = found[2].strip()
            break
    airline = next((_AIRLINE.search(line)[1].strip() for line in block
                    if _AIRLINE.search(line) and _AIRLINE.search(line)[1].strip()), None)
    if is_flight:
        start, end = _flight_period(block, anchor)
        return _common_fields(trip_id, anchor, observed_at, block, 'flight', '항공료',
                              routes[0] if routes else label, start, end, status, amount,
                              None, None, airline, passengers, routes)
    start, end = _lodging_period(joined, anchor)
    if city is None:
        city = next((line for line in block[1:]
                     if line not in _IGNORE and not _PRICE.search(line) and not _LODGING_RANGE.search(line)
                     and not _ROOMS.search(line) and not _PASSENGERS.search(line)
                     and not line.startswith(('완료', '취소됨', '취소')) and not _AIRLINE.search(line)), None)
    return _common_fields(trip_id, anchor, observed_at, block, 'lodging', '숙박비', label,
                          start, end, status, amount, rooms, city, None, None, [])


def parse_trip(record):
    """One saved trip screen as a list of booking facts. Every block must be readable."""
    trip = record.get('trip') or {}
    trip_id = str(trip.get('id') or '')
    if not trip_id:
        raise ValueError('BOOKING_TRIP_ID_REQUIRED')
    if not trip.get('startDate') or not trip.get('endDate'):
        raise ValueError('BOOKING_TRIP_PERIOD_REQUIRED')
    anchor = date.fromisoformat(trip['startDate'])
    if date.fromisoformat(trip['endDate']) < anchor:
        raise ValueError('BOOKING_TRIP_PERIOD_INVALID')
    observed_at = _utc(record['observed_at'])
    blocks = _text_blocks(_booking_area(record.get('text') or ''))
    if not blocks:
        raise ValueError('BOOKING_NO_RESERVATIONS')
    facts = [_parse_block(block, trip_id, anchor, observed_at) for block in blocks]
    identities = _snapshot_identities(record.get('snapshot') or '')
    aligned = (len(identities) == len(facts)
               and all(ident[0] == fact['product_type'] and ident[2] == fact['label']
                       for ident, fact in zip(identities, facts)))
    for ordinal, fact in enumerate(facts, 1):
        if aligned:
            product, token, _heading = identities[ordinal - 1]
            fact['booking_number'] = _identity(product, token)
            fact['identity_kind'] = 'confirmation_token'
        else:
            fact['booking_number'] = f'bkg-trip-{trip_id}-{ordinal}'
            fact['identity_kind'] = 'trip_ordinal'
        fact['snapshot_sha256'] = hashlib.sha256((record.get('snapshot') or '').encode('utf-8')).hexdigest()
    if len({fact['booking_number'] for fact in facts}) != len(facts):
        raise ValueError('BOOKING_DUPLICATE_BLOCK')
    return facts


def trip_list_nodes(directory):
    """Trip nodes from the saved PAST/CANCELLED lists, keyed by trip id."""
    root = Path(directory)
    nodes = {}
    for name in ('booking-list-PAST.json', 'booking-list-CANCELLED.json'):
        path = root / name
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding='utf-8'))
        for edge in ((payload.get('data') or {}).get('userTrips') or {}).get('edges') or []:
            node = edge.get('node') or {}
            if node.get('id'):
                nodes[node['id']] = node
    return nodes


def records(directory):
    """Saved trip screens joined with their list node for identity binding."""
    root = Path(directory)
    details = root / 'booking' / 'details'
    nodes = trip_list_nodes(root)
    for path in sorted(details.glob('trip-*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        trip = record.get('trip') or {}
        if nodes and str(trip.get('id')) not in nodes:
            raise ValueError('BOOKING_TRIP_IDENTITY_MISSING')
        if nodes:
            listed = nodes[str(trip['id'])]
            if (listed.get('startDate'), listed.get('endDate')) != (trip.get('startDate'), trip.get('endDate')):
                raise ValueError('BOOKING_TRIP_PERIOD_MISMATCH')
        yield path, record
