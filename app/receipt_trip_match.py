"""Find the trip a receipt belongs to from the trip name printed at the top of the photo (RCPT-030)."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

HEADER_TOP_FRACTION = 0.2
MAX_HEADER_CHARS = 500
_NAME = re.compile(r'^(\d{4})_?(.*)$')
_MMDD = (re.compile(r'(?<!\d)(\d{1,2})\s*[/.\-월]\s*(\d{1,2})(?!\d)'), re.compile(r'(?<!\d)(\d{2})(\d{2})(?!\d)'))


def normalize(text) -> str:
    """Width, case, spaces, underscores and punctuation do not matter: '０６２５ _ 아키타' equals '0625아키타'."""
    text = unicodedata.normalize('NFKC', text if isinstance(text, str) else '').casefold()
    return ''.join(ch for ch in text if ch.isalnum())


def header_lines(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        value = '\n'.join(str(item) for item in value if isinstance(item, str))
    if not isinstance(value, str):
        return []
    return [line.strip() for line in value[:MAX_HEADER_CHARS].splitlines() if line.strip()][:8]


def top_lines(lines, fraction: float = HEADER_TOP_FRACTION) -> list[str]:
    """The OCR lines that start in the upper part of the picture, in reading order."""
    picked = []
    for line in lines or []:
        top = line.get('top') if isinstance(line, dict) else None
        text = line.get('text') if isinstance(line, dict) else None
        if isinstance(text, str) and type(top) in (int, float) and 0 <= top < fraction and text.strip():
            picked.append(text.strip())
    return picked


def _display(trip: dict) -> str:
    name = str(trip.get('name') or trip.get('id') or '')
    qualified = re.fullmatch(r'andre::\d{4}::(.+)', name)
    return qualified[1] if qualified else name


def _parts(trip: dict) -> tuple[str, str]:
    match = _NAME.match(_display(trip))
    if match:
        return match[1], normalize(match[2]) or normalize(trip.get('destination'))
    return '', normalize(trip.get('destination')) or normalize(_display(trip))


def _mmdd(line: str) -> set[str]:
    text = unicodedata.normalize('NFKC', line)
    found = set()
    for pattern in _MMDD:
        for month, day in pattern.findall(text):
            if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
                found.add(f'{int(month):02d}{int(day):02d}')
    return found


def _names_place(line: str, destination: str) -> bool:
    """The place starts a word of the line: 오사카시 names 오사카, 히가시오사카 does not."""
    words = [re.sub(r'^\d+', '', normalize(word)) for word in re.split(r'[\W_]+', unicodedata.normalize('NFKC', line))]
    words = [word for word in words if word]
    return any(''.join(words[i:]).startswith(destination) for i in range(len(words)))


def match_header(value, trips: list[dict], *, require_date: bool = False) -> dict:
    """{'raw', 'ids', 'exact'}: the trips whose destination is written in the header.

    exact means the trip's MMDD is written too. require_date keeps only those (text read by OCR,
    where the top lines may be the store's own name and address).
    """
    hits: dict[str, tuple[str, bool, str]] = {}
    for line in header_lines(value):
        dates = _mmdd(line)
        for trip in trips:
            prefix, destination = _parts(trip)
            if len(destination) < 2 or not _names_place(line, destination):
                continue
            exact = bool(prefix) and prefix in dates
            if trip['id'] not in hits or (exact and not hits[trip['id']][1]):
                hits[trip['id']] = (line, exact, destination)
    # A longer place name wins over a name inside it: 신도쿄 is not 도쿄.
    for a, (_, _, dest_a) in list(hits.items()):
        if any(dest_a != dest_b and dest_a in dest_b for _, _, dest_b in hits.values()):
            del hits[a]
    exact_ids = [key for key, (_, exact, _) in hits.items() if exact]
    ids = exact_ids if exact_ids or require_date else list(hits)
    return {'raw': hits[ids[0]][0] if ids else '', 'ids': ids, 'exact': bool(exact_ids)}


def _period(trip: dict, trips: list[dict]) -> tuple[str, str]:
    start, end = str(trip.get('starts_on') or ''), str(trip.get('ends_on') or '')
    if start and not end:
        later = sorted(str(t['starts_on']) for t in trips if str(t.get('starts_on') or '') > start)
        if later:
            end = (dt.date.fromisoformat(later[0]) - dt.timedelta(days=1)).isoformat()
        else:
            end = start
    return start, end


def _in_period(trip: dict, date: str, trips: list[dict]) -> bool:
    start, end = _period(trip, trips)
    return bool(start and date and start <= date <= end)


def decide(header: dict, date: str | None, trips: list[dict]) -> dict:
    """{'trip_id', 'source', 'raw'}: header name first, then the receipt date. Nothing is guessed beyond them.

    A header with only the place name does not win over the receipt date: when the date lies
    outside that trip, the receipt stays unassigned.
    """
    ids, raw = header['ids'], header['raw']
    if len(ids) == 1:
        trip = next(t for t in trips if t['id'] == ids[0])
        if header.get('exact') or not date or _in_period(trip, date, trips):
            return {'trip_id': ids[0], 'source': 'header_text', 'raw': raw}
        return {'trip_id': '', 'source': '', 'raw': raw}
    pool = [t for t in trips if t['id'] in ids] if ids else trips
    by_date = [t['id'] for t in pool if _in_period(t, date or '', trips)]
    if len(by_date) == 1:
        return {'trip_id': by_date[0], 'source': 'date', 'raw': raw}
    return {'trip_id': '', 'source': '', 'raw': raw}


def is_header_text(merchant, header_value, trips: list[dict]) -> bool:
    """True when a merchant reading is really the trip title line, so it is not a store name."""
    text = normalize(merchant)
    if not text:
        return False
    if any(normalize(line) == text for line in header_lines(header_value)):
        return True
    for trip in trips:
        prefix, destination = _parts(trip)
        if prefix and destination and text == prefix + destination:
            return True
    return False
