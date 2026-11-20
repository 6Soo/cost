"""M6 transition boundary: Python source parsers, before Rust cross-source operations.

Only an explicit evidence-store copy is accepted. No live snapshot, database
writes or output file writes occur here. The response is private subprocess IPC,
like the existing ``extract`` command; costcore prints only a count and digest.
"""
from pathlib import Path
import re
import tempfile

from .extract_baseline import _portal_content_fingerprints, sqlite_logical_fingerprint
from .ota_input import DEFAULT_HOST, _sources, is_live


def forest_name_keys(stages):
    """Keep Python's exact Unicode word/casefold semantics while source parsing is bridged."""
    names = {event.get('hotel_name') or '' for event in stages['forest_portal_events']}
    for key in ('mail_events', 'portal_events', 'trip_reservation_events', 'booking_trip_events'):
        names.update(event.get('merchant_name') or '' for event in stages[key]
                     if event.get('evidence_kind') == 'authenticated_forest_pg_card_receipt')
    return {name: re.sub(r'\W', '', name).casefold() for name in names}


def collect(sources):
    from app import ota_mail, ota_payments as op
    from app.ota_store import is_store

    failures = []
    for scope in (sources, sources.get('ota_source_inventory') or {}):
        for key in ('missing', 'diagnostics'):
            failures.extend(op._as_items(scope.get(key)))
    registered = sources.get('registered') or {}
    for key, kind in (('mail_directories', 'mail_directory'),
                      ('portal_databases', 'portal_database'),
                      ('reference_documents', 'reference_document')):
        for value in op._as_items(registered.get(key)):
            path = Path(value)
            exists = (path.is_dir() or is_store(path)) if kind == 'mail_directory' else path.is_file()
            if not exists:
                failures.append({'kind': kind, 'path': str(path)})
    if failures:
        raise op.OtaSourcesError(failures)
    references = op._as_items(sources.get('reference_documents'))
    if references:
        try:
            report = ota_mail.load_reference_documents(references)
        except Exception as exc:
            raise op.OtaSourcesError([{'kind': 'reference_loader', 'error': type(exc).__name__}]) from exc
        if report.get('errors'):
            raise op.OtaSourcesError(report['errors'])
    stages = {
        'schema_version': 'ota-extract-stages/1',
        'mail_events': op._mail_events(sources.get('mail_directories')),
        'portal_events': op._portal_events(sources.get('portal_databases'),
                                         source_lineage_ids=sources.get('source_lineage_ids'),
                                         content_fingerprints=sources.get('portal_content_fingerprints')),
        'trip_reservation_events': op._trip_reservation_events(sources.get('portal_databases')),
        'booking_trip_events': op._booking_trip_events(sources.get('portal_databases')),
        'forest_portal_events': op._forest_portal_events(sources.get('portal_databases')),
    }
    stages['forest_name_keys'] = forest_name_keys(stages)
    return stages


def capture(request, error):
    if not request.get('ota_evidence'):
        raise error('OTA_EVIDENCE_REQUIRED')
    evidence = Path(request['ota_evidence'])
    # Always protect the actual default host as well as a supplied synthetic host.
    for host in (DEFAULT_HOST, request.get('host_root') or DEFAULT_HOST):
        data = Path(host) / 'data'
        for live in (data / 'ota-evidence.sqlite', data / 'board.sqlite',
                     data / 'ota-review' / 'ota-review.sqlite'):
            if is_live(evidence, live):
                raise error('DB_IS_LIVE')
    if not evidence.is_file():
        raise error('DB_NOT_FOUND')
    with tempfile.TemporaryDirectory(prefix='cost-extract-sources-') as work:
        sources = _sources(evidence, work)
        sources['portal_content_fingerprints'] = _portal_content_fingerprints(
            evidence, sqlite_logical_fingerprint(evidence), sources.get('portal_databases'), error)
        return collect(sources)
