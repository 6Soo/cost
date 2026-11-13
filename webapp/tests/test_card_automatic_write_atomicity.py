"""Automatic inference and every projection form one recoverable write."""
from unittest.mock import patch

import pytest

from webapp.tests.test_card_automatic_ux import flow


def snapshot(conn):
    tables = ('transactions', 'ledger_entries', 'board_rows', 'board_revisions',
              'change_log', 'requests')
    return {table: conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            for table in tables}


@pytest.mark.parametrize('fail_at', [1, 2])
@pytest.mark.parametrize('nested', [False, True])
def test_projection_failure_restores_classification_and_all_prior_writes(flow, fail_at, nested):
    f, batch, _ = flow
    conn = f.board.conn
    if nested:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("CREATE TABLE caller_write(value TEXT)")
        conn.execute("INSERT INTO caller_write VALUES ('keep')")
    before = snapshot(conn)
    project = f.project
    calls = []

    def fail(entry):
        calls.append(entry['transaction_id'])
        project(entry)  # Include a partially completed projection in the rollback.
        if len(calls) == fail_at:
            raise RuntimeError('synthetic projection failure')

    with patch.object(f, 'project', side_effect=fail):
        with pytest.raises(RuntimeError, match='synthetic projection failure'):
            f.auto_record(batch)
    assert len(calls) == fail_at
    assert snapshot(conn) == before
    assert conn.in_transaction is nested
    if nested:
        assert conn.execute('SELECT value FROM caller_write').fetchall() == [('keep',)]
        conn.commit()
    # No idempotency record or partial projection may obstruct retry.
    assert f.auto_record(batch)['auto_recorded'] == 2
    assert f.auto_record(batch)['auto_recorded'] == 0


def test_success_joins_the_callers_transaction_without_committing_it(flow):
    f, batch, _ = flow
    conn = f.board.conn
    before = snapshot(conn)
    conn.execute('BEGIN IMMEDIATE')
    assert f.auto_record(batch)['auto_recorded'] == 2
    assert conn.in_transaction
    conn.rollback()
    assert snapshot(conn) == before
