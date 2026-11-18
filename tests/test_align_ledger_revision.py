"""`ledger.revision` 정합 도구 — 합성 DB로만 검증한다.

운영·호스트 경로를 읽지 않는다. 검사는 (a) 661건과 같은 한 방향 차이를 재현해 정렬하면
0이 되는지, (b) 두 번 돌리면 두 번째가 0건인지(멱등), (c) `board_rows`가 한 바이트도
바뀌지 않는지, (d) 한쪽에만 있는 거래를 건드리지 않는지를 고정한다. 추가로 검사 모드가
읽기 전용이라 파일을 바꾸지 않는다는 것과, 호스트 DB 경로를 거부한다는 것을 확인한다.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app import db
from tools import align_ledger_revision as align

BOARD_SCHEMA = """
CREATE TABLE board_rows (
    row_id TEXT PRIMARY KEY,
    row_kind TEXT NOT NULL,
    display_tab_id TEXT,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def build(path: Path, *, lagging: int = 661, forward_inverse: int = 1,
          ledger_only: list[str] = ('card-orphan-ledger-1', 'card-orphan-ledger-2',
                                    'card-orphan-ledger-3', 'card-orphan-ledger-4'),
          board_only: list[str] = ('card-orphan-board-1', 'card-orphan-board-2',
                                   'card-orphan-board-3', 'card-orphan-board-4')) -> Path:
    """A board file where `lagging` card rows have a ledger revision one behind the column.

    Amounts are identical on both sides (the finding was that money never drifted), and
    the column is the value a save compares, so the column is the truth to copy from.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.executescript(BOARD_SCHEMA)      # executescript commits, so DDL first
        conn.executescript(db.LEDGER_SCHEMA_SQL)   # the real 42-column contract
        conn.execute('BEGIN')                 # then one transaction for the rows

        board_rows, ledger_rows = [], []
        total = lagging + forward_inverse
        for index in range(total):
            row_id = f'card-trade-{index:04d}'
            column_revision = (index % 7) + 3      # starts above 1, like a saved row
            payload = {
                'row_id': row_id, 'row_kind': 'expense',
                'display_tab_id': 'trip-A', 'amount_krw': 10_000 + index,
                'item': '숙박비', 'description': '합성',
                # The automatic path lags the payload; inverse rows have a forward payload
                # to prove the tool still copies the column rather than trusting payloads.
                'revision': column_revision - 1 if index < lagging else column_revision + 1,
            }
            board_rows.append((row_id, 'expense', 'trip-A', column_revision,
                               json.dumps(payload, ensure_ascii=False, sort_keys=True)))
            ledger_revision = (column_revision - 1 if index < lagging
                               else column_revision + 1)
            ledger_rows.append((row_id, f'trade-{index:04d}', 'expense', '숙박비', '합성',
                            10_000 + index, '2026-05-01', 'trip-A', 'trip-A',
                            ledger_revision, '2026-10-07T14:48:18+00:00'))
        for row_id in board_only:
            board_rows.append((row_id, 'expense', 'trip-A', 5,
                               json.dumps({'row_id': row_id, 'row_kind': 'expense',
                                           'display_tab_id': 'trip-A', 'amount_krw': 0,
                                           'revision': 4}, sort_keys=True)))
        for row_id in ledger_only:
            ledger_rows.append((row_id, row_id[len('card-'):], 'expense', '수기', '합성',
                                0, '2026-05-01', 'trip-A', 'trip-A', 9,
                                '2026-10-07T14:48:18+00:00'))

        conn.executemany(
            'INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)'
            ' VALUES (?,?,?,?,?)', board_rows)
        conn.executemany(
            'INSERT INTO ledger(entry_id,transaction_id,entry_kind,item,description,'
            'amount_krw,occurred_on,display_tab_id,trip_id,revision,created_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?)', ledger_rows)
        conn.execute('COMMIT')
    finally:
        conn.close()
    return path


def digest(path: Path, table: str) -> str:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest()


def read(path: Path, sql: str, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_reproduces_the_one_direction_lag_then_converges_to_zero(tmp_path):
    """661건과 같은 '+1' 한 방향 차이를 재현하고, 적용하면 0건이 된다."""
    db = build(tmp_path / 'board.sqlite')
    preview = align.differences(align.connect(db, readonly=True))
    assert preview['board_rows'] == 661 + 1 + 4
    assert preview['ledger'] == 661 + 1 + 4
    assert preview['differing'] == 662
    assert preview['difference_delta'] == {'1': 661, '-1': 1}

    result = align.apply(align.connect(db, readonly=False))
    assert result['updated'] == 662
    assert result['remaining_differing'] == 0
    assert align.differences(align.connect(db, readonly=True))['differing'] == 0


def test_column_wins_even_when_the_payload_was_ahead(tmp_path):
    """payload가 앞선 행도 열 값으로 맞춘다. 열이 낙관적 잠금의 기준이기 때문."""
    db = build(tmp_path / 'board.sqlite', lagging=0, forward_inverse=3,
               ledger_only=[], board_only=[])
    align.apply(align.connect(db, readonly=False))
    # index 1 → 열 revision = (1 % 7) + 3 = 4. payload는 열보다 앞선 5였다.
    row = read(db, "SELECT l.revision, b.revision FROM ledger l JOIN board_rows b"
                    " ON b.row_id=l.entry_id WHERE l.entry_id='card-trade-0001'")
    assert row == [(4, 4)]
    payload = json.loads(read(db, "SELECT payload_json FROM board_rows"
                                 " WHERE row_id='card-trade-0001'")[0][0])
    assert payload['revision'] == 5   # payload는 건드리지 않는다


def test_second_run_updates_nothing(tmp_path):
    """멱등: 두 번째 적용은 0건을 쓴다."""
    db = build(tmp_path / 'board.sqlite')
    first = align.apply(align.connect(db, readonly=False))
    second = align.apply(align.connect(db, readonly=False))
    assert first['updated'] == 662
    assert second['updated'] == 0
    assert second['remaining_differing'] == 0


def test_board_rows_is_never_written(tmp_path):
    """`board_rows` 테이블은 적용 전후 완전히 같다(열·payload 모두)."""
    db = build(tmp_path / 'board.sqlite')
    before = digest(db, 'board_rows')
    align.apply(align.connect(db, readonly=False))
    assert digest(db, 'board_rows') == before


def test_rows_on_only_one_side_are_counted_but_not_written(tmp_path):
    """`ledger`에만 있는 4건·`board_rows`에만 있는 4건은 건드리지 않는다."""
    db = build(tmp_path / 'board.sqlite')
    before_ledger_only = read(
        db, "SELECT entry_id, revision FROM ledger WHERE entry_id LIKE 'card-orphan-ledger-%'"
            " ORDER BY entry_id")
    result = align.apply(align.connect(db, readonly=False))
    assert result['ledger_without_board_match'] == 4
    assert result['board_rows_without_ledger'] == 4
    after_ledger_only = read(
        db, "SELECT entry_id, revision FROM ledger WHERE entry_id LIKE 'card-orphan-ledger-%'"
            " ORDER BY entry_id")
    assert after_ledger_only == before_ledger_only
    assert read(db, "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'card-orphan-board-%'"
                    " AND revision != 5") == [(0,)]


def test_inspect_mode_is_read_only_and_leaves_the_file_untouched(tmp_path):
    """검사 모드는 `mode=ro`로 열어 쓰기가 불가능하다. 파일 해시도 그대로다."""
    db = build(tmp_path / 'board.sqlite')
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    result = align.differences(align.connect(db, readonly=True))
    assert result['differing'] == 662
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before

    conn = align.connect(db, readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('UPDATE ledger SET revision=1')
    finally:
        conn.close()


def test_cli_preview_writes_nothing_and_apply_reports_applied(tmp_path, capsys):
    """CLI 기본값은 검사다. `--apply`를 줘야 쓰고, 그때 상태가 APPLIED로 나온다."""
    db = build(tmp_path / 'board.sqlite')
    before = digest(db, 'ledger')
    assert align.main(['--db', str(db)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['status'] == 'PREVIEW'
    assert preview['rows_to_update'] == 662
    assert digest(db, 'ledger') == before

    assert align.main(['--db', str(db), '--apply']) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied['status'] == 'APPLIED'
    assert applied['updated'] == 662


def test_live_host_database_is_refused(tmp_path, monkeypatch):
    """호스트 데이터 폴더 안 경로는 쓰지 않는다. 감독이 사본만 넘기게 하기 위함."""
    monkeypatch.setattr(align, 'LIVE_HOST', tmp_path)
    live = tmp_path / 'data'
    live.mkdir()
    db = build(live / 'board.sqlite')
    assert align.main(['--db', str(db)]) == 3
    assert align.main(['--db', str(db), '--apply']) == 3


def test_missing_tables_are_a_named_error(tmp_path, capsys):
    """표가 없을 때 조용히 0건을 보고하지 않는다."""
    db = tmp_path / 'empty.sqlite'
    sqlite3.connect(db).close()
    assert align.main(['--db', str(db)]) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'LEDGER_TABLE_MISSING'
