"""Complete card classifications from weak evidence without inventing payment links."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from .provisional_assignment import canonical_trip_periods, card_trip_candidates
from .quarter_costs import quarter_of
from .assignment_status import row_assignment
from .rules import merchant_country
from .trip_selection import regional_trips, period_or_preparation

POLICY = 'complete-card-inference-v1'
FIELDS = ('classification_state', 'classification_source', 'classification_basis',
          'item', 'description', 'display_tab_id', 'trip_id')
COMPLETION_SOURCE = 'cost.classification_completion'
COMPLETION_VERSION = 'cuv-04-cuv-05-v1'


def _completion_audit():
    """Return explicit provenance for a read-only completion decision."""
    return {'source': COMPLETION_SOURCE, 'version': COMPLETION_VERSION,
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}


def completion_for_row(row, valid, *, nets=None):
    """Completion requires classification and a valid destination, free of conflicts."""
    from .closed_period import excluded
    if excluded(row, list(valid.values())):
        return dict(transaction_id=row['transaction_id'], complete=True,
                    execution_origin='preserved', mode='preserved', blocked_by=[])
    reasons = []
    source = row.get('classification_source') or ''
    manual = bool(row.get('decided_at')) or source in {'user_decision', 'user_exception', 'manual'}
    if row.get('classification_state') != 'classified' or not row.get('item'):
        reasons.append('TRANSACTION_NATURE_UNCONFIRMED')
    direction = str(row.get('transaction_direction') or '').strip().casefold()
    kind = str(row.get('transaction_kind') or '').strip()
    if direction not in {'purchase', 'cancellation', 'refund'} or not kind:
        if 'TRANSACTION_NATURE_UNCONFIRMED' not in reasons:
            reasons.append('TRANSACTION_NATURE_UNCONFIRMED')
    assignment = row_assignment(row, valid)
    if (assignment['status'] != 'ASSIGNED'
            or any(conflict in assignment['conflicts']
                   for conflict in ('STALE_DISPLAY_DESTINATION', 'STALE_TRIP_DESTINATION'))):
        reasons.append('TRIP_INVALID_OR_MISSING')
    if assignment['conflicts']:
        reasons.append('TRIP_ASSIGNMENT_CONFLICT')
    if any(row.get(k) for k in ('parse_error', 'conflict_reason', 'duplicate_of')):
        reasons.append('SOURCE_UNRESOLVED')
    if source in {'rule_conflict', 'inference_conflict', 'travel_location_hold', 'manual_hold'}:
        reasons.append('CLASSIFICATION_SOURCE_CONFLICT')
    from .classification_provenance import origin
    return {'transaction_id': row['transaction_id'], 'complete': not reasons,
            'execution_origin': origin(row),
            'mode': 'manual' if manual else ('auto' if not reasons else 'unresolved'),
            'blocked_by': reasons}


def classification_completion(conn, batch_id, trips, *, nets=None):
    valid = canonical_trip_periods(trips)
    c = conn.conn if hasattr(conn, 'conn') else conn
    columns = ('transaction_id', 'transaction_direction', 'transaction_kind',
               'classification_state', 'classification_source', 'classification_basis',
               'item', 'trip_id', 'display_tab_id', 'decided_at')
    rows = [dict(zip(columns, values)) for values in c.execute(
        'SELECT ' + ','.join(columns) + ' FROM transactions '
        'WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) '
        'ORDER BY transaction_id', (batch_id,))]
    available = {column[1] for column in c.execute('PRAGMA table_info(transactions)')}
    optional = [field for field in ('parse_error', 'conflict_reason', 'duplicate_of',
                                   'approval_date', 'posting_date') if field in available]
    if optional and rows:
        extra = {row[0]: dict(zip(optional, row[1:])) for row in c.execute(
            'SELECT transaction_id,' + ','.join(optional) + ' FROM transactions '
            'WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)',
            (batch_id,))}
        for row in rows:
            row.update(extra.get(row['transaction_id'], {}))
    results = [completion_for_row(row, valid, nets=nets) for row in rows]
    return {'batch_id': batch_id, 'complete': bool(rows) and all(r['complete'] for r in results),
            'rows': results, 'audit': _completion_audit(),
            'reconciliation': {'status': 'SEPARATE', 'financial_complete': False}}


def reconciliation_completion(conn, batch_id):
    from .partial_refund import refund_links
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT t.transaction_id FROM import_batch_rows b JOIN transactions t USING(transaction_id) "
        "WHERE b.batch_id=? AND t.transaction_direction IN ('cancellation','refund')", (batch_id,))]
    links = refund_links(conn, ids)
    verified = {tid: link for tid, link in links.items()
                if not link.get('inferred') and link.get('status') != 'excess'}
    return {'batch_id': batch_id,
            'cancellations': [{'transaction_id': tid, 'original_id': link['original_id'],
                               'linked': True, 'status': link.get('status', 'unknown')}
                              for tid, link in sorted(verified.items())],
            'unlinked_cancellations': [tid for tid in ids if tid not in verified],
            'financial_complete': False, 'audit': _completion_audit()}


def infer_item(row):
    """Industry and service vocabulary apply across merchants, with an explicit fallback."""
    from .trip_selection import is_fukutake_purchase
    if (is_fukutake_purchase(row) and row.get('classification_source') not in
            ('user_decision', 'user_exception', 'owner_booking')):
        return '입장료', '사용자 규칙: FUKUTAKE FOUNDATION 미술관 입장료'
    if row.get('item'):
        return row['item'], '기존 항목 유지'
    raw = str(row.get('description_raw') or '')
    industry = raw.removeprefix('card-category:') if raw.startswith('card-category:') else ''
    groups = (
        ('주차비', r'주차|parking'), ('주유비', r'주유|충전소|gas station|fuel'),
        ('통행료', r'통행료|고속도로|toll'), ('항공료', r'항공|airline|airways|aviation|gotogate|고투게이트'),
        ('렌터카', r'렌터카|렌트카|rent.?a.?car|rent.?car|rent.?lease'),
        ('숙박비', r'숙박|호텔|여관|모텔|펜션|리조트|hotel|inn\b|resort|agoda|booking\.com|airbnb|ryokan'),
        ('식비', r'음식|식당|한식|중식|일식|양식|제과|커피|카페|식음료|국밥|김밥|칼국수|restaurant|cafe|coffee|bakery'),
        ('편의점', r'편의점|슈퍼|마트|convenience|supermarket'),
        ('교통비', r'택시|철도|버스|지하철|승차권|여객선|taxi|rail|train|subway|transit|ferry'),
        ('입장료', r'입장|관람|박물관|수목원|미술관|museum|admission'),
        ('여행경비', r'여행|관광|투어|tour|trip\.com|klook'),
    )
    for text, basis in ((industry,'카드사 업종 공통 규칙'),
                        (str(row.get('merchant') or ''),'가맹점 서비스 용도 공통 규칙')):
        for item, pattern in groups:
            if re.search(pattern, text, re.I):
                return item, basis
    if row.get('transaction_direction') in ('refund', 'cancellation'):
        return '취소·환불', '원결제 항목 단서 부족 · 취소·환불 원행 용도'
    if merchant_country(row) not in ('', 'KR'):
        return '현지경비', '해외 카드 사용 · 세부 업종 단서 부족'
    return '기타경비', '업종·용도 단서 부족 · 업무 카드 지출 기본 분류'


def _quarter_destination(row):
    """Use an observed payment quarter only after no real trip can be inferred."""
    if (row.get('transaction_direction') != 'purchase'
            or type(row.get('amount_krw')) is not int or row['amount_krw'] <= 0):
        return None
    from .card_destination import observed_quarter
    return observed_quarter(row)


def infer_trip(row, trips, *, nets=None, reconsider=False, _canonical=None, completed_evidence=None):
    """Pick the best real trip, resolving weak ties deterministically and explaining them."""
    from .closed_period import excluded
    if excluded(row, trips, evidence=completed_evidence):
        return '', 'PROC-072 · 완료 기간 자료'
    # Reuse only this plan's validation; independent calls revalidate authority.
    valid = canonical_trip_periods(trips) if _canonical is None else _canonical
    from .trip_selection import card_trip_allowed
    valid = {key: trip for key, trip in valid.items() if card_trip_allowed(row, trip)}
    from .trip_selection import fukutake_trips, FUKUTAKE_BASIS
    preferred = fukutake_trips(row, valid.values())
    if preferred is not None:
        return (preferred[0]['trip_id'] if preferred else '', FUKUTAKE_BASIS)
    for key in ('trip_id', 'display_tab_id'):
        if row.get(key) in valid and not reconsider:
            return row[key], '기존 실제 여행 유지'
    candidates_trips = regional_trips(row, valid.values(), booking_agnostic=True)
    valid = {trip['trip_id']: trip for trip in candidates_trips}
    candidates = card_trip_candidates(row, candidates_trips, nets=nets, _canonical=valid)
    if candidates:
        candidates.sort(key=lambda c: (-c['score'], valid[c['trip_id']]['starts_on'], c['trip_id']))
        top = candidates[0]
        ties = sum(c['score'] == top['score'] for c in candidates)
        return top['trip_id'], top['basis'] + (f' · 동률 {ties}개 중 일정·ID 고정 순서로 선택' if ties > 1 else '')
    # Preserve the pre-existing missing/invalid-use-date path. This change is
    # limited to generic preparation inference for an observed outside date.
    from datetime import date
    try:
        date.fromisoformat(row.get('approval_date') or '')
    except (TypeError, ValueError):
        if valid:
            target = max(valid, key=lambda key: (valid[key]['starts_on'], key))
            return target, '이용일 단서 없음 · 가장 최근 시작한 실제 여행 선택'
    return '', 'PROC-004 · 이용일을 포함하는 여행 없음 · 결제일 분기 기타비용'


def _card3820_owner_policy(row, trips, *, _canonical=None):
    """Apply the explicit 3820 policy before generic completion inference.

    This mirrors the primary card-classification path: the Singapore exception
    wins when exactly one matching trip exists; otherwise an eligible domestic
    purchase goes to its transaction quarter. Overseas purchases use matching
    trip periods regardless of country. Outside those dates PROC-004 applies.
    Missing dates and the absence of real trips cannot invent an assignment.
    """
    if row.get('card_tail') != '3820':
        return None
    if row.get('transaction_direction') != 'purchase':
        return None
    if any(marker in str(row.get('transaction_kind') or '').lower()
           for marker in ('refund', 'cancel', '취소', '승인')):
        return None
    if row.get('parse_error') or type(row.get('amount_krw')) is not int or row['amount_krw'] <= 0:
        return None
    day = row.get('approval_date') or row.get('posting_date') or ''
    try:
        from datetime import date
        occurred = date.fromisoformat(day)
    except (TypeError, ValueError):
        return None

    valid = canonical_trip_periods(trips) if _canonical is None else _canonical
    singapore = [trip for trip in valid.values()
                 if trip.get('destination') == '싱가포르'
                 and trip.get('starts_on') and trip.get('ends_on')
                 and trip['starts_on'] <= occurred.isoformat() <= trip['ends_on']]
    if occurred.isoformat() >= '2026-09-19' and occurred.isoformat() <= '2026-09-24':
        if len(singapore) == 1:
            target = singapore[0]['trip_id']
            return dict(item=row.get('item') or '현지경비', description=row.get('description') or '',
                        display_tab_id=target, trip_id=target,
                        basis='사용자 예외: 2026-09-19~2026-09-24 카드 3820 사용내역은 싱가포르 여행에 배정',
                        source='user_exception')
        return None

    from .rules import transaction_region
    if transaction_region(row) == 'overseas':
        candidates, preparation = period_or_preparation(
            regional_trips(row, valid.values()), occurred.isoformat())
        if not candidates:
            return None
        target, basis = infer_trip(row, candidates, reconsider=True,
                                   _canonical={t['trip_id']: t for t in candidates})
        return dict(item=row.get('item') or infer_item(row)[0], description=row.get('description') or '',
                    display_tab_id=target, trip_id=target, source='inference',
                    basis='AUTO_INFERRED · 낮음 · 해외 사용 · 국가 일치 불필요 · ' + basis)
    year, quarter = quarter_of(occurred)
    return dict(item='분기 기타비용', description=f'{year}년 {quarter}분기 기타비용',
                display_tab_id=f'quarter:{year}:{quarter}', trip_id='',
                basis='사용자 규칙: 기존 대사 후 남은 카드 3820 거래를 분기 기타비용으로 분류',
                source='owner_card_residual')


def _read(conn, selected=None):
    columns = ('transaction_id', 'source_hash', 'issuer', 'card_tail', 'card_kind',
               'transaction_direction', 'transaction_kind', 'approval_number',
               'original_approval_number', 'approval_date', 'posting_date', 'merchant',
               'merchant_normalized', 'amount_krw', 'foreign_amount', 'foreign_currency',
               'description_raw', 'raw_row_json', 'parse_error', 'duplicate_of', 'conflict_reason',
               *FIELDS, 'revision', 'decided_at')
    query, parameters = 'SELECT ' + ','.join(columns) + ' FROM transactions', ()
    if selected is not None:
        query += ' WHERE transaction_id IN (SELECT value FROM json_each(?))'
        parameters = (json.dumps(sorted(selected)),)
    rows = [dict(zip(columns, r)) for r in conn.execute(query + ' ORDER BY transaction_id', parameters)]
    return rows


def _context(conn, selected=None):
    from .decision_provenance import active_decision_sql
    rows = _read(conn, selected)
    decisions = {r[0]: r[1] for r in conn.execute(
        'SELECT d.transaction_id,d.display_tab_id FROM review_decisions d WHERE '+active_decision_sql()+' ORDER BY revision')}
    holds = {r[0] for r in conn.execute('SELECT transaction_id FROM transaction_review_holds')}
    excluded = {r[0] for r in conn.execute('SELECT transaction_id FROM transaction_company_exclusions WHERE excluded=1')}
    overrides = {r[0] for r in conn.execute('SELECT row_id FROM board_manual_overrides')}
    ledger = {r[0]: dict(zip(('item','description','display_tab_id','trip_id'), r[1:])) for r in conn.execute(
        'SELECT transaction_id,item,description,display_tab_id,trip_id FROM ledger_entries')}
    boards = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT row_id,display_tab_id,payload_json,revision FROM board_rows WHERE row_kind='expense'")}
    return rows, decisions, holds, excluded, overrides, ledger, boards


def _protected_row(row, tid, holds, excluded):
    return (tid in holds or tid in excluded
            or any(row[k] for k in ('parse_error', 'duplicate_of', 'conflict_reason')))


def _refund_original_is_complete(row, tid, links, reconsider):
    if (row['classification_state'] != 'classified'
            or row.get('classification_source') != 'refund_original'):
        return False
    verified = links.get(tid) or {}
    return (not reconsider or verified.get('inferred')
            or verified.get('status') not in ('full', 'partial'))


def _has_history(row, tid, decisions, overrides):
    return (tid in decisions or row['decided_at'] is not None
            or row['classification_source'] in ('user_decision', 'user_exception', 'owner_booking')
            or 'card-' + tid in overrides)


def _restore_historical_row(row, chosen, tid, valid, nets, decisions, ledger, boards):
    """Preserve historical item choices while repairing a missing destination."""
    if not chosen['item']:
        chosen['raw_row'] = json.loads(row['raw_row_json'] or '{}')
        chosen['item'], _ = infer_item(chosen)
    chosen['classification_state'] = 'classified'
    empty_trip = (not row['trip_id'] and row['display_tab_id'] in (None, '', 'unclassified'))
    if not empty_trip or chosen['item'] == '분기 기타비용':
        return chosen
    recorded = ledger.get(tid) or {}
    board = boards.get('card-' + tid)
    candidates = [board[0] if board else '', decisions.get(tid),
                  recorded.get('trip_id'), recorded.get('display_tab_id')]
    target = next((value for value in candidates if value in valid or value == 'refunds'), '')
    if target:
        chosen.update(display_tab_id=target, trip_id='' if target == 'refunds' else target,
                      classification_basis='TRIP_ASSIGNMENT_RESTORED · 기존 항목 보존 · 기존 장부/분류 이력의 배정 복원')
    else:
        target, basis = infer_trip(chosen, list(valid.values()), nets=nets, _canonical=valid)
        if target:
            chosen.update(display_tab_id=target, trip_id=target,
                          classification_basis=f'AUTO_TRIP_INFERRED · 낮음 · 기존 항목 보존 · {basis} · {POLICY}')
    if target and row['classification_source'] not in ('user_decision', 'user_exception', 'owner_booking'):
        chosen['classification_source'] = 'inference'
    return chosen


def _classify_new_row(row, chosen, tid, valid, trips, nets, links, resolved, ledger, boards,
                      reconsider, evidence):
    """Infer one row without historical decisions; return it or ``None`` when unchanged."""
    recorded = ledger.get(tid) or {}
    board = boards.get('card-' + tid)
    if board and not chosen['item']:
        chosen['item'] = json.loads(board[1]).get('item') or ''
    if recorded.get('item'):
        chosen['item'] = recorded['item']
    recorded_tab = recorded.get('trip_id') or recorded.get('display_tab_id')
    existing_tab = next((value for value in (board[0] if board else '', recorded_tab)
                         if value in valid or value == 'refunds'), '')
    if existing_tab and not (chosen['trip_id'] in valid or chosen['display_tab_id'] in valid):
        chosen.update(trip_id='' if existing_tab == 'refunds' else existing_tab,
                      display_tab_id=existing_tab)
    from .closed_period import completed_period
    fact = evidence.get(tid) if reconsider or completed_period(row) else None
    valid_fact = bool(fact and fact.get('source_hash') == row['source_hash']
                      and fact.get('trip_id') in valid
                      and row['transaction_direction'] == 'purchase')
    # A recorded calendar guess is still an automatic inference. A later,
    # source-bound reservation period may correct it during explicit review.
    # Historical/manual rows have already taken the protected branch in plan().
    recorded_correction = bool(valid_fact and existing_tab and existing_tab != 'refunds'
        and row['classification_source'] == 'inference' and not links.get(tid)
        and (not board or json.loads(board[1]).get('confirmed_by') == 'automatic')
        and (not recorded_tab or recorded_tab == existing_tab))
    airfare_ota = bool(re.search(r'gotogate|고투게이트', str(row.get('merchant') or ''), re.I))
    residual_with_fact = (valid_fact and row['classification_source'] == 'owner_card_residual')
    if (residual_with_fact or (airfare_ota and row['classification_source'] == 'owner_card_residual')) and not existing_tab:
        verified_item = fact.get('item') if valid_fact else None
        chosen.update(item=verified_item or infer_item(dict(chosen, item=''))[0], description='')
    if (not valid_fact and not airfare_ota and not existing_tab
            and row.get('card_tail') == '3820' and row.get('transaction_direction') == 'purchase'):
        owner_policy = _card3820_owner_policy(chosen, trips, _canonical=valid)
        if owner_policy is None:
            # No special-card match must not leave a human classification task.
            # Valid ordinary purchases still use the shared real-trip/quarter
            # inference below. Source/date/money guards remain authoritative.
            if _quarter_destination(chosen) is None:
                return None, True
        else:
            chosen.update({key: owner_policy[key] for key in FIELDS if key in owner_policy})
            chosen.update(classification_state='classified', classification_source=owner_policy['source'],
                          classification_basis=owner_policy['basis'])
            return chosen, False

    link = links.get(tid)
    original = resolved.get((link or {}).get('original_id'))
    if link and not link.get('inferred') and original and original.get('item'):
        chosen.update(item=original['item'], trip_id=original.get('trip_id') or '',
                      display_tab_id=original.get('display_tab_id') or '')
        item_basis = '검증된 원결제 항목·여행 상속'
    else:
        chosen['raw_row'] = json.loads(row['raw_row_json'] or '{}')
        chosen['item'], item_basis = infer_item(chosen)
        if reconsider:
            specific, _ = infer_item(dict(chosen, item=''))
            if chosen['item'] in ('기타경비', '현지경비', '여행경비'):
                chosen['item'] = specific
            item_basis = '기존 항목·카드 업종·서비스 용도 재대조'
    applied_fact = False
    if (valid_fact and chosen.get('display_tab_id') != 'refunds'
            and chosen['item'] != '분기 기타비용' and (not existing_tab or recorded_correction)):
        applied_fact = True
        chosen.update(trip_id=fact['trip_id'], display_tab_id=fact['trip_id'])
        if chosen['item'] in ('', '기타경비', '현지경비', '여행경비') and fact.get('item'):
            chosen['item'] = fact['item']
        item_basis += ' · 예약 이용기간 근거 우선: ' + fact['basis']
    quarter_assigned = False
    special = (chosen.get('display_tab_id') == 'refunds' or chosen['item'] == '분기 기타비용')
    if special:
        target, trip_basis = chosen.get('trip_id') or '', '환불/분기 비용 기존 배정 유지'
    else:
        rerank = (reconsider and not existing_tab and not valid_fact and not link
                  and (row['classification_source'] == 'inference' or (
                      row['classification_source'] in {'code_inference','auto_inferred'}
                      and '다음 여행 준비기간 · ' in (row['classification_basis'] or '')))
                  and '예약 이용기간' not in (row['classification_basis'] or ''))
        target, trip_basis = infer_trip(chosen, list(valid.values()), nets=nets,
                                      reconsider=rerank, _canonical=valid, completed_evidence=fact)
        if target:
            chosen.update(trip_id=target, display_tab_id=target)
            if reconsider and applied_fact:
                trip_basis = fact['basis']
            elif reconsider:
                ranked = card_trip_candidates(chosen, list(valid.values()), nets=nets, _canonical=valid)
                trip_basis = next((candidate['basis'] for candidate in ranked if candidate['trip_id'] == target),
                                  '유효 여행 유지 · 이용일 단서 없음')
        else:
            quarter = _quarter_destination(chosen)
            if quarter and (rerank or chosen.get('display_tab_id') in (None, '', 'unclassified')):
                # Preserve an explicit item rule that matched this import. The
                # transaction's prior source is empty on a new import, while
                # ``chosen`` already carries the rule provenance.
                quarter_item = (chosen['item'] if chosen['item'] and chosen.get('classification_source') in
                                {'rule','pattern','user_exception','owner_booking'} else '분기 기타비용')
                chosen.update(display_tab_id=quarter[0], trip_id='',
                              item=quarter_item,
                              description=chosen.get('description') or quarter[1])
                trip_basis = '실제 여행 후보 없음 · 결제일 기준 분기 기타비용'
                quarter_assigned = True
            else:
                chosen['display_tab_id'] = chosen.get('display_tab_id') or 'unclassified'
    from .trip_selection import is_fukutake_purchase
    owner_item_correction = is_fukutake_purchase(row) and chosen['item'] != row['item']
    needs_completion = ((quarter_assigned and chosen['display_tab_id'] != row['display_tab_id'])
                        or (completed_period(row) and valid_fact and any(
                            chosen[k] != row[k] for k in ('trip_id','display_tab_id','item')))
                        or owner_item_correction or reconsider or row['classification_state'] != 'classified' or not row['item']
                        or (not special and valid and not (row['trip_id'] in valid or row['display_tab_id'] in valid))
                        or (existing_tab and row['display_tab_id'] in (None, '', 'unclassified')
                            and chosen['display_tab_id'] != row['display_tab_id']))
    if not needs_completion:
        return None, False
    chosen.update(classification_state='classified', classification_source='inference',
                  classification_basis=f'AUTO_INFERRED · 낮음 · {item_basis} · {trip_basis} · {POLICY}')
    if reconsider:
        unchanged = all(chosen.get(k) == row.get(k) for k in ('item', 'trip_id', 'display_tab_id'))
        if unchanged and row['classification_source'] not in ('', 'inference'):
            chosen['classification_source'] = row['classification_source']
        chosen['classification_basis'] = 'CODE_REVIEW · ' + chosen['classification_basis']
    if link and not link.get('inferred') and original and original.get('item'):
        chosen.update(classification_source='refund_original',
                      classification_basis=f"원거래 승인번호 {row['original_approval_number']}의 배정을 따름")
    if not reconsider and row['classification_source'] in ('rule_conflict', 'inference_conflict',
                                                            'travel_location_hold', 'booking_evidence_needed'):
        chosen['classification_basis'] += ' · 이전 단서: ' + (row['classification_basis'] or '')[:600]
    return chosen, False


def plan(conn, trips, *, nets=None, transaction_ids=None, reconsider=False, evidence=None):
    from .decision_provenance import closed_review_ids
    closed_reviews = closed_review_ids(conn)
    """Read only. Private targets remain in memory; callers publish aggregate summaries."""
    selected = None if transaction_ids is None else set(transaction_ids)
    context = _context(conn, selected)
    rows, decisions, holds, excluded, overrides, ledger, boards = context
    valid = canonical_trip_periods(trips)
    from .partial_refund import refund_links
    links = refund_links(conn, [r['transaction_id'] for r in rows])
    targets, protected = [], 0
    evidence = evidence or {}
    resolved = {r['transaction_id']: r for r in rows}
    # A scoped refund still inherits its actual original outside this batch.
    # Load only those dependencies instead of materializing every source row.
    originals = {link['original_id'] for link in links.values()} - resolved.keys()
    if originals:
        resolved.update((row['transaction_id'], row) for row in _read(conn, originals))
    for row in sorted(rows, key=lambda r: (r['transaction_direction'] != 'purchase', r['transaction_id'])):
        tid = row['transaction_id']
        if selected is not None and tid not in selected:
            continue
        from .closed_period import excluded as completed_excluded
        if completed_excluded(row, trips, evidence=evidence.get(tid),
                    manual=tid in decisions or 'card-'+tid in overrides):
            protected += 1
            continue
        if _protected_row(row, tid, holds, excluded):
            protected += 1
            continue
        if row['classification_source'] == 'ai_inference':
            # P1 never silently overwrites a recorded P2 judgement. A new AI
            # review is explicit and version-bound in ai_classification.
            continue
        if _refund_original_is_complete(row, tid, links, reconsider):
            continue
        if (row.get('card_tail') == '3820'
                and (row.get('decided_at') is not None
                     or row.get('classification_source') in ('user_decision', 'user_exception'))):
            # The owner policy is intentionally subordinate to an explicit
            # decision, including a decision whose trip is blank.
            protected += 1
            continue
        if tid in closed_reviews:
            protected += 1
            continue
        has_history = _has_history(row, tid, decisions, overrides)
        current = tuple(row[k] or '' for k in FIELDS)
        chosen = dict(row)
        if has_history:
            chosen = _restore_historical_row(row, chosen, tid, valid, nets, decisions, ledger, boards)
        else:
            row_evidence = evidence
            if tid in ledger or 'card-' + tid in boards:
                refund = conn.execute(
                    "SELECT 1 FROM transactions WHERE issuer=? AND card_tail=?"
                    " AND original_approval_number=? AND COALESCE(original_approval_number,'')!=''"
                    " AND (transaction_direction IN ('cancellation','refund') OR amount_krw<0) LIMIT 1",
                    (row['issuer'], row['card_tail'], row['approval_number'])).fetchone()
                if refund:
                    row_evidence = {}
            chosen, protected_by_policy = _classify_new_row(
                row, chosen, tid, valid, trips, nets, links, resolved, ledger, boards,
                reconsider, row_evidence)
            if protected_by_policy:
                protected += 1
                continue
            if chosen is None:
                continue
        values = tuple(chosen.get(k) or '' for k in FIELDS)
        if values != current:
            correction = bool(not has_history and reconsider and evidence.get(tid)
                and chosen.get('trip_id') != row.get('trip_id')
                and '예약 이용기간 근거 우선:' in chosen.get('classification_basis', '')
                and ('card-' + tid in boards or tid in ledger))
            targets.append({'id': tid, 'values': values, 'revision': row['revision'],
                            'has_prior_classification': has_history,
                            **({'booking_trip_correction': True} if correction else {})})
            resolved[tid] = chosen
    payload = [context, trips, nets or {}, sorted(selected) if selected is not None else None,
               targets, POLICY, reconsider, evidence]
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        default=lambda value: sorted(value) if isinstance(value, set) else str(value)).encode()).hexdigest()
    scanned = sum(selected is None or row['transaction_id'] in selected for row in rows)
    return {'digest': fingerprint, 'targets': targets,
            'summary': {'to_classify': len(targets), 'protected': protected,
                        'valid_trips': len(valid), 'policy': POLICY,
                        'scanned': scanned, 'reviewed': scanned - protected, 'reconsider': reconsider}}


def apply(conn, expected, trips, *, nets=None, transaction_ids=None, reconsider=False, evidence=None):
    """Atomic classification-only writes; amounts, source identity and financial links stay intact."""
    from .db import utc_now
    nested = conn.in_transaction
    conn.execute('SAVEPOINT complete_card_classification' if nested else 'BEGIN IMMEDIATE')
    try:
        current = plan(conn, trips, nets=nets, transaction_ids=transaction_ids,
                       reconsider=reconsider, evidence=evidence)
        if current['digest'] != expected['digest']:
            raise ValueError('CLASSIFICATION_PREVIEW_STALE')
        for target in current['targets']:
            tid, values = target['id'], target['values']
            correction = target.get('booking_trip_correction', False)
            before = None
            if correction:
                original = _read(conn, {tid})[0]
                before = {'transaction': {key: original[key] for key in (*FIELDS, 'revision')},
                    'ledger': conn.execute('SELECT display_tab_id,trip_id FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()}
            conn.execute('UPDATE transactions SET ' + ','.join(k+'=?' for k in FIELDS)
                         + ',revision=revision+1 WHERE transaction_id=? AND revision=?',
                         (*values, tid, target['revision']))
            item, tab, trip = values[3], values[5], values[6]
            # Existing records only gain missing classification fields. No new entries or payment links.
            conn.execute("UPDATE ledger_entries SET item=CASE WHEN COALESCE(item,'')='' THEN ? ELSE item END,"
                "display_tab_id=CASE WHEN COALESCE(display_tab_id,'') IN ('','unclassified') THEN ? ELSE display_tab_id END,"
                "trip_id=CASE WHEN COALESCE(trip_id,'') IN ('','unclassified') THEN ? ELSE trip_id END WHERE transaction_id=?",
                (item, tab, trip, tid))
            if correction:
                conn.execute('UPDATE ledger_entries SET display_tab_id=?,trip_id=? WHERE transaction_id=?',
                             (tab, trip, tid))
            board = conn.execute('SELECT payload_json,display_tab_id FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone()
            if board:
                payload = json.loads(board[0])
                payload['classification_state'] = 'classified'
                payload['item'] = payload.get('item') or item
                board_tab = tab if board[1] in (None,'','unclassified') else board[1]
                if correction:
                    board_tab = tab
                    payload.update(display_tab_id=tab, classification_source=values[1],
                                   classification_basis=values[2])
                if payload.get('display_tab_id') in (None,'','unclassified'):
                    payload['display_tab_id'] = board_tab
                if payload != json.loads(board[0]) or board_tab != board[1]:
                    if correction:
                        old_revision = conn.execute('SELECT revision FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone()[0]
                        payload['revision'] = old_revision + 1
                        conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                            ('card-'+tid, old_revision+1, board[0], json.dumps(payload,ensure_ascii=False,sort_keys=True),
                             '', 'rule_change', 'automatic', utc_now(), 'booking-period-'+current['digest'][:24]))
                    conn.execute('UPDATE board_rows SET payload_json=?,display_tab_id=?,revision=revision+1 WHERE row_id=?',
                        (json.dumps(payload,ensure_ascii=False,sort_keys=True), board_tab, 'card-'+tid))
            if correction:
                conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                    (utc_now(), 'card.booking_trip_correction', tid,
                     json.dumps({'before': before, 'trip_id': trip, 'basis': values[2]},ensure_ascii=False,sort_keys=True)))
        if current['targets']:
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(), 'card.automatic_classification', POLICY,
                 json.dumps(current['summary'],sort_keys=True)))
        conn.execute('RELEASE SAVEPOINT complete_card_classification' if nested else 'COMMIT')
        return current['summary']
    except BaseException:
        if nested:
            conn.execute('ROLLBACK TO SAVEPOINT complete_card_classification')
            conn.execute('RELEASE SAVEPOINT complete_card_classification')
        else:
            conn.rollback()
        raise
