"""Trip.com 항공 메일 본문에서 승객·여정 근거만 읽는다. 가이드 여부는 정하지 않는다."""
import collections
import copy
import datetime
import hashlib
import json
import re

from app import ota_mail


PARSER_VERSION = "flight-evidence-v2"
PROVIDER_DOMAINS = {"trip": ("trip.com", "trip.co.kr")}

_INVISIBLE = dict.fromkeys([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, *range(0x202A, 0x202F)])
_HEADER = re.compile(r"(가는편|오는편|\d구간|여정\s*\d)\s*:\s*(.+?)\s*-\s*(.+?)\s*(?:\|(.*))?")
_DATE = re.compile(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일")
_NAME = re.compile(r"[A-Za-z가-힣][A-Za-z가-힣 .'\-]*")
_TIME = re.compile(r"\d{1,2}:\d{2}")
_IATA = re.compile(r"[A-Z]{3}(?![A-Za-z])")
_FLIGHT = re.compile(r"[A-Z0-9]{2}\s?\d{1,4}")
_MEMO = {}


def strip_invisible(text: str) -> str:
    return text.translate(_INVISIBLE)


def parse_flight_text(text: str) -> dict | None:
    tokens = [" ".join(line.split()) for line in strip_invisible(text).splitlines()]
    tokens = [token for token in tokens if token]
    passengers = _passengers(tokens)
    headers = [i for i, token in enumerate(tokens) if _HEADER.fullmatch(token)]
    cancellation_status = _cancellation_status(tokens)
    booking_ref = _booking_ref(tokens)
    if not passengers and not headers and (cancellation_status == "NONE" or not booking_ref):
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
    legs.sort(key=_leg_order)
    legs_complete = bool(legs) and all(leg["departure_on"] and leg["segments"] for leg in legs)
    source_digests = sorted({part["source_digest"] for part in parts if part.get("source_digest")})
    cancellation_states = {part.get("cancellation_status", "NONE") for part in parts}
    cancellation_status = ("CONFLICT" if "CANCELLED" in cancellation_states and "NONE" in cancellation_states
                           or "CONFLICT" in cancellation_states else
                           "CANCELLED" if "CANCELLED" in cancellation_states else "NONE")
    digest_body = {"v": PARSER_VERSION,
                   "passengers": sorted([p["surname"].casefold(), p["given_name"].casefold()] for p in passengers),
                   "legs": legs, "source_digests": source_digests,
                   "cancellation_status": cancellation_status, "conflict": conflict}
    return {"booking_ref": booking_ref, "passengers": passengers, "legs": legs,
            "legs_complete": legs_complete, "conflict": conflict, "source_digests": source_digests,
            "cancellation_status": cancellation_status,
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
    for message_id, message in messages.items():
        authenticated = ota_mail.authenticated_headers(message, trip_domains)
        if not authenticated:
            continue
        provider = next(name for name, bases in PROVIDER_DOMAINS.items() if authenticated[1] in bases)
        subject = str((authenticated[0] or {}).get("subject") or "")
        body_text = ota_mail.message_text(message)
        parsed = parse_flight_text("Subject: " + subject + "\n" + body_text)
        if parsed:
            subject_status = _cancellation_status(["Subject: " + subject])
            if subject_status != "NONE":
                parsed["cancellation_status"] = subject_status
        if not parsed or not parsed["booking_ref"]:
            continue
        parsed["source_digest"] = hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()
        grouped[(provider, parsed["booking_ref"])].append(parsed)
    result = {group_key: merge_booking_evidence(parts) for group_key, parts in grouped.items()}
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
    points, flights = [], []
    index = 0
    while index < len(block):
        token = block[index]
        iata = _IATA.match(block[index + 1]) if index + 1 < len(block) and _TIME.fullmatch(token) else None
        if iata:
            points.append((token, iata.group(0)))
            index += 2
            continue
        if _FLIGHT.fullmatch(token):
            flights.append(token.replace(" ", ""))
        index += 1
    if len(points) == 2 and len(flights) == 1:
        pairs = [(0, 1, 0)]
    elif len(points) >= 4 and len(points) % 2 == 0 and len(flights) == len(points) // 2:
        pairs = [(k, k + 1, k // 2) for k in range(0, len(points), 2)]
    else:
        return []
    return [{"departure_time": points[d][0], "departure_airport": points[d][1],
             "arrival_time": points[a][0], "arrival_airport": points[a][1],
             "flight_number": flights[f]} for d, a, f in pairs]
