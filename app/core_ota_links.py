"""Switch for who solves OTA event <-> card links: Python `match_ota_payment_events` (default) or `costcore links ota`.

`WEBLEDGER_LINKS_PRODUCER=rust` (the same switch as the refund pairs) makes `CoreOtaPaymentBackend._data` take the
solver result from the Rust core; anything else, including unset or a typo, keeps Python. Unsetting it is the rollback.
The input is assembled by Python exactly as before (events, cards, manual links, rules, frozen groups); costcore only
solves. Links are not stored by the solver, so nothing needs restoring. A costcore failure raises: there is no quiet
fallback to Python, because two producers disagreeing silently is the failure this switch exists to prevent.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# One switch for both link producers: the decision and the variable names live in core_links.
from .core_links import BIN_ENV, PRODUCER_ENV, selected  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _plain(value):
    return sorted(value) if isinstance(value, (set, frozenset)) else str(value)


def _run(request: dict, command='ota') -> dict:
    binary = os.environ.get(BIN_ENV, '')
    if not binary:
        raise RuntimeError('CORE_LINKS_NOT_CONFIGURED')
    done = subprocess.run([binary, 'links', command, '--input', '-', '--repo-root', str(ROOT)],
                          input=json.dumps(request, ensure_ascii=False, default=_plain),
                          capture_output=True, text=True, encoding='utf-8', timeout=300)
    try:
        response = json.loads(done.stdout.splitlines()[0])
    except (IndexError, ValueError):
        raise RuntimeError('CORE_LINKS_NO_RESPONSE') from None
    if not response.get('ok') or done.returncode != 0:
        raise RuntimeError((response.get('error') or {}).get('code', 'CORE_LINKS_FAILED'))
    return response['result']


def match_ota_payment_events(events, transactions, *, existing_links=None, rules=None, frozen_groups=None):
    """Same contract as the Python matcher, solved by costcore."""
    results, _ = solve(events, transactions, existing_links=existing_links, rules=rules, frozen_groups=frozen_groups)
    return results


def solve(events, transactions, *, existing_links=None, rules=None, frozen_groups=None):
    """Return link results and whether this costcore supports batched candidate diagnostics.

    costcore returns the link columns only; each result is the original event dict overlaid with them, which is what
    the Python solver builds (`dict(event, status=..., ...)`). Duplicate event ids or a result for an unknown event
    fail instead of being guessed.
    """
    by_id = {}
    for event in events:
        identity = str(event.get('ota_event_id'))
        if identity in by_id:
            raise RuntimeError('CORE_LINKS_DUPLICATE_EVENT')
        by_id[identity] = event
    response = _run({'events': events, 'transactions': transactions, 'existing_links': existing_links or {},
                     'rules': rules or [], 'frozen_groups': frozen_groups or []})
    results, seen = [], set()
    for link in response['results']:
        identity = str(link.get('ota_event_id'))
        event = by_id.get(identity)
        if event is None:
            raise RuntimeError('CORE_LINKS_UNKNOWN_EVENT')
        if identity in seen:
            raise RuntimeError('CORE_LINKS_DUPLICATE_RESULT')
        seen.add(identity)
        results.append(dict(event, **link))
    if len(results) != len(by_id):
        raise RuntimeError('CORE_LINKS_RESULT_COUNT')
    if 'supports_candidate_batch' in response and response['supports_candidate_batch'] is not True:
        raise RuntimeError('CORE_OTA_CANDIDATE_CAPABILITY')
    return results, 'supports_candidate_batch' in response


def search_card_candidates(events, transactions, *, existing_links, rules):
    """Search all requested events in one costcore call. Null marks a provider-specific Python search."""
    response = _run({'events': events, 'transactions': transactions, 'existing_links': existing_links,
                     'rules': rules}, 'ota-candidates')
    searches = response.get('searches')
    by_id = {event['ota_event_id']: event for event in events}
    if len(by_id) != len(events) or not isinstance(searches, dict) or searches.keys() != by_id.keys():
        raise RuntimeError('CORE_OTA_CANDIDATE_KEYS')
    for identity, trace in searches.items():
        if trace is None:
            event = by_id[identity]
            if event.get('event_type') != 'reservation' or event.get('provider') not in ('forest', 'toyoko', 'rakuten'):
                raise RuntimeError('CORE_OTA_CANDIDATE_DELEGATION')
        elif (not isinstance(trace, dict) or not isinstance(trace.get('status'), str)
              or not isinstance(trace.get('candidates'), list)
              or not isinstance(trace.get('rejected', []), list)):
            raise RuntimeError('CORE_OTA_CANDIDATE_RESPONSE')
    return searches
