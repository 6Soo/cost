"""Ephemeral source-row reconciliation over the existing transaction store."""
from collections import defaultdict
from datetime import date
import json
from urllib.parse import quote

from .automatic_classification import completion_for_row
from .card_preflight import masked_text
from .db import utc_now
from .partial_refund import refund_links
from .provisional_assignment import canonical_trip_periods

KEYS = ('T', 'E', 'N', 'C', 'U', 'H', 'P', 'R')


def summarize(pipeline, received, parsed, trips, *, nets=None, inspection=None):
    """Re-read every source occurrence, including duplicates and failed parses.

    No report tables or report snapshots are created. Decisions use the existing
    transaction + change_log path, and repeat uploads add no decision audit.
    """
    conn = pipeline.store.conn
    batch = received['batch_id']
    rows = {r['transaction_id']: r for r in pipeline.get_batch(batch)['rows']}
    identity_index = defaultdict(list)
    for tid, row in rows.items():
        approval = row.get('approval_number') or ''
        if approval:
            key = (row.get('issuer') or '', row.get('card_tail') or '', row.get('card_kind') or '',
                   row.get('approval_date') or '', row.get('foreign_currency') or '',
                   row.get('transaction_direction') or '', row.get('amount_krw'), approval)
            identity_index[key].append(tid)
    positions = defaultdict(list)
    for tid, index in conn.execute(
            'SELECT transaction_id,row_index FROM import_batch_rows WHERE batch_id=? ORDER BY row_index,transaction_id',
            (batch,)):
        positions[index].append(tid)
    origins = dict(conn.execute(
        'SELECT transaction_id,batch_id FROM transactions WHERE transaction_id IN '
        '(SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)', (batch,)))
    valid = canonical_trip_periods(trips)
    links = refund_links(conn, rows)
    counts = dict.fromkeys(KEYS, 0)
    monthly = defaultdict(lambda: dict.fromkeys(KEYS, 0))
    failures, seen, duplicate_rows = [], set(), 0
    dates, issuers = [], set()
    decisions = []
    for source in parsed.rows:
        day = source.approval_date or source.posting_date
        valid_date = True
        has_date = bool(day)
        try:
            if not has_date:
                raise TypeError('TRANSACTION_DATE_UNKNOWN')
            parsed_day = date.fromisoformat(day)
            month = parsed_day.strftime('%Y-%m')
            dates.append(parsed_day.isoformat())
        except (ValueError, TypeError):
            month = 'unknown'
            # Missing dates are an aggregate bucket, not a parsing failure.
            valid_date = not has_date
        issuers.add(masked_text(source.issuer))
        bucket = monthly[month]
        counts['T'] += 1
        bucket['T'] += 1
        candidates = positions[source.row_index]
        # Composite Hana components share a physical row, but have distinct
        # signs/directions. Preserve each source transaction exactly once.
        tid = next((i for i in candidates if rows[i]['transaction_direction'] == source.transaction_direction
                    and rows[i]['amount_krw'] == source.amount_krw), None)
        if not tid and not candidates:
            # File-internal duplicate lines may map to the one unambiguous DB identity.
            # Never pick arbitrarily when the indexed identity itself collides.
            key = (source.issuer or '', source.card_tail or '', source.card_kind or '',
                   source.approval_date or '', source.foreign_currency or '',
                   source.transaction_direction or '', source.amount_krw, source.approval_number or '')
            matches = identity_index.get(key, ()) if source.approval_number else ()
            tid = matches[0] if len(matches) == 1 else None
        row = rows.get(tid, {})
        reasons = []
        if source.parse_error or not valid_date:
            outcome = 'P'
            reasons = [source.parse_error or 'TRANSACTION_DATE_INVALID']
        elif not tid or row.get('conflict_reason') or row.get('duplicate_of'):
            outcome = 'H'
            reasons = [row.get('conflict_reason') or 'IDENTITY_UNRESOLVED']
        else:
            outcome = 'N' if (not received.get('reused') and origins[tid] == batch and tid not in seen) else 'E'
            verdict = completion_for_row(row, valid, nets=nets)
            reasons = verdict['blocked_by']
            state = 'C' if verdict['complete'] else 'U'
            counts[state] += 1
            bucket[state] += 1
            if verdict['complete'] and verdict['mode'] == 'auto' and row['classification_source'] != 'upload_confirmed':
                decisions.append((tid, row['classification_source'], row['classification_basis'], row['revision']))
        counts[outcome] += 1
        bucket[outcome] += 1
        if tid and tid in seen:
            duplicate_rows += 1
        if tid:
            seen.add(tid)
        link = links.get(tid) or {}
        refund_pending = source.transaction_direction in ('refund', 'cancellation') and (
            not link or link.get('inferred') or link.get('status') == 'excess')
        if refund_pending:
            counts['R'] += 1
            bucket['R'] += 1
        if reasons or refund_pending:
            failures.append({'row_number': source.row_index, 'date': day,
                'masked_identity': '****' + source.card_tail,
                'merchant': masked_text(source.merchant), 'amount': source.amount_krw,
                'currency': source.foreign_currency or 'KRW', 'matched': bool(tid),
                'trip_id': row.get('trip_id') or row.get('display_tab_id') or '',
                'item': row.get('item') or '', 'reason': masked_text(' · '.join(reasons + (
                    ['REFUND_ORIGINAL_UNVERIFIED'] if refund_pending else []))),
                'basis': masked_text(row.get('classification_basis')),
                'review_url': '/import?batch=' + quote(row.get('batch_id') or batch) + '&transaction=' + quote(tid or '')})
    assert counts['T'] == counts['E'] + counts['N'] + counts['H'] + counts['P']
    assert counts['E'] + counts['N'] == counts['C'] + counts['U']
    # Explicit automatic completion provenance, atomically written once per
    # decision. Existing manual and financial fields are never changed here.
    if decisions:
        with pipeline.store.lock:
            conn.execute('SAVEPOINT upload_completion')
            try:
                audited = set()
                for subject, raw in conn.execute(
                        'SELECT subject,detail_json FROM change_log WHERE kind=?',
                        ('classification.upload_confirmed',)):
                    try:
                        detail = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    audited.add((subject, detail.get('version'), detail.get('source'), detail.get('basis'),
                                 detail.get('trip_id'), detail.get('item')))
                for tid, previous_source, basis, revision in dict((d[0], d) for d in decisions).values():
                    stable = {'version': 'cuv-v2', 'source': previous_source,
                              'basis': basis, 'trip_id': rows[tid]['trip_id'], 'item': rows[tid]['item']}
                    identity = (tid, *(stable[key] for key in ('version', 'source', 'basis', 'trip_id', 'item')))
                    if identity not in audited:
                        detail = {**stable, 'at': utc_now()}
                        pipeline.store.log_change('classification.upload_confirmed', tid,
                                                  detail)
                        audited.add(identity)
                conn.execute('RELEASE SAVEPOINT upload_completion')
            except BaseException:
                conn.execute('ROLLBACK TO SAVEPOINT upload_completion')
                conn.execute('RELEASE SAVEPOINT upload_completion')
                raise
    success = counts['T'] > 0 and not (counts['P'] or counts['H'] or counts['U'])
    return {'counts': counts, 'rate': 100 * counts['C'] / counts['T'] if counts['T'] else None,
            'status': 'passed' if success else ('empty' if not counts['T'] else 'incomplete'),
            'file': {'filename': masked_text(str(received['filename']).replace('\\', '/').split('/')[-1]),
                     'issuers': sorted(issuers), 'period_start': min(dates) if dates else '',
                     'period_end': max(dates) if dates else ''},
            'inspection': inspection or {}, 'duplicate_rows': duplicate_rows,
            'monthly_reconciliation': [dict(month=m, **c) for m, c in sorted(monthly.items()) if m != 'unknown'],
            'unknown_date_reconciliation': [dict(month='날짜 확인 필요', **monthly['unknown'])] if 'unknown' in monthly else [],
            'financial_warning': '취소 원결제 미연결 또는 검증 미완료 ' + str(counts['R']) + '건' if counts['R'] else '',
            'failures': failures, 'financial_complete': False}
