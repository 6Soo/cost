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

ROOT = Path(__file__).resolve().parents[1]
PRODUCER_ENV = 'WEBLEDGER_LINKS_PRODUCER'
BIN_ENV = 'WEBLEDGER_COSTCORE_BIN'


def selected() -> str:
    return 'rust' if os.environ.get(PRODUCER_ENV, '').strip().lower() == 'rust' else 'python'


def _plain(value):
    return sorted(value) if isinstance(value, (set, frozenset)) else str(value)


def _run(request: dict) -> list:
    binary = os.environ.get(BIN_ENV, '')
    if not binary:
        raise RuntimeError('CORE_LINKS_NOT_CONFIGURED')
    done = subprocess.run([binary, 'links', 'ota', '--input', '-', '--repo-root', str(ROOT)],
                          input=json.dumps(request, ensure_ascii=False, default=_plain),
                          capture_output=True, text=True, encoding='utf-8', timeout=300)
    try:
        response = json.loads(done.stdout.splitlines()[0])
    except (IndexError, ValueError):
        raise RuntimeError('CORE_LINKS_NO_RESPONSE') from None
    if not response.get('ok') or done.returncode != 0:
        raise RuntimeError((response.get('error') or {}).get('code', 'CORE_LINKS_FAILED'))
    return response['result']['results']


def match_ota_payment_events(events, transactions, *, existing_links=None, rules=None, frozen_groups=None):
    """Same contract as `app.ota_payments.match_ota_payment_events`, solved by costcore.

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
    columns = _run({'events': events, 'transactions': transactions, 'existing_links': existing_links or {},
                    'rules': rules or [], 'frozen_groups': frozen_groups or []})
    results = []
    for link in columns:
        event = by_id.get(str(link.get('ota_event_id')))
        if event is None:
            raise RuntimeError('CORE_LINKS_UNKNOWN_EVENT')
        results.append(dict(event, **link))
    return results
