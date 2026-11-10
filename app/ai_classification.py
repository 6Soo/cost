"""Local connected-agent P2 review, after code classification (P1).

No model service, original-text export, human decision, financial-link write or
schema migration. A response is bound to the code result and actual trip set.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from . import automatic_classification as code
from . import classification_correction as correction
from .classification_provenance import CODE_SOURCES
from .provisional_assignment import canonical_trip_periods, card_trip_candidates
from .trip_selection import regional_trips

VERSION = 'connected-agent-inference-v1'
ITEMS = ('주차비', '주유비', '통행료', '항공료', '렌터카', '숙박비', '식비',
         '편의점', '교통비', '입장료', '여행경비', '현지경비', '기타경비')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()


def prepare(conn, trips, transaction_ids, *, reconsider=False, nets=None):
    """Read only, bounded, derived facts for a local AI agent; never raw rows."""
    selected = set(transaction_ids)
    if not selected or len(selected) > 50:
        raise ValueError('AI_SCOPE_REQUIRED_MAX_50')
    if code.plan(conn, trips, transaction_ids=selected, nets=nets)['targets']:
        raise ValueError('CODE_STAGE_REQUIRED')
    valid = canonical_trip_periods(trips)
    rules = conn.execute("SELECT optional_json,origin,rule_hash FROM cost_classification_rules WHERE status='active' ORDER BY rule_id").fetchall()
    authoritative = {json.loads(optional).get('source_hash') for optional, origin, _ in rules
                     if origin in ('owner-ota-booking','auto-ota-period','ota-mail-live','ota-portal-live','guide-airfare-live')}
    rows = code._read(conn, selected)
    if len(rows) != len(selected):
        raise ValueError('AI_SOURCE_MISSING')
    cases, protected = [], 0
    for row in rows:
        tid = row['transaction_id']
        if row['source_hash'] in authoritative:
            protected += 1
            continue
        if row['classification_source'] not in CODE_SOURCES | {'ai_inference'}:
            # Exact/manual booking, airfare and refund authority stay in P1.
            # P2 is an attribution review, never a replacement payment matcher.
            protected += 1
            continue
        if row['classification_source'] == 'ai_inference' and not reconsider:
            continue
        weak = (row['classification_source'] in CODE_SOURCES
                and row['item'] in ('기타경비', '현지경비', '여행경비'))
        if not reconsider and not weak and row['classification_state'] == 'classified' and row['trip_id'] in valid:
            continue
        candidates = regional_trips(row, valid.values(), booking_agnostic=True)
        if '예약 이용기간' in str(row.get('classification_basis') or '') and row['trip_id'] in valid:
            candidates = [valid[row['trip_id']]]
        allowed = {trip['trip_id'] for trip in candidates}
        if not allowed:
            continue  # An AI cannot invent an actual trip.
        target = row['trip_id'] if row['trip_id'] in allowed else sorted(allowed)[0]
        probe = dict(transaction_id=tid, source_hash=row['source_hash'], revision=row['revision'],
                     trip_id=target, item=row['item'] or '기타경비', basis='eligibility check')
        try:
            binding = correction.preview(conn, [probe], trips)['digest']
        except ValueError as exc:
            if str(exc) != 'CORRECTION_PROTECTED' and str(exc) != 'CORRECTION_REQUIRES_PURCHASE':
                raise
            protected += 1
            continue
        ranking = card_trip_candidates(row, candidates, nets=nets)
        # Identity and amounts remain local, and no names, raw text, PAN or booking
        # references are included. Only derived classification facts are exported.
        cases.append(dict(transaction_id=tid, source_hash=row['source_hash'], revision=row['revision'],
            binding=binding, code_item=row['item'], code_trip=row['trip_id'],
            service_item=code.infer_item(dict(row, item=''))[0],
            country=code.merchant_country(row),
            occurred_on=row['approval_date'] or '',
            allowed_items=sorted(set(ITEMS) | {row['item']} - {''}),
            trips=[dict(trip_id=key, starts_on=valid[key]['starts_on'], ends_on=valid[key]['ends_on'],
                        destination=valid[key].get('destination', ''),
                        code_score=next((r['score'] for r in ranking if r['trip_id'] == key), 0))
                   for key in sorted(allowed)]))
    request = dict(version=VERSION, reconsider=bool(reconsider), scope=sorted(selected), cases=cases,
                   protected=protected, trip_context=_digest(trips), nets_context=_digest(nets or {}),
                   rules_context=_digest(rules))
    return dict(request, digest=_digest(request))


def _p2_metadata(conn, request, response, bundle):
    from . import p2_case
    if response.get('more_evidence'):
        raise ValueError('AI_MORE_EVIDENCE_PENDING')
    if (bundle.get('request_digest') != request['digest']
            or bundle.get('digest') != p2_case.digest({k: v for k, v in bundle.items() if k != 'digest'})):
        raise ValueError('AI_CASE_INVALID')
    current = {r['transaction_id']: p2_case.sanitize(r) for r in code._read(
        conn, [c['transaction_id'] for c in request['cases']])}
    if any(current.get(c['transaction_id']) != c['transaction'] for c in bundle['cases']):
        raise ValueError('AI_CASE_STALE')
    if p2_case.policy_context(bundle['policy'].keys() - {'CORE'}) != bundle['policy']:
        raise ValueError('AI_POLICY_STALE')
    refs = {}
    for evidence in bundle['evidence']:
        refs.setdefault(evidence['transaction_id'], set()).add(evidence['ref'])
    rule_ids = set(re.findall(r'\b[A-Z]+-\d{3}\b', p2_case.encoded(bundle['policy'])))
    expected_keys = {'transaction_id','trip_id','item','service_start','service_end',
                     'evidence_refs','basis','uncertainty','rule_ids'}
    metadata = {}
    if set(response) != {'request_digest', 'execution', 'results', 'more_evidence'}:
        raise ValueError('AI_RESPONSE_SCHEMA_INVALID')
    if not isinstance(response['more_evidence'], list) or not isinstance(response['results'], list):
        raise ValueError('AI_RESPONSE_SCHEMA_INVALID')
    for result in response['results']:
        if not isinstance(result, dict) or set(result) != expected_keys:
            raise ValueError('AI_RESPONSE_SCHEMA_INVALID')
        start, end = result['service_start'], result['service_end']
        try:
            if any(not isinstance(d, str) or (d and (len(d) != 10 or date.fromisoformat(d).isoformat() != d)) for d in (start, end)):
                raise ValueError()
            if bool(start) != bool(end) or (start and end < start):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('AI_SERVICE_PERIOD_INVALID') from None
        if not start and not result['uncertainty']:
            raise ValueError('AI_SERVICE_UNCERTAINTY_REQUIRED')
        for key, allowed in (('evidence_refs', refs.get(result['transaction_id'], set())), ('rule_ids', rule_ids)):
            value = result[key]
            if (not isinstance(value, list) or len(value) > 32
                    or any(not isinstance(v, str) or v not in allowed for v in value)
                    or len(set(value)) != len(value)):
                raise ValueError('AI_EVIDENCE_INVALID')
        metadata[result['transaction_id']] = dict(
            service_start=start, service_end=end, evidence_refs=result['evidence_refs'],
            rule_ids=result['rule_ids'], uncertainty=result['uncertainty'], case_digest=bundle['digest'])
    return metadata


def preview(conn, trips, request, response, *, nets=None, bundle=None):
    """Validate an actual agent result, not a relabelled deterministic fallback."""
    if (request.get('version') != VERSION or response.get('request_digest') != request.get('digest')
            or request.get('digest') != _digest({k: v for k, v in request.items() if k != 'digest'})):
        raise ValueError('AI_REQUEST_INVALID')
    ids = [case['transaction_id'] for case in request['cases']]
    metadata = _p2_metadata(conn, request, response, bundle) if bundle is not None else {}
    current = prepare(conn, trips, request['scope'], reconsider=request['reconsider'], nets=nets)
    if current != request:
        raise ValueError('AI_REQUEST_STALE')
    execution = response.get('execution') or {}
    if (execution.get('kind') != 'connected_agent'
            or any(not isinstance(execution.get(k), str) or not execution[k].strip()
                   or len(execution[k]) > 160 for k in ('provider', 'model', 'run_id'))):
        raise ValueError('AI_EXECUTION_REQUIRED')
    results = response.get('results')
    if not isinstance(results, list) or len(results) != len(ids):
        raise ValueError('AI_RESULTS_INCOMPLETE')
    by_id = {case['transaction_id']: case for case in request['cases']}
    fixes, seen = [], set()
    for result in results:
        tid = result.get('transaction_id')
        if tid not in by_id or tid in seen:
            raise ValueError('AI_SCOPE_INVALID')
        seen.add(tid)
        case = by_id[tid]
        if (result.get('trip_id') not in {t['trip_id'] for t in case['trips']}
                or result.get('item') not in case['allowed_items']):
            raise ValueError('AI_ATTRIBUTION_INVALID')
        if (not isinstance(result.get('basis'), str) or not result['basis'].strip()
                or len(result['basis']) > 2000
                or not isinstance(result.get('uncertainty'), str) or len(result['uncertainty']) > 500):
            raise ValueError('AI_REASON_REQUIRED')
        fixes.append(dict(transaction_id=tid, source_hash=case['source_hash'], revision=case['revision'],
                          trip_id=result['trip_id'], item=result['item'],
                          basis=result['basis'] + (' · 불확실성: ' + result['uncertainty'] if result['uncertainty'] else ''),
                          classification_source='ai_inference',
                          execution={key: execution[key] for key in ('kind','provider','model','run_id')}))
        if tid in metadata:
            fixes[-1]['p2_metadata'] = metadata[tid]
    expected = correction.preview(conn, fixes, trips)
    return dict(expected, corrections=fixes, request_digest=request['digest'])


def apply(conn, trips, request, response, *, request_id, nets=None, bundle=None):
    """Revalidate and atomically apply AI provenance, attribution and audit."""
    payload = _digest([request, response, bundle]) if bundle is not None else _digest([request, response])
    nested = conn.in_transaction
    conn.execute('SAVEPOINT ai_classification' if nested else 'BEGIN IMMEDIATE')
    try:
        previous = conn.execute("SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope='ai_classification'", (request_id,)).fetchone()
        if previous:
            if previous[0] != payload:
                raise ValueError('AI_REQUEST_CONFLICT')
            result = dict(json.loads(previous[1]), applied=0, replay=True)
        else:
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError('AI_REQUEST_ID_REQUIRED')
            expected = preview(conn, trips, request, response, nets=nets, bundle=bundle)
            result = correction.apply(conn, expected, expected['corrections'], trips,
                                      request_id='ai:' + request_id)
            result['digest'] = expected['digest']
            from .db import utc_now
            conn.execute('INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES (?,?,?,?,?)',
                         (request_id, 'ai_classification', payload, json.dumps(result), utc_now()))
        conn.execute('RELEASE SAVEPOINT ai_classification' if nested else 'COMMIT')
        return result
    except BaseException:
        if nested:
            conn.execute('ROLLBACK TO SAVEPOINT ai_classification')
            conn.execute('RELEASE SAVEPOINT ai_classification')
        else:
            conn.rollback()
        raise
