"""Complete card classifications from weak evidence without inventing payment links."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from .provisional_assignment import canonical_trip_periods, card_trip_candidates
from .quarter_costs import quarter_of
from .rules import merchant_country

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
    """Completion is classification plus a real trip; financial links are separate."""
    reasons = []
    trip = row.get('trip_id') or row.get('display_tab_id') or ''
    source = row.get('classification_source') or ''
    manual = bool(row.get('decided_at')) or source in {'user_decision', 'user_exception', 'manual'}
    if row.get('classification_state') != 'classified' or not row.get('item'):
        reasons.append('TRANSACTION_NATURE_UNCONFIRMED')
    direction = str(row.get('transaction_direction') or '').strip().casefold()
    kind = str(row.get('transaction_kind') or '').strip()
    if direction not in {'purchase', 'cancellation', 'refund'} or not kind:
        if 'TRANSACTION_NATURE_UNCONFIRMED' not in reasons:
            reasons.append('TRANSACTION_NATURE_UNCONFIRMED')
    if trip not in valid:
        reasons.append('TRIP_INVALID_OR_MISSING')
    if (row.get('trip_id') in valid and row.get('display_tab_id') in valid
            and row['trip_id'] != row['display_tab_id']):
        reasons.append('TRIP_ASSIGNMENT_CONFLICT')
    if any(row.get(k) for k in ('parse_error', 'conflict_reason', 'duplicate_of')):
        reasons.append('SOURCE_UNRESOLVED')
    if source in {'rule_conflict', 'inference_conflict', 'travel_location_hold', 'manual_hold'}:
        reasons.append('CLASSIFICATION_SOURCE_CONFLICT')
    return {'transaction_id': row['transaction_id'], 'complete': not reasons,
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
    optional = [field for field in ('parse_error', 'conflict_reason', 'duplicate_of') if field in available]
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


def infer_trip(row, trips, *, nets=None, reconsider=False):
    """Pick the best real trip, resolving weak ties deterministically and explaining them."""
    valid = canonical_trip_periods(trips)
    for key in ('trip_id', 'display_tab_id'):
        if row.get(key) in valid and not reconsider:
            return row[key], '기존 실제 여행 유지'
    candidates_trips = list(valid.values())
    candidates = card_trip_candidates(row, candidates_trips, nets=nets)
    if candidates:
        candidates.sort(key=lambda c: (-c['score'], valid[c['trip_id']]['starts_on'], c['trip_id']))
        top = candidates[0]
        ties = sum(c['score'] == top['score'] for c in candidates)
        return top['trip_id'], top['basis'] + (f' · 동률 {ties}개 중 일정·ID 고정 순서로 선택' if ties > 1 else '')
    if valid:
        # A missing use date does not turn the posting date into a service date.
        target = max(valid, key=lambda key: (valid[key]['starts_on'], key))
        return target, '이용일 단서 없음 · 가장 최근 시작한 실제 여행 선택'
    return '', '등록된 유효 여행 없음 · 비용 항목 분류 완료'


def _card3820_owner_policy(row, trips):
    """Apply the explicit 3820 policy before generic completion inference.

    This mirrors the primary card-classification path: the Singapore exception
    wins when exactly one matching trip exists; otherwise an eligible domestic
    purchase goes to its transaction quarter.  Missing dates and foreign
    location holds stay unresolved so this completion pass cannot invent a
    travel or quarter assignment.
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

    valid = canonical_trip_periods(trips)
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

    if row.get('foreign_currency') or merchant_country(row) not in ('', 'KR'):
        return None
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
    rows = [dict(zip(columns, r)) for r in conn.execute('SELECT ' + ','.join(columns) + ' FROM transactions ORDER BY transaction_id')
            if selected is None or r[0] in selected]
    return rows


def _context(conn, selected=None):
    rows = _read(conn)
    decisions = {r[0]: r[1] for r in conn.execute(
        'SELECT transaction_id,display_tab_id FROM review_decisions ORDER BY revision')}
    holds = {r[0] for r in conn.execute('SELECT transaction_id FROM transaction_review_holds')}
    excluded = {r[0] for r in conn.execute('SELECT transaction_id FROM transaction_company_exclusions WHERE excluded=1')}
    overrides = {r[0] for r in conn.execute('SELECT row_id FROM board_manual_overrides')}
    ledger = {r[0]: dict(zip(('item','description','display_tab_id','trip_id'), r[1:])) for r in conn.execute(
        'SELECT transaction_id,item,description,display_tab_id,trip_id FROM ledger_entries')}
    boards = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT row_id,display_tab_id,payload_json,revision FROM board_rows WHERE row_kind='expense'")}
    return rows, decisions, holds, excluded, overrides, ledger, boards


