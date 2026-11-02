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
    if not available(board.conn):
        return dict(available=False, coverages=[], gaps=[], rechecks=[])
    return dict(CoverageStore(board.conn).summary(**filters), available=True)


def record_coverage(board, batch_id, evidence):
    if not available(board.conn):
        raise StoreError('COVERAGE_NOT_READY', '조회기간 저장 기능의 준비가 필요합니다. 기존 업로드는 계속 사용할 수 있습니다.')
    with board._lock:
        return CoverageStore(board.conn).record(batch_id, evidence)


def dispatch(handler, parsed, board, *, query=None, raw=None, csrf=''):
    parts = parsed.path.strip('/').split('/')
    summary_route = parsed.path == '/api/cards/coverage/summary'
    batch_route = len(parts) in (4, 5) and parts[:2] == ['api', 'imports'] and parts[3] == 'coverage'
    if not summary_route and not batch_route:
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
                elif len(parts) == 4:
                    result = batch_inspection(board, parts[2])
                else:
                    handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
                    return True
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
