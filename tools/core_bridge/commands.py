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
    if kind == 'ota':
        from app.ota_payments import match_ota_payment_events
        results = match_ota_payment_events(request['events'], request['transactions'],
                                           existing_links=request.get('existing_links'),
                                           rules=request.get('rules'),
                                           frozen_groups=request.get('frozen_groups'))
        return {'results': results}
    raise BridgeError('LINKS_KIND_INVALID', str(kind))


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


COMMANDS = {'snapshot': snapshot, 'facts': facts, 'links': links, 'plan': plan,
            'classify': classify, 'extract': extract}


def canonical(value):
    """Stable JSON-able form: sorted sets, str() for anything else non-JSON."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else str(v)))
