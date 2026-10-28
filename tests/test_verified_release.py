import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest

from tools import verify_protected_release_state as protection

ROOT = Path(__file__).resolve().parents[1]


def test_protected_snapshot_preserves_source_and_detects_content_and_schema_changes(tmp_path):
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE transactions (amount INTEGER, source_id TEXT)')
        connection.execute("INSERT INTO transactions VALUES (12500,'synthetic-original')")
        connection.execute('CREATE TABLE unrelated (value TEXT)')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    before = protection.snapshot({'board': path})
    assert set(before) == {'board:transactions'}
    assert before['board:transactions']['count'] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    protection.verify(protection.snapshot({'board': path}), before)
    with sqlite3.connect(path) as connection:
        connection.execute('UPDATE transactions SET amount=12501')
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify(protection.snapshot({'board': path}), before)
    with sqlite3.connect(path) as connection:
        connection.execute('UPDATE transactions SET amount=12500')
        connection.execute('ALTER TABLE transactions ADD COLUMN changed TEXT')
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify(protection.snapshot({'board': path}), before)


def test_operating_snapshot_is_not_created_when_source_is_missing(tmp_path):
    path = tmp_path / 'missing.sqlite'
    with pytest.raises(sqlite3.OperationalError):
        protection.snapshot({'board': path})
    assert not path.exists()


def test_cli_fails_closed_on_count_drift_and_does_not_publish_rows(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(protection, 'snapshot', lambda _: {'board:transactions': {'count': 1, 'sha256': 'synthetic'}})
    assert protection.main(['--evidence-dir', str(tmp_path), '--phase', 'before']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'PROTECTED_STATE_UNVERIFIED'
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell parser and command contract')
def test_deploy_default_preview_does_not_read_review_or_access_host():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-File',
        str(ROOT / 'tools/deploy_verified_release.ps1'), '-CandidateSha', 'a' * 40,
        '-PreviousSha', 'b' * 40, '-ReviewEvidence', 'Z:/nonexistent/private-review.json'],
        capture_output=True, text=True)
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report['status'] == 'PREVIEW' and report['executed'] == []
    assert 'Z:/nonexistent' not in result.stdout


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell command contract')
@pytest.mark.parametrize('candidate,previous', [('invalid', 'b' * 40), ('a' * 40, 'a' * 40)])
def test_invalid_or_identical_release_is_rejected_before_host_access(candidate, previous):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-File',
        str(ROOT / 'tools/deploy_verified_release.ps1'), '-CandidateSha', candidate,
        '-PreviousSha', previous, '-ReviewEvidence', 'Z:/nonexistent/private-review.json', '-Apply'],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert 'INVALID_SHA' in result.stderr or 'IDENTICAL_RELEASE_SHA' in result.stderr
    assert 'WebLedger-Board' not in result.stderr
