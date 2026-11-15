"""Synthetic Git repositories only; no customer or operating paths."""
import hashlib
import json
from pathlib import Path
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


def preserved_policy(tmp_path, entries):
    policy = load_policy()
    policy['externally_preserved'] = [{'archive': 'synthetic-archive', 'manifest_sha256': 'a' * 64,
                                       'files': entries}]
    path = tmp_path / 'preserved-policy.json'
    path.write_text(json.dumps(policy), encoding='utf-8')
    return path


def blob_entry(repo, path, data='SYNTHETIC_SENTINEL'):
    oid = git(repo, 'rev-parse', f'HEAD:{path}').stdout.decode().strip()
    return {'path': path, 'sha256': hashlib.sha256(data.encode()).hexdigest(), 'git_blob': oid}


def test_externally_preserved_untrack_allowed_only_for_listed_exact_blob(repo, tmp_path, capsys):
    write(repo, 'outputs/other.json', 'SYNTHETIC_OTHER')
    git(repo, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic other')
    policy_path = preserved_policy(tmp_path, [blob_entry(repo, 'outputs/existing.sqlite')])
    git(repo, 'rm', '-q', '--cached', '--', 'outputs/existing.sqlite')
    result = inspect(repo, policy_path=policy_path)
    finding = next(x for x in result['files'] if x['status'] == 'DELETED')
    assert result['blocked_count'] == 0 and not finding['blocked']
    assert 'EXTERNALLY_PRESERVED_UNTRACK' in finding['risk_markers']
    assert 'PROTECTED_DELETION' not in finding['risk_markers']
    assert main(['--root', str(repo), '--policy', str(policy_path)]) == 0
    # A protected path outside the list stays blocked in the same change.
    git(repo, 'rm', '-q', '--cached', '--', 'outputs/other.json')
    result = inspect(repo, policy_path=policy_path)
    blocked = [x['path'] for x in result['files'] if x['blocked']]
    assert blocked == ['outputs/other.json'] and result['blocked_count'] == 1
    assert main(['--root', str(repo), '--policy', str(policy_path)]) == 1
    assert 'SYNTHETIC_' not in capsys.readouterr().out
    assert (repo / 'outputs/existing.sqlite').read_text(encoding='utf-8') == 'SYNTHETIC_SENTINEL'


@pytest.mark.parametrize('field,value', [('sha256', 'b' * 64), ('git_blob', 'c' * 40)])
def test_externally_preserved_hash_mismatch_still_blocks(repo, tmp_path, field, value):
    entry = blob_entry(repo, 'outputs/existing.sqlite') | {field: value}
    policy_path = preserved_policy(tmp_path, [entry])
    git(repo, 'rm', '-q', '--cached', '--', 'outputs/existing.sqlite')
    result = inspect(repo, policy_path=policy_path)
    assert result['blocked_count'] == 1
    assert 'PROTECTED_DELETION' in result['files'][0]['risk_markers']


def test_externally_preserved_base_mode_after_commit(repo, tmp_path):
    before = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    policy_path = preserved_policy(tmp_path, [blob_entry(repo, 'outputs/existing.sqlite')])
    git(repo, 'rm', '-q', '--cached', '--', 'outputs/existing.sqlite')
    git(repo, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic untrack')
    assert inspect(repo, mode='base', base=before, policy_path=policy_path)['blocked_count'] == 0
    assert inspect(repo, mode='base', base=before)['blocked_count'] == 1


@pytest.mark.parametrize('entry', [
    {'path': 'outputs/*', 'sha256': 'a' * 64, 'git_blob': 'b' * 40},
    {'path': 'outputs/', 'sha256': 'a' * 64, 'git_blob': 'b' * 40, 'extra': 1},
    {'path': 'app/auth.py', 'sha256': 'a' * 64, 'git_blob': 'b' * 40},
    {'path': 'outputs/../app/auth.py', 'sha256': 'a' * 64, 'git_blob': 'b' * 40},
    {'path': 'outputs/x.json', 'sha256': 'short', 'git_blob': 'b' * 40},
    {'path': 'outputs/x.json', 'sha256': 'a' * 64, 'git_blob': None},
    'outputs/x.json',
])
def test_externally_preserved_entries_must_be_exact_protected_paths(tmp_path, entry):
    with pytest.raises(ValueError):
        load_policy(preserved_policy(tmp_path, [entry]))


def test_externally_preserved_duplicate_path_is_rejected(tmp_path):
    entry = {'path': 'outputs/x.json', 'sha256': 'a' * 64, 'git_blob': 'b' * 40}
    with pytest.raises(ValueError):
        load_policy(preserved_policy(tmp_path, [entry, dict(entry)]))


def test_source_reference_candidates_are_opt_in_exact_and_contextual(repo, capsys):
    data_path = 'outputs/new.json'
    write(repo, data_path, '{"sentinel":"PRIVATE_DATA_SENTINEL"}')
    second_path = 'outputs/second.json'
    write(repo, second_path)
    source = """\
from pathlib import Path
bare = 'outputs/new.json'
Path('outputs/new.json')
Path('outputs/new.json').write_text('outputs/second.json')
open('outputs/new.json', 'maybe')
open('outputs/new.json', MODE)
open('outputs/new.json')
unrelated = 'prefix outputs/new.json suffix'
message = 'unrelated sentinel SOURCE_SENTINEL'
"""
    write(repo, 'app/reader.py', source)

    default = inspect(repo)
    assert default['metadata_only'] is True
    assert 'source_references' not in default['files'][0]
    assert 'PRIVATE_DATA_SENTINEL' not in json.dumps(default)

    result = inspect(repo, source_references=True)
    assert result['metadata_only'] is False
    finding = next(item for item in result['files'] if item['path'] == data_path)
    refs = finding['source_references']
    candidates = [ref['candidate'] for ref in refs]
    assert candidates.count('REFERENCE') == 4
    assert candidates.count('WRITE_CANDIDATE') == 1
    assert candidates.count('READ_CANDIDATE') == 1
    second = next(item for item in result['files'] if item['path'] == second_path)
    assert [ref['candidate'] for ref in second['source_references']] == ['REFERENCE']
    assert all(ref['source_path'] == 'app/reader.py' for ref in refs)
    assert all(ref['reason'] == 'EXACT_TRACKED_PATH_LITERAL' for ref in refs)
    rendered = json.dumps(result)
    assert 'PRIVATE_DATA_SENTINEL' not in rendered
    assert 'SOURCE_SENTINEL' not in rendered
    assert 'DATA_PATH' not in rendered
    assert finding['producer'] == 'UNKNOWN' and finding['consumer'] == 'UNKNOWN'
    assert finding['active_use'] == 'UNVERIFIED'
    assert result['source_reference_provenance'] == {
        'path_metadata': 'Git index', 'source_text': 'working tree'
    }

    assert main(['--root', str(repo)]) == 1
    summary = capsys.readouterr().out
    assert data_path not in summary
    assert 'SOURCE_SENTINEL' not in summary


def test_source_scan_aggregates_parse_and_external_symlink_errors(repo, tmp_path, capsys):
    write(repo, 'outputs/new.json')
    write(repo, 'app/good.py', "open('outputs/new.json', 'r')\n")
    write(repo, 'app/bad.py', 'def broken(:\n')
    outside = tmp_path.parent / f'{tmp_path.name}-outside.py'
    outside.write_text("open('outputs/new.json', 'w')\n", encoding='utf-8')
    link = repo / 'tools' / 'linked.py'
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    git(repo, 'add', '--', 'tools/linked.py')
    read_error = repo / 'app' / 'read-error.py'
    read_error.write_bytes(b'\xff')
    git(repo, 'add', '--', 'app/read-error.py')

    # The default metadata-only path must not parse/read tracked source.
    default = inspect(repo)
    assert default['metadata_only'] is True
    assert 'errors' not in default
    result = inspect(repo, source_references=True)
    assert result['blocked_count'] == 2  # protected data plus changed symlink metadata
    assert result['errors'] == [
        {'path': 'app/bad.py', 'reason': 'SOURCE_PARSE_FAILED'},
        {'path': 'app/read-error.py', 'reason': 'SOURCE_READ_FAILED'},
        {'path': 'tools/linked.py', 'reason': 'SOURCE_PATH_OUTSIDE_OR_MISSING'},
    ]
    finding = next(item for item in result['files'] if item['path'] == 'outputs/new.json')
    assert [ref['candidate'] for ref in finding['source_references']] == ['READ_CANDIDATE']
    assert main(['--root', str(repo), '--source-references']) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary['source_error_count'] == 3
    assert summary['source_reference_count'] == 1
    assert 'errors' not in summary
    assert 'outputs/new.json' not in json.dumps(summary)


def test_source_bom_is_accepted_and_error_cli_is_safe(repo, capsys):
    write(repo, 'outputs/new.json')
    write(repo, 'app/bom.py', "open('outputs/new.json', 'r')\n")
    (repo / 'app' / 'bom.py').write_text(
        "\ufeffopen('outputs/new.json', 'r')\n", encoding='utf-8'
    )
    git(repo, 'add', '--', 'app/bom.py')
    write(repo, 'app/bad.py', 'SOURCE_SECRET def broken(:')
    result = main(['--root', str(repo), '--source-references', '--json'])
    assert result == 2
    output = capsys.readouterr().out
    assert 'SOURCE_SECRET' not in output
    assert 'SOURCE_PARSE_FAILED' in output
    assert 'outputs/new.json' in output


def test_internal_source_symlink_cannot_read_data_blob(repo, monkeypatch):
    write(repo, 'outputs/new.json', 'PRIVATE_DATA_NOT_SOURCE')
    link = repo / 'app' / 'linked.py'
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(repo / 'outputs/new.json')
    git(repo, 'add', '--', 'app/linked.py')
    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        assert path.resolve() != (repo / 'outputs/new.json').resolve()
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', guarded_read)
    result = inspect(repo, source_references=True)
    assert result['errors'] == [
        {'path': 'app/linked.py', 'reason': 'SOURCE_PATH_OUTSIDE_OR_MISSING'}
    ]


def test_source_scan_count_is_zero_when_no_targets_need_scanning(repo):
    write(repo, 'app/safe.py', 'def safe(): pass\n')
    result = inspect(repo, source_references=True)
    assert result['source_scan_count'] == 0


def policy_repo(repo, entries=()):
    policy = load_policy() | {'externally_preserved': [
        {'archive': 'synthetic-archive', 'manifest_sha256': 'a' * 64, 'files': list(entries)}] if entries else []}
    write(repo, 'config/tracked-data-policy.json', json.dumps(policy))
    git(repo, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic policy')
    return policy


def test_base_mode_reads_policy_from_base_so_pr_cannot_loosen_it(repo, capsys):
    policy_repo(repo)
    before = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    # The same commit adds the exemption and untracks the protected file.
    policy = json.loads((repo / 'config/tracked-data-policy.json').read_text(encoding='utf-8'))
    policy['externally_preserved'] = [{'archive': 'synthetic-archive', 'manifest_sha256': 'a' * 64,
                                       'files': [blob_entry(repo, 'outputs/existing.sqlite')]}]
    write(repo, 'config/tracked-data-policy.json', json.dumps(policy))
    git(repo, 'rm', '-q', '--cached', '--', 'outputs/existing.sqlite')
    git(repo, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic loosen')
    result = inspect(repo, mode='base', base=before)
    assert result['policy_source'] == 'BASE' and 'POLICY_CHANGED' in result['flags']
    assert result['blocked_count'] == 1
    assert main(['--root', str(repo), '--mode', 'base', '--base', before]) == 1
    assert 'POLICY_CHANGED' in capsys.readouterr().out


def test_base_policy_exemption_still_allows_untrack_without_policy_change(repo):
    policy_repo(repo, [blob_entry(repo, 'outputs/existing.sqlite')])
    before = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    git(repo, 'rm', '-q', '--cached', '--', 'outputs/existing.sqlite')
    git(repo, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic untrack')
    result = inspect(repo, mode='base', base=before)
    assert result['blocked_count'] == 0 and result['flags'] == []
    assert main(['--root', str(repo), '--mode', 'base', '--base', before]) == 0


def test_base_mode_without_base_policy_fails_closed(repo, capsys):
    before = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    assert main(['--root', str(repo), '--mode', 'base', '--base', before]) == 2
    assert 'BASE_POLICY_UNAVAILABLE' in capsys.readouterr().out
