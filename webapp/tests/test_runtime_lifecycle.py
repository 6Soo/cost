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
