"""M1 aggregate-only audit. No application startup, network calls or data writes.

Run from any directory with python -I <this-file>. Each database is opened with
mode=ro, query_only=ON and a read transaction. Trips are pseudonymized locally;
no mapping, raw rows, amounts, account names or source identifiers are emitted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import os
import sys
import threading
from types import SimpleNamespace

GUARD_REFUSALS = Counter()


def refuse(code):
    GUARD_REFUSALS[code] += 1
    raise RuntimeError(code)


def progress(message):
    # Static stage names only; the aggregate JSON remains on stdout.
    print('M1: ' + message, file=sys.stderr, flush=True)


def install_read_only_guards():
    """Process-wide fail-closed guards, installed before importing app helpers."""
    sys.dont_write_bytecode = True
    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if not kwargs.get('uri') or 'mode=ro' not in str(database).split('?')[-1].split('&'):
            refuse('READ_ONLY_SQLITE_REQUIRED')
        conn = original_connect(database, *args, **kwargs)
        conn.execute('PRAGMA query_only=ON')
        assert conn.execute('PRAGMA query_only').fetchone()[0] == 1
        return conn

    sqlite3.connect = connect

    def audit(event, args):
        if event == 'open':
            _path, mode, flags = args
            if (isinstance(mode, str) and any(char in mode for char in 'wax+')) or (
                    flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                refuse('FILE_WRITE_FORBIDDEN')
        if (event.startswith(('socket.', 'subprocess.', 'os.spawn', 'os.exec')) or
                event in {'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.truncate',
                          'os.link', 'os.symlink', 'os.system'}):
            refuse('EXTERNAL_EFFECT_FORBIDDEN')

    sys.addaudithook(audit)


def runtime_periods(root, connection, trips):
    """Rebuild display evidence in memory, without stores that initialize schemas.

    This measures the current-input display calculation, not the running process's
    last complete generation, which may be older. No workers/services are started.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from app import ota_payments, ota_review, ota_sources
    from app.partial_refund import read_only_scope
    from app.ota_matching_defaults import provider_resolution_scope
    from webapp import ledger_design, ledger_stay_evidence, ota_payment_review, read_scope

    sources = ota_sources.resolve_sources(root)
    progress('checking display input stamps')
    before = ota_sources.source_stamps(sources)
    board = SimpleNamespace(conn=connection, _lock=threading.RLock())
    backend = ota_payment_review.CoreOtaPaymentBackend(
        board, root / 'ota-review/ota-review.sqlite', read_only=True,
        payments=ota_payments, store_type=ota_review.OtaReviewStore, sources=sources)
    try:
        with read_only_scope(), provider_resolution_scope():
            progress('parsing and matching display evidence in memory')
            events, cards, links, results = backend._data()
            progress('building service period index in memory')
            manual = {str(row[0]) for row in connection.execute(
                "SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
            data = dict(events=events, transactions=cards, links=links, results=results)
            stay = ledger_stay_evidence._build_index(data, manual)
            progress('reading flight date evidence')
            passengers = ota_payment_review._passenger_index(sources.get('mail_directories', []), strict=True)
            periods = {}
            live = {trip['tab_id'] for trip in trips if not trip['deleted']}
            for trip in trips:
                if trip['deleted']:
                    continue
                try:
                    starts = date.fromisoformat(str(trip['starts_on']))
                    ends = date.fromisoformat(str(trip['ends_on'])) if trip['ends_on'] else None
                except (ValueError, TypeError):
                    continue
                periods[trip['tab_id']] = (starts, ends)
            memo = {'ledger_stay_evidence': stay, 'flight_service_dates': (passengers, manual),
                    'trip_periods': periods}
            token = read_scope._MEMO.set(memo)
            try:
                counts = {item: Counter() for item in PERIOD_ITEMS}
                for raw in connection.execute("SELECT payload_json FROM board_rows WHERE row_kind='expense'"):
                    row = json.loads(raw[0])
                    item = str(row.get('item') or '').strip()
                    if item not in counts or row.get('display_tab_id') not in live:
                        continue
                    if (row.get('amount_krw') or 0) <= 0:
                        continue
                    label = ledger_design._service_date_labels(row)[0]
                    counts[item]['total'] += 1
                    counts[item]['unknown' if label in ledger_design._UNKNOWN_SERVICE_DATES else 'known'] += 1
            finally:
                read_scope._MEMO.reset(token)
        assert before == ota_sources.source_stamps(sources), 'OTA_INPUT_CHANGED_DURING_READ'
        assert not GUARD_REFUSALS, 'READ_ONLY_GUARD_REFUSED_AN_ATTEMPT'
        assert all(count['known'] + count['unknown'] == count['total'] for count in counts.values())
        progress('display reconstruction complete')
        return {'status': 'MEASURED_CURRENT_INPUT_RECONSTRUCTION',
                'scope': 'positive_persisted_expense_rows_on_non_deleted_trips_including_archived',
                'unknown': sum(count['unknown'] for count in counts.values()),
                'by_item': {item: dict(count) for item, count in counts.items()},
                'runtime_generation_verified': False,
                'source_stamps_unchanged': True,
                'evidence_events': len(events), 'evidence_cards': len(cards)}
    finally:
        backend.close()


SOURCES = frozenset((
    'inference', 'rule', 'refund_original', 'owner_card_residual', 'user_decision',
    'code_inference', 'card_category', 'user_exception', 'pattern',
    'booking_evidence_needed', 'ai_inference', 'auto_inferred', 'manual',
    'previous_decision', 'auto', 'owner_booking', 'guide_airfare_evidence',
))
MANUAL = {'manual', 'user_decision', 'user_exception', 'previous_decision'}
CODE = {'inference', 'auto_inferred', 'code_inference'}
AUTO = {'auto', 'rule', 'pattern', 'card_category', 'owner_booking',
        'owner_card_residual', 'guide_airfare_evidence', 'refund_original'}
ISSUERS = ('국민', '하나', '기업')
PERIOD_ITEMS = ('숙박비', '항공료', '항공권', '렌터카')


def read_connection(path):
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    assert connection.execute('PRAGMA query_only').fetchone()[0] == 1
    connection.execute('BEGIN')
    return connection


def origin(row):
    # Mirrors app/classification_provenance.py:origin, including manual priority.
    source = str(row['classification_source'] or '').strip()
    if row['decided_at'] or source in MANUAL:
        return 'manual'
    if source == 'ai_inference':
        return 'ai_inference'
    if source in CODE or str(row['classification_basis'] or '').startswith('AUTO_TRIP_INFERRED'):
        return 'code_inference'
    return 'automatic' if source in AUTO else 'unknown'


def period_status(value, item):
    value = str(value or '').strip()
    if not value:
        return 'missing'
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})', value)
    if not match:
        return 'invalid'
    try:
        start, end = (date.fromisoformat(part) for part in match.groups())
    except ValueError:
        return 'invalid'
    days = (end - start).days
    # ledger_design allows flight ranges without the lodging/rental 366-day cap.
    return 'valid' if days >= 0 and (item in ('항공료', '항공권') or days <= 366) else 'invalid'


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def collect(root):
    result = {'measured_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'scope': 'persisted_data_and_in_memory_current_input_display_reconstruction',
              'database_access': 'mode=ro; query_only=1; BEGIN; no application startup; write/network audit guards'}
    with closing(read_connection(root / 'board.sqlite')) as connection:
        progress('reading persisted card and board aggregates')
        transactions = [dict(row) for row in connection.execute('SELECT * FROM transactions')]
        trips = [dict(row) for row in connection.execute('SELECT * FROM trip_tabs ORDER BY tab_id')]
        # Sorted IDs stay in memory; the output contains T001 etc. only.
        aliases = {row['tab_id']: f'T{index:03d}' for index, row in enumerate(trips, 1)}
        booked = {row[0] for row in connection.execute('SELECT transaction_id FROM ledger_entries')}
        board_ids = {row[0] for row in connection.execute('SELECT row_id FROM board_rows')}
        held = {row[0] for row in connection.execute('SELECT transaction_id FROM transaction_review_holds')}
        excluded = {row[0] for row in connection.execute(
            'SELECT transaction_id FROM transaction_company_exclusions WHERE excluded=1')}
        states, sources, origins = Counter(), Counter(), Counter()
        normal, undecided, normal_undecided = [], [], []
        for row in transactions:
            state = row['classification_state'] or 'empty'
            states[state if state in {'classified', 'needs_review', 'unclassified', 'empty'} else 'other'] += 1
            source = row['classification_source'] or 'empty'
            sources[source if source in SOURCES or source == 'empty' else 'other'] += 1
            origins[origin(row)] += 1
            # Baseline of persisted destination presence, not live trip authority.
            destination = row['display_tab_id'] or row['trip_id'] or ''
            has_decision = (state == 'classified' and bool(row['item'])
                            and (destination not in ('', 'unclassified')
                                 or row['item'] == '분기 기타비용'
                                 or row['classification_source'] == 'guide_airfare_evidence'))
            if not has_decision:
                undecided.append(row)
            is_normal = (row['transaction_direction'] == 'purchase'
                         and isinstance(row['amount_krw'], int) and row['amount_krw'] > 0
                         and not any(row[key] for key in ('duplicate_of', 'conflict_reason', 'parse_error'))
                         and row['transaction_id'] not in held | excluded)
            if is_normal:
                normal.append(row)
                if not has_decision:
                    normal_undecided.append(row)
        unrecorded = [row for row in transactions if row['transaction_id'] not in booked
                      and 'card-' + row['transaction_id'] not in board_ids]
        unrecorded_ids = {row['transaction_id'] for row in unrecorded}
        trip_rows = []
        for trip in trips:
            assigned = [row for row in transactions if row['display_tab_id'] == trip['tab_id']]
            trip_rows.append({'trip': aliases[trip['tab_id']], 'deleted': bool(trip['deleted']),
                              'assigned': len(assigned), 'unrecorded': sum(
                                  row['transaction_id'] in unrecorded_ids for row in assigned)})
        result['cards'] = {'total': len(transactions), 'states': dict(states),
                           'sources': dict(sources), 'origins': dict(origins),
                           'normal_purchases': len(normal), 'without_persisted_decision': len(undecided),
                           'normal_without_persisted_decision': len(normal_undecided),
                           'undecided_with_source_conflict': sum(bool(row['conflict_reason']) for row in undecided),
                           'source_conflicts': sum(bool(row['conflict_reason']) for row in transactions),
                           'ledger_entries': len(booked), 'board_rows': len(board_ids),
                           'unrecorded_internal': len(unrecorded),
                           'normal_unrecorded_internal': sum(row['transaction_id'] in unrecorded_ids for row in normal),
                           'live_trip_unrecorded': sum(row['unrecorded'] for row in trip_rows if not row['deleted']),
                           'deleted_trip_unrecorded': sum(row['unrecorded'] for row in trip_rows if row['deleted']),
                           'other_destination_unrecorded': sum(row['display_tab_id'] not in aliases for row in unrecorded),
                           'destination_id_disagreements': sum(bool(row['display_tab_id']) and bool(row['trip_id'])
                               and row['display_tab_id'] != row['trip_id'] for row in transactions),
                           'by_trip': trip_rows}
        issuer_rows = []
        for issuer in ISSUERS:
            rows = [row for row in transactions if row['issuer'] == issuer]
            imported_at = connection.execute(
                'SELECT MAX(b.received_at) FROM import_batches b JOIN import_batch_rows r USING(batch_id) '
                'JOIN transactions t USING(transaction_id) WHERE t.issuer=?', (issuer,)).fetchone()[0]
            issuer_rows.append({'issuer': issuer, 'rows': len(rows),
                                'last_approval_date': max((row['approval_date'] or '' for row in rows), default=''),
                                'last_posting_date': max((row['posting_date'] or '' for row in rows), default=''),
                                'last_import_received_at': imported_at,
                                'issuer_fetch_run_at': None})
        assert sum(row['rows'] for row in issuer_rows) == len(transactions), 'UNEXPECTED_ISSUER'
        result['issuers'] = issuer_rows
        periods = {item: Counter() for item in PERIOD_ITEMS}
        for raw in connection.execute("SELECT payload_json FROM board_rows WHERE row_kind='expense'"):
            row = json.loads(raw[0])
            item = str(row.get('item') or '').strip()
            # Cancellations/refunds have no service day of their own in ledger_design.
            if item not in periods or (row.get('amount_krw') or 0) <= 0:
                continue
            if row.get('display_tab_id') not in {trip['tab_id'] for trip in trips if not trip['deleted']}:
                continue
            periods[item][period_status(row.get('service_period'), item)] += 1
        result['stored_service_periods'] = {item: dict(counts) for item, counts in periods.items()}
        result['service_period_display'] = runtime_periods(root, connection, trips)
        from webapp.autonomous_cleanup_worker import detection_sql
        sql = detection_sql()
        worker_rows = connection.execute(sql).fetchall()
        full_rows = connection.execute(sql.rsplit(' LIMIT 400', 1)[0]).fetchall()
        result['worker_candidates'] = {'limited_join_rows': len(worker_rows),
            'limited_distinct_transactions': len({row['transaction_id'] for row in worker_rows}),
            'all_join_rows': len(full_rows),
            'all_distinct_transactions': len({row['transaction_id'] for row in full_rows})}
        assert sum(states.values()) == sum(sources.values()) == sum(origins.values()) == len(transactions)
        assert sum(row['unrecorded'] for row in trip_rows) + result['cards']['other_destination_unrecorded'] == len(unrecorded)
    progress('reading source collection metadata')
    with closing(read_connection(root / 'ota-evidence.sqlite')) as connection:
        # observed_at on revisions is DB import time; fact.observed_at is capture time.
        revisions = {row['current_revision']: dict(row) for row in connection.execute(
            'SELECT s.current_revision,s.kind,r.observed_at FROM ota_sources s '
            'JOIN ota_source_revisions r ON r.revision_id=s.current_revision '
            "WHERE s.kind IN ('direct_capture','direct_observation')")}
        providers = {row[0]: row[1] for row in connection.execute(
            "SELECT booking_id,provider FROM ota_bookings WHERE provider IN ('agoda','trip','booking','klook')")}
        captures = {}
        for row in connection.execute(
                "SELECT booking_id,revision_id,json_extract(fact_json,'$.observed_at') FROM ota_booking_evidence "
                "WHERE revision_id IN (SELECT current_revision FROM ota_sources "
                "WHERE kind IN ('direct_capture','direct_observation'))"):
            if row[0] not in providers:
                continue
            source = revisions[row[1]]
            key = providers[row[0]], source['kind']
            entry = captures.setdefault(key, {'provider': key[0], 'kind': key[1],
                                              'captured_at': None, 'imported_at': None})
            for field, value in [('captured_at', row[2]), ('imported_at', source['observed_at'])]:
                if value and (entry[field] is None or value > entry[field]):
                    entry[field] = value
        result['portal_metadata'] = list(captures.values())
        result['mail_db_last_imported_at'] = connection.execute(
            "SELECT MAX(r.observed_at) FROM ota_sources s JOIN ota_source_revisions r "
            "ON r.revision_id=s.current_revision WHERE s.kind='mail_directory'").fetchone()[0]
    collection = load_json(root / 'ota-mail/collection.json')
    result['gmail_last_run_local'] = collection.get('last_run')
    google = load_json(root / 'google-authority/snapshot.json')
    result['google_sources'] = {key: {field: value.get(field) for field in ('status', 'last_ok_at', 'stale')}
                                for key, value in google.get('sources', {}).items()
                                if key in {'main', 'andre_main', 'archive'}}
    ota_snapshot = load_json(root / 'ota-review/ota-snapshot.json')
    result['ota_snapshot_generated_at'] = ota_snapshot.get('generated_at')
    result['booking_portal_last_capture_at'] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('D:/WebLedgerHost/data'))
    args = parser.parse_args()
    install_read_only_guards()
    try:
        result = collect(args.data_root)
        assert not GUARD_REFUSALS, 'READ_ONLY_GUARD_REFUSED_AN_ATTEMPT'
    except Exception as exc:
        # Never print exception messages/tracebacks: they can contain customer data.
        trace = exc.__traceback__
        while trace.tb_next:
            trace = trace.tb_next
        print(json.dumps({'status': 'FAILED', 'reason': 'M1_BASELINE_UNAVAILABLE_OR_INVARIANT_FAILED',
                          'exception_type': type(exc).__name__, 'function': trace.tb_frame.f_code.co_name,
                          'line': trace.tb_lineno, 'guard_refusals': dict(GUARD_REFUSALS)}))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
