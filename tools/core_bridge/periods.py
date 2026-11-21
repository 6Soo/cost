"""Bridge adapter for the ``periods`` command; the pure evidence surface lives in ``app.core_period_evidence``.

The names below are re-exported so the historical ``tools.core_bridge.periods`` surface (CLI, goldens,
shadow tooling) keeps working on the same implementation the Rust writer (``app.core_writer``) uses.
Nothing here writes.
"""
from __future__ import annotations

from app.core_period_evidence import (BASES, CARD_KEYS, EVENT_KEYS, FACT_KEYS, FLIGHTS_KEY,
                                       evidence_from_snapshot, facts_from_snapshot, flights_from_snapshot,
                                       found_from_snapshot, inferred_from_snapshot, p2_index, stay_index,
                                       verified_report, verified_from_snapshot)

__all__ = ['BASES', 'CARD_KEYS', 'EVENT_KEYS', 'FACT_KEYS', 'FLIGHTS_KEY', 'evidence_from_snapshot',
           'facts_from_snapshot', 'flights_from_snapshot', 'found_from_snapshot', 'inferred_from_snapshot',
           'p2_index', 'stay_index', 'verified_report', 'verified_from_snapshot', 'periods']


def periods(request):
    """Bridge command: ``{data, manual, rows?}`` -> ``{facts, verified?}`` (nothing is applied).

    With ``inference`` set the answer also carries ``inferred``, ``flights`` and ``found`` (the new evidence
    kinds); without it the output is the one the first golden cases were written with.  The explicit
    ``report: true`` option (needs ``rows``) adds ``period_report``: the verified-only read of each row
    (value / manual / verified / none) that stops at what the rule verifies (DATE-109) - no candidates,
    no screen-only inference, no stored projection, no writes.
    """
    data, manual = request['data'], set(request.get('manual') or ())
    result = {'facts': facts_from_snapshot(data, manual)}
    if 'rows' in request:
        result['verified'] = verified_from_snapshot(data, manual, request['rows'])
    if request.get('inference'):
        p2 = p2_index(request.get('p2') or [])
        result['inferred'] = inferred_from_snapshot(data, manual, p2)
        result['flights'] = flights_from_snapshot(data, manual)
        if 'rows' in request:
            result['found'] = found_from_snapshot(data, manual, request['rows'], p2)
    if request.get('report') and 'rows' in request:
        result['period_report'] = verified_report(request['rows'], result['verified'], manual)
    return result
