from tools.verify_operational_backup_restore import product_files, digest_file, database_inputs


def test_passenger_confirmations_remain_in_backup_when_feature_is_disabled(tmp_path):
    passenger = tmp_path/'flight-passenger.sqlite'
    passenger.write_bytes(b'synthetic-passenger-store')
    databases, _ = database_inputs(tmp_path, {'decisions_db_path':str(tmp_path/'board.sqlite')}, {})
    assert databases['flight-passenger.sqlite'] == passenger


def test_wal_source_backup_is_self_contained_without_changing_source(tmp_path):
    import sqlite3
    from tools.verify_operational_backup_restore import backup_database, database_state
    source, target = tmp_path / 'live.sqlite', tmp_path / 'offline.sqlite'
    conn = sqlite3.connect(source)
    try:
        assert conn.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        conn.execute('CREATE TABLE original(id INTEGER PRIMARY KEY AUTOINCREMENT, value BLOB)')
        conn.execute('INSERT INTO original(value) VALUES (?)', (b'synthetic-original',))
        conn.commit()
        before = database_state(source)
        backup_database(source, target)
        assert database_state(target) == before
        assert database_state(source) == before
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert not any(tmp_path.glob('offline.sqlite-*'))
    finally:
        conn.close()


def test_unified_decisions_do_not_omit_operator_and_ota_databases(tmp_path):
    for name in ('board.sqlite', 'board.operator.sqlite', 'real-review.sqlite', 'ota.sqlite'):
        (tmp_path / name).write_bytes(b'synthetic')
    databases, decision_name = database_inputs(tmp_path, {'decisions_db_path': str(tmp_path / 'board.sqlite')},
                                             {'ota_review': {'review_db': str(tmp_path / 'ota.sqlite')}})
    assert set(databases) == {'board.sqlite', 'board.operator.sqlite', 'real-review.sqlite', 'ota-review.sqlite'}
    assert decision_name == 'board.sqlite'


def test_backup_covers_receipt_original_decisions_and_google_generation(tmp_path):
    paths = ['config/card-flow.json', 'data/receipts/receipts.json',
             'data/receipts/receipts.images/synthetic.bin',
             'data/google-authority/snapshot.json', 'data/google-authority/rows.generation.json']
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('synthetic:' + name).encode())
    secret = tmp_path / 'secrets/session-secret.txt'
    secret.parent.mkdir()
    secret.write_text('synthetic-secret')
    before = {name: digest_file(tmp_path / name) for name in paths}
    files = product_files(tmp_path)
    assert set(files) == {'host-config/card-flow.json', 'receipts/receipts.json',
                          'receipts/receipts.images/synthetic.bin',
                          'google-authority/snapshot.json', 'google-authority/rows.generation.json'}
    assert {name: digest_file(tmp_path / name) for name in paths} == before
    assert secret not in files.values()
