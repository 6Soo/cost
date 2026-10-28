"""Authenticated booking evidence, independently refreshed from financial matching."""
import atexit
import json
import os
from pathlib import Path
from threading import Lock

from app import flight_evidence, ota_sources
from . import flight_booking_projection, ota_snapshot

# Facade re-exports of pure projection, normalization, and query helpers
from .flight_booking_projection import (
    load_cached_passenger_data,
    normalize_name_tokens,
    project_booking_reservation,
    project_itinerary_leg,
    query_booking_reservations,
    resolve_flight_sources_key,
)

_CREATE_LOCK = Lock()


def _sources(board):
    from .ota_payment_review import SOURCES_ENV
    raw = os.environ.get(SOURCES_ENV, '').strip()
    if raw:
        sources = json.loads(raw)
    else:
        directory = Path(board.path).parent
        sources = ota_sources.resolve_sources(
            directory, mail_default=os.environ.get('WEBLEDGER_OTA_MAIL_DIR') or directory / 'ota-mail')
    if not isinstance(sources, dict) or any(
            item.get('kind') == 'mail_directory' for item in sources.get('missing', [])):
        raise ValueError('FLIGHT_SOURCES_UNAVAILABLE')
    return sources


def _key(sources):
    return resolve_flight_sources_key(sources, parser_version=flight_evidence.PARSER_VERSION)


def service_for(board):
    with _CREATE_LOCK:
        service = getattr(board, '_flight_booking_service', None)
        if service is not None:
            return service
        # Validate configuration before starting a worker; fake/unbound stores fail closed.
        _sources(board)
        from .ota_payment_review import review_db_path, _passenger_index, _write_passenger_index, PASSENGER_SCHEMA
        path = Path(review_db_path()).parent / 'flight-search-passengers.json'
        observed = {}

        def input_key():
            sources = _sources(board)
            key = _key(sources)
            observed.update(sources=sources, key=key)
            return key

        def build():
            sources, key = observed['sources'], observed['key']
            cached = load_cached_passenger_data(
                path,
                expected_key=key,
                schema=PASSENGER_SCHEMA,
                parser_version=flight_evidence.PARSER_VERSION,
            )
            if cached is not None:
                passengers = cached
            else:
                passengers = _passenger_index(sources['mail_directories'], strict=True)
            # Never publish a parse spanning a changed collection or source configuration.
            if key != _key(_sources(board)):
                raise ValueError('FLIGHT_SOURCE_CHANGED')
            return {'public': {}, 'data': {'passengers': passengers}}

        service = ota_snapshot.OtaSnapshotService(
            key_fn=input_key, reconcile_fn=build,
            log_path=path.with_name('flight-search.log'),
            on_published=lambda current: _write_passenger_index(path, current))
        from .ota_payment_review import _stop_quietly
        atexit.register(_stop_quietly, service)
        board._flight_booking_service = service
        return service


def prewarm(board):
    try:
        service_for(board).request_check()
    except (OSError, ValueError, TypeError, AttributeError, ota_sources.OtaSourcesError):
        pass


def passenger_index_for(board):
    try:
        service = service_for(board)
        service.request_check()
        current, state = service.display_context()
        if state.get('fresh'):
            return (current.get('data') or {}).get('passengers') or {}
    except (OSError, ValueError, TypeError, AttributeError, ota_sources.OtaSourcesError):
        pass
    return {}


def source_status(board):
    try:
        service = service_for(board)
        _, state = service.display_context()
        if state.get('fresh'):
            return 'VERIFIED'
        if state.get('status') in ('loading', 'refreshing'):
            return 'LOADING'
    except (OSError, ValueError, TypeError, AttributeError, ota_sources.OtaSourcesError):
        pass
    return 'UNAVAILABLE'


def search_reservations(board, name, *, cards=None, offset=0, limit=100, revision=None):
    """Facade to query and project booking reservations for the active board."""
    index = passenger_index_for(board)
    status = source_status(board)
    return query_booking_reservations(
        index,
        name,
        cards=cards,
        offset=offset,
        limit=limit,
        revision=revision,
        fallback_status=status,
    )
