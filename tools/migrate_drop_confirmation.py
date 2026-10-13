"""카드 거래의 확정 표식을 제거한다.

classification_state 'confirmed'를 'classified'로 바꾸고 transactions.user_confirmed 열을 삭제한다.
장부 기록(ledger_entries)과 카드 원본 열은 바꾸지 않는다. 한 트랜잭션으로 처리하며 두 번 실행해도 안전하다.
사용: python tools/migrate_drop_confirmation.py <board.sqlite> [--check]
"""
import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import Store, decided_sql  # noqa: E402


def migrate(path: str, check_only: bool = False) -> dict:
    with closing(sqlite3.connect(path, isolation_level=None, timeout=30)) as conn:
        columns = [r[1] for r in conn.execute('PRAGMA table_info(transactions)')]
        if 'user_confirmed' not in columns:
            return {'status': 'ALREADY_DONE', 'schema_differences': Store.schema_differences(conn)}
        booked = conn.execute('SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM ledger_entries').fetchone()
        relabel = conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_state='confirmed'").fetchone()[0]
        # 열을 지우면 보호 근거가 사라지므로, 모든 확정 행이 새 기준(사용자 결정·장부 기록)으로 보호되는지 먼저 확인한다.
        unprotected = conn.execute(
            f'SELECT COUNT(*) FROM transactions WHERE user_confirmed=1 AND NOT {decided_sql()}').fetchone()[0]
        report = {'status': 'CHECKED', 'relabel': relabel, 'unprotected': unprotected,
                  'ledger_entries': booked[0], 'ledger_total_krw': booked[1]}
        if check_only or unprotected:
            report['status'] = 'CHECKED' if check_only else 'REFUSED_UNPROTECTED_ROWS'
            return report
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute("UPDATE transactions SET classification_state='classified' WHERE classification_state='confirmed'")
            conn.execute('ALTER TABLE transactions DROP COLUMN user_confirmed')
            after = conn.execute('SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM ledger_entries').fetchone()
            if after != booked:
                raise RuntimeError('LEDGER_CHANGED')
            conn.execute('COMMIT')
        except BaseException:
            conn.execute('ROLLBACK')
            raise
        report['status'] = 'MIGRATED'
        report['schema_differences'] = Store.schema_differences(conn)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = migrate(args.database, check_only=args.check)
    print(result)
    sys.exit(0 if result['status'] in ('MIGRATED', 'ALREADY_DONE', 'CHECKED') else 1)
