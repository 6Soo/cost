import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from tools import code_release_manifest as release


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    files = {'app/core.py': 'VALUE = 1\n', 'webapp/static/css/site.css': 'body{}',
             'requirements.txt': '', 'outputs/private.sqlite': 'PRIVATE_ORIGINAL',
             'ledger/data/source.json': 'PRIVATE_ORIGINAL', 'config/review_source.json': 'PRIVATE_CONFIG',
             'app/.env': 'PRIVATE_CONFIG', 'webapp/tests/fixture.py': 'TEST_ONLY',
             'docs/handoff/source.md': 'PRIVATE_DOCUMENT', 'app/large.py': 'x' * 1048577}
    policy = (Path(__file__).resolve().parents[1] / 'config/tracked-data-policy.json').read_text(encoding='utf-8')
    files['config/tracked-data-policy.json'] = policy
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    git(tmp_path, 'add', '.')
    git(tmp_path, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic')
    return tmp_path, git(tmp_path, 'rev-parse', 'HEAD').decode().strip()


def test_package_contains_only_pinned_code_and_assets_and_preserves_originals(repo, tmp_path):
    root, sha = repo
    report = release.manifest(root, sha)
    assert {row['path'] for row in report['included']} == {'app/core.py', 'requirements.txt', 'webapp/static/css/site.css'}
    original = {row['path']: (root / row['path']).read_bytes() for row in report['excluded']}
    (root / 'app/core.py').write_text('UNCOMMITTED_PRIVATE_VALUE', encoding='utf-8')
    path = tmp_path / 'package.zip'
    release.package(root, report, path)
    with zipfile.ZipFile(path) as archive:
        assert archive.read('app/core.py') == b'VALUE = 1\n'
        assert set(archive.namelist()) == {'app/core.py', 'requirements.txt', 'webapp/static/css/site.css', 'CODE_RELEASE.json'}
        marker = json.loads(archive.read('CODE_RELEASE.json'))
        assert marker['sha'] == sha and marker['runtime_accepted'] is False
        assert 'PRIVATE' not in str(marker) and 'source.json' not in str(marker)
    assert all((root / name).read_bytes() == data for name, data in original.items())


def test_existing_output_is_never_overwritten(repo, tmp_path):
    root, sha = repo
    output = tmp_path / 'existing.zip'
    output.write_bytes(b'USER_OWNED')
    assert release.main(['--root', str(root), '--sha', sha, '--output', str(output)]) == 2
    assert output.read_bytes() == b'USER_OWNED'


def test_preview_does_not_create_artifact_or_print_original_values(repo, capsys):
    root, sha = repo
    before = set(root.iterdir())
    assert release.main(['--root', str(root), '--sha', sha]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['status'] == 'PREVIEW'
    assert 'PRIVATE_' not in output and 'review_source.json' not in output
    assert set(root.iterdir()) == before


@pytest.mark.parametrize('path', ['/app/x.py', 'app/../private.py', 'app\\secret.py', 'webapp/tests/x.py', 'config/review_source.json'])
def test_unknown_or_indirect_paths_are_not_permitted(path):
    assert release.permitted(path) is False


def test_bad_sha_fails_closed_without_echo(repo, capsys):
    root, _ = repo
    assert release.main(['--root', str(root), '--sha', 'PRIVATE_VALUE']) == 2
    assert 'PRIVATE_VALUE' not in capsys.readouterr().out


def test_large_asset_exception_is_pinned_to_path_blob_and_size(monkeypatch, tmp_path):
    path = 'webapp/static/fonts/approved.woff2'
    entry = {'oid': 'a' * 40, 'size': 2000000, 'kind': 'blob', 'mode': '100644'}
    monkeypatch.setattr(release, 'load_policy', lambda _: {})
    monkeypatch.setattr(release, 'tree', lambda *args: {path: entry})
    monkeypatch.setattr(release, 'reasons', lambda *args: ['LARGE_BLOB'])
    monkeypatch.setattr(release, 'LICENSED_LARGE_ASSETS', {path: ('a' * 40, 2000000)})
    assert len(release.manifest(tmp_path, 'b' * 40)['included']) == 1
    entry['oid'] = 'c' * 40
    assert release.manifest(tmp_path, 'b' * 40)['included'] == []
    entry.update(oid='a' * 40, size=2000001)
    assert release.manifest(tmp_path, 'b' * 40)['included'] == []


def test_externally_preserved_blob_is_marked_outside_git_only_on_exact_blob(repo):
    root, _ = repo
    policy_path = root / 'config/tracked-data-policy.json'
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    oid = git(root, 'rev-parse', 'HEAD:outputs/private.sqlite').decode().strip()
    policy['externally_preserved'] = [{'archive': 'synthetic-archive', 'manifest_sha256': 'a' * 64, 'files': [
        {'path': 'outputs/private.sqlite', 'sha256': hashlib.sha256(b'PRIVATE_ORIGINAL').hexdigest(), 'git_blob': oid},
        {'path': 'ledger/data/source.json', 'sha256': 'b' * 64, 'git_blob': 'c' * 40}]}]
    policy_path.write_text(json.dumps(policy), encoding='utf-8')
    git(root, 'add', 'config/tracked-data-policy.json')
    git(root, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic preserved policy')
    report = release.manifest(root, git(root, 'rev-parse', 'HEAD').decode().strip())
    retention = {row['path']: row['retention'] for row in report['excluded']}
    assert retention['outputs/private.sqlite'] == 'PRESERVED_OUTSIDE_GIT'
    assert retention['ledger/data/source.json'] == 'PRESERVE_IN_ORIGINAL_REPOSITORY'
    assert 'outputs/private.sqlite' not in {row['path'] for row in report['included']}


def test_ledger_package_code_is_preserved_but_embedded_data_code_is_excluded(repo):
    root, _ = repo
    for name in ('ledger/__init__.py', 'ledger/data/original.py'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('VALUE = 1\n', encoding='utf-8')
    git(root, 'add', 'ledger')
    git(root, '-c', 'core.hooksPath=NUL', 'commit', '-qm', 'synthetic ledger sources')
    sha = git(root, 'rev-parse', 'HEAD').decode().strip()
    report = release.manifest(root, sha)
    assert 'ledger/__init__.py' in {item['path'] for item in report['included']}
    assert 'ledger/data/original.py' in {item['path'] for item in report['excluded']}
