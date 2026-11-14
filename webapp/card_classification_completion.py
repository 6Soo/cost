"""Shared final inference stage for current and future imported card transactions."""
from app import automatic_classification as policy


def missing_assignment_sql(alias='t'):
    """An automatic category alone cannot complete an ordinary trip expense."""
    return (f"({alias}.classification_state='classified'"
            f" AND COALESCE({alias}.item,'') NOT IN ('','분기 기타비용')"
            f" AND COALESCE({alias}.classification_source,'')!='guide_airfare_evidence'"
            f" AND COALESCE({alias}.display_tab_id,'') IN ('','unclassified')"
            f" AND COALESCE({alias}.trip_id,'') IN ('','unclassified'))")


def context(flow):
    from .card_flow import _google_nets
    trips = [dict(trip, trip_id=trip['tab_id']) for trip in flow.board.list_trips()
             if flow.trip_valid(trip['tab_id'])]
    return trips, _google_nets()


def completed_period_evidence(board, trips=None, flow=None):
    """Read only the fresh published core; no match recomputation or source writes."""
    from app.closed_period import completed_period, formal_facts
    dates = board.conn.execute('SELECT transaction_id,approval_date,posting_date FROM transactions').fetchall()
    completed = {r[0] for r in dates if completed_period(dict(zip(('approval_date','posting_date'),r[1:])))}
    if not completed:
        return {}
    from .card_flow import CardFlow
    flow = flow or CardFlow(board)
    current,fresh = flow._held_ota_snapshot()
    if not current or not fresh:
        return {}
    if trips is None:
        trips = [dict(t,trip_id=t['tab_id']) for t in board.list_trips() if flow.trip_valid(t['tab_id'])]
    return {k:v for k,v in formal_facts(flow._canonical_snapshot_report(current).get('matches',[]),trips).items()
            if k in completed}


def open_period_evidence(board, trips=None, flow=None):
    """Confirmed reservation periods for open-period purchases; read-only, fresh core snapshot only."""
    from app.closed_period import booking_period_evidence, completed_period
    from app import automatic_classification as policy
    from .card_flow import CardFlow
    flow = flow or CardFlow(board)
    current, fresh = flow._held_ota_snapshot()
    if not current or not fresh:
        return {}
    if trips is None:
        trips = [dict(t, trip_id=t['tab_id']) for t in board.list_trips() if flow.trip_valid(t['tab_id'])]
    matches = flow._canonical_snapshot_report(current).get('matches', [])
    ids = {m.get('transaction_id') for m in matches if m.get('transaction_id')}
    if not ids:
        return {}
    rows = {r['transaction_id']: r for r in policy._read(board.conn, ids)}
    found, _ = booking_period_evidence(matches, rows, trips)
    return {k: v for k, v in found.items() if not completed_period(rows[k])}


def classification_evidence(board, trips=None, flow=None):
    """Closed-period exceptions plus open-period booking evidence; the two key sets are disjoint."""
    return {**open_period_evidence(board, trips, flow), **completed_period_evidence(board, trips, flow)}


def complete(flow, batch_id, transaction_ids=None):
    selected = {row[0] for row in flow.board.conn.execute(
        'SELECT transaction_id FROM import_batch_rows WHERE batch_id=?', (batch_id,))}
    if transaction_ids is not None:
        selected.intersection_update(transaction_ids)
    return complete_scope(flow, selected)


def complete_scope(flow, selected=None):
    from app import core_writer
    rust = core_writer.selected() == 'rust'
    for attempt in (0, 1):
        # The Rust writer's period evidence can take minutes when cold; build it before taking the board lock.
        periods, key = core_writer.periods_with_key(flow.board.conn, flow.board._lock) if rust else (None, None)
        with flow.board._lock:
            if rust and core_writer.periods_key(flow.board.conn) != key:
                continue  # the evidence inputs moved while it was built; rebuild once, then fail
            trips, nets = context(flow)
            evidence = classification_evidence(flow.board,trips,flow)
            preview = policy.plan(flow.board.conn, trips, nets=nets, transaction_ids=selected,evidence=evidence)
            return policy.apply(flow.board.conn, preview, trips, nets=nets, transaction_ids=selected,
                                evidence=evidence, periods=periods)
    raise ValueError('CLASSIFICATION_PREVIEW_STALE')

def correct_recorded_booking_periods(flow, batch_id, transaction_ids=None):
    """An explicit classification write may repair an old automatic calendar guess.

    Only the fresh central match supplies dates. Reading a board, restarting a
    server, or completing an unrelated import never migrates recorded expenses.
    """
    conn = flow.board.conn
    selected = {row[0] for row in conn.execute(
        "SELECT t.transaction_id FROM import_batch_rows r JOIN transactions t USING(transaction_id)"
        " WHERE r.batch_id=? AND t.classification_source='inference'"
        " AND EXISTS(SELECT 1 FROM board_rows b WHERE b.row_id='card-'||t.transaction_id)", (batch_id,))}
    if transaction_ids is not None:
        selected.intersection_update(transaction_ids)
    if not selected:
        return 0
    current, fresh = flow._held_ota_snapshot()
    if not current or not fresh:
        return 0
    report = flow._canonical_snapshot_report(current)
    facts = report.get('matches', [])
    blocked_sources = set(report.get('evidence_gate', {}).get('blocked_inference_sources', ()))
    events = {str(e.get('ota_event_id')): e for e in (current.get('data') or {}).get('events', [])}
    from app.ota_payments import _event_is_paid
    choices = {}
    blocked = set()
    for fact in facts:
        tid = fact.get('transaction_id')
        if tid not in selected:
            continue
        period = fact.get('period') or {}
        event = events.get(str(fact.get('ota_event_id')), {})
        if (event.get('event_type') != 'charge' or not _event_is_paid(event)
                or event.get('refund_status') not in (None, '', 'none_displayed')
                or fact.get('source_hash') in blocked_sources
                or fact.get('reservation_status') not in ('confirmed', 'completed', 'observed')
                or fact.get('period_conflict') or fact.get('service_period_conflict')
                or not period.get('starts_on') or not period.get('ends_on')
                or not fact.get('source_sha256')):
            blocked.add(tid)
            continue
        row = next(iter(policy._read(conn, {tid})), None)
        if not row or row['source_hash'] != fact.get('source_hash'):
            blocked.add(tid)
            continue
        trip = flow.booking_trip(row, dict(period, service=fact.get('item') != '숙박비'))
        evidence = dict(source_hash=fact['source_hash'], trip_id=trip, item=fact.get('item') or '',
                        basis=f"검증된 예약 이용기간 {period['starts_on']}~{period['ends_on']}",
                        service_period=dict(period),formal_link=bool(fact.get('core_link') and not fact.get('inferred_link')
                                                                   and fact.get('service_period_basis') != 'LINK-108'))
        if not trip or (tid in choices and choices[tid] != evidence):
            blocked.add(tid)
        choices[tid] = evidence
    evidence = {tid: value for tid, value in choices.items() if tid not in blocked}
    if not evidence:
        return 0
    trips, nets = context(flow)
    options = dict(nets=nets, transaction_ids=set(evidence), reconsider=True, evidence=evidence)
    preview = policy.plan(conn, trips, **options)
    policy.apply(conn, preview, trips, **options)
    return sum(bool(target.get('booking_trip_correction')) for target in preview['targets'])
