import os
from pathlib import Path
import sqlite3

import pytest

from tools import audit_google_expense_groups as tool


def test_local_audit_uses_readonly_query_connection_and_restores_environment(tmp_path, monkeypatch):
    db = tmp_path/'board.sqlite'
    conn=sqlite3.connect(db)
    conn.execute('CREATE TABLE marker(value TEXT)')
    conn.execute("INSERT INTO marker VALUES ('original')")
    conn.commit();conn.close()
    before=db.read_bytes()
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT','previous-snapshot')
    monkeypatch.delenv('WEBLEDGER_GOOGLE_LEDGER_ROWS',raising=False)
    def audit(store):
        assert store.conn.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            store.conn.execute('DELETE FROM marker')
        return {'available':True,'trips':[]}
    monkeypatch.setattr(tool,'audit_all_trips',audit)
    result=tool.audit(board_db=db,snapshot=tmp_path/'snapshot.json',rows=tmp_path/'rows.json')
    assert result['database_changes'] == 0 and db.read_bytes() == before
    assert os.environ['WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT'] == 'previous-snapshot'
    assert 'WEBLEDGER_GOOGLE_LEDGER_ROWS' not in os.environ
    assert not (tmp_path/'snapshot.json').exists() and not (tmp_path/'rows.json').exists()


def test_missing_board_does_not_create_a_new_database(tmp_path):
    missing=tmp_path/'missing.sqlite'
    with pytest.raises(sqlite3.OperationalError):
        tool.audit(board_db=missing,snapshot=tmp_path/'snapshot.json',rows=tmp_path/'rows.json')
    assert not missing.exists()
