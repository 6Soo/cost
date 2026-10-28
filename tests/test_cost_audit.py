import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import cost_audit


def test_preview_never_launches_a_child(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('preview launched subprocess')
    monkeypatch.setattr(cost_audit.subprocess, 'run', forbidden)
    for command in cost_audit.COMMANDS:
        assert cost_audit.main([command]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report['executed'] == [] and report['status'] == 'PREVIEW'


@pytest.mark.parametrize('argv', [
    ['deploy', '--run'], ['test-environment', '--collect', '--run'],
    ['tracked-data', '--mode', 'base', '--run'],
    ['runtime-catalog', '--root', 'D:/private', '--run'],
])
def test_writers_collection_and_arbitrary_arguments_are_rejected(argv, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid input launched subprocess')
    monkeypatch.setattr(cost_audit.subprocess, 'run', forbidden)
    with pytest.raises(SystemExit) as error:
        cost_audit.main(argv)
    assert error.value.code == 2


def test_run_keeps_child_exit_status_and_uses_no_shell(monkeypatch):
    calls = []
    def child(argv, **options):
        calls.append((argv, options))
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(cost_audit.subprocess, 'run', child)
    assert cost_audit.main(['test-environment', '--run']) == 7
    argv, options = calls.pop()
    assert Path(argv[1]).name == 'audit_test_environment.py'
    assert argv[2:] == ['--summary']
    assert options['shell'] is False and options['cwd'] == cost_audit.ROOT


def test_unavailable_child_fails_closed_without_path_leak(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cost_audit, 'ROOT', tmp_path)
    assert cost_audit.main(['tracked-data', '--run']) == 2
    report = json.loads(capsys.readouterr().out)
    assert report == {'status': 'ERROR', 'code': 'AUDIT_TOOL_UNAVAILABLE'}
    assert str(tmp_path) not in str(report)
