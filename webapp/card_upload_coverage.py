"""Read-only inspection and owner-scoped query coverage writes."""
import json
import sqlite3
from app.card_upload_coverage import CoverageStore, inspect
from app.db import StoreError


def available(conn):
    return CoverageStore(conn).available()


def inspect_file(board, content, filename, parsed=None):
    return inspect(content, filename, parsed)


def batch_inspection(board, batch_id):
    row = board.conn.execute('SELECT content_bytes,filename FROM import_batches WHERE batch_id=?', (batch_id,)).fetchone()
    if row is None:
        raise StoreError('BATCH_NOT_FOUND', '업로드 자료를 찾을 수 없습니다.')
    result = inspect(row[0], row[1])
    result.update(batch_id=batch_id, available=available(board.conn))
    result['records'] = CoverageStore(board.conn).get_coverage_for_batch(batch_id) if result['available'] else []
    return result


def get_coverage_summary(board, **filters):
    """Owner-only read projection: card/query coverage and the actual uploaded files.

    Never infer a queried period from the first/last transaction date.
    Files without rows must remain visible; unknown/weak card identity is never
    merged across uploads. This GET does not parse original blobs or write DB.
    """
    if not available(board.conn):
        return dict(available=False, coverages=[], gaps=[], rechecks=[],
                    cards=[], files=[], overview={}, coverage_state='unavailable')
    store = CoverageStore(board.conn)
    result = store.summary(**filters)
    records_by_batch = {}
    rechecks_by_batch = {}
    for evidence in store._records():
        if evidence.get('confirmed'):
            records_by_batch.setdefault(evidence['batch_id'], []).append(evidence)
        else:
            rechecks_by_batch.setdefault(evidence['batch_id'], []).append(evidence)
    selected = {}
    gap_lookup = {(g['card_id'], g['date_basis']): g['gaps'] for g in result['gaps']}
    for coverage in result['coverages']:
        key = (coverage['card_id'], coverage['date_basis'])
        selected[key] = dict(coverage, gaps=gap_lookup.get(key, []), files=[],
                             status=('GAPS_FOUND' if gap_lookup.get(key) else
                                     'BASELINE_UNSET' if not coverage.get('management_start')
                                     else 'COVERAGE_COMPLETE'))
    rows = board.conn.execute(
        "SELECT b.batch_id,b.filename,b.status,b.row_count,b.error_count,b.received_at,"
        "COUNT(DISTINCT t.transaction_id),"
        "MIN(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
        "MAX(COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
        "COUNT(DISTINCT CASE WHEN t.issuer != '' AND t.card_tail != '' "
        "THEN t.issuer || char(31) || t.card_tail END),"
        "MIN(NULLIF(t.issuer,'')),MIN(NULLIF(t.card_tail,'')) "
        "FROM import_batches b LEFT JOIN import_batch_rows r ON r.batch_id=b.batch_id "
        "LEFT JOIN transactions t ON t.transaction_id=r.transaction_id "
        "GROUP BY b.batch_id ORDER BY b.received_at DESC,b.batch_id DESC"
    ).fetchall()
    files, review_count = [], 0
    filtered = any(filters.get(k) for k in ('issuer', 'card_tail', 'date_basis'))
    for row in rows:
        (batch_id, filename, status, source_rows, errors, received_at,
         unique, first, last, card_pairs, issuer_hint, tail_hint) = row
        evidences = records_by_batch.get(batch_id, [])
        # Card/last-four are DISPLAY hints from linked transactions, not a
        # shared physical-card identity or queried-period evidence.
        single_hint = card_pairs == 1 and bool(issuer_hint and tail_hint)
        file = dict(batch_id=batch_id, filename=filename, status=status,
                    source_rows=source_rows, error_count=errors, received_at=received_at,
                    unique_transactions=unique, transaction_start=first or '',
                    transaction_end=last or '',
                    issuer_hint=issuer_hint if single_hint else '',
                    card_tail_hint=tail_hint if single_hint else '',
                    card_hint_scope='display_only' if single_hint else 'unknown',
                    query_periods=[
                        dict(start=e['start_date'], end=e['end_date'],
                             date_basis=e['date_basis'], card_id=e['card_id'])
                        for e in evidences],
                    coverage_status=('confirmed' if evidences else
                                     'needs_recheck' if rechecks_by_batch.get(batch_id) else
                                     'needs_review'),
                    zero_rows=source_rows == 0)
        matched = False
        for evidence in evidences:
            key = (evidence['card_id'], evidence['date_basis'])
            if key in selected:
                selected[key]['files'].append(file)
                matched = True
        if matched or not filtered:
            files.append(file)
            if not evidences:
                review_count += 1
    cards = sorted(selected.values(), key=lambda c: (
        c['issuer'], c['card_tail'], c['date_basis'], c['card_id']))
    # An empty coverage set cannot prove there are zero missing intervals.
    # State and gap_count are intentionally separate so the UI says "not yet
    # assessable" rather than a misleading "no gaps".
    coverage_state = ('needs_evidence' if not cards else
                      'partial' if review_count else 'confirmed')
    result.update(cards=cards, files=files, coverage_state=coverage_state, overview=dict(
        card_count=len({c['card_id'] for c in cards}),
        covered_bases=len(cards),
        gap_count=sum(len(c['gaps']) for c in cards),
        gaps_assessable=bool(cards),
        files_need_review=review_count,
        file_count=len(files)))
    return result


