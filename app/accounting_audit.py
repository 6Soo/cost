"""Read-only accounting invariants across source cards and saved projections.

Findings are evidence to investigate, never instructions to move money or rows.
Manual decisions are inspected as well; they do not make a source discrepancy
disappear. Their history is reported separately from financial corruption.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import json

from .closed_period import completed_period


def audit_cards(transactions, ledger_entries, board_rows, trips, *, manual_fields=()):
    findings = []
    locked = set(manual_fields)
    known_trips = {str(t.get('tab_id') or t.get('trip_id')): t for t in trips}

    def finding(code, identity, *, category='inconsistency', fields=()):
        findings.append(dict(code=code, identity=identity, category=category, fields=list(fields)))

    def index(rows, key, kind):
        result = {}
        for row in rows:
            identity = row.get(key)
            if not isinstance(identity, str) or not identity:
                finding(kind+'_IDENTITY_MISSING', '', category='source_gap')
                continue
            if identity in result:
                finding(kind+'_IDENTITY_REPEATED', identity)
            else:
                result[identity] = row
        return result

    cards = index(transactions, 'transaction_id', 'CARD')
    ledger = index(ledger_entries, 'transaction_id', 'LEDGER')
    board = {}
    for raw in board_rows:
        rid = raw.get('row_id')
        if not isinstance(rid, str) or not rid.startswith('card-'):
            continue
        tid = rid[5:]
        if tid in board:
            finding('BOARD_IDENTITY_REPEATED', tid)
            continue
        try:
            payload = json.loads(raw['payload_json'])
            if not isinstance(payload, dict):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            finding('BOARD_PAYLOAD_INVALID', tid)
            board[tid] = (raw, None)
            continue
        board[tid] = (raw, payload)

    for tid in sorted(cards.keys() | ledger.keys() | board.keys()):
        card, entry = cards.get(tid), ledger.get(tid)
        saved, payload = board.get(tid, (None, None))
        if not card:
            finding('RECORDED_CARD_SOURCE_MISSING', tid, category='source_gap')
            continue
        if entry and not saved:
            finding('LEDGER_WITHOUT_BOARD', tid)
        if saved and not entry:
            finding('BOARD_WITHOUT_LEDGER', tid)
        if entry:
            changed = [k for k in ('amount_krw','source_hash','transaction_direction')
                       if card.get(k) != entry.get(k)]
            if changed:
                finding('LEDGER_FINANCIAL_SOURCE_CONFLICT', tid, fields=changed)
        if saved and payload is not None:
            source_fields = (('amount_krw', 'amount_krw'),
                             ('source_fact_digest', 'source_hash'),
                             ('source_event_id', 'transaction_id'))
            missing = [key for key, _ in source_fields
                       if key not in payload or payload.get(key) in (None, '')]
            if missing:
                finding('BOARD_SOURCE_EVIDENCE_MISSING', tid, category='source_gap', fields=missing)
            changed = [k for k, source in source_fields
                       if k in payload and payload.get(k) not in (None, '')
                       and payload.get(k) != card.get(source)]
            if changed:
                finding('BOARD_FINANCIAL_SOURCE_CONFLICT', tid, fields=changed)
            if payload.get('display_tab_id') != saved.get('display_tab_id'):
                finding('BOARD_ATTRIBUTION_SPLIT', tid)
            if entry and any((entry.get(k) or '') != (payload.get(k) or '')
                             for k in ('item', 'display_tab_id')
                             if k in payload):
                finding('LEDGER_BOARD_ATTRIBUTION_SPLIT', tid,
                        category='projection_difference', fields=[k for k in ('item', 'display_tab_id')
                                                                  if k in payload and (entry.get(k) or '') != (payload.get(k) or '')])
            # A source-bound period is checked even if the row was manually moved.
            period = payload.get('service_period')
            trip = known_trips.get(saved.get('display_tab_id'))
            if isinstance(period, dict) and trip and period.get('starts_on') and period.get('ends_on'):
                try:
                    start,end = (date.fromisoformat(period[k]) for k in ('starts_on','ends_on'))
                    first,last = (date.fromisoformat(trip[k]) for k in ('starts_on','ends_on'))
                    if end < start:
                        finding('SERVICE_PERIOD_INVALID',tid)
                    elif end < first or start > last:
                        finding('SERVICE_PERIOD_OUTSIDE_TRIP',tid,category='evidence_conflict')
                except (KeyError,TypeError,ValueError):
                    finding('SERVICE_PERIOD_UNVERIFIABLE',tid,category='source_gap')
        # Historical import projections and explicit manual overrides are not
        # assumed corrupt. Still retain every changed field for original review.
        projections = [('ledger',entry)] if entry else []
        if saved and payload is not None:
            projections.append(('board',payload))
        for name, projection in projections:
            keys = ('item', 'display_tab_id')
            if name == 'ledger':
                keys += ('trip_id',)
            changed = [k for k in keys if (card.get(k) or '') != (projection.get(k) or '')]
            if changed:
                manual = any(('card-'+tid,k) in locked for k in changed)
                finding(name.upper()+'_CLASSIFICATION_DIFFERENCE',tid,
                        category='manual_difference' if manual else 'projection_difference',fields=changed)
        protected = any(card.get(k) for k in ('duplicate_of','conflict_reason','parse_error'))
        if protected and (entry or saved):
            finding('PROTECTED_SOURCE_RECORDED',tid,fields=[k for k in ('duplicate_of','conflict_reason','parse_error') if card.get(k)])
        if not entry and not saved and not protected:
            closed = bool(completed_period(card))
            finding('COMPLETED_SOURCE_UNRECORDED' if closed else 'OPEN_SOURCE_UNRECORDED',tid,category='coverage_gap')
        target = saved.get('display_tab_id') if saved else card.get('display_tab_id')
        if target and target not in ('refunds','unclassified') and not target.startswith('quarter:') and target not in known_trips:
            finding('TRIP_REFERENCE_MISSING',tid,category='source_gap')
        if target == 'refunds' and card.get('transaction_direction') == 'purchase':
            # A tab name proves neither cancellation nor bank settlement.
            finding('REFUND_TAB_REQUIRES_ORIGINAL_EVIDENCE',tid,category='evidence_check')
    counts = Counter(f['code'] for f in findings)
    categories = Counter(f['category'] for f in findings)
    return dict(schema='accounting-audit-v1', scope='all source cards including manual decisions',
                source_count=len(cards), ledger_count=len(ledger), board_card_count=len(board),
                finding_count=len(findings), affected_card_count=len({f['identity'] for f in findings if f['identity']}),
                counts=dict(sorted(counts.items())), categories=dict(sorted(categories.items())),
                financial_writes=0, findings=findings)
