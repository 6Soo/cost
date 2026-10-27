"""Synthetic Git repositories only; no customer or operating paths."""
import json
import subprocess
import pytest
from tools.check_tracked_data import inspect, load_policy, main


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def write(root, name, data='SYNTHETIC_SENTINEL'):
    dest = root / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(data, encoding='utf-8')
    git(root, 'add', '--', name)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Synthetic Test')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    write(tmp_path, 'outputs/existing.sqlite')
    write(tmp_path, 'app/auth.py', 'value = 1\n')
    git(tmp_path, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic baseline')
    return tmp_path


def test_baseline_preserved_and_sensitivity_never_cleared(repo):
    assert inspect(repo)['files'] == []
    inventory = inspect(repo, mode='inventory')
    assert all(x['sensitivity'] == 'UNASSESSED' and not x['blocked'] for x in inventory['files'])
    assert 'SYNTHETIC_SENTINEL' not in json.dumps(inventory)


@pytest.mark.parametrize('name', ['outputs/new.json', 'ledger/data/new.txt', 'data/new.sqlite',
    '.env', 'secrets/test.py', 'customer_source/test.json', 'data/new.xlsx', 'data/new.csv'])
def test_new_sensitive_artifact_blocks_with_nonzero_exit(repo, name, capsys):
    write(repo, name)
    result = inspect(repo)
    assert result['blocked_count'] == 1 and result['files'][0]['path'] == name
    assert main(['--root', str(repo), '--json']) == 1
    assert 'SYNTHETIC_SENTINEL' not in capsys.readouterr().out


def test_staged_blob_not_worktree_and_existing_data_modification_blocks(repo):
    write(repo, 'outputs/existing.sqlite', 'SYNTHETIC_MODIFIED')
    (repo / 'outputs/existing.sqlite').write_text('SYNTHETIC_SENTINEL', encoding='utf-8')
    assert inspect(repo)['files'][0]['status'] == 'MODIFIED'
    assert inspect(repo)['blocked_count'] == 1
    git(repo, 'reset', '-q', 'HEAD', '--', 'outputs/existing.sqlite')
    assert inspect(repo)['files'] == []


def test_auth_source_not_blocked_by_name_and_untracked_file_not_read(repo):
    write(repo, 'app/auth.py', 'value = 2\n')
    (repo / 'untracked.sqlite').write_text('DO_NOT_READ', encoding='utf-8')
    result = inspect(repo)
    assert [x['path'] for x in result['files']] == ['app/auth.py']
    assert result['blocked_count'] == 0


def test_base_comparison_and_spaces(repo):
    before = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    write(repo, 'outputs/space name.json')
    git(repo, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic addition')
    result = inspect(repo, mode='base', base=before)
    assert result['blocked_count'] == 1 and result['files'][0]['path'] == 'outputs/space name.json'


def test_exact_fixture_exception_and_no_wildcard_exemption(repo, tmp_path):
    policy = load_policy()
    policy['synthetic_allowlist'] = ['tests/fixtures/approved.csv']
    policy_path = tmp_path / 'policy.json'
    policy_path.write_text(json.dumps(policy), encoding='utf-8')
    write(repo, 'tests/fixtures/approved.csv', 'SYNTHETIC_APPROVED_FIXTURE')
    write(repo, 'tests/fixtures/unapproved.csv', 'SYNTHETIC_UNAPPROVED_FIXTURE')
    result = inspect(repo, policy_path=policy_path)
    assert {x['path'] for x in result['files'] if x['blocked']} == {'tests/fixtures/unapproved.csv'}
    policy['synthetic_allowlist'] = ['tests/fixtures/*']
    policy_path.write_text(json.dumps(policy), encoding='utf-8')
    with pytest.raises(ValueError):
        load_policy(policy_path)


def test_invalid_git_or_policy_fail_closed(tmp_path, capsys):
    assert main(['--root', str(tmp_path)]) == 2
    broken = tmp_path / 'broken.json'
    broken.write_text('{', encoding='utf-8')
    assert main(['--root', str(tmp_path), '--policy', str(broken)]) == 2
    assert 'status' in capsys.readouterr().out


def test_large_blob_and_renamed_protected_object_cannot_hide_as_source(repo):
    write(repo, 'app/oversize.py', 'x' * (1048576 + 1))
    write(repo, 'app/disguised.py')  # Same synthetic blob as protected baseline.
    result = inspect(repo)
    entries = {x['path']: x for x in result['files']}
    assert 'LARGE_BLOB' in entries['app/oversize.py']['risk_markers']
    assert 'REUSED_PROTECTED_OBJECT' in entries['app/disguised.py']['risk_markers']
    assert result['blocked_count'] == 2


def test_protected_deletion_blocks_without_touching_original_worktree(repo, capsys):
    git(repo, 'rm', '--cached', '--', 'outputs/existing.sqlite')
    result = inspect(repo)
    assert result['deleted_count'] == 1 and result['blocked_count'] == 1
    finding = next(x for x in result['files'] if x['status'] == 'DELETED')
    assert 'PROTECTED_DELETION' in finding['risk_markers']
    assert 'PROTECTED_PATH' in finding['risk_markers']
    assert main(['--root', str(repo), '--json']) == 1
    assert 'SYNTHETIC_SENTINEL' not in capsys.readouterr().out
    assert (repo / 'outputs/existing.sqlite').read_text(encoding='utf-8') == 'SYNTHETIC_SENTINEL'
