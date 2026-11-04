"""Read-only search of evidenced flight routes and inclusive journey dates."""
from __future__ import annotations

from datetime import date
import re
import unicodedata

# Search aliases only; never change itinerary or passenger evidence.
_AIRPORT_ALIASES = (
    frozenset(('fsz', '시즈오카', 'shizuoka')),
    frozenset(('fuk', '후쿠오카', 'fukuoka')),
)
_DATE_QUERY = re.compile(
    r'(?<!\w)(?:(?P<year>\d{4})\s*(?:[-/.]|년)\s*)?'
    r'(?P<month>\d{1,2})\s*(?:[-/.]|월)\s*(?P<day>\d{1,2})(?:일)?(?!\w)'
    r'|(?<!\w)(?P<day_only>\d{1,2})일(?!\w)')


def parse_search(value, name_key_fn):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    dates = []

    def consume(match):
        year = int(match['year']) if match['year'] else None
        month = int(match['month']) if match['month'] else None
        day = int(match['day'] or match['day_only'])
        try:
            date(year if year is not None else 2000, month if month is not None else 1, day)
        except ValueError:
            raise ValueError('INVALID_NAME') from None
        dates.append((year, month, day))
        return ' '

    words = name_key_fn(_DATE_QUERY.sub(consume, text))
    if not words and not dates:
        raise ValueError('INVALID_NAME')
    return words, tuple(dates)


def _journey_dates(evidence):
    days = []
    for leg in evidence.get('legs') or []:
        try:
            days.append(date.fromisoformat(leg.get('departure_on') or ''))
        except (TypeError, ValueError):
            continue
    return sorted(set(days))


def _date_in_range(criteria, start, end):
    year, month, day = criteria
    # Up to eight years cover leap days even across a non-leap century.
    years = (year,) if year is not None else range(start.year, min(end.year, start.year + 8) + 1)
    for candidate_year in years:
        for candidate_month in ((month,) if month is not None else range(1, 13)):
            try:
                candidate = date(candidate_year, candidate_month, day)
            except ValueError:
                continue
            if start <= candidate <= end:
                return True
    return False


def matches_dates(evidence, criteria):
    if not criteria:
        return True
    days = _journey_dates(evidence)
    if not days:
        return False
    # Conflicting evidence matches stated dates only; do not infer a stay.
    intervals = [(day, day) for day in days] if evidence.get('conflict') else [(days[0], days[-1])]
    return all(any(_date_in_range(item, start, end) for start, end in intervals) for item in criteria)


def route_tokens(evidence, name_key_fn):
    values = []
    for leg in evidence.get('legs') or []:
        values.extend(leg.get(key) for key in ('origin_city', 'destination_city'))
        for segment in leg.get('segments') or []:
            values.extend(segment.get(key) for key in ('departure_airport', 'arrival_airport'))
    tokens = set(name_key_fn(' '.join(str(value or '') for value in values)))
    for aliases in _AIRPORT_ALIASES:
        if tokens.intersection(aliases):
            tokens.update(aliases)
    return tokens


def matches_words(words, passenger_tokens, locations):
    return all(word in passenger_tokens or word in locations or
               any(word in place for place in locations if len(word) >= 2 and not word.isascii())
               for word in words)
