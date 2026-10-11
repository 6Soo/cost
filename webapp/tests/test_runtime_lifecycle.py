"""Startup failures must release synthetic sockets, SQLite handles and workers."""

import sqlite3
from unittest.mock import Mock

import pytest

import run_candidate
from webapp import ledger_board, ota_payment_review


@pytest.mark.parametrize('stage,error', [
    ('access', run_candidate.ops.OpsError('ACCESS', 'synthetic refusal')),
    ('oidc', run_candidate.ops.OpsError('OIDC', 'synthetic refusal')),
    ('oidc', RuntimeError('SYNTHETIC-PRIVATE-TOKEN')),
    ('reserve', RuntimeError('SYNTHETIC-PRIVATE-TOKEN')),
])
def test_failed_start_releases_resources_and_hides_unexpected_errors(tmp_path, monkeypatch, capsys, stage, error):
    created = []
    serve = ledger_board.serve
    previous = ledger_board._STORE
    monkeypatch.delenv('WEBLEDGER_RESERVE_TRIP_SYNC', raising=False)
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '0')
    monkeypatch.setattr(run_candidate, 'gate_on_readiness', lambda *args, **kwargs: 'synthetic')

    def synthetic_server(**kwargs):
        server = serve(**dict(kwargs, with_worker=False))
        server.card_worker = Mock()
        created.append(server)
        return server

    monkeypatch.setattr(ledger_board, 'serve', synthetic_server)
    if stage == 'reserve':
        from app import reserve_trips
        monkeypatch.setenv('WEBLEDGER_RESERVE_TRIP_SYNC', '1')
        monkeypatch.setenv('WEBLEDGER_TRIP_AUTHORITY', str(tmp_path / 'synthetic.json'))
        monkeypatch.setattr(run_candidate, 'connect_runtime_oidc', lambda *args: None)
        monkeypatch.setattr(reserve_trips, 'start_sync', Mock(side_effect=error))
    else:
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
    handler = SimpleNamespace(server=server, _send_json=Mock())

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
