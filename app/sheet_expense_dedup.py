"""Pure, conservative matching of COST expenses to manual Google sheet rows.

This module does not read or write either store. Callers provide the current
read projection and may persist only the returned stable fingerprint/link.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata

STATUSES = ('MATCHED_MANUAL', 'MATCHED_EXISTING', 'NEW_EXPENSE',
            'REVIEW_CONFLICT', 'SOURCE_UNAVAILABLE')
COUNT_KEYS = STATUSES
_GENERIC_MERCHANTS = {'', 'merchant', 'card', 'purchase', '결제', '가맹점', '카드결제'}


def _text(value):
    return str(value or '').strip()


def _amount(row):
    value = row.get('amount_krw')
    if value is None or value == '':
        return None
    try:
        result = Decimal(str(value).replace(',', ''))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _currency(row):
    return (_text(row.get('currency')) or 'KRW').upper()


def _direction(row):
    direction = _text(row.get('transaction_direction')).casefold()
    amount = _amount(row)
    sign = -1 if amount is not None and amount < 0 else 1
    if direction in {'refund', 'cancellation', 'cancel', '환불', '취소'}:
        return 'refund', sign
    if direction in {'purchase', 'expense', '결제', '지출'}:
        return 'expense', sign
    return direction, sign


def _merchant(row):
    value = row.get('merchant') or row.get('payee') or ''
    value = unicodedata.normalize('NFKC', str(value)).casefold()
    return re.sub(r'[\W_]+', '', value, flags=re.UNICODE)


def _trip(row):
    return _text(row.get('trip_id') or row.get('display_tab_id'))


def _date_values(row):
    values = set()
    for key in ('date', 'occurred_on', 'approval_date'):
        value = _text(row.get(key))
        if value:
            try:
                values.add(date.fromisoformat(value[:10]).isoformat())
            except ValueError:
                continue
    return values


def _card(row):
    tail = re.sub(r'\D', '', _text(row.get('card_tail')))[-4:]
    return (_text(row.get('issuer')).casefold(), tail)


def _approval(row):
    return re.sub(r'\s+', '', _text(row.get('approval_number'))).casefold()


def _stable_cost_id(row):
    return _text(row.get('transaction_id'))


def _stable_sheet_id(row):
    return _text(row.get('stable_id') or row.get('transaction_id'))


def _fingerprint(row):
    fields = ('trip_id', 'sheet_id', 'source', 'stable_id', 'transaction_id',
              'approval_number', 'card_tail', 'issuer', 'date', 'payee',
              'category', 'description', 'amount_krw', 'currency',
              'transaction_direction', 'evidence', 'booking_ref', 'service_period')
    payload = {key: row.get(key) for key in fields}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _sheet_key(row):
    # Row numbers are only location hints; never use one as an identity.
    identity = _stable_sheet_id(row) or _fingerprint(row)
    return ':'.join((_trip(row), _text(row.get('sheet_id')),
                     _text(row.get('source')), identity))


def _core_equal(cost, sheet):
    ca, sa = _amount(cost), _amount(sheet)
    return (ca is not None and sa is not None and ca == sa
            and _currency(cost) == _currency(sheet)
            and _direction(cost) == _direction(sheet))


def _core_conflict(cost, sheet):
    ca, sa = _amount(cost), _amount(sheet)
    return ((ca is not None and sa is not None and ca != sa)
            or (_currency(cost) != _currency(sheet))
            or (_direction(cost) != _direction(sheet)))


def _common_identity(cost, sheet):
    cost_id = _stable_cost_id(cost)
    sheet_ids = {_text(sheet.get('transaction_id')), _text(sheet.get('stable_id'))}
    sheet_ids.discard('')
    if cost_id and cost_id in sheet_ids:
        return 'transaction_id'
    ca, sa = _approval(cost), _approval(sheet)
    if ca and sa and ca == sa:
        cc, sc = _card(cost), _card(sheet)
        # Approval numbers are only stable within a known issuer/card scope.
        if cc[0] and sc[0] and cc[1] and sc[1] and cc == sc:
            return 'approval_number'
    return ''


def _date_identity(cost, sheet):
    cd, sd = _date_values(cost), _date_values(sheet)
    if cd & sd:
        return True
    # A booking reference plus an exact service interval explains a booking
    # ledger date differing from the card authorization date.
    cb, sb = _text(cost.get('booking_ref')), _text(sheet.get('booking_ref'))
    cp, sp = _text(cost.get('service_period')), _text(sheet.get('service_period'))
    return bool(cb and sb and cb == sb and cp and sp and cp == sp)


def _card_conflict(cost, sheet):
    cc, sc = _card(cost), _card(sheet)
    return bool(cc[1] and sc[1] and cc[1] != sc[1]) or bool(
        cc[0] and sc[0] and cc[0] != sc[0])


def _non_card_evidence(row):
    values = [row.get('source'), row.get('transaction_direction'), row.get('evidence'),
              row.get('payment_method'), row.get('tender')]
    text = ' '.join(_text(value) for value in values).casefold()
    return any(token in text for token in (
        'cash', 'point', 'points', '현금', '포인트', 'cash+card', 'split',
        '합산', '분할', '복합결제'))


def _explicit_non_card_conflict(cost, sheet):
    # This matcher only identifies card COST transactions against manual rows;
    # explicit cash/points/split evidence is never a card duplicate candidate.
    return _non_card_evidence(cost) or _non_card_evidence(sheet)


def _merchant_identity(cost, sheet):
    cm, sm = _merchant(cost), _merchant(sheet)
    return bool(cm and sm and cm == sm and cm not in _GENERIC_MERCHANTS)


def _differences(cost, sheet):
    pairs = {
        'date': (sheet.get('date'), cost.get('date') or cost.get('occurred_on')),
        'merchant': (sheet.get('payee'), cost.get('merchant') or cost.get('payee')),
        'category': (sheet.get('category'), cost.get('item') or cost.get('category')),
        'description': (sheet.get('description'), cost.get('description') or cost.get('memo')),
    }
    return {key: {'manual': left, 'cost': right}
            for key, (left, right) in pairs.items()
            if _text(left) != _text(right)}


def _links_by_cost(existing_links):
    if not existing_links:
        return {}
    if isinstance(existing_links, dict):
        return {_text(key): value for key, value in existing_links.items() if _text(key)}
    result = {}
    for link in existing_links:
        if isinstance(link, dict) and _text(link.get('transaction_id')):
            result[_text(link['transaction_id'])] = link
    return result


def reconcile(cost_rows, sheet_rows, *, trip_id, source_available=True,
              existing_links=None, source_metadata=None):
    """Classify each COST row against a read-only projection of manual rows.

    Only unique, same-trip, exact-money matches are linked. Ambiguous evidence,
    stale links, and core-field conflicts are held for review.
    """
    costs, sheets = list(cost_rows or ()), list(sheet_rows or ())
    counts = Counter({key: 0 for key in COUNT_KEYS})
    if not source_available:
        results = [_result(row, 'SOURCE_UNAVAILABLE', trip_id=trip_id,
                           source_metadata=source_metadata,
                           reason='SHEET_SOURCE_UNAVAILABLE')
                   for row in costs]
        counts['SOURCE_UNAVAILABLE'] = len(results)
        return {'results': results, 'counts': dict(counts)}

    target_trip = _text(trip_id)
    eligible_sheets = [row for row in sheets if _trip(row) == target_trip and target_trip]
    by_trip_amount = defaultdict(list)
    by_trip_identity = defaultdict(list)
    by_trip_approval = defaultdict(list)
    by_trip_date = defaultdict(list)
    by_trip_merchant = defaultdict(list)
    all_trip_identity = defaultdict(list)
    all_trip_approval = defaultdict(list)
    for index, row in enumerate(sheets):
        stable = _stable_sheet_id(row)
        if stable:
            all_trip_identity[stable].append(index)
        approval = _approval(row)
        if approval:
            all_trip_approval[approval].append(index)
    for index, row in enumerate(eligible_sheets):
        amount = _amount(row)
        if amount is not None:
            by_trip_amount[(_trip(row), _currency(row), _direction(row), amount)].append(index)
        stable = _stable_sheet_id(row)
        if stable:
            by_trip_identity[(_trip(row), stable)].append(index)
        approval = _approval(row)
        if approval:
            by_trip_approval[(_trip(row), approval)].append(index)
        for day in _date_values(row):
            by_trip_date[(_trip(row), day)].append(index)
        merchant = _merchant(row)
        if merchant and merchant not in _GENERIC_MERCHANTS:
            by_trip_merchant[(_trip(row), merchant)].append(index)

    prior = _links_by_cost(existing_links)
    by_key_fingerprint = defaultdict(list)
    for index, row in enumerate(eligible_sheets):
        by_key_fingerprint[(_sheet_key(row), _fingerprint(row))].append(index)
    occupied = defaultdict(set)
    for owner, link in prior.items():
        if isinstance(link, dict) and link.get('sheet_row_key') and link.get('sheet_fingerprint'):
            occupied[(_text(link['sheet_row_key']), _text(link['sheet_fingerprint']))].add(owner)
    proposed = []
    for cost in costs:
        tid = _stable_cost_id(cost)
        ct = _trip(cost)
        if not target_trip or not ct or ct != target_trip:
            proposed.append(_result(cost, 'REVIEW_CONFLICT', trip_id=target_trip,
                                    source_metadata=source_metadata,
                                    reason='TRIP_ID_MISMATCH'))
            continue
        # A known identical source identity on another real tab is a trip
        # assignment conflict, not evidence for a fresh expense in this tab.
        cross_trip = [sheets[i] for i in all_trip_identity.get(tid, [])
                      if tid and _trip(sheets[i]) != ct]
        approval = _approval(cost)
        issuer, tail = _card(cost)
        if approval and issuer and tail:
            cross_trip.extend(sheets[i] for i in all_trip_approval.get(approval, [])
                              if _trip(sheets[i]) != ct
                              and _card(sheets[i]) == (issuer, tail))
        if cross_trip:
            proposed.append(_result(cost, 'REVIEW_CONFLICT', trip_id=target_trip,
                                    source_metadata=source_metadata,
                                    reason='TRANSACTION_ON_DIFFERENT_TRIP'))
            continue
        link = prior.get(tid)
        if link:
            key = _text(link.get('sheet_row_key'))
            fingerprint = _text(link.get('sheet_fingerprint'))
            candidates = by_key_fingerprint.get((key, fingerprint), [])
            if len(candidates) == 1:
                i = candidates[0]
                row = eligible_sheets[i]
                if _trip(row) == ct and _core_equal(cost, row):
                    other_owners = occupied.get((key, fingerprint), set()) - {tid}
                    if other_owners:
                        proposed.append(_result(cost, 'REVIEW_CONFLICT', trip_id=target_trip,
                                                source_metadata=source_metadata,
                                                reason='SHEET_ROW_OCCUPIED_BY_EXISTING_LINK'))
                        continue
                    proposed.append(_result(cost, 'MATCHED_EXISTING', row, i,
                                            ['validated_existing_link'], _differences(cost, row),
                                            manual_override=bool(link.get('manual_override')
                                                or link.get('link_source') == 'manual')))
                    continue
            # A stale or repointed link is not silently discarded/reused.
            proposed.append(_result(cost, 'REVIEW_CONFLICT', trip_id=target_trip,
                                    source_metadata=source_metadata,
                                    reason='EXISTING_LINK_STALE'))
            continue

        stable_id = tid
        exact_ids = by_trip_identity.get((ct, stable_id), []) if stable_id else []
        exact_approvals = by_trip_approval.get((ct, approval), []) if approval else []
        strong_indexes = set(exact_ids) | set(exact_approvals)
        strong_valid, strong_conflicts = [], []
        for i in strong_indexes:
            row = eligible_sheets[i]
            identity = _common_identity(cost, row)
            if not identity:
                continue
            if _card_conflict(cost, row) or _explicit_non_card_conflict(cost, row) or not _core_equal(cost, row):
                strong_conflicts.append(i)
            else:
                strong_valid.append((i, identity))
        if len(strong_valid) == 1 and not strong_conflicts:
            i, basis = strong_valid[0]
            row = eligible_sheets[i]
            key = (_sheet_key(row), _fingerprint(row))
            other_owners = occupied.get(key, set()) - {tid}
            if other_owners:
                proposed.append(_result(cost, 'REVIEW_CONFLICT', trip_id=target_trip,
                                        source_metadata=source_metadata,
                                        reason='SHEET_ROW_OCCUPIED_BY_EXISTING_LINK'))
            else:
                proposed.append(_result(cost, 'MATCHED_MANUAL', row, i, [basis],
                                        _differences(cost, row), manual_override=False))
            continue
        if strong_valid or strong_conflicts:
            proposed.append(_result(cost, 'REVIEW_CONFLICT', trip_id=target_trip,
                                    source_metadata=source_metadata,
                                    reason='STRONG_ID_CONFLICT_OR_AMBIGUITY'))
            continue

        indexed = set()
        bucket = (_trip(cost), _currency(cost), _direction(cost), _amount(cost))
        indexed.update(by_trip_amount.get(bucket, []))
        for day in _date_values(cost):
            indexed.update(by_trip_date.get((ct, day), []))
        merchant = _merchant(cost)
        if merchant and merchant not in _GENERIC_MERCHANTS:
            indexed.update(by_trip_merchant.get((ct, merchant), []))

        valid, conflicts, weak = [], [], []
        for i in indexed:
            row = eligible_sheets[i]
            if _trip(row) != ct:
                continue
            identity = _common_identity(cost, row)
            exact_money = _core_equal(cost, row)
            same_date = _date_identity(cost, row)
            same_merchant = _merchant_identity(cost, row)
            enough_context = same_merchant and (same_date or identity)
            if not enough_context:
                if exact_money and same_merchant:
                    weak.append(i)
                continue
            if _card_conflict(cost, row) or _explicit_non_card_conflict(cost, row) or _core_conflict(cost, row):
                conflicts.append(i)
            elif exact_money and same_date and same_merchant:
                valid.append((i, 'amount_date_merchant'))
            elif exact_money and (same_date or same_merchant):
                weak.append(i)
        if len(valid) == 1 and not conflicts and not weak:
            i, basis = valid[0]
            row = eligible_sheets[i]
            proposed.append(_result(cost, 'MATCHED_MANUAL', row, i, [basis],
                                    _differences(cost, row),
                                    manual_override=False))
        elif valid or conflicts or weak:
            proposed.append(_result(cost, 'REVIEW_CONFLICT', reason=(
                'MULTIPLE_OR_CONFLICTING_CANDIDATES' if len(valid) > 1 or conflicts else
                'INSUFFICIENT_UNIQUE_EVIDENCE'), trip_id=target_trip,
                source_metadata=source_metadata))
        else:
            proposed.append(_result(cost, 'NEW_EXPENSE', trip_id=target_trip,
                                    source_metadata=source_metadata,
                                    reason='NO_PLAUSIBLE_MANUAL_MATCH'))


    # Reverse uniqueness: a single manual row cannot be linked to two COST rows.
    owners = defaultdict(list)
    for pos, result in enumerate(proposed):
        if result['status'] in ('MATCHED_MANUAL', 'MATCHED_EXISTING'):
            owners[result['sheet_row_key']].append(pos)
    for positions in owners.values():
        if len(positions) > 1:
            manual_positions = [pos for pos in positions
                                if proposed[pos]['manual_override']]
            keep = manual_positions[0] if len(manual_positions) == 1 else None
            for pos in positions:
                if pos == keep:
                    continue
                proposed[pos] = _result(costs[pos], 'REVIEW_CONFLICT',
                                        trip_id=target_trip, source_metadata=source_metadata,
                                        reason='SHEET_ROW_ALREADY_CLAIMED')

    for result in proposed:
        counts[result['status']] += 1
    return {'results': proposed, 'counts': dict(counts)}


def _result(cost, status, sheet=None, index=None, basis=None, differences=None,
            reason='', *, trip_id='', source_metadata=None, manual_override=False):
    metadata = source_metadata or {}
    return {
        'transaction_id': _stable_cost_id(cost), 'status': status,
        'trip_id': (_trip(sheet) if sheet is not None else '') or
                   (_trip(cost) or _text(trip_id)),
        'sheet_id': (_text(sheet.get('sheet_id')) if sheet is not None else '') or
                    _text(metadata.get('sheet_id')),
        'source': (_text(sheet.get('source')) if sheet is not None else '') or
                  _text(metadata.get('source')),
        'sheet_row_key': _sheet_key(sheet) if sheet is not None else '',
        'row_number': sheet.get('row_number') if sheet is not None else None,
        'sheet_fingerprint': _fingerprint(sheet) if sheet is not None else '',
        'basis': list(basis or []), 'differences': dict(differences or {}),
        'manual_override': bool(manual_override),
        'reason': reason,
    }
