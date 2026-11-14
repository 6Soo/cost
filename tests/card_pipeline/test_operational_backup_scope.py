import hashlib
import json
import sqlite3

import pytest

from tools import verify_operational_backup_restore as backup


def _db(path, rows=3):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE board_rows(id INTEGER PRIMARY KEY, v TEXT)')
    conn.execute('CREATE TABLE board_requests(id INTEGER PRIMARY KEY, v TEXT)')
    conn.executemany('INSERT INTO board_rows(v) VALUES (?)', [('r%d' % i,) for i in range(rows)])
    conn.commit()
    conn.close()


def _host(tmp_path):
    host = tmp_path / 'host'
    data = host / 'data'
    for name in ('config', 'review', 'source', 'evidence', 'exports', 'receipts', 'google-authority'):
        (host / name if name == 'config' else data / name).mkdir(parents=True)
    _db(data / 'board.sqlite')
    _db(data / 'ota-evidence.sqlite', 5)
    _db(data / 'core.sqlite', 2)
    (data / 'source' / 'a.txt').write_text('a')
    (data / 'ota-sources.json').write_text(json.dumps({'unified_database': str(data / 'ota-evidence.sqlite')}))
    files = {}
    for kind, text in (('snapshot', 'snap'), ('review', 'rev'), ('master', 'mas')):
        path = data / 'review' / (kind + '.txt')
        path.write_text(text, encoding='utf-8')
        files[kind + '_path'] = str(path)
        files[kind + '_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    files['decisions_db_path'] = str(data / 'board.sqlite')
    (host / 'config' / 'real-review.json').write_text(json.dumps(files), encoding='utf-8')
    return host, data


@pytest.fixture
def host(tmp_path, monkeypatch):
    host, data = _host(tmp_path)
    from app import ota_store
    monkeypatch.setattr(ota_store, 'is_store', lambda path: True)
    monkeypatch.setattr('app.ota_sources.read_manifest',
                        lambda path, required=False: json.loads(path.read_text()))
    return host, data


def _run(host, tmp_path, scope=None):
    out = tmp_path / 'evidence.json'
    backup.main(out, scope, host)
    return json.loads(out.read_text())


def test_default_scope_covers_all_databases_and_folders(host, tmp_path):
    result = _run(host[0], tmp_path)
    assert result['database_count'] == 2
    assert result['all_database_tables_and_columns_compared'] is True
    assert 'backup_scope' not in result
    assert result['file_count'] >= 4


def test_scope_serializes_only_in_scope_databases(host, tmp_path, monkeypatch):
    seen = []
    real = backup.database_state
    monkeypatch.setattr(backup, 'database_state', lambda path: seen.append(path.name) or real(path))
    result = _run(host[0], tmp_path, ['board'])
    assert set(seen) == {'board.sqlite'}
    assert result['backup_scope'] == ['board.sqlite']
    assert result['out_of_scope_databases'] == ['ota-evidence.sqlite']
    assert result['out_of_scope_unchanged'] is True
    assert result['all_database_tables_and_columns_compared'] is True
    assert result['board_rows'] == 3
    assert not list((host[1] / 'backups').rglob('ota-evidence.sqlite'))


def test_scope_can_include_core_sqlite(host, tmp_path):
    result = _run(host[0], tmp_path, ['board.sqlite', 'core.sqlite'])
    assert result['backup_scope'] == ['board.sqlite', 'core.sqlite']
    assert result['database_count'] == 2


def test_scope_unknown_database_or_missing_decisions_db_fails(host, tmp_path):
    with pytest.raises(RuntimeError, match='BACKUP_SCOPE_UNKNOWN_DATABASE'):
        _run(host[0], tmp_path, ['nope.sqlite'])
    with pytest.raises(RuntimeError, match='BACKUP_SCOPE_MISSING_DECISIONS_DB'):
        _run(host[0], tmp_path, ['core.sqlite'])


def test_out_of_scope_database_change_fails(host, tmp_path, monkeypatch):
    data = host[1]
    real = backup.backup_database

    def touch_then_backup(source, target):
        real(source, target)
        conn = sqlite3.connect(data / 'ota-evidence.sqlite')
        conn.execute("INSERT INTO board_rows(v) VALUES ('late')")
        conn.commit()
        conn.close()
    monkeypatch.setattr(backup, 'backup_database', touch_then_backup)
    with pytest.raises(RuntimeError, match='OUT_OF_SCOPE_INPUT_CHANGED_DURING_BACKUP'):
        _run(host[0], tmp_path, ['board'])


def test_out_of_scope_folder_change_fails(host, tmp_path, monkeypatch):
    data = host[1]
    real = backup.backup_database

    def touch_then_backup(source, target):
        real(source, target)
        (data / 'source' / 'new.txt').write_text('x')
    monkeypatch.setattr(backup, 'backup_database', touch_then_backup)
    with pytest.raises(RuntimeError, match='OUT_OF_SCOPE_INPUT_CHANGED_DURING_BACKUP'):
        _run(host[0], tmp_path, ['board'])


def test_fingerprint_detects_wal_only_write(tmp_path):
    path = tmp_path / 'w.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE t(v)')
    conn.commit()
    before = backup.database_fingerprint(path)
    conn.execute('INSERT INTO t VALUES (1)')
    conn.commit()
    assert backup.database_fingerprint(path) != before
    conn.close()
