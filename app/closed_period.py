"""PROC-072: completed card periods are a boundary before classification.

An inferred destination, provenance label, or booking candidate is never proof
of an exception. Callers may supply source-bound, formally linked service facts.
"""
from datetime import date
import hashlib
import json


def completed_period(row):
    raw = row.get('approval_date') or row.get('posting_date') or ''
    try:
        day = date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if day.year == 2025:
        return '2025'
    if date(2026, 1, 1) <= day <= date(2026, 3, 31):
        return '2026Q1'
    return None


def trip_map(trips):
    return {str(t.get('trip_id') or t.get('tab_id')): t for t in trips}


def open_trip(trip):
    return bool(trip and not trip.get('deleted') and not trip.get('archived')
                and (trip.get('starts_on') or '') >= '2026-06-30')


def completed_trip(trip):
    day = (trip or {}).get('starts_on') or ''
    return '2025-01-01' <= day <= '2026-03-31'


def exception_trip(row, trips, *, evidence=None, manual=False, valid=None):
    valid = trip_map(trips) if valid is None else valid
    current = row.get('trip_id') or row.get('display_tab_id')
    if manual and open_trip(valid.get(current)):
        return current
    fact = evidence or {}
    target = fact.get('trip_id')
    trip = valid.get(target)
    period = fact.get('service_period') or {}
    start, end = period.get('starts_on'), period.get('ends_on')
    if (fact.get('formal_link') is True and row.get('source_hash')
            and fact.get('source_hash') == row['source_hash'] and open_trip(trip)
            and start and end and trip.get('ends_on')
            and trip['starts_on'] <= start <= end <= trip['ends_on']):
        return target
    return None


def excluded(row, trips=(), *, evidence=None, manual=False, valid=None):
    if not completed_period(row):
        return False
    valid = trip_map(trips) if valid is None else valid
    closed_quarters = {'quarter:2025:'+str(n) for n in range(1,5)} | {'quarter:2026:1'}
    if any(row.get(k) in closed_quarters for k in ('trip_id','display_tab_id')):
        return True
    # Submitted historical travel ledgers are immutable even with later facts.
    if any(completed_trip(valid.get(row.get(k))) for k in ('trip_id', 'display_tab_id')):
        return True
    return not exception_trip(row, trips, evidence=evidence, manual=manual, valid=valid)


def recoverable_unrecorded_booking(row, trips, *, evidence=None, recorded=True, manual=False):
    """An unposted calendar guess is not a submitted historical ledger.

    Only a source-bound formal booking for an open trip can cross the period
    boundary. Callers must positively verify absence from BOTH ledger stores;
    unknown recording state is protected by default. No booking is inferred here.
    """
    if (recorded or manual or not completed_period(row)
            or row.get('decided_at') is not None
            or row.get('classification_source') not in ('', 'rule', 'inference', 'code_inference', 'auto_inferred')
            or row.get('transaction_direction') != 'purchase'
            or type(row.get('amount_krw')) is not int or row['amount_krw'] <= 0
            or any(row.get(k) for k in ('parse_error', 'conflict_reason', 'duplicate_of'))):
        return False
    fact = evidence or {}
    period = fact.get('service_period') or {}
    try:
        date.fromisoformat(period.get('starts_on', ''))
        date.fromisoformat(period.get('ends_on', ''))
    except (TypeError, ValueError):
        return False
    return bool(exception_trip(row, trips, evidence=fact))


def manual_ids(conn):
    from .decision_provenance import active_decision_sql
    ids = {r[0] for r in conn.execute('SELECT d.transaction_id FROM review_decisions d WHERE ('
        "COALESCE(d.item,'')!='' OR COALESCE(d.display_tab_id,'') NOT IN ('','unclassified')) AND "
        + active_decision_sql(conn=conn))}
    from .manual_overrides import manual_rows
    ids.update(row_id[5:] for row_id in manual_rows(conn) if row_id.startswith('card-'))
    return ids


