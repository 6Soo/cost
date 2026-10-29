"""Read-only reconciliation of COST expenses with the selected Google trip sheet."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from collections import Counter
from datetime import date, datetime

from app import google_authority

from . import google_ledger_page


STATUSES = ('MATCHED_MANUAL', 'MATCHED_EXISTING', 'NEW_EXPENSE',
            'REVIEW_CONFLICT', 'SOURCE_UNAVAILABLE')
BLOCKING_TRIP_FLAGS = {'POSSIBLE_DUPLICATE', 'DUPLICATE_IN_SOURCE', 'COPY_NAME', 'SOURCE_STALE'}


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _unavailable(cost_rows, reason, *, trip_id='', revision=None, links_path=''):
    rows = list(cost_rows or ())
    results = [{'transaction_id': str(row.get('transaction_id') or ''),
                'status': 'SOURCE_UNAVAILABLE', 'sheet_row_key': None, 'row_number': None,
                'sheet_fingerprint': None, 'trip_id': str(trip_id), 'sheet_id': None,
                'source': None, 'basis': [], 'differences': {}, 'reason': reason,
                'user_corrected': False, 'correction_source': ''}
               for row in rows]
    counts = dict.fromkeys(STATUSES, 0)
    counts['SOURCE_UNAVAILABLE'] = len(results)
    return {'results': results, 'counts': counts, 'source_available': False,
            'source_digest': '', 'source_info': {'reason': reason}, 'revision': revision,
            'links_path': links_path, 'preview_digest': _digest((trip_id, reason, results))}


def _store_and_trip(board, trip_id):
    active_store = getattr(board, '_active_store', None)
    store = getattr(board, 'store', None) or (active_store() if callable(active_store) else None) or board
    if not hasattr(store, 'conn') or not hasattr(store.conn, 'execute'):
        return None, None
    trips_fn = (getattr(board, 'list_trips', None) or getattr(store, 'list_trips', None)
                or getattr(store, 'trips', None))
    if not callable(trips_fn):
        return None, None
    trips = trips_fn()
    matches = [trip for trip in trips if str(trip.get('tab_id') or trip.get('trip_id') or '') == str(trip_id)]
    if len(matches) != 1 or matches[0].get('deleted'):
        return store, None
    return store, matches[0]


def normalize_cost_rows(board, rows, trip_id):
    """Normalize card and receipt rows from the existing trip expense projection."""
    normalized = []
    for source_row in rows or ():
        row = dict(source_row)
        row_trip = str(row.get('display_tab_id') or row.get('trip_id') or row.get('tab_id') or '')
        if row_trip != str(trip_id):
            continue
        identity = row.get('source_event_id') or row.get('row_id') or row.get('transaction_id')
        evidence_kind = row.get('evidence_type')
        evidence = {'카드': 'card', '영수증': 'receipt'}.get(
            evidence_kind, evidence_kind if evidence_kind in {'card', 'receipt'} else row.get('evidence'))
        row.update({
            'transaction_id': str(identity or ''), 'trip_id': row_trip,
            'display_tab_id': row_trip,
            'date': row.get('date') or row.get('occurred_on') or row.get('approval_date') or '',
            'merchant': row.get('source_merchant') or row.get('merchant') or row.get('payee') or row.get('description') or '',
            'item': row.get('item') or row.get('category') or '',
            'amount_krw': row.get('display_amount_krw') if row.get('display_amount_krw') is not None else row.get('amount_krw'),
            'booking_ref': row.get('booking_ref') or row.get('reservation_no') or '',
            'service_period': row.get('service_period') or row.get('period') or '',
            'evidence': evidence or '',
        })
        normalized.append(row)
    return normalized


def _board_expense_rows(board):
    callback = getattr(board, '_expense_rows', None)
    if callable(callback):
        return callback()
    from . import ledger_board
    return ledger_board._expense_rows()


def _load_existing_links(path: Path):
    try:
        from app.sheet_expense_links import load_links
        return load_links(path)
    except Exception:
        raise ValueError('LINKS_UNAVAILABLE') from None


def _sheet_rows(rows, *, trip_id, google_key, sheet_id, source):
    from app.sheet_expense_dedup import _fingerprint, _sheet_key
    projected = []
    for row in rows:
        number = row.get('row')
        raw_date = row.get('date')
        if isinstance(raw_date, datetime):
            raw_date = raw_date.date().isoformat()
        elif isinstance(raw_date, date):
            raw_date = raw_date.isoformat()
        elif raw_date:
            raw_date = str(raw_date)[:10]
        item = {
            'trip_id': trip_id, 'sheet_id': sheet_id, 'source': source,
            'row_number': number, 'stable_id': None, 'transaction_id': None,
            'approval_number': None, 'card_tail': None, 'issuer': None,
            'date': raw_date or '', 'payee': row.get('payee') or '',
            'category': row.get('category') or '', 'description': row.get('category') or '',
            'amount_krw': row.get('amount'), 'currency': 'KRW',
            'transaction_direction': 'refund' if row.get('amount') is not None and row.get('amount') < 0 else 'purchase',
            'evidence': row.get('evidence') or '',
            'booking_ref': row.get('reservation') or '', 'service_period': row.get('period') or '',
        }
        item['sheet_row_key'] = _sheet_key(item)
        item['sheet_fingerprint'] = _fingerprint(item)
        projected.append(item)
    return projected


def preview_for_trip(board, trip_id, cost_rows=None, *, _include_projection=False):
    """Reconcile one COST trip against a fresh, selected, verified Google snapshot.

    This function only reads the COST store and local Google snapshots/settings.
    It never writes to Google, the COST ledger, or the link file.
    """
    costs = list(cost_rows or ())
    try:
        store, cost_trip = _store_and_trip(board, trip_id)
        if store is None or cost_trip is None:
            raise ValueError('COST_TRIP_UNAVAILABLE')
        if cost_rows is None:
            projected = _board_expense_rows(board)
            costs = normalize_cost_rows(board, projected, trip_id)
        else:
            costs = normalize_cost_rows(board, cost_rows, trip_id)
        if not google_ledger_page.enabled():
            raise ValueError('GOOGLE_SOURCE_DISABLED')
        snapshot_path = google_ledger_page.snapshot_path()
        rows_path = google_ledger_page.rows_path()
        snapshot, all_rows = google_authority.load_consistent(snapshot_path, rows_path)
        snapshot = google_ledger_page.snapshot_for_display(snapshot)
        mapping = google_ledger_page.load_mapping(snapshot_path)
        keys = [key for key, tab in mapping.items() if str(tab) == str(trip_id)]
        if len(keys) != 1:
            raise ValueError('TRIP_MAPPING_UNAVAILABLE')
        google_key = keys[0]
        choices = google_ledger_page.load_choices(snapshot_path)
        resolved = google_ledger_page.owner_payload(snapshot, choices)
        trip_matches = [trip for trip in resolved['trips'] if trip.get('key') == google_key]
        if len(trip_matches) != 1:
            raise ValueError('GOOGLE_TRIP_UNAVAILABLE')
        trip = trip_matches[0]
        source = trip.get('chosen_source')
        if source not in ('main', 'archive'):
            raise ValueError('SOURCE_NOT_SELECTED')
        source_info = (resolved.get('sources') or {}).get(source) or {}
        copy_info = (trip.get('copies') or {}).get(source) or {}
        if (source_info.get('status') != 'ok' or source_info.get('stale')
                or copy_info.get('layout') != 'rev'
                or not (copy_info.get('expense') or {}).get('verified')
                or set(trip.get('review') or ()) & BLOCKING_TRIP_FLAGS):
            raise ValueError('SOURCE_NOT_VERIFIED')
        sheet_id = copy_info.get('sheet')
        source_rows = all_rows.get(source) or {}
        source_hash = source_rows.get('content_sha256')
        if (not sheet_id or not isinstance(source_hash, str)
                or not re.fullmatch(r'[0-9a-f]{64}', source_hash)
                or source_hash != (snapshot.get('sources', {}).get(source) or {}).get('content_sha256')):
            raise ValueError('SOURCE_FINGERPRINT_MISMATCH')
        detail = google_ledger_page.owner_rows(all_rows, google_key, source)
        if detail is None:
            raise ValueError('SHEET_ROWS_UNAVAILABLE')
        sheet_rows = _sheet_rows(detail['expense'], trip_id=trip_id, google_key=google_key,
                                 sheet_id=sheet_id, source=source)
        source_digest = _digest({'snapshot_source_digest': (snapshot.get('sources', {}).get(source) or {}).get('content_sha256'),
                                 'generation': snapshot.get('rows_generation'),
                                 'trip': google_key, 'sheet': sheet_id, 'rows': sheet_rows})
        revision = None
        source_revision = {'generation': snapshot.get('rows_generation'),
                           'synced_at': snapshot.get('synced_at'), 'source_digest': source_digest}
        links_path = snapshot_path.with_name('manual-expense-links.json')
        link_doc = _load_existing_links(links_path)
        revision = link_doc['revision']
        existing_links = [{**link, 'sheet_row_key': link.get('sheet_row_key') or link.get('stable_key')}
                          for link in link_doc['links'] if link.get('trip_id') == str(trip_id)]
        links_by_transaction = {str(link.get('transaction_id') or ''): link
                                for link in existing_links}
        from app.sheet_expense_dedup import reconcile
        result = reconcile(costs, sheet_rows, trip_id=str(trip_id), source_available=True,
                           existing_links=existing_links,
                           source_metadata={'trip_id': str(trip_id), 'sheet_id': str(sheet_id), 'source': source})
        if (not isinstance(result, dict) or not isinstance(result.get('results'), list)
                or not isinstance(result.get('counts'), dict)
                or len(result['results']) != len(costs)):
            raise ValueError('RECONCILIATION_INVALID')
        cost_ids = [str(row.get('transaction_id') or '') for row in costs]
        result_ids = [str(row.get('transaction_id') or '') for row in result['results']]
        if Counter(cost_ids) != Counter(result_ids):
            raise ValueError('RECONCILIATION_INVALID')
        if any(item.get('status') not in STATUSES for item in result['results']):
            raise ValueError('RECONCILIATION_INVALID')
        actual_counts = Counter(item['status'] for item in result['results'])
        if any(not isinstance(result['counts'].get(status), int)
               or isinstance(result['counts'].get(status), bool)
               or result['counts'][status] < 0
               or result['counts'][status] != actual_counts[status] for status in STATUSES):
            raise ValueError('RECONCILIATION_INVALID')
        for item in result['results']:
            key = item.get('sheet_row_key')
            matched = next((candidate for candidate in sheet_rows
                            if candidate['sheet_row_key'] == key), None)
            item.setdefault('trip_id', str(trip_id))
            item.setdefault('sheet_id', matched.get('sheet_id') if matched else sheet_id)
            item.setdefault('source', matched.get('source') if matched else source)
            if matched:
                item.setdefault('sheet_fingerprint', matched['sheet_fingerprint'])
                item.setdefault('row_number', matched['row_number'])
            link = links_by_transaction.get(str(item.get('transaction_id') or ''), {})
            provenance = link.get('provenance') or {}
            user_corrected = bool(link.get('user_override') or provenance.get('user_override'))
            item['user_corrected'] = bool(item.get('manual_override') or user_corrected)
            item['correction_source'] = ((provenance.get('link_method')
                                          or link.get('correction_source')) if user_corrected else '')
        payload = {'trip_id': str(trip_id), 'revision': revision,
                   'cost_rows': costs, 'sheet_rows': sheet_rows,
                   'results': result['results'], 'counts': result['counts']}
        payload_result = {**result, 'source_available': True, 'source_digest': source_digest,
                'source_info': {'trip_key': google_key, 'sheet_id': sheet_id, 'source': source,
                                'layout': copy_info.get('layout'), 'synced_at': snapshot.get('synced_at')},
                'revision': revision, 'source_revision': source_revision, 'links_path': str(links_path),
                'preview_digest': _digest(payload)}
        if _include_projection:
            payload_result['_sheet_rows'] = sheet_rows
            payload_result['_cost_rows'] = costs
        return payload_result
    except Exception as error:
        candidates = {'COST_TRIP_UNAVAILABLE', 'GOOGLE_SOURCE_DISABLED', 'TRIP_MAPPING_UNAVAILABLE',
                      'GOOGLE_TRIP_UNAVAILABLE', 'SOURCE_NOT_SELECTED', 'SOURCE_NOT_VERIFIED',
                      'SOURCE_FINGERPRINT_MISMATCH', 'SHEET_ROWS_UNAVAILABLE',
                      'LINKS_UNAVAILABLE', 'RECONCILIATION_INVALID'}
        code = getattr(error, 'code', None)
        reason = code if code in candidates else (str(error) if isinstance(error, ValueError)
                                                   and str(error) in candidates else 'SOURCE_UNAVAILABLE')
        links_path = ''
        try:
            if google_ledger_page.enabled():
                links_path = str(google_ledger_page.snapshot_path().with_name('manual-expense-links.json'))
        except Exception:
            pass
        return _unavailable(costs, reason, trip_id=trip_id, links_path=links_path)


def export_for_trip(board, preview_rows, trip_id):
    """Re-fetch the selected workbook in memory, then reconcile immediately before TSV."""
    rows = list(preview_rows) if preview_rows is not None else None
    fresh = preview_for_trip(board, trip_id, cost_rows=rows, _include_projection=True)
    if not fresh['source_available']:
        held = list(fresh.get('results') or [])
        return {'tsv': '', 'row_count': 0, 'total_krw': 0, 'held': held,
                'reconciliation': _public_preview(fresh), 'source_available': False, 'matched': [],
                'held_results': held}
    from app.google_authority import EXPORT_URL, SPREADSHEET_IDS, parse_workbook, SourceError
    from app.sheet_expense_dedup import _fingerprint
    source = fresh['source_info']['source']
    sheet_id = fresh['source_info']['sheet_id']
    auth_mode = os.environ.get('WEBLEDGER_GOOGLE_AUTH', 'public').strip().lower()
    try:
        timeout, max_bytes = google_authority.DEFAULT_TIMEOUT, google_authority.DEFAULT_MAX_BYTES
        if auth_mode == 'adc':
            from app.google_adc_export import authorized_export_fetcher
            fetcher = authorized_export_fetcher(timeout=timeout, max_bytes=max_bytes)
        elif auth_mode == 'public':
            fetcher = lambda url: google_authority._download(url, timeout=timeout, max_bytes=max_bytes)
        else:
            raise ValueError('GOOGLE_AUTH_MODE_UNAVAILABLE')
        if sheet_id not in SPREADSHEET_IDS.values():
            raise ValueError('SOURCE_NOT_ALLOWED')
        live = fetcher(EXPORT_URL.format(sheet_id=sheet_id))
        tabs = [tab for tab in parse_workbook(live, rollover=(source == 'main'))
                if tab.get('sheet') == fresh['source_info']['trip_key']]
        if len(tabs) != 1 or tabs[0].get('layout') != 'rev' or not tabs[0].get('verified'):
            raise ValueError('SOURCE_CHANGED')
        fresh_rows = _sheet_rows([
            {'row': row['row'], 'date': row['cells'].get('B'), 'payee': row['cells'].get('C'),
             'category': row['cells'].get('D'), 'period': row['cells'].get('E'),
             'reservation': row['cells'].get('F'), 'evidence': row['cells'].get('G'),
             'amount': row['amount']} for row in tabs[0].get('rows', {}).get('expense', [])],
            trip_id=str(trip_id), google_key=fresh['source_info']['trip_key'],
            sheet_id=sheet_id, source=source)
        expected = Counter(_fingerprint(row) for row in fresh.get('_sheet_rows', []))
        actual = Counter(_fingerprint(row) for row in fresh_rows)
        if expected != actual:
            raise ValueError('SOURCE_CHANGED')
    except Exception as error:
        code = getattr(error, 'code', None)
        reason = code if code in {'SOURCE_ACCESS_DENIED', 'SOURCE_UNREACHABLE', 'SOURCE_NOT_FOUND',
                                  'GOOGLE_AUTH_REFRESH_REQUIRED', 'SOURCE_CHANGED'} else (
                    str(error) if isinstance(error, ValueError) and str(error) in {
                        'SOURCE_CHANGED', 'SOURCE_NOT_ALLOWED', 'GOOGLE_AUTH_MODE_UNAVAILABLE'}
                    else 'SOURCE_UNAVAILABLE')
        unavailable = _unavailable(rows or (), reason, trip_id=trip_id,
                                   revision=fresh.get('revision'), links_path=fresh.get('links_path', ''))
        unavailable['source_info'] = {**fresh.get('source_info', {}), 'reason': reason}
        held = list(unavailable['results'])
        return {'tsv': '', 'row_count': 0, 'total_krw': 0, 'held': held,
                'reconciliation': unavailable, 'source_available': False, 'matched': [],
                'held_results': held}
    rows = list(fresh.get('_cost_rows') or ())
    # Preserve duplicate IDs/multiplicity so the TSV adapter can reject them.
    by_id = {}
    for row in rows:
        by_id.setdefault(str(row.get('transaction_id') or ''), []).append(row)
    result_by_id = {str(result.get('transaction_id') or ''): result
                    for result in fresh.get('results', [])}
    allowed = []
    for tid, source_rows in by_id.items():
        result = result_by_id.get(tid)
        if result and result.get('status') == 'NEW_EXPENSE':
            # Keep held same-ID siblings so the TSV builder still detects duplicate IDs.
            allowed.extend(source_rows)
    from app.google_tsv import expense_tsv
    tsv_rows = [{
        'transaction_id': str(row.get('source_event_id') or row.get('row_id') or row.get('transaction_id') or ''),
        'status': 'blocked' if row.get('blocked') or row.get('excluded_from_company') else 'ready',
        'date': row.get('date') or row.get('occurred_on') or row.get('approval_date'),
        'payee': row.get('source_merchant') or row.get('merchant') or row.get('description') or '',
        'category': row.get('item') or row.get('category') or '',
        'period': row.get('service_period') or row.get('period') or '',
        'reservation_no': row.get('booking_ref') or row.get('reservation_no') or '',
        'evidence': {'카드': 'card', '영수증': 'receipt'}.get(row.get('evidence_type'), row.get('evidence')),
        'amount_krw': row.get('display_amount_krw') if row.get('display_amount_krw') is not None else row.get('amount_krw'),
    } for row in allowed]
    exported = expense_tsv(tsv_rows, layout='rev')
    matched = [result for result in fresh['results']
               if result.get('status') in ('MATCHED_MANUAL', 'MATCHED_EXISTING')]
    held = [result for result in fresh['results']
            if result.get('status') not in ('NEW_EXPENSE', 'MATCHED_MANUAL', 'MATCHED_EXISTING')]
    return {**exported, 'reconciliation': _public_preview(fresh), 'matched': matched,
            'held_results': held, 'source_available': True}


def _public_preview(value):
    return {key: item for key, item in value.items() if not key.startswith('_')}
