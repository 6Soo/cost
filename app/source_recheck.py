"""Explicit source recheck of legacy Q2 automatic attributions (PROC-073).

This is maintenance evidence, never a new P1 matcher or a payment/refund link.
The private review binds original bytes and current card fields; destinations
are recalculated with the common policy rather than trusted from the manifest.
"""
from datetime import date
import hashlib
import json
from pathlib import Path

SCOPE = 'q2_source_recheck'


def load(conn, trips, directory):
    from .automatic_classification import _read, infer_trip, _quarter_destination
    from .import_card import parse_card_file
    root = Path(directory).resolve()
    path = root / 'manifest.json'
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('SOURCE_RECHECK_INVALID')
    doc = json.loads(raw)
    if (doc.get('version') != 1 or not isinstance(doc.get('review_id'), str)
            or not doc['review_id'].strip() or not isinstance(doc.get('reviews'), list)
            or not 1 <= len(doc['reviews']) <= 100):
        raise ValueError('SOURCE_RECHECK_INVALID')
    result, parsed = {}, {}
    for review in doc['reviews']:
        tid = review['transaction_id']
        rows = _read(conn, {tid})
        if len(rows) != 1 or tid in result:
            raise ValueError('SOURCE_RECHECK_INVALID')
        row = rows[0]
        keys = ('source_hash', 'approval_date', 'amount_krw', 'issuer', 'card_tail',
                'merchant', 'approval_number')
        if any(review['card'].get(k) != row.get(k) for k in keys):
            raise ValueError('SOURCE_RECHECK_SOURCE_CHANGED')
        originals, roles, hashes, mail_facts = review.get('originals'), set(), [], {}
        if not isinstance(originals, list) or not 1 <= len(originals) <= 30:
            raise ValueError('SOURCE_RECHECK_INVALID')
        for original in originals:
            source = (root / original['path']).resolve()
            if (not source.is_relative_to(root) or source == path or not source.is_file()
                    or source.stat().st_size > 20 * 1024 * 1024):
                raise ValueError('SOURCE_RECHECK_INVALID')
            original_bytes = source.read_bytes()
            if len(original_bytes) > 20 * 1024 * 1024:
                raise ValueError('SOURCE_RECHECK_INVALID')
            digest = hashlib.sha256(original_bytes).hexdigest()
            if digest != original.get('sha256'):
                raise ValueError('SOURCE_RECHECK_ORIGINAL_CHANGED')
            if original.get('role') not in ('card_original', 'payment_confirmation',
                    'cancellation_confirmation', 'counter_evidence', 'manual_ledger'):
                raise ValueError('SOURCE_RECHECK_INVALID')
            roles.add(original['role']);hashes.append(digest)
            if review.get('kind') == 'cancelled_booking_payment' and original['role'] in (
                    'payment_confirmation', 'cancellation_confirmation'):
                from .ota_mail import extract_mail
                try:
                    fact = extract_mail(json.loads(original_bytes))
                except (ValueError, TypeError, KeyError):
                    raise ValueError('SOURCE_RECHECK_CANCELLATION_INVALID') from None
                if fact is None:
                    raise ValueError('SOURCE_RECHECK_CANCELLATION_INVALID')
                mail_facts.setdefault(original['role'], []).append(fact)
            if original.get('role') == 'card_original':
                batch = conn.execute('SELECT b.content_sha256,b.filename,t.row_index FROM transactions t '
                    'JOIN import_batches b ON b.batch_id=t.batch_id WHERE t.transaction_id=?', (tid,)).fetchone()
                if not batch or batch[0] != digest:
                    raise ValueError('SOURCE_RECHECK_SOURCE_CHANGED')
                if digest not in parsed:
                    parsed[digest] = parse_card_file(original_bytes, batch[1], use_cache=False)
                exact = [r for r in parsed[digest].rows if r.row_index == batch[2]
                    and all(getattr(r, k) == row[k] for k in (
                        'issuer', 'card_tail', 'approval_date', 'merchant', 'amount_krw',
                        'transaction_direction', 'approval_number'))]
                if len(exact) != 1:
                    raise ValueError('SOURCE_RECHECK_SOURCE_CHANGED')
        if 'card_original' not in roles or not isinstance(review.get('basis'), str) or not review['basis'].strip():
            raise ValueError('SOURCE_RECHECK_INVALID')
        kind = review.get('kind')
        if kind == 'cancelled_booking_payment':
            if (not {'payment_confirmation', 'cancellation_confirmation'} <= roles
                    or review.get('reservation_status') != 'cancelled'
                    or not review.get('booking_ref')
                    or review.get('cancelled_booking_ref') != review.get('booking_ref')):
                raise ValueError('SOURCE_RECHECK_CANCELLATION_INVALID')
            paid = mail_facts.get('payment_confirmation', [])
            cancelled = mail_facts.get('cancellation_confirmation', [])
            if (len(paid) != 1 or len(cancelled) != 1
                    or paid[0].get('booking_ref') != review['booking_ref']
                    or cancelled[0].get('booking_ref') != review['booking_ref']
                    or paid[0].get('reservation_status') not in ('confirmed', 'completed')
                    or cancelled[0].get('reservation_status') != 'cancelled'
                    or paid[0].get('paid_amount_krw') != row['amount_krw']
                    or paid[0].get('paid_on') != row['approval_date']):
                raise ValueError('SOURCE_RECHECK_CANCELLATION_INVALID')
            target, trip_basis = '', 'TRIP-097 · 취소 완료 예약은 실제 이용기간 근거에서 제외'
        elif kind == 'payment_outside_trip':
            target, trip_basis = infer_trip(dict(row, trip_id='', display_tab_id=''), trips, reconsider=True)
        else:
            raise ValueError('SOURCE_RECHECK_INVALID')
        quarter = _quarter_destination(row)
        if not target and not quarter:
            raise ValueError('SOURCE_RECHECK_INVALID')
        result[tid] = dict(kind=SCOPE, review_id=doc['review_id'], source_hash=row['source_hash'],
            approval_date=row['approval_date'], amount_krw=row['amount_krw'],
            before_tab=review['before_tab'], purpose=kind,
            display_tab_id=target or quarter[0], item=row['item'] if target else '분기 기타비용',
            basis=review['basis'] + ' · ' + trip_basis,
            evidence_digest=hashlib.sha256(raw + ''.join(sorted(hashes)).encode()).hexdigest(),
            original_hashes=sorted(hashes), original_roles=sorted(roles))
    return result