def formal_facts(facts, trips):
    """Only exact central links with a contained actual service period qualify."""
    from .provisional_assignment import ota_service_period_candidate
    grouped = {}
    for fact in facts:
        tid, period = fact.get('transaction_id'), fact.get('period') or {}
        if (not tid or not fact.get('core_link') or fact.get('inferred_link')
                or fact.get('service_period_basis') == 'LINK-108'
                or fact.get('reservation_status') not in ('confirmed','completed','observed')
                or any(fact.get(k) for k in ('period_conflict','service_period_conflict','evidence_changed','evidence_missing'))
                or not fact.get('source_sha256') or not period.get('starts_on') or not period.get('ends_on')):
            continue
        candidates = ota_service_period_candidate({'service_period':period},trips)
        if len(candidates) != 1:
            continue
        value = dict(source_hash=fact.get('source_hash'), trip_id=candidates[0]['trip_id'],
                     service_period=dict(period), formal_link=True,
                     evidence_digest=hashlib.sha256(json.dumps(fact,sort_keys=True,default=str).encode()).hexdigest())
        grouped.setdefault(tid,[]).append(value)
    return {tid: values[0] for tid,values in grouped.items()
            if all(v == values[0] for v in values)}


BOOKING_STATUSES = ('confirmed', 'completed', 'observed')


def booking_period_evidence(matches, rows, trips, *, confirmed_only=True):
    """Source-bound unique reservation-period facts for purchases (TRIP-036/041/062).

    With ``confirmed_only`` (production) only confirmed statuses count; cancelled, unknown or empty never do. Returns
    ``(evidence, conflict_count)`` and reads nothing but its arguments.
    """
    from collections import defaultdict
    from .provisional_assignment import ota_service_period_candidate
    formal = formal_facts(matches, trips)
    candidates = defaultdict(list)
    for fact in matches:
        row = rows.get(fact.get('transaction_id'))
        if (not row or row['source_hash'] != fact.get('source_hash')
                or row['transaction_direction'] != 'purchase'
                or (fact.get('reservation_status') not in BOOKING_STATUSES if confirmed_only
                    else fact.get('reservation_status') == 'cancelled')
                or fact.get('period_conflict') or fact.get('service_period_conflict')):
            continue
        period = fact.get('period') or fact.get('service_period')
        if not isinstance(period, dict) or not period.get('starts_on') or not period.get('ends_on'):
            continue
        options = ota_service_period_candidate({'service_period': period}, trips)
        if len(options) == 1:
            candidates[row['transaction_id']].append(dict(
                source_hash=row['source_hash'], trip_id=options[0]['trip_id'],
                item=fact.get('item') or '',
                basis='보관 예약 이용기간 ' + period['starts_on'] + '~' + period['ends_on'] + ' · 비용 귀속 추론이며 결제 연결 미확정',
                evidence_digest=hashlib.sha256(json.dumps(fact, sort_keys=True, default=str).encode()).hexdigest(),
                service_period=dict(period), formal_link=row['transaction_id'] in formal))
    evidence, conflicts = {}, 0
    for tid, options in candidates.items():
        if len({option['trip_id'] for option in options}) != 1:
            conflicts += 1
            continue
        evidence[tid] = sorted(options, key=lambda option: option['evidence_digest'])[0]
    return evidence, conflicts


def open_scope(row, trips):
    valid = trip_map(trips)
    return (any(open_trip(valid.get(row.get(k))) for k in ('trip_id','display_tab_id'))
            or (row.get('approval_date') or row.get('posting_date') or '') >= '2026-06-30')


def excluded_ids(conn, trips=(), *, evidence=None):
    """Narrow projection for review counters; never read customer source blobs."""
    fields = ('transaction_id','source_hash','approval_date','posting_date','trip_id','display_tab_id',
              'classification_source','decided_at','transaction_direction','amount_krw',
              'parse_error','conflict_reason','duplicate_of')
    available = {r[1] for r in conn.execute('PRAGMA table_info(transactions)')}
    # Legacy read projections contain the six source/destination columns only.
    # Missing optional recovery metadata cannot prove a booking exception.
    selection = list(fields[:6]) + [f if f in available else 'NULL AS ' + f for f in fields[6:]]
    rows = [dict(zip(fields,r)) for r in conn.execute('SELECT '+','.join(selection)+' FROM transactions')]
    completed = [r for r in rows if completed_period(r)]
    if not completed:
        return set()
    manual, valid = manual_ids(conn), trip_map(trips)
    recorded = {r[0] for r in conn.execute('SELECT transaction_id FROM ledger_entries')}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_rows'").fetchone():
        recorded.update(r[0][5:] for r in conn.execute("SELECT row_id FROM board_rows WHERE row_id LIKE 'card-%'"))
    return {r['transaction_id'] for r in completed
            if excluded(r,trips,evidence=(evidence or {}).get(r['transaction_id']),manual=r['transaction_id'] in manual,valid=valid)
            and not recoverable_unrecorded_booking(r,trips,evidence=(evidence or {}).get(r['transaction_id']),
                recorded=r['transaction_id'] in recorded,manual=r['transaction_id'] in manual)}
