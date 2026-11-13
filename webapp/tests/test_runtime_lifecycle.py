"""Startup failures must release synthetic sockets, SQLite handles and workers."""

import os
import sqlite3
from unittest.mock import Mock

import pytest

import run_candidate
from webapp import ledger_board, ota_payment_review


@pytest.mark.parametrize('stage,error', [
    ('access', run_candidate.ops.OpsError('ACCESS', 'synthetic refusal')),
    ('oidc', run_candidate.ops.OpsError('OIDC', 'synthetic refusal')),
    ('oidc', RuntimeError('SYNTHETIC-PRIVATE-TOKEN')),
])
def test_failed_start_releases_resources_and_hides_unexpected_errors(tmp_path, monkeypatch, capsys, stage, error):
    created = []
    serve = ledger_board.serve
    previous = ledger_board._STORE
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '0')
    monkeypatch.setattr(run_candidate, 'gate_on_readiness', lambda *args, **kwargs: 'synthetic')

    def synthetic_server(**kwargs):
        server = serve(**dict(kwargs, with_worker=False))
        server.card_worker = Mock()
        created.append(server)
        return server

    monkeypatch.setattr(ledger_board, 'serve', synthetic_server)
    monkeypatch.setattr(run_candidate, 'bind_runtime_access' if stage == 'access' else 'connect_runtime_oidc',
                        Mock(side_effect=error))
    stop_snapshot = Mock()
    monkeypatch.setattr(ota_payment_review, 'shutdown_snapshot_service', stop_snapshot)
    try:
        assert run_candidate.main(['--environment', 'local-synthetic', '--data-root', str(tmp_path),
                                   '--port', '0', '--no-worker']) == 2
        server, = created
        assert server.socket.fileno() == -1
        server.card_worker.stop.assert_called_once_with(timeout=5)
        stop_snapshot.assert_called_once_with(server.card_store)
        with pytest.raises(sqlite3.ProgrammingError):
            server.card_store.conn.execute('SELECT 1')
        assert ledger_board._STORE is None
        assert ledger_board._ACCESS is None
        assert ledger_board._OIDC is None
        output = capsys.readouterr()
        assert 'SYNTHETIC-PRIVATE-TOKEN' not in output.err
        assert 'Traceback' not in output.err
    finally:
        for server in created:
            server.server_close()
            server.card_store.close()
        ledger_board.bind_oidc(None)
        ledger_board.bind_access(None)
        ledger_board.bind_store(previous)


def test_cleanup_continues_after_worker_stop_fails(tmp_path, capsys):
    previous = ledger_board._STORE
    server = ledger_board.serve(port=0, db_path=tmp_path / 'synthetic.sqlite', with_worker=False, seed_demo=False)
    server.card_worker = Mock()
    server.card_worker.stop.side_effect = RuntimeError('SYNTHETIC-PRIVATE-TOKEN')
    try:
        run_candidate.close_runtime(server)
        assert server.socket.fileno() == -1
        with pytest.raises(sqlite3.ProgrammingError):
            server.card_store.conn.execute('SELECT 1')
        assert ledger_board._STORE is None
        assert 'RUNTIME_RESOURCE' in capsys.readouterr().err
    finally:
        server.server_close()
        server.card_store.close()
        ledger_board.bind_store(previous)


def test_bind_failure_closes_new_store_and_preserves_existing_binding(tmp_path, monkeypatch):
    import socket
    from webapp import ledger_store
    created = []
    previous = ledger_board._STORE
    store_type = ledger_store.LedgerStore

    def capture(*args, **kwargs):
        store = store_type(*args, **kwargs)
        created.append(store)
        return store

    monkeypatch.setattr(ledger_store, 'LedgerStore', capture)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        try:
            with pytest.raises(OSError):
                ledger_board.serve(port=occupied.getsockname()[1], db_path=tmp_path / 'synthetic.sqlite',
                                   with_worker=False, seed_demo=False)
            assert ledger_board._STORE is previous
            store, = created
            with pytest.raises(sqlite3.ProgrammingError):
                store.conn.execute('SELECT 1')
        finally:
            for store in created:
                store.close()
            ledger_board.bind_store(previous)


def test_worker_start_failure_closes_socket_and_store(tmp_path, monkeypatch):
    from webapp import card_import, ledger_store
    stores, servers = [], []
    store_type, server_type = ledger_store.LedgerStore, ledger_board.ThreadingHTTPServer
    previous = ledger_board._STORE
    worker = Mock()
    worker.start.side_effect = RuntimeError('synthetic start failure')

    def capture_store(*args, **kwargs):
        stores.append(store_type(*args, **kwargs))
        return stores[-1]

    def capture_server(*args, **kwargs):
        servers.append(server_type(*args, **kwargs))
        return servers[-1]

    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '0')
    monkeypatch.setattr(ledger_store, 'LedgerStore', capture_store)
    monkeypatch.setattr(ledger_board, 'ThreadingHTTPServer', capture_server)
    monkeypatch.setattr(card_import, 'CardWorker', lambda *args: worker)
    try:
        with pytest.raises(RuntimeError, match='synthetic start failure'):
            ledger_board.serve(port=0, db_path=tmp_path / 'synthetic.sqlite', seed_demo=False)
        worker.stop.assert_called_once_with(timeout=5)
        assert servers[0].socket.fileno() == -1
        with pytest.raises(sqlite3.ProgrammingError):
            stores[0].conn.execute('SELECT 1')
        assert ledger_board._STORE is previous
    finally:
        for server in servers:
            server.server_close()
        for store in stores:
            store.close()
        ledger_board.bind_store(previous)


