"""Read-only reconciliation of COST expenses with the selected Google trip sheet."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from collections import Counter

from app import google_authority, ledger

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
    return {'results': results, 'cost_rows': rows, 'counts': counts, 'source_available': False,
            'source_digest': '', 'source_info': {'reason': reason}, 'revision': revision,
            'links_path': links_path, 'preview_digest': _digest((trip_id, reason, results))}


def _store_and_trip(board, trip_id, include_archived=False):
    store = getattr(board, 'store', None) or board
    if not hasattr(store, 'conn') or not hasattr(store.conn, 'execute'):
        return None, None
    trips_fn = getattr(board, 'list_trips', None) or getattr(store, 'list_trips', None)
    if not callable(trips_fn):
        return None, None
    trips = trips_fn(include_archived=True) if include_archived else trips_fn()
    matches = [trip for trip in trips if str(trip.get('tab_id') or trip.get('trip_id') or '') == str(trip_id)]
    if len(matches) != 1 or matches[0].get('deleted'):
        return store, None
    return store, matches[0]


def _cost_preview_rows(store, trip_id):
    batch_ids = [row[0] for row in store.conn.execute(
        "SELECT DISTINCT batch_id FROM transactions WHERE "
        "COALESCE(NULLIF(display_tab_id,''),trip_id)=? ORDER BY batch_id", (trip_id,))]
    rows = []
    for batch_id in batch_ids:
        preview = ledger.preview(store, batch_id)
        rows.extend(row for row in preview.get('rows', [])
                    if str(row.get('display_tab_id') or '') == str(trip_id))
    # Include the board's receipt/manual expenses, using the same source IDs as
    # the card preview so a booked card is represented exactly once.
    if hasattr(store, 'list_tab_rows'):
        by_id = {str(row.get('transaction_id') or ''): row for row in rows}
        for row in store.list_tab_rows(trip_id):
            if row.get('row_kind') == 'expense' and str(row.get('display_tab_id') or '') == str(trip_id):
                if hasattr(store, 'projected'):
                    row = {**row, **store.projected(row)}
                normalized = _normalize_cost_row(row)
                prior = by_id.get(normalized['transaction_id'], {})
                by_id[normalized['transaction_id']] = {**prior, **normalized,
                    'blocked': prior.get('blocked') or normalized.get('blocked')}
        rows = list(by_id.values())
    return rows


def _normalize_cost_row(row):
    if row.get('transaction_id'):
        return {**row, 'trip_id': row.get('display_tab_id') or row.get('trip_id')}
    amount = row.get('display_amount_krw', row.get('amount_krw'))
    return {**row, 'transaction_id': str(row.get('source_event_id') or row.get('row_id') or ''),
            'trip_id': row.get('display_tab_id'),
            'date': row.get('display_occurred_on') or row.get('occurred_on'),
            'occurred_on': row.get('display_occurred_on') or row.get('occurred_on'),
            'merchant': row.get('source_merchant') or row.get('description') or '',
            'booking_ref': row.get('reservation_no') or '', 'amount_krw': amount,
            'evidence': {'카드': 'card', '영수증': 'receipt'}.get(row.get('evidence_type'), ''),
            'currency': 'KRW', 'transaction_direction': 'refund' if amount is not None and amount < 0 else 'purchase'}


def _enrich_card_facts(store, costs):
    missing = [row['transaction_id'] for row in costs
               if (row.get('source_hash') or row.get('evidence') == 'card' or row.get('already_booked'))
               and not all(key in row for key in ('issuer', 'card_tail', 'approval_number'))]
    facts = {}
    for start in range(0, len(missing), 500):
        ids = missing[start:start + 500]
        marks = ','.join('?' for _ in ids)
        for tid, issuer, tail, approval in store.conn.execute(
                f'SELECT transaction_id,issuer,card_tail,approval_number FROM transactions WHERE transaction_id IN ({marks})', ids):
            facts[tid] = {'issuer': issuer, 'card_tail': tail, 'approval_number': approval}
    return [{**row, **facts.get(row['transaction_id'], {})} for row in costs]


def _card_tail(evidence):
    # Only explicit card labels followed by a masked or four-digit tail are
    # identity clues; arbitrary reservation/date digits are never card IDs.
    match = re.search(r'(?:카드|card)\s*[:(\- ]*[*xX•\- ]*(\d{4})(?!\d)', str(evidence or ''), re.I)
    return match.group(1) if match else None


def _load_existing_links(path: Path):
    from app.sheet_expense_links import load_links
    return {row['transaction_id']: {**row, 'sheet_row_key': row['stable_key'],
                'manual_override': bool(row.get('user_override')),
                'user_corrected': bool(row.get('user_override')),
                'correction_source': row.get('link_method') if row.get('user_override') else ''}
            for row in load_links(path)['links']}


def _sheet_rows(rows, *, trip_id, google_key, sheet_id, source):
    projected = []
    occurrences = {}
    for row in rows:
        number = row.get('row')
        cells = {key: row.get(key) for key in ('date', 'payee', 'category', 'period',
                                                'reservation', 'evidence', 'amount')}
        fingerprint = _digest({'trip_id': trip_id, 'google_key': google_key,
                               'sheet_id': sheet_id, 'source': source, 'cells': cells})
        occurrence = occurrences.get(fingerprint, 0)
        occurrences[fingerprint] = occurrence + 1
        key = _digest({'source': source, 'sheet_id': sheet_id, 'fingerprint': fingerprint,
                       'occurrence': occurrence})
        projected.append({
            'trip_id': trip_id, 'sheet_id': sheet_id, 'source': source,
            'row_number': number, 'stable_id': None, 'transaction_id': None,
            'approval_number': None, 'card_tail': _card_tail(row.get('evidence')), 'issuer': None,
            'date': row.get('date') or '', 'payee': row.get('payee') or '',
            'category': row.get('category') or '', 'description': row.get('category') or '',
            'amount_krw': row.get('amount'), 'currency': 'KRW',
            'transaction_direction': 'purchase', 'evidence': row.get('evidence') or '',
            'booking_ref': row.get('reservation') or '', 'service_period': row.get('period') or '',
            'sheet_row_key': key, 'sheet_fingerprint': fingerprint,
        })
    return projected


def preview_for_trip(board, trip_id, cost_rows=None, *, include_sheet_rows=False):
    """Reconcile one COST trip against a fresh, selected, verified Google snapshot.

    This function only reads the COST store and local Google snapshots/settings.
    It never writes to Google, the COST ledger, or the link file.
    """
    costs = [_normalize_cost_row(row) for row in (cost_rows or ())]
    try:
        store, cost_trip = _store_and_trip(board, trip_id)
        if store is None or cost_trip is None:
            raise ValueError('COST_TRIP_UNAVAILABLE')
        if cost_rows is None:
            costs = [_normalize_cost_row(row) for row in _cost_preview_rows(store, trip_id)]
        ids = [str(row.get('transaction_id') or '') for row in costs]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise ValueError('RECONCILIATION_INVALID')
        costs = _enrich_card_facts(store, costs)
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
        if source not in google_authority.SPREADSHEET_IDS:
            raise ValueError('SOURCE_NOT_SELECTED')
        source_info = (resolved.get('sources') or {}).get(source) or {}
        copy_info = (trip.get('copies') or {}).get(source) or {}
        if copy_info.get('layout') != 'rev':
            raise ValueError('SOURCE_LAYOUT_UNSUPPORTED')
        if (source_info.get('status') != 'ok' or source_info.get('stale')
                or set(trip.get('review') or ()) & BLOCKING_TRIP_FLAGS):
            raise ValueError('SOURCE_NOT_VERIFIED')
        expense = copy_info.get('expense') or {}
        if not expense.get('verified'):
            total, row_sum = expense.get('sheet_total'), expense.get('row_sum')
            if type(total) is int and type(row_sum) is int and total != row_sum:
                raise ValueError('SOURCE_EXPENSE_TOTAL_MISMATCH')
            raise ValueError('SOURCE_EXPENSE_UNVERIFIED')
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
        revision = {'generation': snapshot.get('rows_generation'),
                    'synced_at': snapshot.get('synced_at'), 'source_digest': source_digest}
        links_path = snapshot_path.with_name('manual-expense-links.json')
        existing_links = {key: value for key, value in _load_existing_links(links_path).items()
                          if value.get('trip_id') == str(trip_id)}
        from app.sheet_expense_dedup import reconcile
        result = reconcile(costs, sheet_rows, trip_id=str(trip_id), source_available=True,
                           existing_links=existing_links)
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
            link = existing_links.get(str(item.get('transaction_id') or ''), {})
            user_corrected = bool(link.get('user_corrected') or link.get('manual_decision')
                                  or link.get('manual_override')
                                  or link.get('source') in {'manual', 'user', 'owner'})
            item.setdefault('user_corrected', user_corrected)
            item.setdefault('correction_source', link.get('correction_source')
                            or link.get('manual_source')
                            or (link.get('source') if user_corrected else '') or '')
        payload = {'trip_id': str(trip_id), 'revision': revision,
                   'cost_rows': costs, 'sheet_rows': sheet_rows,
                   'results': result['results'], 'counts': result['counts']}
        return {**result, **({'sheet_rows': sheet_rows} if include_sheet_rows else {}),
                'cost_rows': costs, 'source_available': True, 'source_digest': source_digest,
                'source_info': {'trip_key': google_key, 'sheet_id': sheet_id, 'source': source,
                                'layout': copy_info.get('layout'), 'synced_at': snapshot.get('synced_at')},
                'revision': revision, 'links_path': str(links_path),
                'preview_digest': _digest(payload)}
    except Exception as error:
        candidates = {'COST_TRIP_UNAVAILABLE', 'GOOGLE_SOURCE_DISABLED', 'TRIP_MAPPING_UNAVAILABLE',
                      'GOOGLE_TRIP_UNAVAILABLE', 'SOURCE_NOT_SELECTED', 'SOURCE_NOT_VERIFIED',
                      'SOURCE_FINGERPRINT_MISMATCH', 'SHEET_ROWS_UNAVAILABLE',
                      'LINKS_UNAVAILABLE', 'RECONCILIATION_INVALID', 'SOURCE_LAYOUT_UNSUPPORTED',
                      'SOURCE_EXPENSE_TOTAL_MISMATCH', 'SOURCE_EXPENSE_UNVERIFIED'}
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
    """Refresh source and matching immediately before producing NEW_EXPENSE TSV rows."""
    fresh = preview_for_trip(board, trip_id, cost_rows=preview_rows)
    rows = list(fresh.get('cost_rows') or ())
    if not fresh['source_available']:
        return {'tsv': '', 'row_count': 0, 'total_krw': 0, 'held': [],
                'reconciliation': fresh, 'source_available': False, 'matched': [],
                'held_results': list(fresh.get('results') or [])}
    by_id = {str(row.get('transaction_id') or ''): row for row in rows}
    result_by_id = {str(result.get('transaction_id') or ''): result
                    for result in fresh.get('results', [])}
    allowed = [by_id[tid] for tid, result in result_by_id.items()
               if tid in by_id and result.get('status') == 'NEW_EXPENSE'
               and not by_id[tid].get('blocked')
               and not by_id[tid].get('excluded_from_company')]
    from app.google_tsv import expense_tsv
    exported = {**expense_tsv([{
        'transaction_id': row['transaction_id'], 'date': row.get('occurred_on') or row.get('date'),
        'payee': row.get('merchant'), 'category': row.get('item'), 'period': row.get('service_period'),
        'reservation_no': row.get('booking_ref'), 'evidence': row.get('evidence') or 'card',
        'amount_krw': row.get('amount_krw'), 'status': 'ready',
    } for row in allowed], layout='rev'), 'tab_id': str(trip_id)}
    matched = [result for result in fresh['results']
               if result.get('status') in ('MATCHED_MANUAL', 'MATCHED_EXISTING')]
    held = [result for result in fresh['results']
            if result.get('status') not in ('NEW_EXPENSE', 'MATCHED_MANUAL', 'MATCHED_EXISTING')]
    holds = [{'transaction_id': row['transaction_id'], 'reason': row.get('reason') or row['status']}
             for row in held]
    holds.extend({'transaction_id': row['transaction_id'], 'reason': row.get('blocked') or 'COMPANY_EXCLUDED'}
                 for row in rows if row.get('blocked') or row.get('excluded_from_company'))
    return {**exported, 'held': list(exported.get('held') or []) + holds,
            'reconciliation': fresh, 'matched': matched,
            'held_results': held, 'source_available': True}
