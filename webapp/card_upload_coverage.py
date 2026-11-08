"""Read-only inspection and owner-scoped query coverage writes."""
import hashlib
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
    """Owner-only read projection based on observed transaction dates.

    Query-period evidence is intentionally not part of this dashboard anymore.
    Each observed transaction day contributes one date; gaps are days between
    the first and last observations with no transactions. This GET does not parse original
    blobs or write DB.
    """
    if not available(board.conn):
        return dict(available=False, coverages=[], gaps=[], rechecks=[],
                    cards=[], files=[], overview={}, coverage_state='unavailable')
    from app.card_upload_coverage import Period, find_gaps, merge_periods, parse_iso_date

    date_basis = '거래일자'
    selected = {}
    file_rows = {}
    rows = board.conn.execute(
        "SELECT b.batch_id,b.filename,b.status,b.row_count,b.error_count,b.received_at,"
        "COUNT(DISTINCT t.transaction_id),"
        "GROUP_CONCAT(DISTINCT COALESCE(NULLIF(t.approval_date,''),NULLIF(t.posting_date,''))),"
        "t.issuer "
        "FROM import_batches b LEFT JOIN import_batch_rows r ON r.batch_id=b.batch_id "
        "LEFT JOIN transactions t ON t.transaction_id=r.transaction_id "
        "GROUP BY b.batch_id,t.issuer ORDER BY b.received_at DESC,b.batch_id DESC"
    ).fetchall()
    for row in rows:
        (batch_id, filename, status, source_rows, errors, received_at,
         unique, observed_dates, issuer) = row
        dates = sorted({parsed for value in (observed_dates or '').split(',')
                        if (parsed := parse_iso_date(value))})
        first, last = (dates[0], dates[-1]) if dates else ('', '')
        if filters.get('issuer') and filters['issuer'] != issuer:
            continue
        if filters.get('date_basis') and filters['date_basis'] != date_basis:
            continue
        file = file_rows.setdefault(batch_id, dict(batch_id=batch_id, filename=filename, status=status,
            source_rows=source_rows, error_count=errors, received_at=received_at, unique_transactions=0,
            transaction_start='', transaction_end='', issuer_hint='', card_tail_hint='',
            card_hint_scope='unknown', query_periods=[], transaction_periods=[],
            coverage_status='no_transaction_dates', zero_rows=source_rows == 0, card_ids=[], hints=set()))
        file['unique_transactions'] += unique or 0
        file['transaction_start'] = min(x for x in (file['transaction_start'], first or '') if x) if (file['transaction_start'] or first) else ''
        file['transaction_end'] = max(file['transaction_end'], last or '')
        if issuer:
            file['hints'].add(issuer)
        if first and last:
            key_source = [issuer or '', batch_id if not issuer else '']
            card_id = hashlib.sha256(json.dumps(key_source, ensure_ascii=False).encode()).hexdigest()
            if card_id not in selected:
                selected[card_id] = dict(card_id=card_id, issuer=issuer or '', card_tail='',
                                         identity_scope='issuer' if issuer else 'source_file',
                                         date_basis=date_basis, periods=[], files=[])
            if card_id not in file['card_ids']:
                file['card_ids'].append(card_id)
            selected[card_id]['periods'].extend(Period(day, day) for day in dates)
            file['transaction_periods'].append({'start': first, 'end': last, 'card_id': card_id})
            file['coverage_status'] = 'transaction_dates'
    files = list(file_rows.values())
    for file in files:
        file.pop('card_ids', None)
        hints = file.pop('hints')
        if len(hints) == 1:
            file['issuer_hint'] = next(iter(hints))
            file['card_hint_scope'] = 'issuer'
    cards = []
    for card in selected.values():
        periods = merge_periods(card.pop('periods'))
        card['periods'] = [vars(period) for period in periods]
        if periods:
            card['gaps'] = [vars(gap) for gap in find_gaps(periods, periods[0].start, periods[-1].end)]
            for file in files:
                if any(item['card_id'] == card['card_id'] for item in file['transaction_periods']):
                    card['files'].append(file)
        else:
            card['gaps'] = []
        card['status'] = 'TRANSACTION_GAPS' if card['gaps'] else 'TRANSACTION_DATES'
        cards.append(card)
    cards.sort(key=lambda c: (c['issuer'], c['card_tail'], c['card_id']))
    result = dict(available=True, coverages=[], gaps=[], rechecks=[], cards=cards, files=files,
        coverage_state='transaction_dates' if cards else 'needs_transactions', overview=dict(
        card_count=len({c['card_id'] for c in cards}),
        covered_bases=len(cards),
        gap_count=sum(len(c['gaps']) for c in cards),
        gaps_assessable=bool(cards),
        files_need_review=sum(1 for f in files if not f['transaction_start']),
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
