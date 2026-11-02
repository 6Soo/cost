"""Read current OTA stay evidence for old card ledger rows without rewriting them."""
from app.ota_core_projection import card_matches
from app.ota_mail import ledger_metadata
from collections import defaultdict


def stay_index(store):
    from . import ota_payment_review

    if store is None or not ota_payment_review.enabled():
        return {}
    # Reading a ledger must not start reconciliation or turn stale evidence into fact.
    service = getattr(store, '_ota_snapshot_service', None)
    if service is None:
        return {}
    current, state = service.display_context()
    if not current or not state.get('fresh'):
        return {}
    data = current.get('data') or {}
    facts = card_matches([], data)
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    blocked = {str(r.get('ota_event_id')) for r in data.get('results', [])
               if r.get('period_conflict')}
    by_source = defaultdict(list)
    for fact in facts:
        by_source[fact.get('source_hash')].append(fact)
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    with store._lock:
        manual = {str(r[0]) for r in store.conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
    result = {}
    for fact in facts:
        tid = str(fact.get('transaction_id') or '')
        card = cards.get(tid) or {}
        event_id = str(fact.get('ota_event_id'))
        event = events.get(event_id) or {}
        period = fact.get('period')
        if (fact.get('item') != '숙박비' or 'card-' + tid in manual
                or not tid or not card.get('source_hash')
                or event_id in blocked or event.get('period_conflict')
                or fact.get('reservation_status') == 'refunded'
                or not isinstance(period, dict)
                or not period.get('starts_on') or not period.get('ends_on')):
            continue
        metadata = ledger_metadata({'matches': by_source[card.get('source_hash')]}, {
            'transaction_id': tid, 'source_hash': card.get('source_hash'),
            'transaction_direction': card.get('transaction_direction'), 'item': '숙박비',
        })
        if metadata.get('service_period'):
            result[tid] = metadata
    return result


def period_for(row, index):
    """An explicit stored value or a different saved reservation always wins."""
    stored = str(row.get('service_period') or '').strip()
    if stored:
        return stored
    row_id = str(row.get('row_id') or '')
    if not row_id.startswith('card-'):
        return ''
    tid = str(row.get('source_event_id') or row_id[5:])
    if row_id != 'card-' + tid:
        return ''
    found = index.get(tid) or {}
    reservation = str(row.get('reservation_no') or '').strip()
    if reservation and reservation != found.get('booking_ref'):
        return ''
    return found.get('service_period') or ''
