"""분류와 기록은 한 동작이다. 모든 배치의 분류 가능한 거래를 장부에 기록한다(소유자 승인 2026-10-15)."""
import sqlite3


def batch_is_new(conn, batch_id: str) -> bool:
    try:
        row = conn.execute('SELECT 1 FROM import_batches WHERE batch_id=?', (batch_id,)).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None