def test_entry_reports_safe_server_start_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_candidate, 'gate_on_readiness', lambda *args, **kwargs: 'synthetic')
    monkeypatch.setattr(ledger_board, 'serve', Mock(side_effect=OSError('SYNTHETIC-PRIVATE-PATH')))
    assert run_candidate.main(['--environment', 'local-synthetic', '--data-root', str(tmp_path),
                               '--port', '0', '--no-worker']) == 2
    output = capsys.readouterr()
    assert 'SERVER_START' in output.err
    assert 'SYNTHETIC-PRIVATE-PATH' not in output.err
    assert 'Traceback' not in output.err


def test_runtime_close_waits_for_active_write_and_refuses_queued_work(tmp_path):
    import threading
    from types import SimpleNamespace
    path = tmp_path / 'synthetic.sqlite'
    previous = ledger_board._STORE
    server = ledger_board.serve(port=0, db_path=path, with_worker=False, seed_demo=False)
    entered, release, closing, closed = (threading.Event() for _ in range(4))
    errors = []
    # The request wrapper reads the handler's path/command to decide whether a
    # request may skip the store lock; a write request carries both.
    handler = SimpleNamespace(server=server, _send_json=Mock(),
                              path='/board', command='POST')

    def write(handler):
        try:
            conn = handler.server.card_store.conn
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                         ('synthetic-shutdown', 'card_expense', 'synthetic-trip', 1, '{}'))
            entered.set()
            assert release.wait(5)
            conn.commit()
        except Exception as error:
            errors.append(error)

    def close():
        closing.set()
        run_candidate.close_runtime(server)
        closed.set()

    writer = threading.Thread(target=lambda: ledger_board._store_request_locked(write)(handler))
    closer = threading.Thread(target=close)
    try:
        writer.start()
        assert entered.wait(5)
        closer.start()
        assert closing.wait(5)
        assert not closed.wait(0.1), 'the active transaction must finish before SQLite is closed'
        release.set()
        writer.join(5)
        closer.join(5)
        assert not errors and closed.is_set()
        conn = sqlite3.connect(path)
        try:
            assert conn.execute('SELECT row_id FROM board_rows').fetchall() == [('synthetic-shutdown',)]
        finally:
            conn.close()
        business = Mock()
        ledger_board._store_request_locked(business)(handler)
        business.assert_not_called()
        assert handler._send_json.call_args.kwargs['code'] == 503
    finally:
        release.set()
        writer.join(5)
        if closer.ident is not None:
            closer.join(5)
        server.server_close()
        server.card_store.close()
        ledger_board.bind_store(previous)


@pytest.mark.parametrize('name', ['WEBLEDGER_RECEIPTS_STORE', 'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT',
                                  'WEBLEDGER_GOOGLE_LEDGER_ROWS'])
@pytest.mark.parametrize('location,code', [('relative.json', 'RELATIVE_SETTING'),
                                         ('temporary', 'TEMP_DATA_ROOT'),
                                         ('checkout', 'CHECKOUT_DATA_ROOT')])
def test_production_refuses_non_durable_optional_data_paths(tmp_path, monkeypatch, name, location, code):
    from types import SimpleNamespace
    if location == 'temporary':
        location = str(tmp_path / 'private.json')
    elif location == 'checkout':
        location = str(run_candidate.HERE / 'private.json')
    monkeypatch.setenv(name, location)
    with pytest.raises(run_candidate.ops.OpsError) as error:
        run_candidate.validate_optional_data_paths(SimpleNamespace(environment='production'))
    assert error.value.code == code


def test_production_path_refusal_precedes_data_root_and_database_access(monkeypatch, capsys):
    # The production entry intentionally leaves require in force. Restore the
    # caller environment after this refusal test, including newly added keys.
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    monkeypatch.setenv('WEBLEDGER_RECEIPTS_STORE', 'relative-private.json')
    configure = Mock(side_effect=AssertionError('must not access the data root'))
    monkeypatch.setattr(run_candidate.ops, 'durable_config_for', configure)
    assert run_candidate.main(['--environment', 'production']) == 2
    configure.assert_not_called()
    assert 'RELATIVE_SETTING' in capsys.readouterr().err
    assert os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] == 'require'


@pytest.mark.parametrize('configured', [False, True])
def test_optional_features_remain_off_or_use_explicit_durable_paths(tmp_path, monkeypatch, configured):
    from types import SimpleNamespace
    names = ('WEBLEDGER_RECEIPTS_STORE', 'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', 'WEBLEDGER_GOOGLE_LEDGER_ROWS')
    for index, name in enumerate(names):
        monkeypatch.delenv(name, raising=False)
        if configured:
            monkeypatch.setenv(name, str(tmp_path / 'not-created' / f'private-{index}.json'))
    # Model a persistent mount without touching a real persistent or operational path.
    monkeypatch.setattr(run_candidate.ops.tempfile, 'gettempdir', lambda: str(tmp_path / 'different-temp-root'))
    run_candidate.validate_optional_data_paths(SimpleNamespace(environment='production'))
    assert not (tmp_path / 'not-created').exists()


def test_data_root_io_failure_returns_safe_startup_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_candidate.ops, 'durable_config_for',
                        Mock(side_effect=OSError('SYNTHETIC-PRIVATE-PATH disk full')))
    serve = Mock()
    monkeypatch.setattr(ledger_board, 'serve', serve)
    assert run_candidate.main(['--environment', 'local-synthetic', '--data-root', str(tmp_path)]) == 2
    serve.assert_not_called()
    output = capsys.readouterr()
    assert 'STARTUP_CONFIG' in output.err
    assert 'SYNTHETIC-PRIVATE-PATH' not in output.err