def allowed(conn, row, correction, manifest, fact, valid):
    """Narrow Q2 exception; normal review, Q1 and genuine decisions stay protected."""
    from .card_destination import observed_quarter
    if (manifest.get('scope') != SCOPE or not fact or fact.get('kind') != SCOPE
            or fact.get('review_id') != manifest['review_id']
            or any(fact.get(k) != row.get(k) for k in ('source_hash', 'approval_date', 'amount_krw'))
            or any(correction.get(k) != fact.get(k) for k in ('display_tab_id', 'item', 'basis'))
            or row.get('transaction_direction') != 'purchase' or row.get('amount_krw', 0) <= 0
            or row.get('classification_source') != 'inference'
            or not any(x in (row.get('classification_basis') or '') for x in ('AUTO_INFERRED', 'AUTO_TRIP_INFERRED'))
            or row.get('display_tab_id') != fact.get('before_tab')
            or row.get('trip_id') != fact.get('before_tab')):
        return False
    trip = valid.get(fact['before_tab']) or {}
    if not ('2026-04-01' <= (trip.get('starts_on') or '') < '2026-06-30'):
        return False
    # Legacy import used actor=owner even for generated card rows. Only that
    # exact first-insert shape is eligible; later owner edits are never waived.
    revisions = conn.execute(
            'SELECT actor,prev_json,new_json,client_request_id FROM board_revisions WHERE row_id=? ORDER BY id',
            ('card-' + row['transaction_id'],)).fetchall()
    if not revisions:
        return False
    for index, (actor, previous, new, request) in enumerate(revisions):
        payload = json.loads(new or '{}')
        if index == 0 and (previous not in (None, '', '{}', 'null')
                or request != 'card-' + row['transaction_id']
                or payload.get('confirmed_by') != 'automatic'
                or payload.get('classification_source') != 'inference'):
            return False
        if actor != 'automatic':
            if (index != 0 or actor != 'owner' or previous not in (None, '', '{}', 'null')
                    or request != 'card-' + row['transaction_id']
                    or payload.get('confirmed_by') != 'automatic'
                    or payload.get('classification_source') != 'inference'):
                return False
    quarter = observed_quarter(row)
    if fact['purpose'] == 'cancelled_booking_payment':
        return bool(quarter and correction['display_tab_id'] == quarter[0]
                    and correction['item'] == '분기 기타비용')
    day = row.get('approval_date') or ''
    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return bool(day >= '2026-07-01' and trip.get('ends_on') and trip['ends_on'] < day)
