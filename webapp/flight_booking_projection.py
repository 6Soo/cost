"""Pure read projection, normalization, and query helpers for flight bookings.

Extracted responsibilities from flight booking index:
- resolve_flight_sources_key: Compute canonical snapshot digest key for mail directories
- load_cached_passenger_data: Validate and load passenger cache from disk
- normalize_name_tokens: NFKC-normalized alphanumeric token set for passenger name search
- project_itinerary_leg: Clean projection of flights, airports, and departure facts
- project_booking_reservation: Pure DTO for a verified booking reservation with dates and flags
- query_booking_reservations: Filter, project, sort, and paginate reservations by passenger name

Strictly read-only and in-memory:
- No database writes, network calls, or direct filesystem collection
- Preserves date priorities (EXPLICIT_LABEL > FIRST_RECEIVED > CONFLICT/UNKNOWN)
- Preserves cancellation status, conflict status, and source digest lineage
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import unicodedata


def resolve_flight_sources_key(sources: Mapping[str, Any], *, parser_version: str | None = None) -> str:
    """Compute snapshot key for flight mail sources, failing closed if directories missing."""
    from app import flight_evidence, ota_sources
    from . import ota_snapshot

    directories = sources.get('mail_directories') or []
    if not directories or any(not Path(p).exists() for p in directories):
        raise ValueError('FLIGHT_MAIL_UNAVAILABLE')
    version = parser_version or flight_evidence.PARSER_VERSION
    return ota_snapshot.digest({
        'parser': version,
        'directories': list(map(str, directories)),
        'mail': ota_sources.mail_stamps(directories),
    })


def load_cached_passenger_data(
    cache_path: Path,
    *,
    expected_key: str,
    schema: str,
    parser_version: str,
) -> dict[str, Any] | None:
    """Load cached passenger dictionary if schema, parser version, and source key match."""
    try:
        saved = json.loads(cache_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if (saved.get('schema') == schema and saved.get('key') == expected_key
            and saved.get('parser') == parser_version
            and isinstance(saved.get('passengers'), dict)):
        return saved['passengers']
    return None


def normalize_name_tokens(value: object) -> tuple[str, ...]:
    """Only normalize spelling and token order, never infer Korean transliteration."""
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    tokens = [''.join(ch for ch in part if ch.isalnum()) for part in text.replace('/', ' ').replace(',', ' ').split()]
    return tuple(sorted(token for token in tokens if token))


def project_itinerary_leg(leg: Mapping[str, Any]) -> dict[str, Any]:
    """Project single itinerary leg with flight segments."""
    projected = {key: leg.get(key) for key in ('label', 'origin_city', 'destination_city', 'departure_on')}
    projected['segments'] = [{key: segment.get(key) for key in
        ('flight_number', 'departure_airport', 'departure_time', 'arrival_airport', 'arrival_time')}
        for segment in leg.get('segments') or []]
    return projected


def project_booking_reservation(
    booking_ref: str,
    evidence: Mapping[str, Any],
    passenger_name: str,
    *,
    linked_cards: Sequence[Mapping[str, Any]] | None = None,
    provider: str = 'trip',
) -> dict[str, Any]:
    """Project verified booking evidence into canonical reservation DTO.

    Preserves explicit dates and FIRST_RECEIVED KST dates, while blanking out
    dates during CONFLICT or UNKNOWN statuses.
    """
    legs = [project_itinerary_leg(leg) for leg in evidence.get('legs') or []]
    booking_date_status = evidence.get('booking_date_status', 'UNKNOWN')
    date_verified = booking_date_status in ('EXPLICIT_LABEL', 'FIRST_RECEIVED')
    return {
        'booking_ref': str(booking_ref),
        'passenger_name': passenger_name,
        'legs': legs,
        'cancelled': evidence.get('cancellation_status', 'NONE') != 'NONE',
        'conflict': bool(evidence.get('conflict')),
        'source_verified': True,
        'linked_cards': list(linked_cards or []),
        'provider': provider,
        'reserved_on': evidence.get('reserved_on') if date_verified else '',
        'booking_card_day': evidence.get('booking_card_day') if date_verified else '',
        'booking_date_evidence': evidence.get('booking_date_evidence', []),
        'booking_date_status': booking_date_status,
    }


def query_booking_reservations(
    index: Mapping[str, Any],
    query_name: str,
    *,
    cards: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    offset: int = 0,
    limit: int = 100,
    revision: str | None = None,
    fallback_status: str = 'UNAVAILABLE',
) -> dict[str, Any]:
    """Filter, project, sort, and paginate verified reservations matching name tokens."""
    query = normalize_name_tokens(query_name)
    if not query:
        raise ValueError('INVALID_NAME')
    if type(offset) is not int or offset < 0 or offset > 1000000 or (offset and not revision):
        raise ValueError('INVALID_CURSOR')

    cards = cards or {}
    results = []
    fingerprints = []
    for booking_ref, evidence in (index or {}).items():
        if not isinstance(evidence, dict) or not evidence.get('source_digests'):
            continue
        passengers = evidence.get('passengers') or []
        for person in passengers:
            if not isinstance(person, dict):
                continue
            full_name = ' '.join((str(person.get('surname') or ''), str(person.get('given_name') or ''))).strip()
            original_name_tokens = normalize_name_tokens(full_name)
            if any(token not in original_name_tokens for token in query):
                continue
            linked = cards.get(str(booking_ref), [])
            reservation = project_booking_reservation(booking_ref, evidence, full_name, linked_cards=linked)
            results.append(reservation)
            fingerprints.append((str(booking_ref), evidence.get('digest'), evidence.get('source_digests')))
            break

    results.sort(key=lambda row: row['booking_ref'])
    results.sort(key=lambda row: max((leg.get('departure_on') or '' for leg in row['legs']), default=''), reverse=True)
    current_revision = hashlib.sha256(json.dumps([sorted(fingerprints), results],
        sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()

    if revision is not None and revision != current_revision:
        raise LookupError('SOURCE_CHANGED')

    end = offset + limit
    has_verified = any(isinstance(row, dict) and row.get('source_digests') for row in (index or {}).values())
    status = 'VERIFIED' if has_verified else fallback_status
    return {
        'reservations': results[offset:end],
        'truncated': len(results) > end,
        'next_offset': end if len(results) > end else None,
        'total': len(results),
        'revision': current_revision,
        'source_status': status,
    }
