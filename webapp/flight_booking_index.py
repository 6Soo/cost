"""Authenticated booking evidence, independently refreshed from financial matching."""
import atexit
import json
import os
from pathlib import Path
from threading import Lock

from app import flight_evidence, ota_sources
from . import ota_snapshot

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
    directories = sources.get('mail_directories') or []
    if not directories or any(not Path(p).exists() for p in directories):
        raise ValueError('FLIGHT_MAIL_UNAVAILABLE')
    return ota_snapshot.digest({'parser': flight_evidence.PARSER_VERSION,
                                'directories': list(map(str, directories)),
                                'mail': ota_sources.mail_stamps(directories)})


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
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                saved = {}
            if (saved.get('schema') == PASSENGER_SCHEMA and saved.get('key') == key
                    and saved.get('parser') == flight_evidence.PARSER_VERSION
                    and isinstance(saved.get('passengers'), dict)):
                passengers = saved['passengers']
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
        # Use the worker's check interval; polling a search must not repeatedly
        # hash the entire mail collection while a fresh index is already held.
        service.view()
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
