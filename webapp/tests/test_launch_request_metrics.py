"""The production launcher forwards --request-metrics only when asked (#1001).

Synthetic credential files and a mocked preparation chain: no server starts,
no port binds, and nothing outside the temporary folder is read or written.
The counter code itself is unchanged; its content-free contract is covered by
tests/test_http_request_counts.py and webapp/tests/test_http_counting.py.
"""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    'launch_web_ledger', ROOT / 'tools' / 'launch_web_ledger.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

#: A synthetic port. Nothing in this file binds or connects to it.
PORT = 18765


def _credential_argv(host):
    return ['--checkout', str(host.checkout),
            '--data-root', str(host.root),
            '--oauth-file', str(host.oauth),
            '--session-secret-file', str(host.secret),
            '--port', str(PORT)]


def _expected_candidate_argv(host):
    return ['--host', '127.0.0.1',
            '--port', str(PORT),
            '--data-root', str(host.root.resolve()),
            '--environment', 'production',
            '--no-worker']


@pytest.fixture
def synthetic_host(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    root = tmp_path / 'data'
    root.mkdir()
    oauth = tmp_path / 'synthetic-oauth.json'
    oauth.write_text(json.dumps({'web': {'client_id': 'synthetic-id',
                                         'client_secret': 'synthetic-secret'}}),
                     encoding='utf-8')
    secret = tmp_path / 'synthetic-secret.txt'
    secret.write_text('synthetic-session-secret', encoding='utf-8')
    return SimpleNamespace(checkout=checkout, root=root, oauth=oauth, secret=secret)


def _launch(host, extra=()):
    config = SimpleNamespace(db_path=host.root / 'synthetic-board.sqlite',
                             data_root=host.root)
    with patch.dict(os.environ), \
            patch('webapp.ops.durable_config_for', return_value=config), \
            patch('webapp.ledger_store.LedgerStore'), \
            patch('webapp.access_control.attach_to_ledger_store',
                  return_value=object()), \
            patch('webapp.google_oidc.try_connect_from_env',
                  return_value=object()), \
            patch('webapp.ledger_board.bind_oidc'), \
            patch('run_candidate.validate_optional_data_paths'), \
            patch('run_candidate.main', return_value=0) as candidate:
        os.environ.pop('WEBLEDGER_CARD_FLOW', None)
        os.environ.pop('WEBLEDGER_UNIFIED_DB', None)
        rc = launcher.main(_credential_argv(host) + list(extra))
    assert rc == 0
    assert candidate.call_count == 1
    return candidate.call_args[0][0]


def test_default_forwarding_is_the_unchanged_production_argv(synthetic_host):
    argv = _launch(synthetic_host)
    assert argv == _expected_candidate_argv(synthetic_host)
    assert '--request-metrics' not in argv
    # The launcher never creates the counter file itself, opt-in or not.
    assert not (synthetic_host.root / 'metrics').exists()


def test_opt_in_appends_the_existing_run_candidate_flag(synthetic_host):
    argv = _launch(synthetic_host, extra=['--request-metrics'])
    assert argv == _expected_candidate_argv(synthetic_host) + ['--request-metrics']
    assert not (synthetic_host.root / 'metrics').exists()


def test_the_parser_defaults_to_off(synthetic_host):
    parser = launcher.build_parser()
    assert parser.parse_args(_credential_argv(synthetic_host)).request_metrics is False
    assert parser.parse_args(
        _credential_argv(synthetic_host) + ['--request-metrics']).request_metrics is True
