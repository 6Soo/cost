"""Report or align `ledger.revision` with the `board_rows` column that really is the source.

`board_rows.revision` is the value the board uses for optimistic locking: every save
compares `expected_revision` against that column, and a person's save writes the same
number into the payload and the column. The automatic paths build the payload first and
then bump only the column (`payload['revision'] = old_revision + 1` happens on the
correction branch alone), so the revision embedded in `payload_json` can lag the column
by exactly one. `tools/migrate_to_ledger.py` copies the payload value into `ledger`
(`payload.setdefault('revision', revision)`), so `ledger.revision` inherits that lag.

Nothing reads `ledger.revision` to decide anything today. This tool therefore treats the
`board_rows` column as the source and copies it into `ledger`, which is the only table it
writes. `board_rows` is read, never updated.

    python -I tools/align_ledger_revision.py --db <copy of board.sqlite>          # inspect
    python -I tools/align_ledger_revision.py --db <copy of board.sqlite> --apply  # write

Inspect mode opens the file read-only and prints counts only: how many rows differ, in
which direction, and how many rows exist on only one side. `--apply` opens one
`BEGIN IMMEDIATE`, re-reads the same differences inside it, updates only the rows whose
`ledger.revision` differs from the `board_rows` column, confirms zero remain, and commits
once. A second run therefore finds zero rows (idempotent). Rows that exist on only one
side are counted but never written.

This tool refuses the live host database. It is for a copy, and production application
goes through the backup/inspect/apply/verify procedure in docs/operations.md.
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

LIVE_HOST = Path('D:/WebLedgerHost')
CARD_PREFIX = 'card-'


def _refuse_live(path: Path) -> None:
    """A path under the live host data directory is refused, matching how the copy is made."""
    resolved = path.resolve()
    live_data = (LIVE_HOST / 'data').resolve()
    if resolved.is_relative_to(live_data):
        raise ValueError('LIVE_DB_REFUSED')


def _card_transaction_id(row_id: str) -> str | None:
    """`card-<transaction_id>` → transaction_id. Anything else has no trade to match."""
    if not row_id.startswith(CARD_PREFIX):
        return None
    return row_id[len(CARD_PREFIX):]


def differences(conn: sqlite3.Connection) -> dict:
    """Rows whose `ledger.revision` disagrees with the `board_rows` column, plus orphans.

    The contract says a ledger `entry_id` is a `board_rows` `row_id` unchanged, and a card
    entry's `transaction_id` is the id after `card-`. Matching by entry_id is the primary
    rule; a ledger row whose entry_id copy is not the board id but whose trade matches a
    single board card row is aligned through that trade instead of being left out.
    """
    has_ledger = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'").fetchone())
    has_board = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_rows'").fetchone())
    if not has_ledger:
        raise ValueError('LEDGER_TABLE_MISSING')
    if not has_board:
        raise ValueError('BOARD_ROWS_TABLE_MISSING')

    board = {row_id: revision for row_id, revision
             in conn.execute('SELECT row_id, revision FROM board_rows')}
    by_trade = {}
    for row_id, revision in board.items():
        trade = _card_transaction_id(row_id)
        if trade is not None:
            by_trade.setdefault(trade, []).append(revision)

    ledger = [(entry_id, transaction_id, revision) for entry_id, transaction_id, revision
              in conn.execute('SELECT entry_id, transaction_id, revision FROM ledger')]

    rows_to_update = []       # (entry_id, current ledger revision, board column)
    unreachable = []          # card trade with no matching board row on either side
    unidentifiable = []       # no entry-id match and no card identity (manual rows)
    for entry_id, transaction_id, revision in ledger:
        if entry_id in board:
            expected = board[entry_id]
        elif transaction_id is not None and len(by_trade.get(transaction_id, ())) == 1:
            expected = by_trade[transaction_id][0]
        elif transaction_id is not None:
            unreachable.append(entry_id)
            continue
        else:
            unidentifiable.append(entry_id)
            continue
        if revision != expected:
            rows_to_update.append((entry_id, revision, expected))

    delta = {}
    for _entry_id, had, want in rows_to_update:
        delta[want - had] = delta.get(want - had, 0) + 1

    board_ids = set(board)
    ledger_ids = {entry_id for entry_id, _transaction_id, _revision in ledger}
    board_without_ledger = sorted(board_ids - ledger_ids)

    return {
        'board_rows': len(board),
        'ledger': len(ledger),
        'matched_by_entry_id': len(board_ids & ledger_ids),
        'differing': len(rows_to_update),
        'difference_delta': {str(k): v for k, v in sorted(delta.items())},
        'ledger_without_board_match': len(unreachable),
        'ledger_without_card_identity': len(unidentifiable),
        'board_rows_without_ledger': len(board_without_ledger),
        'rows_to_update': rows_to_update,
        'board_rows_without_ledger_sample': board_without_ledger[:5],
        'ledger_without_board_match_sample': unreachable[:5],
    }


def apply(conn: sqlite3.Connection) -> dict:
    """Copy the `board_rows` revision into every differing `ledger` row, in one transaction.

    The UPDATE targets the entry ids found inside this transaction, so a file changed
    between inspect and apply cannot get an unrelated revision. After the writes, the
    same difference query runs again; only zero remaining allows a commit.
    """
    conn.execute('BEGIN IMMEDIATE')
    try:
        found = differences(conn)
        for entry_id, _had, want in found['rows_to_update']:
            conn.execute('UPDATE ledger SET revision=? WHERE entry_id=?', (want, entry_id))
        remaining = differences(conn)
        if remaining['differing']:
            raise ValueError('ALIGN_DID_NOT_CONVERGE')
        conn.execute('COMMIT')
    except BaseException:
        conn.execute('ROLLBACK')
        raise

    result = {k: v for k, v in found.items() if k != 'rows_to_update'}
    result.update(updated=len(found['rows_to_update']),
                  remaining_differing=remaining['differing'],
                  ledger_after=remaining['ledger'])
    return result


def connect(path: Path, *, readonly: bool) -> sqlite3.Connection:
    """Read-only inspect and a write-capable apply; neither takes schema or migration action."""
    target = path.resolve()
    if readonly:
        conn = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=5)
        conn.execute('PRAGMA query_only=ON')
    else:
        conn = sqlite3.connect(str(target), isolation_level=None, timeout=30)
    return conn


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--db', type=Path, required=True, help='board.sqlite copy')
    parser.add_argument('--apply', action='store_true', help='write; default is inspect only')
    parser.add_argument('--report', type=Path, help='write the result JSON here')
    args = parser.parse_args(argv)

    path = args.db
    if not path.is_file():
        print(json.dumps({'status': 'ERROR', 'reason': f'DB 없음: {path}'}, ensure_ascii=False))
        return 2

    try:
        _refuse_live(path)
        conn = connect(path, readonly=not args.apply)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'status': 'REFUSED', 'reason': str(exc)}, ensure_ascii=False))
        return 3

    try:
        if args.apply:
            result = dict(status='APPLIED', **apply(conn))
        else:
            before = differences(conn)
            result = dict(status='PREVIEW',
                          **{k: v for k, v in before.items() if k != 'rows_to_update'},
                          rows_to_update=len(before['rows_to_update']))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.report:
            args.report.write_text(
                json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True),
                encoding='utf-8')
        return 0
    except (sqlite3.Error, ValueError) as exc:
        print(json.dumps({'status': 'ERROR', 'reason': str(exc)}, ensure_ascii=False))
        return 2
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
