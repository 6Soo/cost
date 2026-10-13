"""Explicit, reversible company-expense exclusion. Source and decisions never change."""
import hashlib

from .db import StoreError, canonical, decided_sql, utc_now


def states(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='transaction_company_exclusions' AND type='table'").fetchone():
        return {}
    return {tid: dict(source_hash=source, excluded=bool(excluded), revision=revision)
            for tid, source, excluded, revision in conn.execute(
                'SELECT transaction_id, source_hash, excluded, revision FROM transaction_company_exclusions')}


def set_excluded(store, *, transaction_id, expected_revision, expected_exclusion_revision,
                 excluded, confirmed, request_id, note=''):
    if confirmed is not True:
        raise StoreError('EXCLUSION_CONFIRMATION_REQUIRED', '회사 경비 제외 또는 복원을 별도로 확인해 주세요')
    if type(excluded) is not bool or not isinstance(request_id, str) or not request_id.strip():
        raise StoreError('INVALID_INPUT', '제외 상태와 요청 번호가 필요합니다')
    payload = dict(transaction_id=transaction_id, expected_revision=expected_revision,
                   expected_exclusion_revision=expected_exclusion_revision, excluded=excluded, note=note)
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
    with store.lock:
        store.conn.execute('BEGIN IMMEDIATE')
        try:
            replay = store.replay_request(request_id, 'company_exclusion', digest)
            if replay is not None:
                store.conn.commit()
                return replay
            row = store.conn.execute(
                'SELECT source_hash, revision, ' + decided_sql() + ', transaction_direction, duplicate_of, '
                'conflict_reason, parse_error FROM transactions WHERE transaction_id=?', (transaction_id,)).fetchone()
            if row is None:
                raise StoreError('NOT_FOUND', '거래를 찾을 수 없습니다')
            source, revision, decided, direction, duplicate, conflict, parse_error = row
            current = states(store.conn).get(transaction_id)
            version = current['revision'] if current else 0
            if revision != expected_revision or version != expected_exclusion_revision:
                raise StoreError('REVISION_CONFLICT', '거래 또는 제외 상태가 바뀌었습니다. 다시 확인해 주세요')
            if current and current['source_hash'] != source:
                raise StoreError('SOURCE_CONFLICT', '제외를 확인한 원본이 달라 다시 검토해야 합니다')
            from .partial_refund import refund_group
            from .review_holds import active_holds
            booked = store.conn.execute('SELECT 1 FROM ledger_entries WHERE transaction_id=?', (transaction_id,)).fetchone()
            if (booked or (decided and excluded) or direction != 'purchase' or duplicate or conflict or parse_error
                    or transaction_id in active_holds(store.conn) or len(refund_group(store.conn, transaction_id)) > 1):
                raise StoreError('EXCLUSION_PROTECTED', '기록·환불·보류 거래는 이 기능으로 바꾸지 않습니다')
            if bool(current and current['excluded']) == excluded:
                result = dict(transaction_id=transaction_id, excluded=excluded, exclusion_revision=version)
            else:
                result = dict(transaction_id=transaction_id, excluded=excluded, exclusion_revision=version + 1)
                store.conn.execute(
                    'INSERT INTO transaction_company_exclusions VALUES (?,?,?,?,?,?) '
                    'ON CONFLICT(transaction_id) DO UPDATE SET excluded=excluded.excluded, '
                    'revision=excluded.revision, note=excluded.note, updated_at=excluded.updated_at',
                    (transaction_id, source, int(excluded), version + 1, str(note), utc_now()))
                store.log_change('transaction.company_exclusion', transaction_id,
                                 dict(result, source_hash=source, from_excluded=bool(current and current['excluded']), note=note))
            store.remember_request(request_id, 'company_exclusion', digest, result)
            store.conn.commit()
            return result
        except Exception:
            store.conn.rollback()
            raise
