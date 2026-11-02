"""Trip.com 항공 메일 본문에서 승객·여정 근거만 읽는다. 가이드 여부는 정하지 않는다."""
import collections
import copy
import datetime
import hashlib
import json
import re

from app import ota_mail


PARSER_VERSION = "flight-evidence-v7-conservative-asiana-skyticket"
PROVIDER_DOMAINS = {
    "trip": ("trip.com", "trip.co.kr"),
    "asiana": ("flyasiana.com",),
    "skyticket": ("skyticket.com",),
}

_INVISIBLE = dict.fromkeys([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, *range(0x202A, 0x202F)])
_HEADER = re.compile(
    r"(가는편|오는편|\d+구간|여정\s*\d+|"
    r"\d+(?=\s*:\s*[^:\n|]+?\s+-\s+[^:\n|]+?\s*\|\s*\d{4}년))"
    r"\s*:\s*(.+?)\s*-\s*(.+?)\s*(?:\|(.*))?")
_INLINE_HEADER = re.compile(
    r"(?<!\d)((?:가는편|오는편|\d+구간|여정\s*\d+|\d+)\s*:\s*"
    r"[^\n|:]+?\s+-\s+[^\n|:]+?\s*\|\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일)")
_INLINE_PASSENGER = re.compile(
    r"(?<![A-Za-z])([A-Za-z][A-Za-z .'\-]*?)\s*\(성\)\s*"
    r"([A-Za-z][A-Za-z .'\-]*?)\s*\(이름\)")
_INLINE_FLIGHT = re.compile(
    r"(?<![A-Z0-9])([A-Z0-9]{2}\s?\d{1,4})\s*\|\s*"
    r"(?:일반석|이코노미|비즈니스|퍼스트|Economy|Business|First)(?=\s|\||$)")
