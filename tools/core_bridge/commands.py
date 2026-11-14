"""Read-only bridge commands. Each takes a request dict and returns a JSON-able result."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .synthetic import scenario_db


class BridgeError(Exception):
    def __init__(self, code, detail=''):
        super().__init__(code)
        self.code, self.detail = code, detail


@contextmanager
def open_ro(path):
    """The only way the bridge opens a database: mode=ro, query_only, no writes."""
    target = Path(path).resolve()
    if not target.is_file():
        raise BridgeError('DB_NOT_FOUND')
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        conn.execute('PRAGMA query_only=ON')
        yield conn


@contextmanager
def _database(request):
    """A real database (read-only) or a synthetic scenario built in a temp directory."""
    if 'scenario' in request:
        with scenario_db(request['scenario']) as path, open_ro(path) as conn:
            yield conn, path
    elif request.get('db'):
        with open_ro(request['db']) as conn:
            yield conn, Path(request['db'])
    else:
        raise BridgeError('DB_OR_SCENARIO_REQUIRED')


def _trips(request, conn):
    if 'trips' in request:
        return request['trips']
    cursor = conn.execute('SELECT tab_id,display_key,destination,starts_on,ends_on FROM trip_tabs WHERE deleted=0')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r), trip_id=r[0]) for r in cursor]


def snapshot(request):
    """Input projection: the columns the planner reads, plus the P2 scope projection tables."""
    from tools.p2_batch.scope import read_projection
    path = request.get('db')
    if not path:
        raise BridgeError('DB_REQUIRED')
    if not Path(path).is_file():
        raise BridgeError('DB_NOT_FOUND')
    data = read_projection(path, completed_evidence=request.get('completed_evidence', {}))
    data.pop('read_seconds', None)
    return {'projection': data,
            'counts': {k: len(v) for k, v in data.items() if isinstance(v, list)}}


def facts(request):
    """Booking-period facts per card transaction. Needs registered sources (host) or a supplied report."""
    from tools.complete_card_classification import load_review_evidence
    with _database(request) as (conn, _path):
        trips = _trips(request, conn)
        if 'report' in request:
            evidence, summary = load_review_evidence(conn, None, trips, report=request['report'])
        elif request.get('host'):
            evidence, summary = load_review_evidence(conn, Path(request['host']), trips)
        else:
            raise BridgeError('HOST_OR_REPORT_REQUIRED')
    return {'evidence': evidence, 'summary': summary}


def links(request):
    """kind=refund: refund pairing from a DB or scenario. kind=ota: OTA-to-card matching of given events/cards."""
    kind = request.get('kind')
    if kind == 'refund':
        from app import partial_refund as pr
        with _database(request) as (conn, _path):
            ids = request.get('transaction_ids')
            if ids is None:
                ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions ORDER BY transaction_id')]
            found = pr.refund_links(conn, ids)
            originals = sorted({link['original_id'] for link in found.values()})
            return {'links': found,
                    'groups': {o: pr.refund_group(conn, o) for o in originals},
                    'group_exclusions': {o: pr.partial_group_exclusion(conn, o) for o in originals},
                    'held': pr.count_held_cancellations(conn),
                    'review_originals': pr.refund_review_originals(conn)}
    if kind == 'refund_group':
        return _refund_group(request)
    if kind == 'ota':
        from app.ota_payments import match_ota_payment_events
        results = match_ota_payment_events(request['events'], request['transactions'],
                                           existing_links=request.get('existing_links'),
                                           rules=request.get('rules'),
                                           frozen_groups=request.get('frozen_groups'))
        return {'results': results}
    raise BridgeError('LINKS_KIND_INVALID', str(kind))


def candidates(request):
    """OTA 후보 단계(M3 U13): 이벤트별 후보 카드, 카드별 쌍 검사 코드, 진단 탐색. 연결은 만들지 않는다."""
    from app import ota_payments as op
    from app.ota_matching_defaults import provider_resolution_scope
    cards, rules, links = request['transactions'], request.get('rules') or [], request.get('existing_links') or {}
    out = []
    with provider_resolution_scope():
        for event in request['events']:
            out.append({
                'ota_event_id': event.get('ota_event_id'),
                'eligible': [row['transaction_id'] for row in op._eligible_cards(event, cards, rules=rules)],
                'pair_check': {str(row['transaction_id']): op.pair_check(event, row, rules) for row in cards},
                'search': op.search_card_candidates(event, cards, existing_links=links, rules=rules)})
    return {'events': out}


def _refund_group(request):
    """Refund-group judgement on a scenario: batch selection (_ready_rows), pair judgement (_apply_refund_pairs),
    half-booked check (_check_refund_groups) and verified group scope (scope_group). Nothing is written."""
    from types import SimpleNamespace
    from app import ledger
    from app import partial_refund as pr
    from app.db import StoreError
    with _database(request) as (conn, _path):
        store = SimpleNamespace(conn=conn)
        out = {}
        if request.get('batch_id'):
            picked = ledger._ready_rows(store, request['batch_id'],
                                        include_verified_full_refunds=bool(request.get('extension')))
            out['selected'] = sorted(r[0] for r in picked)
        booked = {r[0] for r in conn.execute('SELECT transaction_id FROM ledger_entries')}
        scenario_rows = {r[0]: r for r in conn.execute(
            "SELECT transaction_id, source_hash, amount_krw, COALESCE(NULLIF(approval_date,''),posting_date)"
            " FROM transactions")}
        entries = []
        for spec in request.get('entries', []):
            entry = {'item': '', 'description': '', 'display_tab_id': '', 'trip_id': '', **spec,
                     'already_booked': spec['transaction_id'] in booked}
            _, entry['source_hash'], entry['amount_krw'], entry['occurred_on'] = scenario_rows[spec['transaction_id']]
            if entry.get('blocked'):
                entry['reason'] = 'synthetic hold'
            entries.append(entry)
        ready = [e for e in entries if not e.get('blocked')]
        unresolved = [e for e in entries if e.get('blocked')]
        trips, tabs = request.get('valid_trips'), request.get('valid_tabs')
        ledger._apply_refund_pairs(store, entries, ready, unresolved,
                                   None if trips is None else (lambda t: t in trips),
                                   None if tabs is None else (lambda t: t in tabs))
        try:
            ledger._check_refund_groups(store, entries)
            out['group_check'] = ''
        except StoreError as exc:
            out['group_check'] = exc.code
        keys = ('transaction_id', 'blocked', 'reason', 'item', 'description', 'display_tab_id', 'trip_id',
                'refund_link')
        out['entries'] = [dict({k: e.get(k) for k in keys}, bucket='ready' if any(e is r for r in ready) else 'unresolved')
                          for e in entries]
        links = pr.refund_links(conn, list(scenario_rows))
        out['links'] = links
        out['group_exclusions'] = {link['original_id']: pr.partial_group_exclusion(conn, link['original_id'])
                                   for link in links.values()}
        scope = {}
        for original in sorted({link['original_id'] for link in links.values()}):
            try:
                scoped = ledger.scope_group(store, {'rows': [dict(e) for e in entries], 'batch_id': 'syn-batch',
                                                    'version': 'v'}, original, require_verified_zero=True)
                scope[original] = {'code': '', 'recordable': scoped['recordable']}
            except StoreError as exc:
                scope[original] = {'code': exc.code, 'recordable': False}
        out['scope'] = scope
        return out


def plan(request):
    """app.automatic_classification.plan on a DB or scenario. Nothing is applied."""
    from app import automatic_classification as policy
    with _database(request) as (conn, _path):
        before = conn.total_changes
        result = policy.plan(conn, _trips(request, conn), transaction_ids=request.get('transaction_ids'),
                             reconsider=bool(request.get('reconsider')), evidence=request.get('evidence'),
                             nets=request.get('nets'))
        if conn.total_changes != before:
            raise BridgeError('PLAN_WROTE_DATA')
    return result


def _pick(hint, trips):
    wanted = hint.get('inferred_trip_id') if isinstance(hint, dict) else None
    return wanted if wanted in trips else trips[0]


def classify(request):
    """app.classify.classify_transaction for synthetic transactions with given rules (no DB)."""
    from app.classify import classify_transaction
    out = []
    for case in request['cases']:
        trips = case.get('trip_ids', [])
        resolver = (lambda txn, hint, _t=trips: _pick(hint, _t)) if trips else None
        out.append(classify_transaction(case['transaction'], rules=case.get('rules', []),
                                        prior_decision=case.get('prior_decision'), trip_resolver=resolver,
                                        residual_policy=bool(case.get('residual_policy'))))
    return {'verdicts': out}


def extract(request):
    """Reference output of the Python extractors: payment facts from messages, or events from sources."""
    from app import ota_payments
    kind = request.get('kind')
    if kind == 'message':
        return {'facts': [ota_payments.extract_payment_fact(m) for m in request['messages']]}
    if kind == 'sources':
        return {'events': ota_payments.build_ota_payment_events(request['sources'])}
    raise BridgeError('EXTRACT_KIND_INVALID', str(kind))


def trips(request):
    """Pure trip attribution (no DB): infer_trip, candidates, stay_trip, booking_trip, card3820, infer_item."""
    from types import SimpleNamespace
    from app import automatic_classification as policy
    from app import provisional_assignment as provisional
    from app import reconciliation as rc
    op, rows = request.get('op'), request.get('trips', [])
    nets = request.get('nets')
    if op == 'infer_trip':
        trip, basis = policy.infer_trip(request['row'], rows, nets=nets, reconsider=bool(request.get('reconsider')),
                                        completed_evidence=request.get('completed_evidence'))
        return {'trip_id': trip, 'basis': basis}
    if op == 'candidates':
        return {'candidates': provisional.card_trip_candidates(request['row'], rows, nets=nets)}
    if op == 'stay_trip':
        chosen = rc.stay_trip(rows, request['check_in'], request['check_out'],
                              service=bool(request.get('service')), nets=nets)
        return {'tab_id': chosen['tab_id'] if chosen else None}
    if op == 'booking_trip':
        from webapp.card_trip_authority import booking_trip
        flow = SimpleNamespace(board=SimpleNamespace(list_trips=lambda: rows), trip_valid=lambda tab_id: True)
        period = dict(starts_on=request['check_in'], ends_on=request['check_out'], service=bool(request.get('service')),
                      target_code=request.get('target_code'))
        return {'tab_id': booking_trip(flow, request['row'], period, google_nets=lambda: nets or {},
                                       handover_days=rc.handover_days, overlaps_stay=rc.overlaps_stay,
                                       stay_trip=rc.stay_trip)}
    if op == 'card3820':
        return {'policy': policy._card3820_owner_policy(request['row'], rows)}
    if op == 'infer_item':
        item, basis = policy.infer_item(request['row'])
        return {'item': item, 'basis': basis}
    raise BridgeError('TRIPS_OP_INVALID', str(op))


def periods(request):
    """Booking-period inputs for the Rust period rule plus the Python verified period per row (no DB)."""
    from .periods import periods as run
    return run(request)


COMMANDS = {'snapshot': snapshot, 'facts': facts, 'links': links, 'candidates': candidates, 'plan': plan,
            'classify': classify, 'extract': extract, 'trips': trips, 'periods': periods}


def canonical(value):
    """Stable JSON-able form: sorted sets, str() for anything else non-JSON."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else str(v)))
