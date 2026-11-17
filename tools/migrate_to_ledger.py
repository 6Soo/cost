# -*- coding: utf-8 -*-
"""M6 ���별 이관: `board_rows` + `ledger_entries` → `ledger`.

기본은 dry-run이다. `--apply`를 줘야 쓴다. 운영 DB에 직접 쓰지 않는다:
사본에 먼저 예행하고, 대조가 통과한 사본만 별도 절차로 적용한다.

이관은 테이블 변환이 아니라 **기존 행을 새 장부에 그대로 옮겨 적는 것**이다.
금액·부호·ID·원문 해시는 바꾸지 않는다. `entry_id`는 기존 `row_id`를 그대로
쓰므로 새 ID를 만들지 않는다.

    python -I tools/migrate_to_ledger.py --db <사본 경로>            # 예행
    python -I tools/migrate_to_ledger.py --db <사본 경로> --apply     # 적용

두 번 돌려도 두 번째는 아무것도 넣지 않는다(멱등).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import LEDGER_SCHEMA_SQL, _execute_statements  # noqa: E402

# `ledger` 테이블 컬럼 가운데 payload/다른 테이블에서 채우는 것들.
PAYLOAD_COLUMNS = (
    'entry_kind', 'item', 'description', 'amount_krw', 'occurred_on',
    'display_tab_id', 'service_period', 'reservation_no', 'evidence_type',
    'source_kind', 'source_event_id', 'source_fact_digest', 'source_merchant',
    'source_issuer', 'source_card_last4', 'source_approval_number',
    'source_approval_date', 'source_posting_date', 'source_local_amount',
    'source_currency', 'event_kind', 'classification_state', 'confirmed_by',
    'memo', 'operator_note', 'revision',
)
# `ledger_entries`에서만 오는 것들. 카드 거래의 기장 사실이다.
ENTRY_COLUMNS = ('committed_at', 'batch_id')


def _card_transaction_id(row_id: str) -> str | None:
    """카드 행의 `card-<transaction_id>`에서 거래 ID를 꺼낸다."""
    return row_id[len('card-'):] if row_id.startswith('card-') else None


def _payload_values(row_id: str, kind: str, payload: dict) -> dict:
    """payload 하나를 ledger 컬럼 값으로 편다. 없는 키는 기본값으로 둔다."""
    values = {name: payload.get(name) for name in PAYLOAD_COLUMNS}
    values['entry_id'] = row_id                      # 계약 규칙 1
    values['transaction_id'] = _card_transaction_id(row_id)
    values['entry_kind'] = payload.get('row_kind') or payload.get('entry_kind') or kind or 'expense'
    values['display_tab_id'] = payload.get('display_tab_id')
    # NOT NULL 컬럼은 None 이 아니라 빈 문자열로 채운다.
    for name in PAYLOAD_COLUMNS:
        if name in ('amount_krw', 'revision', 'display_tab_id'):
            continue
        if values[name] is None:
            values[name] = ''
    if values['revision'] is None:
        values['revision'] = 1
    return values


def read_existing(conn: sqlite3.Connection) -> tuple[list[dict], dict]:
    """board_rows + ledger_entries 를 ledger 행 모양으로 만든다."""
    has_ledger_entries = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_entries'").fetchone())
    entries = {}
    if has_ledger_entries:
        for r in conn.execute(
                'SELECT transaction_id, batch_id, committed_at FROM ledger_entries'):
            entries[r[0]] = {'batch_id': r[1] or '', 'committed_at': r[2]}

    rows = []
    seen = set()
    for row_id, kind, display_tab_id, revision, payload_json in conn.execute(
            'SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows'):
        payload = json.loads(payload_json or '{}')
        payload.setdefault('display_tab_id', display_tab_id)
        payload.setdefault('revision', revision)
        values = _payload_values(row_id, kind, payload)
        txid = values['transaction_id']
        entry = entries.get(txid) if txid else None
        if entry:
            values['batch_id'] = entry['batch_id']
            values['committed_at'] = entry['committed_at']
        if values['entry_id'] in seen:
            raise SystemExit('MIGRATION_DUPLICATE_ENTRY_ID: ' + values['entry_id'])
        seen.add(values['entry_id'])
        rows.append(values)
    return rows, {'ledger_entries_rows': len(entries)}


def totals(conn: sqlite3.Connection, table: str) -> dict:
    """탭별 지출 합계와 전체 건수. 이관 전후 대조에 쓴다.

    `board_rows`는 금액이 `payload_json` 안에 있고 `ledger`는 실제 컬럼이다.
    같은 값을 같은 모양으로 비교하려고 여기서 양쪽을 dict로 만든다.
    """
    out = {}
    if table == 'board_rows':
        for row_id, kind, tab, payload_json in conn.execute(
                'SELECT row_id, row_kind, display_tab_id, payload_json FROM board_rows'):
            payload = json.loads(payload_json or '{}')
            tab = tab if tab is not None else payload.get('display_tab_id')
            key = (tab, kind)
            bucket = out.setdefault(key, {'count': 0, 'amount': 0})
            bucket['count'] += 1
            bucket['amount'] += int(payload.get('amount_krw') or 0)
        return out
    for tab, kind, count, amount in conn.execute(
            'SELECT display_tab_id, entry_kind, COUNT(*), COALESCE(SUM(amount_krw), 0)'
            ' FROM ledger GROUP BY display_tab_id, entry_kind'):
        out[(tab, kind)] = {'count': count, 'amount': amount}
    return out


def summarize(conn: sqlite3.Connection) -> dict:
    has_board = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_rows'").fetchone())
    has_ledger = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'").fetchone())
    return {
        'board_rows': totals(conn, 'board_rows') if has_board else {},
        'ledger': totals(conn, 'ledger') if has_ledger else {},
    }


def compare(before: dict, after: dict) -> list[str]:
    """이관 전 board_rows 합계가 이관 후 ledger 합계와 같은지 확인한다."""
    problems = []
    src = before['board_rows']
    dst = after['ledger']
    for key, want in src.items():
        got = dst.get(key)
        if got is None:
            problems.append(f'MISSING_TAB {key}')
        elif got['count'] != want['count'] or got['amount'] != want['amount']:
            problems.append(
                f'AMOUNT_OR_COUNT_CHANGED {key}: was {want} now {got}')
    extra = set(dst) - set(src)
    for key in sorted(extra, key=str):
        problems.append(f'UNEXPECTED_TAB {key}')
    return problems


def migrate(conn: sqlite3.Connection, *, apply: bool) -> dict:
    """새 장부 스키마를 만들고 기존 행을 옮긴다. 멱등이다."""
    before = summarize(conn)
    rows, meta = read_existing(conn)
    _execute_statements(conn, LEDGER_SCHEMA_SQL)

    columns = ('entry_id', 'transaction_id') + PAYLOAD_COLUMNS + ENTRY_COLUMNS + ('created_at',)
    inserted = 0
    skipped = 0
    create_columns = set(ENTRY_COLUMNS) | {'created_at'}
    for values in rows:
        if conn.execute('SELECT 1 FROM ledger WHERE entry_id=?', (values['entry_id'],)).fetchone():
            skipped += 1
            continue
        # 기장되지 않은 행은 이관 시각을 쓴다. 원본 값은 바꾸지 않는다.
        values.setdefault('committed_at', '')
        values.setdefault('created_at', values['committed_at'] or '')
        for name in create_columns:
            values.setdefault(name, '')
        if values['created_at'] == '':
            # 기장되지 않은 행은 이관 시각을 쓴다. 원본 값은 바꾸지 않는다.
            values['created_at'] = values.get('committed_at') or ''
        statement = (f'INSERT INTO ledger({",".join(columns)}) '
                     f'VALUES ({",".join("?" * len(columns))})')
        conn.execute(statement, [values.get(c) for c in columns])
        inserted += 1

    after = summarize(conn)
    problems = compare(before, after)
    result = dict(
        status='APPLIED' if apply else 'PREVIEW',
        migrated_rows=len(rows),
        inserted=inserted,
        skipped_existing=skipped,
        ledger_entries_source_rows=meta['ledger_entries_rows'],
        ledger_total_rows=conn.execute('SELECT COUNT(*) FROM ledger').fetchone()[0],
        problems=problems,
    )
    if not apply:
        conn.rollback()
    else:
        conn.commit()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True, help='대상 SQLite 파일(사본)')
    parser.add_argument('--apply', action='store_true', help='실제로 쓴다(기본은 예행)')
    parser.add_argument('--report', type=Path, help='결과 JSON을 남길 경로')
    args = parser.parse_args(argv)

    path = args.db.resolve()
    if not path.is_file():
        print(json.dumps({'status': 'ERROR', 'reason': f'DB 없음: {path}'}, ensure_ascii=False))
        return 2

    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute('BEGIN IMMEDIATE')
        result = migrate(conn, apply=args.apply)
    except SystemExit as exc:
        conn.rollback()
        print(json.dumps({'status': 'ERROR', 'reason': str(exc)}, ensure_ascii=False))
        return 1
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.report:
        args.report.write_text(text, encoding='utf-8')
    print(text)
    return 0 if not result['problems'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
