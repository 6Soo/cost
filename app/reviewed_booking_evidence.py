"""Local AI review of original booking/payment groups, independent of supplier parsers.

The private manifest is a trusted review artifact, not an automatic matcher.
Original bytes, payment dates, source hashes and amount multiplicities are checked
on every use. A group proves attribution; it never invents individual payment links.
"""
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

from .closed_period import open_trip, trip_map


def _fail():
    raise ValueError('REVIEWED_BOOKING_EVIDENCE_INVALID')


def _day(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            _fail()
    except (TypeError, ValueError):
        _fail()
    return value


def load(conn, trips, directory):
    """Read source-bound facts from a protected local review directory; no writes."""
    root = Path(directory).resolve()
    path = root / 'manifest.json'
    if not path.exists():
        return {}
    if path.stat().st_size > 2 * 1024 * 1024:
        _fail()
    manifest_bytes = path.read_bytes()
    document = json.loads(manifest_bytes)
    reviewer = document.get('reviewer') or {}
    groups = document.get('groups')
    if (document.get('version') != 1 or reviewer.get('kind') != 'ai_review'
            or any(not isinstance(reviewer.get(k), str) or not reviewer[k].strip()
                   for k in ('provider', 'model', 'run_id'))
            or not isinstance(groups, list) or len(groups) > 100):
        _fail()
    from .automatic_classification import _read
    rows = {r['transaction_id']: r for r in _read(conn)}
    valid, result, seen_sources, seen_groups = trip_map(trips), {}, set(), set()
    for group in groups:
        target, period = group.get('trip_id'), group.get('service_period') or {}
        start, end = _day(period.get('starts_on')), _day(period.get('ends_on'))
        trip = valid.get(target)
        cards, originals = group.get('cards'), group.get('originals')
        group_id = group.get('id')
        if (not isinstance(group_id, str) or not group_id or group_id in seen_groups
                or group.get('item') not in ('항공료', '숙박비', '렌터카')
                or not isinstance(group.get('basis'), str) or not group['basis'].strip()
                or not open_trip(trip) or not trip.get('ends_on')
                or not trip['starts_on'] <= start <= end <= trip['ends_on']
                or not isinstance(cards, list) or not 1 <= len(cards) <= 50
                or not isinstance(originals, list) or not 1 <= len(originals) <= 50):
            _fail()
        seen_groups.add(group_id)
        payments, hashes = [], []
        for original in originals:
            source = (root / original['path']).resolve()
            if (not source.is_relative_to(root) or source == path or not source.is_file()
                    or source.stat().st_size > 20 * 1024 * 1024
                    or original.get('status') not in ('confirmed', 'completed')
                    or original.get('service_period') != period):
                _fail()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != original.get('sha256') or digest in seen_sources:
                _fail()
            hashes.append(digest)
            seen_sources.add(digest)
            parts = original.get('payments')
            if not isinstance(parts, list) or not 1 <= len(parts) <= 50:
                _fail()
            for payment in parts:
                amount = payment.get('amount_krw')
                if type(amount) is not int or amount <= 0:
                    _fail()
                payments.append((_day(payment.get('paid_on')), amount))
        bound = []
        for card in cards:
            row = rows.get(card.get('transaction_id'))
            if (not row or row['transaction_id'] in result
                    or any(card.get(k) != row.get(k) for k in
                           ('source_hash', 'amount_krw', 'approval_date'))
                    or not row.get('source_hash') or row['transaction_direction'] != 'purchase'
                    or any(row.get(k) for k in ('parse_error', 'duplicate_of', 'conflict_reason'))):
                _fail()
            bound.append(row)
        if (len({r['transaction_id'] for r in bound}) != len(bound)
                or len({r['source_hash'] for r in bound}) != len(bound)
                or Counter(payments) != Counter((r['approval_date'], r['amount_krw']) for r in bound)):
            _fail()
        # Exact date/amount multiplicities in the reviewed source cohort must
        # cover every matching card, so identical charges cannot be cherry-picked.
        merchants = {r['merchant'] for r in bound}
        cohort = {r['transaction_id'] for r in rows.values()
                  if r['merchant'] in merchants and r['transaction_direction'] == 'purchase'
                  and (r['approval_date'], r['amount_krw']) in set(payments)
                  and not r.get('duplicate_of')}
        if cohort != {r['transaction_id'] for r in bound}:
            _fail()
        digest = hashlib.sha256(manifest_bytes + ''.join(sorted(hashes)).encode()).hexdigest()
        for row in bound:
            result[row['transaction_id']] = dict(source_hash=row['source_hash'], trip_id=target,
                service_period=period, item=group['item'], formal_link=True,
                evidence_digest=digest, basis=group['basis'], reviewed_group=group_id,
                original_hashes=sorted(hashes), group_size=len(bound), reviewer=reviewer)
    return result


def metadata(fact, entry):
    """Never assign a reservation ID to a member of a many-to-many group."""
    if (not fact or fact['source_hash'] != entry.get('source_hash')
            or fact['trip_id'] != entry.get('display_tab_id')
            or fact['trip_id'] != entry.get('trip_id')):
        return {}
    period = fact['service_period']
    return dict(service_period=period['starts_on'] + '~' + period['ends_on'],
        ota_evidence=dict(kind='reviewed_booking_group', source_hash=fact['source_hash'],
            evidence_digest=fact['evidence_digest'], original_hashes=fact['original_hashes'],
            group_id=fact['reviewed_group'], group_size=fact['group_size'],
            individual_payment_link=False, reviewer=fact['reviewer']))
