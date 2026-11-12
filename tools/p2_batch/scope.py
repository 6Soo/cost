"""Read a small projection, close the live database, then compute the open scope."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from app.quarter_costs import destination
from app.ota_matching_defaults import provider_for_merchant
from app.review import _kind_is_cancel

GENERAL = {'현지경비', '기타경비', '여행경비'}
MANUAL = {'user_decision', 'user_exception', 'owner_booking', 'manual', 'manual_hold'}
INFERRED = {'inference', 'code_inference', 'auto_inferred', 'pattern', 'card_category',
            'provider_default', 'ai_inference'}
FIELDS = ('transaction_id source_hash issuer card_tail card_kind transaction_direction '
          'transaction_kind approval_number original_approval_number approval_date posting_date '
          'merchant merchant_normalized amount_krw foreign_amount foreign_currency description_raw '
          'raw_row_json duplicate_of conflict_reason parse_error classification_state '
          'classification_source classification_basis item display_tab_id trip_id revision decided_at').split()


def read_projection(path):
    started = time.monotonic()
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        # A consistent, short read transaction; no source/evidence database is opened.
        conn.execute('BEGIN')
        data = {'transactions': [dict(r) for r in conn.execute('SELECT '+','.join(FIELDS)+' FROM transactions')]}
        for table, columns in (
            ('trip_tabs', 'tab_id,display_key,starts_on,ends_on,deleted'),
            ('review_decisions', 'transaction_id,item,display_tab_id'),
            ('board_manual_overrides', 'row_id,field'),
            ('transaction_review_holds', 'transaction_id,source_hash,kind'),
            ('transaction_company_exclusions', 'transaction_id,source_hash,excluded'),
            ('board_rows', 'row_id,payload_json'),
            ('ledger_entries', 'transaction_id,trip_id,display_tab_id'),
        ):
            from app.decision_provenance import active_decision_sql
            query = 'SELECT '+columns+' FROM '+table
            if table == 'review_decisions':
                query += ' d WHERE '+active_decision_sql(conn=conn)
            data[table] = [dict(r) for r in conn.execute(query)]
        data['allowed_items'] = sorted({r[0] for r in conn.execute(
            "SELECT DISTINCT item FROM transactions WHERE COALESCE(item,'')!='' UNION "
            "SELECT DISTINCT item FROM ledger_entries WHERE COALESCE(item,'')!=''")})
        from app.decision_provenance import closed_review_ids
        data['closed_provenance_review'] = (sorted(closed_review_ids(conn)) if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='change_log'").fetchone() else [])
        conn.rollback()
    data['read_seconds'] = round(time.monotonic()-started, 3)
    return data


def tab(row):
    return row['display_tab_id'] if row['display_tab_id'] not in ('', None, 'unclassified') else row['trip_id']


def projection_disagreements(data):
    """Exclude existing ledger attribution conflicts before any P2 selection."""
    transactions = {r['transaction_id']: r for r in data['transactions']}
    return {r['transaction_id'] for r in data.get('ledger_entries', [])
            if r['transaction_id'] in transactions and any(
                r.get(key) != transactions[r['transaction_id']].get(key)
                for key in ('trip_id', 'display_tab_id'))}


def select(data):
    trips = {r['tab_id']: r for r in data['trip_tabs'] if not r['deleted']}
    opened = {k for k, v in trips.items() if v['starts_on'] >= '2026-06-30'}
    closed = set(trips)-opened
    manual = {r['transaction_id'] for r in data['review_decisions'] if r['item'] or r['display_tab_id'] not in ('', None, 'unclassified')}
    manual |= {r['row_id'][5:] for r in data['board_manual_overrides'] if r['row_id'].startswith('card-')}
    holds = {(r['transaction_id'], r['source_hash']) for r in data['transaction_review_holds']}
    exclusions = {(r['transaction_id'], r['source_hash']) for r in data['transaction_company_exclusions'] if r['excluded']}
    refunds = {(r['issuer'], r['card_tail'], r['original_approval_number']) for r in data['transactions']
               if r['original_approval_number'] and (r['transaction_direction'] in ('cancellation', 'refund') or (r['amount_krw'] or 0) < 0)}
    purchases = [r for r in data['transactions'] if r['transaction_direction']=='purchase' and (r['amount_krw'] or 0)>0]
    scope, eligible, protected = [], [], Counter()
    disagreements = projection_disagreements(data)
    for row in purchases:
        q = destination(row)
        if tab(row) not in opened and not (q and (q['year'], q['quarter']) >= (2026, 3)):
            continue
        scope.append(row)
        key = row['transaction_id'], row['source_hash']
        if row['transaction_id'] in set(data.get('closed_provenance_review', [])):
            reason = 'CLOSED_QUARTER_REVIEW_REQUIRED'
        elif row['transaction_id'] in disagreements:
            reason = 'PROJECTION_ATTRIBUTION_DISAGREEMENT'
        elif row['classification_source'] in MANUAL or row['decided_at'] is not None or row['transaction_id'] in manual:
            reason = 'manual'
        elif row['parse_error']:
            reason = 'PARSE_ERROR'
        elif row['duplicate_of'] or row['conflict_reason']:
            reason = 'DUPLICATE_OR_CONFLICT'
        elif _kind_is_cancel(row['transaction_kind']):
            reason = 'CANCELLATION_OR_REFUND'
        elif key in holds:
            reason = 'REVIEW_HOLD'
        elif key in exclusions:
            reason = 'COMPANY_EXCLUDED'
        elif row['approval_number'] and (row['issuer'], row['card_tail'], row['approval_number']) in refunds:
            reason = 'ORIGINAL_WITH_REFUND'
        else:
            reason = ''
        if reason:
            protected[reason] += 1
        else:
            eligible.append(row)
    general = [r for r in eligible if r['item'] in GENERAL]
    late = Counter(tab(r) for r in purchases if tab(r) in closed and (r['approval_date'] or '') >= '2026-06-30')
    report = dict(open_trips=len(opened), scope_purchases=len(scope),
        projection_attribution_disagreements=sum(r['transaction_id'] in disagreements for r in scope),
        open_trip_purchases=sum(tab(r) in opened for r in scope),
        quarter_other=sum(tab(r) not in opened for r in scope), protected=dict(protected), eligible=len(eligible),
        general_rows=len(general), general_merchants=len({r['merchant_normalized'] or r['merchant'] for r in general}),
        ota_inference=sum(r['classification_source'] in INFERRED and bool(provider_for_merchant(r['merchant'])) for r in eligible),
        early_card_open_trip=sum(tab(r) in opened and bool(r['approval_date']) and r['approval_date']<'2026-06-30' for r in purchases),
        missing_use_date_posted_before_boundary=sum(tab(r) in opened and not r['approval_date']
            and bool(r['posting_date']) and r['posting_date']<'2026-06-30' for r in purchases),
        late_card_closed_trip=sum(late.values()),
        # Trip display keys and counts only; never individual transaction identities.
        quarterly_review=[dict(trip=trips[k]['display_key'], count=n) for k,n in sorted(late.items())],
        read_seconds=data['read_seconds'])
    return report, scope, eligible, general


def service_warnings(data, rows):
    """Use the actual screen function on saved display rows, without a live Board.

    The in-memory OTA generation isn't available outside the server. Report that
    limitation explicitly instead of claiming its derived dates were inspected.
    """
    from datetime import date
    from webapp import ledger_design as design, read_scope
    board = {r['row_id']: json.loads(r['payload_json']) for r in data['board_rows']}
    periods = {r['tab_id']: (date.fromisoformat(r['starts_on']), date.fromisoformat(r['ends_on']) if r['ends_on'] else None)
               for r in data['trip_tabs'] if not r['deleted'] and r['starts_on']}
    memo = {'ledger_stay_evidence': {}, 'flight_service_dates': ({}, set()), 'trip_periods': periods}
    token = read_scope._MEMO.set(memo)
    counts, no_board, ids = Counter(), 0, []
    try:
        for source in rows:
            row = board.get('card-'+source['transaction_id'])
            if row is None:
                no_board += 1
                row = dict(row_id='card-'+source['transaction_id'], item=source['item'],
                           source_merchant=source['merchant'], amount_krw=source['amount_krw'],
                           occurred_on=source['approval_date'], display_tab_id=tab(source))
            # Current authoritative item, even if a stored projection is older.
            row = dict(row, item=source['item'])
            label, _ = design._service_date_labels(row)
            if label in design._UNKNOWN_SERVICE_DATES:
                counts[source['item']] += 1
                ids.append(source['transaction_id'])
    finally:
        read_scope._MEMO.reset(token)
    return dict(count=sum(counts.values()), by_item=dict(counts), missing_board_rows=no_board,
                basis='saved_display_rows_only; volatile_OTA_generation_not_read; upper_bound_for_live_screen'), ids
