"""Rules used when exporting the event-year/manual-ledger result.

These rules are deliberately kept outside the classifier.  They select rows for
the requested reporting workbook without changing candidate decisions or the
Gate5 candidate database.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence


ALLOWED_EVENT_YEARS = frozenset({2026, 2027})

# A country suffix is removed only when it is at the end of the merchant name.
# City tokens are removed only as the immediately preceding token, so a genuine
# merchant name containing a city in the middle is preserved.
COUNTRY_SUFFIXES = (
    "JPN|JAPAN|JP|KOR|KOREA|KR|CHN|CHINA|CN|TWN|TAIWAN|TW|SGP|SINGAPORE|SG|"
    "THA|THAILAND|TH|VNM|VIETNAM|VN|IDN|INDONESIA|ID|MYS|MALAYSIA|MY|"
    "PHL|PHILIPPINES|PH|USA|UNITED STATES|US|CAN|CANADA|CA|AUS|AUSTRALIA|AU|"
    "GBR|UNITED KINGDOM|UK|GB|FRA|FRANCE|FR|DEU|GERMANY|DE|ITA|ITALY|IT|"
    "ESP|SPAIN|ES|NLD|NETHERLANDS|NL|CHE|SWITZERLAND|CH|AUT|AUSTRIA|AT|"
    "NZL|NEW ZEALAND|NZ|HKG|HONG KONG|HK|IND|INDIA|IN|"
    "MEX|MEXICO|MX|BRA|BRAZIL|BR"
).split("|")

CITY_SUFFIXES = (
    "TOKYO|OSAKA|KYOTO|NAGOYA|SAPPORO|FUKUOKA|NIIGATA|NARA|KOBE|HIROSHIMA|"
    "AOMORI|AKITA|MORIOKA|SENDAI|TAKAMATSU|MATSUYAMA|KOCHI|OKAYAMA|KAGAWA|"
    "TAIPEI|TAICHUNG|KAOHSIUNG|SINGAPORE|BANGKOK|HANOI|HO CHI MINH|"
    "AMSTERDAM|PARIS|LONDON|ROME|MILAN|MUNICH|FRANKFURT|BARCELONA|"
    "NEW YORK|LOS ANGELES|SAN FRANCISCO|VANCOUVER|TORONTO|SYDNEY|MELBOURNE"
).split("|")

_COUNTRY_RE = "(?:" + "|".join(re.escape(item) for item in COUNTRY_SUFFIXES) + ")"
_CITY_RE = "(?:" + "|".join(re.escape(item) for item in CITY_SUFFIXES) + ")"
_CITY_COUNTRY_SUFFIX_RE = re.compile(
    rf"(?:\s+{_CITY_RE})?\s+{_COUNTRY_RE}$", re.IGNORECASE
)
_COUNTRY_ONLY_SUFFIX_RE = re.compile(rf"\s+{_COUNTRY_RE}$", re.IGNORECASE)

_TARGET_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])((?:0[1-9]|[12]\d|3[01]))(?!\d)"
)

_EVIDENCE_START_KEYS = {
    "service_start_on",
    "service_start",
    "event_start_on",
    "event_start",
    "checkin",
    "check_in",
    "check_in_on",
    "arrival_on",
    "visit_on",
    "service_date",
    "event_date",
    "event_day",
}
_EVIDENCE_END_KEYS = {
    "service_end_on",
    "service_end",
    "event_end_on",
    "event_end",
    "checkout",
    "check_out",
    "check_out_on",
    "departure_on",
}


@dataclass(frozen=True)
class EventPeriod:
    """The event/service period used for output selection."""

    starts_on: date | None
    ends_on: date | None
    source: str
    target: str
    reason: str

    @property
    def event_years(self) -> frozenset[int]:
        if self.starts_on is None or self.ends_on is None:
            return frozenset()
        return frozenset(range(self.starts_on.year, self.ends_on.year + 1))

    @property
    def eligible(self) -> bool:
        return bool(self.event_years & ALLOWED_EVENT_YEARS)

    @property
    def display(self) -> str:
        if self.starts_on is None or self.ends_on is None:
            return ""
        if self.starts_on == self.ends_on:
            return self.starts_on.isoformat()
        return f"{self.starts_on.isoformat()}~{self.ends_on.isoformat()}"


def normalize_merchant_name(value: object) -> str:
    """Normalize a merchant for the manual-ledger ``항목`` column.

    The original merchant is retained in the audit columns.  This function
    removes only terminal country/location metadata such as ``TOKYO JP`` and
    collapses trailing or repeated whitespace.
    """

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    # A separator immediately before a suffix is metadata punctuation, not part
    # of the merchant name.  Keep ordinary hyphens inside the merchant intact.
    text = re.sub(r"\s*[,|·]+\s*$", "", text).strip()
    previous = None
    while text and text != previous:
        previous = text
        city_country = _CITY_COUNTRY_SUFFIX_RE.search(text)
        if city_country is not None and text[: city_country.start()].strip():
            text = text[: city_country.start()].strip()
        text = _COUNTRY_ONLY_SUFFIX_RE.sub("", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def split_targets(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _as_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _period_from_values(start: object, end: object) -> tuple[date, date] | None:
    starts_on = _as_date(start)
    ends_on = _as_date(end) or starts_on
    if starts_on is None or ends_on is None:
        return None
    if ends_on < starts_on:
        starts_on, ends_on = ends_on, starts_on
    return starts_on, ends_on


def target_date_period(target: str) -> tuple[date, date] | None:
    match = _TARGET_DATE_RE.search(target)
    if match is None:
        return None
    day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return day, day


def _collect_evidence_dates(payload: object) -> tuple[list[date], list[date]]:
    starts: list[date] = []
    ends: list[date] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).lower()
            parsed = _as_date(value)
            if parsed is not None:
                if key_text in _EVIDENCE_START_KEYS:
                    starts.append(parsed)
                elif key_text in _EVIDENCE_END_KEYS:
                    ends.append(parsed)
            else:
                nested_starts, nested_ends = _collect_evidence_dates(value)
                starts.extend(nested_starts)
                ends.extend(nested_ends)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            nested_starts, nested_ends = _collect_evidence_dates(item)
            starts.extend(nested_starts)
            ends.extend(nested_ends)
    return starts, ends


def evidence_date_period(payloads: Sequence[object]) -> tuple[date, date] | None:
    starts: list[date] = []
    ends: list[date] = []
    for payload in payloads:
        payload_starts, payload_ends = _collect_evidence_dates(payload)
        starts.extend(payload_starts)
        ends.extend(payload_ends)
    if not starts and not ends:
        return None
    first = min(starts or ends)
    last = max(ends or starts)
    if last < first:
        first, last = last, first
    return first, last


def _registry_period(
    target: str,
    registries: Mapping[str, Sequence[tuple[object, object]]],
) -> tuple[date, date] | None:
    periods = [_period_from_values(start, end) for start, end in registries.get(target, ())]
    valid = [period for period in periods if period is not None]
    if not valid:
        return None
    return min(item[0] for item in valid), max(item[1] for item in valid)


def event_period_for_targets(
    target_value: object,
    *,
    trips: Mapping[str, tuple[object, object]],
    registries: Mapping[str, Sequence[tuple[object, object]]],
    evidence_payloads: Sequence[object] = (),
    allow_registry: bool = False,
    allow_target_code_date: bool = False,
) -> EventPeriod:
    """Resolve a period without falling back to payment/posting dates.

    Canonical trip schedules take precedence.  Provisional registry windows and
    dates embedded in temporary target codes are *not* event dates by default:
    callers must explicitly opt into those weaker sources.  This prevents a
    bounded card-use window or an ``행사기간미상`` placeholder from being
    silently presented as an event/service period.
    """

    targets = split_targets(target_value)
    for target in targets:
        period = _period_from_values(*(trips[target])) if target in trips else None
        if period is not None:
            return EventPeriod(*period, "trip_schedule", target, "canonical_trip_schedule")

    if allow_registry:
        for target in targets:
            period = _registry_period(target, registries)
            if period is not None:
                return EventPeriod(*period, "trip_registry", target, "provisional_registry_window")

    evidence_period = evidence_date_period(evidence_payloads)
    if evidence_period is not None:
        return EventPeriod(
            *evidence_period,
            "service_evidence",
            targets[0] if targets else "",
            "explicit_service_or_event_date_evidence",
        )

    if allow_target_code_date:
        for target in targets:
            period = target_date_period(target)
            if period is not None:
                return EventPeriod(*period, "target_code_date", target, "date_embedded_in_target_code")

    return EventPeriod(None, None, "none", targets[0] if targets else "", "event_period_unavailable")


def event_year_label(period: EventPeriod) -> str:
    years = sorted(period.event_years & ALLOWED_EVENT_YEARS)
    return ",".join(str(year) for year in years)