def plan(conn, trips, *, nets=None, transaction_ids=None, reconsider=False, evidence=None):
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
    for row in sorted(rows, key=lambda r: (r['transaction_direction'] != 'purchase', r['transaction_id'])):
        tid = row['transaction_id']
        if selected is not None and tid not in selected:
            continue
        if tid in holds or tid in excluded or any(row[k] for k in ('parse_error','duplicate_of','conflict_reason')):
            protected += 1
            continue
        # A refund row that already inherited its item from a verified
        # original is complete even when its own trip display is blank. Do
        # not re-run weak trip inference on the next preview.
        if (row['classification_state'] == 'classified'
                and row.get('classification_source') == 'refund_original'):
            verified = links.get(tid) or {}
            if (not reconsider or verified.get('inferred')
                    or verified.get('status') not in ('full', 'partial')):
                continue
        if (row.get('card_tail') == '3820'
                and (row.get('decided_at') is not None
                     or row.get('classification_source') in ('user_decision', 'user_exception'))):
            # The owner policy is intentionally subordinate to an explicit
            # decision, including a decision whose trip is blank.
            protected += 1
            continue
        has_history = (tid in decisions or row['decided_at'] is not None
                  or row['classification_source'] in ('user_decision','user_exception','owner_booking')
                  or 'card-' + tid in overrides)
        current = tuple(row[k] or '' for k in FIELDS)
        chosen = dict(row)
        if has_history:
            # History protects the entered category and actual chosen trip.
            # A blank/default trip is not evidence that the owner wanted no trip.
            if not chosen['item']:
                chosen['raw_row'] = json.loads(row['raw_row_json'] or '{}')
                chosen['item'], _ = infer_item(chosen)
            chosen['classification_state'] = 'classified'
            empty_trip = (not row['trip_id'] and row['display_tab_id'] in (None,'','unclassified'))
            if empty_trip and chosen['item'] != '분기 기타비용':
                recorded = ledger.get(tid) or {}
                board = boards.get('card-'+tid)
                candidates = [board[0] if board else '', decisions.get(tid),
                              recorded.get('trip_id'), recorded.get('display_tab_id')]
                target = next((value for value in candidates if value in valid or value == 'refunds'), '')
                if target:
                    chosen.update(display_tab_id=target, trip_id='' if target == 'refunds' else target,
                        classification_basis='TRIP_ASSIGNMENT_RESTORED · 기존 항목 보존 · 기존 장부/분류 이력의 배정 복원')
                else:
                    target, basis = infer_trip(chosen, list(valid.values()), nets=nets)
                    if target:
                        chosen.update(display_tab_id=target,trip_id=target,
                            classification_basis=f'AUTO_TRIP_INFERRED · 낮음 · 기존 항목 보존 · {basis} · {POLICY}')
                if target and row['classification_source'] not in ('user_decision','user_exception','owner_booking'):
                    chosen['classification_source'] = 'inference'
        else:
            recorded = ledger.get(tid) or {}
            board = boards.get('card-'+tid)
            if board and not chosen['item']:
                chosen['item'] = json.loads(board[1]).get('item') or ''
            if recorded.get('item'):
                chosen['item'] = recorded['item']
            recorded_tab = recorded.get('trip_id') or recorded.get('display_tab_id')
            existing_tab = next((value for value in (board[0] if board else '', recorded_tab)
                                 if value in valid or value == 'refunds'), '')
            if existing_tab and not (chosen['trip_id'] in valid or chosen['display_tab_id'] in valid):
                chosen.update(trip_id='' if existing_tab == 'refunds' else existing_tab, display_tab_id=existing_tab)
            fact = evidence.get(tid) if reconsider else None
            valid_fact = bool(fact and fact.get('source_hash') == row['source_hash']
                              and fact.get('trip_id') in valid
                              and row['transaction_direction'] == 'purchase')
            airfare_ota = bool(re.search(r'gotogate|고투게이트', str(row.get('merchant') or ''), re.I))
            residual_with_fact = (valid_fact and row['classification_source'] == 'owner_card_residual')
            if (residual_with_fact or (airfare_ota and row['classification_source'] == 'owner_card_residual')) and not existing_tab:
                chosen.update(item=(fact or {}).get('item') or infer_item(dict(chosen,item=''))[0], description='')
            if not valid_fact and not airfare_ota and not existing_tab and row.get('card_tail') == '3820' and row.get('transaction_direction') == 'purchase':
                owner_policy = _card3820_owner_policy(chosen, trips)
                if owner_policy is None:
                    # The explicit rule keeps unreadable dates and foreign
                    # location holds out of generic completion inference.
                    protected += 1
                    continue
                chosen.update({key: owner_policy[key] for key in FIELDS if key in owner_policy})
                chosen['classification_state'] = 'classified'
                chosen['classification_source'] = owner_policy['source']
                chosen['classification_basis'] = owner_policy['basis']
                values = tuple(chosen.get(k) or '' for k in FIELDS)
                if values != current:
                    targets.append({'id': tid, 'values': values, 'revision': row['revision'],
                                    'has_prior_classification': has_history})
                    resolved[tid] = chosen
                continue
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
            if (fact and fact.get('source_hash') == row['source_hash']
                    and fact.get('trip_id') in valid
                    and chosen.get('display_tab_id') != 'refunds'
                    and chosen['item'] != '분기 기타비용'
                    and not existing_tab
                    and row['transaction_direction'] == 'purchase'):
                chosen.update(trip_id=fact['trip_id'], display_tab_id=fact['trip_id'])
                if chosen['item'] in ('', '기타경비', '현지경비', '여행경비') and fact.get('item'):
                    chosen['item'] = fact['item']
                item_basis += ' · 예약 이용기간 근거 우선: ' + fact['basis']
            special = (chosen.get('display_tab_id') == 'refunds' or chosen['item'] == '분기 기타비용')
            if special:
                target, trip_basis = chosen.get('trip_id') or '', '환불/분기 비용 기존 배정 유지'
            else:
                rerank = (reconsider and not existing_tab and not valid_fact and not link
                          and row['classification_source'] == 'inference'
                          and '예약 이용기간' not in (row['classification_basis'] or ''))
                target, trip_basis = infer_trip(chosen, list(valid.values()), nets=nets, reconsider=rerank)
                if target:
                    chosen.update(trip_id=target, display_tab_id=target)
                    if reconsider:
                        ranked = card_trip_candidates(chosen, list(valid.values()), nets=nets)
                        trip_basis = next((candidate['basis'] for candidate in ranked
                                           if candidate['trip_id'] == target),
                                          '유효 여행 유지 · 이용일 단서 없음')
                else:
                    chosen['display_tab_id'] = chosen.get('display_tab_id') or 'unclassified'
            needs_completion = (reconsider or row['classification_state'] != 'classified' or not row['item']
                                or (not special and valid
                                    and not (row['trip_id'] in valid or row['display_tab_id'] in valid))
                                or (existing_tab and row['display_tab_id'] in (None,'','unclassified')
                                    and chosen['display_tab_id'] != row['display_tab_id']))
            if not needs_completion:
                continue
            chosen.update(classification_state='classified', classification_source='inference',
                          classification_basis=f'AUTO_INFERRED · 낮음 · {item_basis} · {trip_basis} · {POLICY}')
            if reconsider:
                unchanged = all(chosen.get(k) == row.get(k) for k in ('item', 'trip_id', 'display_tab_id'))
                if unchanged and row['classification_source'] not in ('', 'inference'):
                    chosen['classification_source'] = row['classification_source']
                chosen['classification_basis'] = 'P2_REVIEW · ' + chosen['classification_basis']
            if link and not link.get('inferred') and original and original.get('item'):
                chosen.update(classification_source='refund_original',
                    classification_basis=f"원거래 승인번호 {row['original_approval_number']}의 배정을 따름")
            if not reconsider and row['classification_source'] in ('rule_conflict','inference_conflict','travel_location_hold','booking_evidence_needed'):
                chosen['classification_basis'] += ' · 이전 단서: ' + (row['classification_basis'] or '')[:600]
        values = tuple(chosen.get(k) or '' for k in FIELDS)
        if values != current:
            targets.append({'id': tid, 'values': values, 'revision': row['revision'], 'has_prior_classification': has_history})
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
            conn.execute('UPDATE transactions SET ' + ','.join(k+'=?' for k in FIELDS)
                         + ',revision=revision+1 WHERE transaction_id=? AND revision=?',
                         (*values, tid, target['revision']))
            item, tab, trip = values[3], values[5], values[6]
            # Existing records only gain missing classification fields. No new entries or payment links.
            conn.execute("UPDATE ledger_entries SET item=CASE WHEN COALESCE(item,'')='' THEN ? ELSE item END,"
                "display_tab_id=CASE WHEN COALESCE(display_tab_id,'') IN ('','unclassified') THEN ? ELSE display_tab_id END,"
                "trip_id=CASE WHEN COALESCE(trip_id,'') IN ('','unclassified') THEN ? ELSE trip_id END WHERE transaction_id=?",
                (item, tab, trip, tid))
            board = conn.execute('SELECT payload_json,display_tab_id FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone()
            if board:
                payload = json.loads(board[0])
                payload['classification_state'] = 'classified'
                payload['item'] = payload.get('item') or item
                board_tab = tab if board[1] in (None,'','unclassified') else board[1]
                if payload.get('display_tab_id') in (None,'','unclassified'):
                    payload['display_tab_id'] = board_tab
                if payload != json.loads(board[0]) or board_tab != board[1]:
                    conn.execute('UPDATE board_rows SET payload_json=?,display_tab_id=?,revision=revision+1 WHERE row_id=?',
                        (json.dumps(payload,ensure_ascii=False,sort_keys=True), board_tab, 'card-'+tid))
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
