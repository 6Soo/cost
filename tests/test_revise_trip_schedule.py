"""Synthetic evidence revisions retain old records and support guarded recovery."""
import json

import pytest

from ledger.domain.direct_trip_schedule_authority import SCHEMA_VERSION, END_SEMANTICS, load_document
from tools import revise_trip_schedule as tool


@pytest.fixture
def setup(tmp_path):
    old_source = tmp_path / 'evidence' / 'original.json'
    old_source.parent.mkdir()
    old_source.write_text('original evidence', encoding='utf-8')
    record = dict(trip_code='0823_Synthetic', event_year=2026, starts_on='2026-08-23', ends_on='2026-08-25',
                  region='Synthetic', authority_kind='user_confirmed_schedule', authority_status='authoritative',
                  source_locator=str(old_source) + '#schedule', source_sha256=tool.digest(old_source.read_bytes()),
                  end_semantics=END_SEMANTICS)
    other = dict(record, trip_code='0901_Other', starts_on='2026-09-01', ends_on='2026-09-02')
    authority = tmp_path / 'authority.json'
    authority.write_bytes(tool.encoded(dict(schema_version=SCHEMA_VERSION, records=[record, other])))
    change = dict(trip_code=record['trip_code'], ends_on='2026-08-26', rule_id='TRIP-SYNTHETIC',
                  decided_on='2026-11-13', reason='Owner-confirmed correction')
    return authority, old_source, change


def test_preview_apply_and_rollback_preserve_evidence_and_original_bytes(setup, tmp_path):
    authority, old_source, change = setup
    original = authority.read_bytes()
    old_evidence = old_source.read_bytes()
    files_before = set(tmp_path.rglob('*'))
    plan = tool.plan_revision(authority, old_source.parent, change)
    assert set(tmp_path.rglob('*')) == files_before
    assert authority.read_bytes() == original
    receipt = tmp_path / 'receipt'
    tool.apply_revision(authority, plan, receipt, tool.digest(original))
    active, _ = load_document(authority)
    assert len(active) == 2 and active[0].ends_on.isoformat() == change['ends_on']
    assert active[1].as_dict() == json.loads(original)['records'][1]
    assert tool.digest(plan['source'].read_bytes()) == active[0].source_sha256
    evidence = json.loads(plan['source'].read_bytes())
    assert evidence['basis']['supersedes'] == json.loads(original)['records'][0]
    assert evidence['basis']['rule_id'] == change['rule_id']
    assert (receipt / 'authority.before.json').read_bytes() == original
    manifest = json.loads((receipt / 'manifest.json').read_bytes())
    assert manifest['old'] == json.loads(original)['records'][0]
    assert old_source.read_bytes() == old_evidence
    after = authority.read_bytes()
    assert tool.rollback_revision(authority, receipt)['status'] == 'rollback_preview'
    assert authority.read_bytes() == after
    tool.rollback_revision(authority, receipt, apply=True)
    assert authority.read_bytes() == original
    assert plan['source'].exists() and old_source.read_bytes() == old_evidence
    assert (receipt / 'rolled-back.json').exists()


@pytest.mark.parametrize('failure', ['stale_plan', 'wrong_preview', 'evidence_conflict', 'replace_failure'])
def test_apply_refuses_conflicts_without_overwriting_authority(setup, tmp_path, monkeypatch, failure):
    authority, old_source, change = setup
    plan = tool.plan_revision(authority, old_source.parent, change)
    expected = tool.digest(plan['before'])
    if failure == 'stale_plan':
        authority.write_bytes(authority.read_bytes() + b'\n')
    elif failure == 'wrong_preview':
        expected = '0' * 64
    elif failure == 'evidence_conflict':
        plan['source'].write_bytes(b'conflict')
    else:
        def fail(*args):
            raise OSError('synthetic write failure')
        monkeypatch.setattr(tool.os, 'replace', fail)
    original = authority.read_bytes()
    with pytest.raises((ValueError, OSError)):
        tool.apply_revision(authority, plan, tmp_path / 'receipt', expected)
    assert authority.read_bytes() == original
    assert not authority.with_name(authority.name + '.revision.lock').exists()
    assert not list(tmp_path.rglob('*.tmp'))


@pytest.mark.parametrize('failure', ['newer_authority', 'damaged_backup', 'wrong_authority'])
def test_rollback_cannot_erase_later_edits_or_restore_bad_bytes(setup, tmp_path, failure):
    authority, old_source, change = setup
    plan = tool.plan_revision(authority, old_source.parent, change)
    receipt = tmp_path / 'receipt'
    tool.apply_revision(authority, plan, receipt, tool.digest(plan['before']))
    target = authority
    if failure == 'newer_authority':
        authority.write_bytes(authority.read_bytes() + b'\n')
    elif failure == 'damaged_backup':
        (receipt / 'authority.before.json').write_bytes(b'{}')
    else:
        target = tmp_path / 'other-authority.json'
        target.write_bytes(authority.read_bytes())
    original = target.read_bytes()
    with pytest.raises(ValueError):
        tool.rollback_revision(target, receipt, apply=True)
    assert target.read_bytes() == original
    assert not target.with_name(target.name + '.revision.lock').exists()


def test_cli_defaults_to_preview_and_apply_requires_reviewed_sha(setup, tmp_path, capsys):
    authority, old_source, change = setup
    change_path = tmp_path / 'change.json'
    change_path.write_bytes(tool.encoded(change))
    args = ['--authority', str(authority), '--evidence-root', str(old_source.parent), '--change', str(change_path)]
    original = authority.read_bytes()
    assert tool.main(args) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'preview'
    assert authority.read_bytes() == original
    assert tool.main(args + ['--apply']) == 1
    assert authority.read_bytes() == original
    capsys.readouterr()
    receipt = tmp_path / 'receipt'
    assert tool.main(args + ['--apply', '--receipt', str(receipt), '--expected-sha256', tool.digest(original)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'applied'
    assert tool.main(['--authority', str(authority), '--rollback', str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'rollback_preview'
    assert authority.read_bytes() != original
    assert tool.main(['--authority', str(authority), '--rollback', str(receipt), '--apply']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'rolled_back'
    assert authority.read_bytes() == original


def test_invalid_or_reversed_schedule_is_rejected_before_writes(setup):
    authority, old_source, change = setup
    original = authority.read_bytes()
    with pytest.raises(ValueError):
        tool.plan_revision(authority, old_source.parent, dict(change, ends_on='2026-08-22'))
    assert authority.read_bytes() == original