def record_coverage(board, batch_id, evidence):
    if not available(board.conn):
        raise StoreError('COVERAGE_NOT_READY', '조회기간 저장 기능의 준비가 필요합니다. 기존 업로드는 계속 사용할 수 있습니다.')
    with board._lock:
        return CoverageStore(board.conn).record(batch_id, evidence)


def dispatch(handler, parsed, board, *, query=None, raw=None, csrf=''):
    parts = parsed.path.strip('/').split('/')
    summary_route = parsed.path == '/api/cards/coverage/summary'
    baseline_route = parsed.path == '/api/cards/coverage/baseline'
    batch_route = len(parts) in (4, 5) and parts[:2] == ['api', 'imports'] and parts[3] == 'coverage'
    if not summary_route and not batch_route and not baseline_route:
        return False
    from .ledger_board import current_role
    if current_role() != 'owner':
        handler._send_json({'code': 'FORBIDDEN'}, 403)
        return True
    try:
        if raw is None:
            with board._lock:
                if summary_route:
                    filters = {key: (query or {}).get(key, [None])[0] for key in ('issuer', 'card_tail', 'date_basis', 'through')}
                    result = get_coverage_summary(board, **filters)
                elif batch_route and len(parts) == 4:
                    result = batch_inspection(board, parts[2])
                else:
                    handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
                    return True
            handler._send_json(result)
        elif baseline_route:
            if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
                handler._send_json({'code': 'CSRF_REQUIRED'}, 403)
                return True
            payload = json.loads(raw.decode('utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('object required')
            with board._lock:
                result = CoverageStore(board.conn).set_management_start(
                    payload.get('card_id'), payload.get('date_basis'),
                    payload.get('management_start'), payload.get('expected_revision'))
            handler._send_json(result)
        elif batch_route and len(parts) == 5 and parts[4] == 'confirm':
            if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
                handler._send_json({'code': 'CSRF_REQUIRED'}, 403)
                return True
            payload = json.loads(raw.decode('utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('object required')
            evidence = payload.get('evidence')
            if not isinstance(evidence, dict) or evidence.get('complete') is not True:
                raise ValueError('complete evidence required')
            evidence = dict(evidence, evidence_source='user', confirmed=True)
            result = record_coverage(board, parts[2], evidence)
            handler._send_json(result)
        else:
            handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
    except StoreError as exc:
        handler._send_json({'code': exc.code, 'message': str(exc)}, 409)
    except (ValueError, TypeError, KeyError, UnicodeError):
        handler._send_json({'code': 'INVALID_INPUT', 'message': '조회 조건을 확인해 주세요.'}, 422)
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc):
            raise
        handler._send_json({'code': 'COVERAGE_NOT_READY'}, 503)
    return True
