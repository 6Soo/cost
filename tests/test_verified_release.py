import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import shutil

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


def test_inventory_requires_original_identities_even_when_count_is_unchanged():
    baseline = {key: {'count': 0, 'sha256': 'synthetic'} for key in protection.REQUIRED_TABLES}
    protection.validate_inventory(baseline)
    baseline.pop('board:transactions')
    baseline['board:receipt_evidence_links'] = {'count': 0, 'sha256': 'new'}
    with pytest.raises(ValueError, match='PROTECTED_TABLE_MISSING'):
        protection.validate_inventory(baseline)


def test_additive_protected_table_needs_explicit_approval_and_must_be_empty():
    original = {'board:transactions': {'count': 1, 'sha256': 'original'}}
    added = 'board:receipt_evidence_links'
    current = {**original, added: {'count': 0, 'sha256': 'new-schema'}}
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify(current, original)
    protection.verify(current, original, allowed_empty_tables=[added])
    current[added]['count'] = 1
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify(current, original, allowed_empty_tables=[added])


def test_approved_addition_cannot_hide_existing_changes_or_unapproved_tables():
    original = {'board:transactions': {'count': 1, 'sha256': 'original'}}
    added = 'board:receipt_evidence_links'
    current = {**original, added: {'count': 0, 'sha256': 'new'}}
    current['board:transactions'] = {'count': 1, 'sha256': 'changed'}
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify(current, original, allowed_empty_tables=[added])
    current['board:transactions'] = original['board:transactions']
    current['board:unapproved_links'] = {'count': 0, 'sha256': 'unknown'}
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify(current, original, allowed_empty_tables=[added, 'board:unapproved_links'])
    with pytest.raises(ValueError, match='PROTECTED_STATE_CHANGED'):
        protection.verify({}, original, allowed_empty_tables=[added])


def test_cli_preserves_and_checks_new_table_after_it_enters_baseline(tmp_path, monkeypatch, capsys):
    current = {key: {'count': 0, 'sha256': key} for key in protection.REQUIRED_TABLES}
    current['board:receipt_evidence_links'] = {'count': 0, 'sha256': 'receipt-schema'}
    monkeypatch.setattr(protection, 'snapshot', lambda _: current)
    assert protection.main(['--evidence-dir', str(tmp_path), '--phase', 'before']) == 0
    assert protection.main(['--evidence-dir', str(tmp_path), '--phase', 'validate-baseline']) == 0
    assert protection.main(['--evidence-dir', str(tmp_path), '--phase', 'after']) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['tables'] == 14
    current['board:receipt_evidence_links']['sha256'] = 'changed-schema'
    assert protection.main(['--evidence-dir', str(tmp_path), '--phase', 'after']) == 2


def test_cli_allows_only_approved_empty_receipt_table_during_migration(tmp_path, monkeypatch):
    current = {key: {'count': 0, 'sha256': key} for key in protection.REQUIRED_TABLES}
    monkeypatch.setattr(protection, 'snapshot', lambda _: current)
    before = ['--evidence-dir', str(tmp_path), '--phase', 'before']
    after = ['--evidence-dir', str(tmp_path), '--phase', 'after']
    assert protection.main(before) == 0
    current['board:receipt_evidence_links'] = {'count': 0, 'sha256': 'receipt-schema'}
    assert protection.main(after) == 2
    assert protection.main(after + ['--allow-empty-table', 'board:receipt_evidence_links']) == 0


def test_deploy_default_preview_does_not_read_review_or_access_host():
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    assert shell, 'PowerShell is required to verify the release entrypoint'
    result = subprocess.run([shell, '-NoProfile', '-File',
        str(ROOT / 'tools/deploy_verified_release.ps1'), '-CandidateSha', 'a' * 40,
        '-PreviousSha', 'b' * 40, '-ReviewEvidence', 'Z:/nonexistent/private-review.json'],
        capture_output=True, text=True)
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report['status'] == 'PREVIEW' and report['executed'] == []
    assert 'Z:/nonexistent' not in result.stdout


@pytest.mark.parametrize('candidate,previous', [('invalid', 'b' * 40), ('a' * 40, 'a' * 40)])
def test_invalid_or_identical_release_is_rejected_before_host_access(candidate, previous):
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    assert shell, 'PowerShell is required to verify the release entrypoint'
    result = subprocess.run([shell, '-NoProfile', '-File',
        str(ROOT / 'tools/deploy_verified_release.ps1'), '-CandidateSha', candidate,
        '-PreviousSha', previous, '-ReviewEvidence', 'Z:/nonexistent/private-review.json', '-Apply'],
        # Windows PowerShell writes errors in the console code page; the checked codes are ASCII.
        capture_output=True, text=True, errors='replace')
    assert result.returncode != 0
    assert 'INVALID_SHA' in result.stderr or 'IDENTICAL_RELEASE_SHA' in result.stderr
    assert 'WebLedger-Board' not in result.stderr
