"""신규 수집분만 자동 기록한다. 활성화 시각 이전에 들어온 배치는 기존 기록 상태를 그대로 둔다."""
import os
import sqlite3


def since() -> str:
    """Activation time in the board's own UTC text format. Unset means nothing is recorded automatically."""
    return os.environ.get('WEBLEDGER_AUTO_RECORD_SINCE', '')


def batch_is_new(conn, batch_id: str) -> bool:
    start = since()
    if not start:
        return False
    try:
        row = conn.execute('SELECT received_at FROM import_batches WHERE batch_id=?', (batch_id,)).fetchone()
    except sqlite3.OperationalError:
        return False
    return bool(row and row[0] and str(row[0]) >= start)
