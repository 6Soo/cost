"""card-flow.json keys set the core writer switches for launched host processes only."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import webledger_worker as worker  # noqa: E402
from app import core_switch_config as switches  # noqa: E402

_spec = importlib.util.spec_from_file_location('launch_web_ledger', ROOT / 'tools' / 'launch_web_ledger.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

NAMES = switches.ENV_NAMES


@pytest.fixture
def host(tmp_path):
    data = tmp_path / 'data'
    config = tmp_path / 'config'
    data.mkdir()
    config.mkdir()
    binary = tmp_path / 'costcore.exe'
    binary.write_bytes(b'')
    core = data / 'core.sqlite'
    core.write_bytes(b'')
    return tmp_path, data, config, binary, core


def _rust(binary, core):
    return {'classification_writer': 'rust', 'costcore_bin': str(binary), 'core_db': str(core)}


def test_no_keys_sets_nothing_and_clears_inherited_values(host):
    _, data, *_ = host
    with patch.dict(os.environ, {name: 'inherited' for name in NAMES}):
        launcher.apply_core_switches({}, data)
        assert not any(name in os.environ for name in NAMES)


def test_rust_with_paths_sets_the_environment(host):
    _, data, _, binary, core = host
    with patch.dict(os.environ):
        launcher.apply_core_switches(_rust(binary, core) | {'links_producer': 'rust'}, data)
        assert os.environ['WEBLEDGER_CLASSIFICATION_WRITER'] == 'rust'
        assert os.environ['WEBLEDGER_LINKS_PRODUCER'] == 'rust'
        assert os.environ['WEBLEDGER_COSTCORE_BIN'] == str(binary)
        assert os.environ['WEBLEDGER_CORE_DB'] == str(core)


def test_python_value_keeps_python_and_sets_no_rust_variable(host):
    _, data, _, binary, core = host
    with patch.dict(os.environ):
        launcher.apply_core_switches({'classification_writer': 'python', 'costcore_bin': str(binary)}, data)
        assert os.environ.get('WEBLEDGER_CLASSIFICATION_WRITER') != 'rust'
        assert 'WEBLEDGER_COSTCORE_BIN' not in os.environ


@pytest.mark.parametrize('mutate,code', [
    (lambda o: o.pop('costcore_bin'), 'CORE_SWITCH_BIN'),
    (lambda o: o.update(costcore_bin='relative.exe'), 'CORE_SWITCH_BIN'),
    (lambda o: o.update(costcore_bin='X:/missing/costcore.exe'), 'CORE_SWITCH_BIN'),
    (lambda o: o.pop('core_db'), 'CORE_SWITCH_DB'),
    (lambda o: o.update(core_db='X:/missing/core.sqlite'), 'CORE_SWITCH_DB'),
    (lambda o: o.update(classification_writer='Rust '), 'CORE_SWITCH_VALUE'),
])
def test_rust_with_missing_or_bad_values_refuses(host, mutate, code):
    _, data, _, binary, core = host
    options = _rust(binary, core)
    mutate(options)
    with patch.dict(os.environ):
        with pytest.raises(launcher._Refused) as refused:
            launcher.apply_core_switches(options, data)
        assert refused.value.code == code
        assert os.environ.get('WEBLEDGER_CLASSIFICATION_WRITER') != 'rust'


def test_core_db_outside_the_data_root_is_refused(host):
    tmp, data, _, binary, _ = host
    stray = tmp / 'core.sqlite'
    stray.write_bytes(b'')
    with pytest.raises(launcher._Refused) as refused:
        launcher.apply_core_switches(_rust(binary, stray), data)
    assert refused.value.code == 'CORE_SWITCH_DB_ROOT'


def test_links_producer_alone_needs_the_binary_but_not_the_core_db(host):
    _, data, _, binary, _ = host
    with patch.dict(os.environ):
        launcher.apply_core_switches({'links_producer': 'rust', 'costcore_bin': str(binary)}, data)
        assert os.environ['WEBLEDGER_LINKS_PRODUCER'] == 'rust'
        assert 'WEBLEDGER_CORE_DB' not in os.environ
        with pytest.raises(launcher._Refused):
            launcher.apply_core_switches({'links_producer': 'rust'}, data)


def test_worker_entry_reads_the_same_card_flow_values(host, monkeypatch):
    tmp, data, config, binary, core = host
    (config / 'card-flow.json').write_text(json.dumps(_rust(binary, core)), encoding='utf-8')
    worker_config = config / 'worker.json'
    worker_config.write_text(json.dumps({'log': str(tmp / 'w.log'), 'jobs': []}), encoding='utf-8')
    seen = {}
    monkeypatch.setattr(worker, 'single_instance', lambda name=None: seen.update(
        {name: os.environ.get(name) for name in NAMES}) or False)
    with patch.dict(os.environ), patch('os.chdir'):
        assert worker.main(['--config', str(worker_config)]) == 75
    assert seen['WEBLEDGER_CLASSIFICATION_WRITER'] == 'rust'
    assert seen['WEBLEDGER_COSTCORE_BIN'] == str(binary)
    assert seen['WEBLEDGER_CORE_DB'] == str(core)


def test_worker_entry_refuses_rust_without_a_binary(host):
    tmp, _, config, binary, core = host
    (config / 'card-flow.json').write_text(json.dumps(_rust(binary, core) | {'costcore_bin': str(tmp / 'gone')}),
                                           encoding='utf-8')
    worker_config = config / 'worker.json'
    worker_config.write_text(json.dumps({'log': str(tmp / 'w.log'), 'jobs': []}), encoding='utf-8')
    with patch.dict(os.environ), patch('os.chdir'), pytest.raises(SystemExit) as refused:
        worker.main(['--config', str(worker_config)])
    assert refused.value.code == 'WORKER_CORE_SWITCH_BIN'


def test_worker_children_inherit_the_values_set_in_the_worker_process(monkeypatch):
    from app.python_launch import child_environment
    with patch.dict(os.environ, {'WEBLEDGER_CLASSIFICATION_WRITER': 'rust'}):
        assert child_environment({}) is None  # inherits os.environ
        assert child_environment({'X': '1'})['WEBLEDGER_CLASSIFICATION_WRITER'] == 'rust'


def _host(tmp_path, options, bom=False):
    config = tmp_path / 'config'
    config.mkdir(exist_ok=True)
    (tmp_path / 'data').mkdir(exist_ok=True)
    (config / 'card-flow.json').write_text(json.dumps(options), encoding='utf-8-sig' if bom else 'utf-8')
    return tmp_path


def test_a_bom_in_card_flow_json_is_read_by_launcher_and_worker_alike(host):
    tmp, data, config, binary, core = host
    (config / 'card-flow.json').write_text(json.dumps(_rust(binary, core)), encoding='utf-8-sig')
    assert switches.read_options(config)['classification_writer'] == 'rust'
    env = {}
    switches.apply_from_host(config, data, env)
    assert env['WEBLEDGER_CLASSIFICATION_WRITER'] == 'rust'


@pytest.mark.parametrize('module', ['tools.complete_card_classification', 'tools.review_card_inference'])
def test_manual_apply_is_refused_while_the_host_writer_is_rust(tmp_path, module, capsys):
    import importlib
    sys.path.insert(0, str(ROOT))
    main = importlib.import_module(module).main
    root = _host(tmp_path, {'classification_writer': 'rust'})
    argv = ['--host-root', str(root), '--apply']
    if module.endswith('review_card_inference'):
        argv += ['--transaction', 'x', '--output', str(tmp_path / 'out.json')]
    assert main(argv) == 1
    assert 'CORE_WRITER_MANUAL_APPLY_REFUSED' in capsys.readouterr().out


def test_manual_apply_guard_passes_without_rust(tmp_path):
    switches.refuse_manual_apply(_host(tmp_path, {'classification_writer': 'python'}))
    switches.refuse_manual_apply(tmp_path / 'nowhere')


def test_check_validates_without_touching_the_environment(host, capsys):
    tmp, data, config, binary, core = host
    _host(tmp, _rust(binary, core), bom=True)
    with patch.dict(os.environ, {}):
        before = dict(os.environ)
        assert switches.main(['--host-root', str(tmp), '--check']) == 0
        assert os.environ == before
    assert capsys.readouterr().out.strip() == 'ok'
    _host(tmp, _rust(binary, core) | {'costcore_bin': str(tmp / 'gone')})
    assert switches.main(['--host-root', str(tmp), '--check']) == 2
    assert 'CORE_SWITCH_BIN' in capsys.readouterr().out


def _record(config, role, **over):
    switches.record_applied(role, config, over.pop('release', 'r' * 40), over.pop('environ', {}))
    path = config / f'core-switch-applied-{role}.json'
    state = json.loads(path.read_text(encoding='utf-8')) | over
    path.write_text(json.dumps(state), encoding='utf-8')


def test_launcher_and_worker_leave_the_writers_they_applied(host, monkeypatch):
    tmp, data, config, binary, core = host
    (config / 'card-flow.json').write_text(json.dumps(_rust(binary, core)), encoding='utf-8')
    with patch.dict(os.environ), patch.object(sys, 'path', list(sys.path)):
        launcher.main(['--checkout', str(ROOT), '--data-root', str(data), '--port', '9',
                       '--oauth-file', str(tmp / 'no-oauth.json'), '--session-secret-file', str(tmp / 'no-secret.txt')])
    board = json.loads((config / 'core-switch-applied-board.json').read_text(encoding='utf-8'))
    assert board['classification_writer'] == 'rust' and board['links_producer'] == 'python'
    assert board['release'] == ROOT.name and board['pid'] == os.getpid()
    worker_config = config / 'worker.json'
    worker_config.write_text(json.dumps({'log': str(tmp / 'w.log'), 'jobs': []}), encoding='utf-8')
    monkeypatch.setattr(worker, 'single_instance', lambda name=None: True)
    monkeypatch.setattr(worker, 'own_children', lambda: None)
    with patch.dict(os.environ), patch('os.chdir'):
        assert worker.main(['--config', str(worker_config)]) == 0
    assert json.loads((config / 'core-switch-applied-worker.json').read_text(encoding='utf-8'))['classification_writer'] == 'rust'


def test_a_refused_second_worker_does_not_overwrite_the_running_workers_record(host, monkeypatch):
    tmp, _, config, *_ = host
    _record(config, 'worker', classification_writer='rust')
    worker_config = config / 'worker.json'
    worker_config.write_text(json.dumps({'log': str(tmp / 'w.log'), 'jobs': []}), encoding='utf-8')
    monkeypatch.setattr(worker, 'single_instance', lambda name=None: False)
    with patch.dict(os.environ), patch('os.chdir'):
        assert worker.main(['--config', str(worker_config)]) == 75
    assert json.loads((config / 'core-switch-applied-worker.json').read_text(encoding='utf-8'))['classification_writer'] == 'rust'


@pytest.mark.parametrize('board,worker,code', [
    ({}, {}, None),
    ({'classification_writer': 'python'}, {}, 'CORE_APPLIED_MISMATCH_BOARD'),
    ({}, {'classification_writer': 'python'}, 'CORE_APPLIED_MISMATCH_WORKER'),
    ({'release': 'old'}, {}, 'CORE_APPLIED_RELEASE_BOARD'),
])
def test_verify_applied_compares_board_and_worker_with_card_flow(host, board, worker, code):
    tmp, _, config, binary, core = host
    (config / 'card-flow.json').write_text(json.dumps(_rust(binary, core)), encoding='utf-8')
    env = {'WEBLEDGER_CLASSIFICATION_WRITER': 'rust'}
    _record(config, 'board', **({'environ': env, 'release': 'new'} | board))
    _record(config, 'worker', environ=env, **worker)
    check = lambda: switches.verify_applied(tmp, 'new', True, alive=lambda pid: True)
    if code is None:
        check()
    else:
        with pytest.raises(switches.CoreSwitchRefused) as refused:
            check()
        assert refused.value.code == code


def test_verify_applied_fails_on_missing_or_dead_records_and_skips_an_absent_optional_worker(host):
    tmp, _, config, *_ = host
    with pytest.raises(switches.CoreSwitchRefused) as refused:
        switches.verify_applied(tmp, 'new', False, alive=lambda pid: True)
    assert refused.value.code == 'CORE_APPLIED_MISSING_BOARD'
    _record(config, 'board', release='new')
    switches.verify_applied(tmp, 'new', False, alive=lambda pid: True)
    with pytest.raises(switches.CoreSwitchRefused) as refused:
        switches.verify_applied(tmp, 'new', True, alive=lambda pid: True)
    assert refused.value.code == 'CORE_APPLIED_MISSING_WORKER'
    with pytest.raises(switches.CoreSwitchRefused) as refused:
        switches.verify_applied(tmp, 'new', False, alive=lambda pid: False)
    assert refused.value.code == 'CORE_APPLIED_STALE_BOARD'


def test_verify_applied_cli_exit_codes(host, capsys):
    tmp, _, config, *_ = host
    _record(config, 'board', release='new')
    base = ['--host-root', str(tmp), '--verify-applied', '--release', 'new']
    assert switches.main(base) == 0
    assert switches.main(base[:-1] + ['other']) == 2
    assert 'CORE_APPLIED_RELEASE_BOARD' in capsys.readouterr().out