_DATE = re.compile(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일")
_NAME = re.compile(r"[A-Za-z가-힣][A-Za-z가-힣 .'\-]*")
_TIME = re.compile(r"\d{1,2}:\d{2}")
_IATA = re.compile(r"[A-Z]{3}(?![A-Za-z])")
_FLIGHT = re.compile(r"[A-Z0-9]{2}\s?\d{1,4}")
_MEMO = {}

_EXPLICIT_BOOKED = re.compile(
    r"^(?:예약(?:\s*완료)?\s*(?:일시|일자|날짜|일)|예약\s*생성\s*(?:일시|일)|"
    r"booking\s*(?:created\s*(?:at|on)|date|time)|booked\s*(?:on|at))"
    r"\s*[:：]\s*(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})(?:일)?"
    r"(?:\s+(\d{1,2}:\d{2}(?::\d{2})?)(?:\s*(KST|UTC|GMT|[+-]\d{2}:?\d{2}))?)?\s*$",
    re.IGNORECASE,
)


def _booking_date_details(tokens):
    """Keep source calendar dates and explicit zones; unknown zones never select a card day."""
    facts = []
    for token in tokens:
        match = _EXPLICIT_BOOKED.fullmatch(token)
        if not match:
            continue
        try:
            year, month, day, clock, zone = match.groups()
            source_day = datetime.date(int(year), int(month), int(day)).isoformat()
            timestamp, card_day = '', ''
            if clock:
                instant = datetime.datetime.combine(datetime.date.fromisoformat(source_day),
                    datetime.time(*(int(value) for value in clock.split(':'))))
                if zone:
                    offset = {'KST': '+09:00', 'UTC': '+00:00', 'GMT': '+00:00'}.get(zone.upper(), zone)
                    instant = datetime.datetime.fromisoformat(instant.isoformat() + offset)
                    timestamp = instant.isoformat()
                    card_day = instant.astimezone(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()
            facts.append({'source_date': source_day, 'timestamp': timestamp,
                          'timezone': (zone or '').upper(), 'card_day': card_day,
                          'meaning': 'explicit_booking_created_label'})
        except ValueError:
            continue
    dates = {fact['source_date'] for fact in facts}
    card_days = {fact['card_day'] for fact in facts if fact['card_day']}
    if len(dates) > 1 or len(card_days) > 1:
        return '', 'CONFLICT', facts, ''
    if dates:
        return next(iter(dates)), 'EXPLICIT_LABEL', facts, next(iter(card_days), '')
    return '', 'UNKNOWN', [], ''


def _explicit_booking_date(tokens):
    return _booking_date_details(tokens)[:2]


def _booking_refs(tokens):
    return {_booking_ref(tokens[i:i + 2]) for i, token in enumerate(tokens)
            if token.startswith('예약번호')} - {''}


def _received_fact(message, source_digest):
    """Mailbox reception milliseconds only; sender Date/Received text is not used."""
    snake = message.get('internal_date')
    camel = message.get('internalDate')
    if snake not in (None, '') and camel not in (None, '') and str(snake) != str(camel):
        # Conflict between original spellings: reject conservatively, keep digest unchanged.
        return None
    raw = str(snake if snake not in (None, '') else camel or '')
    if not re.fullmatch(r'\d{12,13}', raw):
        return None
    try:
        instant = datetime.datetime.fromtimestamp(int(raw) / 1000, datetime.timezone.utc)
        day = instant.astimezone(datetime.timezone(datetime.timedelta(hours=9))).date()
        if not 2000 <= day.year <= 2100:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    return {'source_date': instant.date().isoformat(), 'timestamp': instant.isoformat(),
            'timezone': 'UTC', 'card_day': day.isoformat(), 'source_digest': source_digest,
            'meaning': 'first_received_mail_user_policy', 'source_kind': 'mailbox_internal_date'}


def _with_first_received_day(booking, receipts):
    # Explicit/conflicting dates take precedence. An itinerary conflict remains
    # visible and blocks automatic card queries, but does not erase receipt history.
    if booking.get('booking_date_status') != 'UNKNOWN' or not receipts:
        return booking
    first_time = min(fact['timestamp'] for fact in receipts)
    first = sorted((fact for fact in receipts if fact['timestamp'] == first_time), key=_canonical)
    result = dict(booking, reserved_on=first[0]['card_day'], booking_card_day=first[0]['card_day'],
                  booking_date_status='FIRST_RECEIVED', booking_date_evidence=first)
    result['source_digests'] = sorted(set(booking['source_digests']) |
                                    {fact['source_digest'] for fact in receipts})
    result['digest'] = hashlib.sha256(_canonical({'booking_digest': booking['digest'],
        'status': 'FIRST_RECEIVED', 'facts': first, 'source_digests': result['source_digests']}).encode()).hexdigest()
    return result

def strip_invisible(text: str) -> str:
    return text.translate(_INVISIBLE)


def _flight_tokens(text):
    # Some archived text parts flatten every HTML block onto one line. Split only
    # explicit provider labels; never infer names or dates from nearby prose.
    text = strip_invisible(text)
    text = re.sub(r"예약번호\s*[:：]?\s*(\d(?:[\d ]*\d)?)",
                  lambda m: '\n예약번호\n' + m[1] + '\n', text)
    text = _INLINE_HEADER.sub(lambda m: '\n' + m[1] + '\n', text)
    text = _INLINE_PASSENGER.sub(
        lambda m: '\n' + m[1].strip() + '\n(성)\n' + m[2].strip() + '\n(이름)\n', text)
    text = text.replace('규정 조회', '\n규정 조회')
    tokens = [" ".join(line.split()) for line in text.splitlines()]
    return [token for token in tokens if token]


def parse_flight_text(text: str) -> dict | None:
    tokens = _flight_tokens(text)
    passengers = _passengers(tokens)
    headers = [i for i, token in enumerate(tokens) if _HEADER.fullmatch(token)]
    cancellation_status = _cancellation_status(tokens)
    booking_ref = _booking_ref(tokens)
    reserved_on, booking_date_status, date_facts, card_day = _booking_date_details(tokens)
    # A date from a multi-booking message cannot be attributed to its first reference.
    refs = _booking_refs(tokens)
    # Some authenticated one-way notices use separate explicitly labeled
    # departure/arrival lines instead of an itinerary heading. Do not infer a
    # date from payment prose, multi-booking notices, or multi-leg layouts.
    departures = [t for t in tokens if re.match(r'^출발\s*[:：]\s*\d{4}년', t)]
    arrivals = [t for t in tokens if re.match(r'^도착\s*[:：]\s*\d{4}년', t)]
    labeled_departure = ''
    if (len(refs) == 1 and len(departures) == len(arrivals) == 1
            and tokens.index(departures[0]) < tokens.index(arrivals[0])
            and _TIME.search(departures[0]) and _TIME.search(arrivals[0])):
        departure_match, arrival_match = _DATE.search(departures[0]), _DATE.search(arrivals[0])
        departure_day = _date_on(departure_match.group()) if departure_match else ''
        arrival_day = _date_on(arrival_match.group()) if arrival_match else ''
        if departure_day and arrival_day and departure_day <= arrival_day:
            labeled_departure = departure_day
    if len(refs) > 1:
        reserved_on, booking_date_status, card_day = '', 'CONFLICT', ''
    if not passengers and not headers and not labeled_departure and (cancellation_status == "NONE" or not booking_ref):
        return None
    stops = headers + [i for i, token in enumerate(tokens) if "규정 조회" in token]
    stops += [i - 1 for i, token in enumerate(tokens) if token == "(성)" and i > 0]
    legs = []
    for h in headers:
        label, origin, destination, rest = _HEADER.fullmatch(tokens[h]).groups()
        date_text = (rest or "").strip()
        if not _DATE.match(date_text) and h + 1 < len(tokens):
            date_text = tokens[h + 1]
        end = min([s for s in stops if s > h] + [len(tokens)])
        legs.append({"label": label, "origin_city": origin, "destination_city": destination,
                     "departure_on": _date_on(date_text), "segments": _segments(tokens[h + 1:end])})
    return {"booking_ref": booking_ref, "passengers": passengers, "legs": legs,
            "reserved_on": reserved_on, "booking_date_status": booking_date_status,
            "booking_date_evidence": date_facts, "booking_card_day": card_day,
            "labeled_departure_on": labeled_departure,
            "cancellation_status": cancellation_status,
            "legs_complete": bool(legs) and all(leg["departure_on"] and leg["segments"] for leg in legs)}


def merge_booking_evidence(parts: list[dict]) -> dict:
    refs = {part["booking_ref"] for part in parts if part.get("booking_ref")}
    booking_ref = next((part["booking_ref"] for part in parts if part.get("booking_ref")), "")
    conflict = len(refs) > 1
    passengers, seen = [], set()
    for part in parts:
        for person in part.get("passengers", []):
            key = (person["surname"].casefold(), person["given_name"].casefold())
            if key not in seen:
                seen.add(key)
                passengers.append({"surname": person["surname"], "given_name": person["given_name"]})
    grouped = collections.defaultdict(list)
    for part in parts:
        for leg in part.get("legs", []):
            grouped[(leg["label"], leg["origin_city"], leg["destination_city"])].append(leg)
    legs = []
    for (label, origin, destination), versions in grouped.items():
        departures = {leg["departure_on"] for leg in versions if leg["departure_on"]}
        routes = {_canonical(leg["segments"]): leg["segments"] for leg in versions if leg["segments"]}
        conflict = conflict or len(departures) > 1 or len(routes) > 1
        legs.append({"label": label, "origin_city": origin, "destination_city": destination,
                     "departure_on": min(departures, default=""),
                     "segments": routes[min(routes)] if routes else []})
    labeled_dates = {part.get('labeled_departure_on') for part in parts if part.get('labeled_departure_on')}
    if len(labeled_dates) > 1:
        conflict = True
    elif labeled_dates:
        labeled_day = next(iter(labeled_dates))
        if legs:
            known_days = {leg['departure_on'] for leg in legs if leg['departure_on']}
            if known_days and labeled_day not in known_days:
                conflict = True
        else:
            legs.append({'label': '구간', 'origin_city': '', 'destination_city': '',
                         'departure_on': labeled_day, 'segments': []})
    legs.sort(key=_leg_order)
    legs_complete = bool(legs) and all(leg["departure_on"] and leg["segments"] for leg in legs)
    # Conflicting explicit dates, or one ambiguous source, must never auto-select a day.
    confirmed_days = {part.get("reserved_on") for part in parts if part.get("reserved_on")}
    booking_date_conflict = (len(confirmed_days) > 1 or any(
        part.get("booking_date_status") == "CONFLICT" for part in parts))
    reserved_on = next(iter(confirmed_days)) if len(confirmed_days) == 1 and not booking_date_conflict else ""
    booking_date_status = ("CONFLICT" if booking_date_conflict else
                           "EXPLICIT_LABEL" if reserved_on else "UNKNOWN")
    date_facts = [dict(fact, source_digest=part.get('source_digest', ''))
                  for part in parts for fact in part.get('booking_date_evidence', [])]
    card_days = {part['booking_card_day'] for part in parts if part.get('booking_card_day')}
    card_day = next(iter(card_days)) if len(card_days) == 1 and not booking_date_conflict and not conflict else ''
    if len(card_days) > 1:
        booking_date_status, reserved_on = 'CONFLICT', ''
    source_digests = sorted({part["source_digest"] for part in parts if part.get("source_digest")})
    cancellation_states = {part.get("cancellation_status", "NONE") for part in parts}
    cancellation_status = ("CONFLICT" if "CANCELLED" in cancellation_states and "NONE" in cancellation_states
                           or "CONFLICT" in cancellation_states else
                           "CANCELLED" if "CANCELLED" in cancellation_states else "NONE")
    # Cache invalidation and evidence identity are separate. Preserve the old
    # digest for bookings whose parsed facts have not changed.
    digest_body = {"v": "flight-evidence-v5-flat-layout",
                   "passengers": sorted([p["surname"].casefold(), p["given_name"].casefold()] for p in passengers),
                   "legs": legs, "source_digests": source_digests,
                   "cancellation_status": cancellation_status, "conflict": conflict,
                   "reserved_on": reserved_on, "booking_date_status": booking_date_status,
                   "booking_date_evidence": sorted(date_facts, key=_canonical), "booking_card_day": card_day}
    return {"booking_ref": booking_ref, "passengers": passengers, "legs": legs,
            "legs_complete": legs_complete, "conflict": conflict, "source_digests": source_digests,
            "cancellation_status": cancellation_status,
            "reserved_on": reserved_on, "booking_date_status": booking_date_status,
            "booking_date_evidence": date_facts, "booking_card_day": card_day,
            "digest": hashlib.sha256(_canonical(digest_body).encode("utf-8")).hexdigest()}


def _cancellation_status(tokens):
    subject = " ".join(tokens[:5]).casefold()
    lines = [line.casefold() for line in tokens]
    policy = re.compile(r"(?:완료|요청)\s*(?:되면|될\s*경우|시|할\s*경우)|요청\s*시")
    lines = [line for line in lines if not policy.search(line)]
    body = " ".join(lines)
    if (re.search(r"booking\s+cancellation\s+confirmed", subject)
            or re.search(r"예약\s*취소(?:가)?\s*(?:완료(?:되었습니다|됐습니다)|되었습니다|됐습니다)", body)
            or "예약 취소 완료" in body or "예약이 취소되었습니다" in body):
        return "CANCELLED"
    if (re.search(r"booking\s+cancellation\s+(?:requested|request received)", subject)
            or re.search(r"취소\s*(?:요청이\s*)?(?:접수|완료|되었습니다|됐습니다)", body)):
        return "CONFLICT"
    return "NONE"


def collect_flight_evidence(mail_directories) -> dict:
    directories = ota_mail.as_directories(mail_directories)
    try:
        from app import ota_sources
        stamps = json.dumps(ota_sources.mail_stamps(directories), sort_keys=True)
    except (ImportError, AttributeError):
        stamps = None
    memo_key = (tuple(str(directory) for directory in directories), stamps)
    if stamps is not None and memo_key in _MEMO:
        return copy.deepcopy(_MEMO[memo_key])
    messages, _inventory = ota_mail.load_messages_from(directories)
    trip_domains = tuple(domain for bases in PROVIDER_DOMAINS.values() for domain in bases)
    grouped = collections.defaultdict(list)
    receipts = collections.defaultdict(list)
    for message_id, message in messages.items():
        authenticated = ota_mail.authenticated_headers(message, trip_domains)
        if not authenticated:
            continue
        provider = next(name for name, bases in PROVIDER_DOMAINS.items() if authenticated[1] in bases)
        subject = str((authenticated[0] or {}).get("subject") or "")
        body_text = ota_mail.message_text(message)
        source_digest = hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()
        if provider in ('asiana', 'skyticket'):
            from app import airline_payment_mail
            payment = airline_payment_mail.extract(message)
            cancelled = airline_payment_mail.cancellation_references(message)
            references = ({payment['booking_ref']} if payment else
                          {ref for name, ref in cancelled if name == provider})
            received = _received_fact(message, source_digest)
            period = payment.get('period') if payment else None
            dates = (payment or {}).get('reserved_dates', [])
            date_status = 'CONFLICT' if len(dates) > 1 else 'EXPLICIT_LABEL' if dates else 'UNKNOWN'
            for ref in references:
                if received:
                    receipts[(provider, ref)].append(received)
                grouped[(provider, ref)].append({
                    'booking_ref': ref, 'passengers': [], 'legs': [],
                    'reserved_on': dates[0] if len(dates) == 1 else '', 'booking_date_status': date_status,
                    'booking_date_evidence': ([{'source_date': dates[0], 'timezone': 'GMT',
                                               'meaning': 'explicit_booking_created_label'}]
                                              if len(dates) == 1 else []), 'booking_card_day': '',
                    'labeled_departure_on': (period or {}).get('starts_on', ''),
                    'cancellation_status': 'CONFLICT' if cancelled else 'NONE',
                    'source_digest': source_digest,
                })
            continue
        refs = _booking_refs(_flight_tokens(body_text))
        fact = _received_fact(message, source_digest)
        if len(refs) == 1 and fact:
            receipts[(provider, next(iter(refs)))].append(fact)
        parsed = parse_flight_text("Subject: " + subject + "\n" + body_text)
        if parsed:
            subject_status = _cancellation_status(["Subject: " + subject])
            if subject_status != "NONE":
                parsed["cancellation_status"] = subject_status
        if not parsed or not parsed["booking_ref"]:
            continue
        parsed["source_digest"] = source_digest
        grouped[(provider, parsed["booking_ref"])].append(parsed)
    result = {group_key: _with_first_received_day(merge_booking_evidence(parts), receipts[group_key])
              for group_key, parts in grouped.items()}
    if stamps is not None:
        _MEMO.clear()
        _MEMO[memo_key] = result
    return copy.deepcopy(result)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _leg_order(leg):
    return (leg["label"], leg["departure_on"], _canonical(leg))


def _passengers(tokens):
    people, seen = [], set()
    for index, token in enumerate(tokens):
        if token != "(성)" or index < 1 or index + 2 >= len(tokens) or tokens[index + 2] != "(이름)":
            continue
        surname, given = tokens[index - 1], tokens[index + 1]
        if not (_NAME.fullmatch(surname) and _NAME.fullmatch(given)):
            continue
        key = (surname.casefold(), given.casefold())
        if key not in seen:
            seen.add(key)
            people.append({"surname": surname, "given_name": given})
    return people


def _booking_ref(tokens):
    for index, token in enumerate(tokens):
        if not token.startswith("예약번호"):
            continue
        rest = token[len("예약번호"):].lstrip(" :：|")
        candidate = rest or (tokens[index + 1] if index + 1 < len(tokens) else "")
        match = re.match(r"\d(?:[\d ]*\d)?", candidate)
        if match:
            return match.group(0).replace(" ", "")
    return ""


def _date_on(text):
    match = _DATE.match(text.strip())
    if not match or not match.group(1):
        return ""
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return ""


def _segments(block):
    points = [(m[1], m[2]) for m in re.finditer(
        r"(?<![\d:])(\d{1,2}:\d{2})\s*([A-Z]{3})(?![A-Za-z])", '\n'.join(block))]
    flights = []
    for token in block:
        if _FLIGHT.fullmatch(token):
            flights.append(token.replace(' ', ''))
        else:
            # Seat-class delimiters identify the flight field without treating
            # aircraft model numbers as flight numbers in flattened mail.
            flights.extend(m[1].replace(' ', '') for m in _INLINE_FLIGHT.finditer(token)
                           if any(ch.isalpha() for ch in m[1][:2]))
    if len(points) == 2 and len(flights) == 1:
        pairs = [(0, 1, 0)]
    elif len(points) >= 4 and len(points) % 2 == 0 and len(flights) == len(points) // 2:
        pairs = [(k, k + 1, k // 2) for k in range(0, len(points), 2)]
    else:
        return []
    return [{"departure_time": points[d][0], "departure_airport": points[d][1],
             "arrival_time": points[a][0], "arrival_airport": points[a][1],
             "flight_number": flights[f]} for d, a, f in pairs]
