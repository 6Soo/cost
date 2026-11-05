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
    """One read-only view for card periods, gaps and uploaded source files.

    Query periods come only from validated coverage events, never transaction
    date minima/maxima or source filenames. Unconfirmed files remain visible
    for the owner without being represented as covered intervals.
    """
    if not available(board.conn):
        return dict(available=False, coverages=[], gaps=[], rechecks=[], files=[],
                    summary=dict(cards=0, axes=0, gaps=0, recheck_files=0))
    store = CoverageStore(board.conn)
    result = dict(store.summary(**filters), available=True)
    events = store._records()
    by_batch = {}
    for entry in events:
        by_batch.setdefault(entry.get('batch_id'), []).append(entry)
    # Read small metadata only. In particular, never load stored source bytes
    # or recompute all card classifications on each dashboard refresh.
    rows = board.conn.execute(
        'SELECT b.batch_id,b.filename,b.status,b.row_count,b.error_count,b.received_at,'
        'COUNT(DISTINCT x.transaction_id) '
        'FROM import_batches b LEFT JOIN import_batch_rows x ON x.batch_id=b.batch_id '
        'GROUP BY b.batch_id ORDER BY b.received_at DESC,b.batch_id DESC LIMIT 201'
    ).fetchall()
    files = []
    for batch_id, filename, status, rows_count, errors, received_at, unique_count in rows[:200]:
        proofs = by_batch.get(batch_id, [])
        confirmed = [p for p in proofs if p.get('confirmed')]
        latest = proofs[-1] if proofs else {}
        files.append(dict(batch_id=batch_id, filename=filename,
                          status=status, row_count=rows_count, unique_rows=unique_count,
                          error_count=errors, received_at=received_at,
                          card_id=latest.get('card_id', ''), issuer=latest.get('issuer', ''),
                          card_tail=latest.get('card_tail', ''),
                          date_basis=latest.get('date_basis', ''),
                          source_scope=latest.get('identity_scope', ''),
                          confirmed_periods=[dict(start=p['start_date'], end=p['end_date'],
                                                  date_basis=p['date_basis']) for p in confirmed],
                          coverage_status='confirmed' if confirmed else
                                          ('recheck' if proofs else 'unknown')))
    result['files'] = files
    result['has_more_files'] = len(rows) > 200
    result['summary'] = dict(cards=len(set(c['card_id'] for c in result['coverages'])),
                             axes=len(result['coverages']),
                             gaps=sum(len(g['gaps']) for g in result['gaps']),
                             recheck_files=sum(f['coverage_status'] != 'confirmed' for f in files))
    return result


def record_coverage(board, batch_id, evidence):
    if not available(board.conn):
        raise StoreError('COVERAGE_NOT_READY', '조회기간 저장 기능의 준비가 필요합니다. 기존 업로드는 계속 사용할 수 있습니다.')
    with board._lock:
        return CoverageStore(board.conn).record(batch_id, evidence)


def dispatch(handler, parsed, board, *, query=None, raw=None, csrf=''):
    parts = parsed.path.strip('/').split('/')
    summary_route = parsed.path == '/api/cards/coverage/summary'
    batch_route = len(parts) in (4, 5) and parts[:2] == ['api', 'imports'] and parts[3] == 'coverage'
    baseline_route = parsed.path == '/api/cards/coverage/baseline'
    if not summary_route and not batch_route and not baseline_route:
        return False
    from .ledger_board import current_role
    if current_role() != 'owner':
        handler._send_json({'code': 'FORBIDDEN'}, 403)
        return True
    try:
        if raw is None:
            with board._lock:
                if baseline_route:
                    handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
                    return True
                if summary_route:
                    filters = {key: (query or {}).get(key, [None])[0] for key in ('issuer', 'card_tail', 'date_basis', 'through')}
                    result = get_coverage_summary(board, **filters)
                elif len(parts) == 4:
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
                result = CoverageStore(board.conn).set_baseline(
                    card_id=payload.get('card_id', ''), issuer=payload.get('issuer', ''),
                    card_tail=payload.get('card_tail', ''), date_basis=payload.get('date_basis', ''),
                    management_start=payload.get('management_start', ''),
                    expected_revision=payload.get('expected_revision', 0))
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
