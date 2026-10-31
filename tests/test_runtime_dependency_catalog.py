from pathlib import Path

from tools.runtime_dependency_catalog import build_catalog, classify, tracked_paths


def test_catalog_only_uses_git_tracked_candidate_paths(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tools").mkdir()
    tracked = tmp_path / "tools" / "entry.ps1"
    tracked.write_text("Write-Output synthetic", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("secret = 'never read'", encoding="utf-8")
    subprocess.run(["git", "add", "tools/entry.ps1"], cwd=tmp_path, check=True)
    assert tracked_paths(tmp_path) == [tracked]


def test_classification_does_not_claim_active_from_name_alone(tmp_path):
    path = tmp_path / "tools" / "deploy_old.py"
    path.parent.mkdir()
    category, _, _ = classify(path, "# no runtime evidence")
    assert category in {"HISTORICAL", "UNKNOWN"}


def test_fixture_paths_are_labeled_as_fixtures(tmp_path):
    path = tmp_path / "tests" / "fixture.ps1"
    category, _, confidence = classify(path, "Write-Output synthetic")
    assert category == "TEST_FIXTURE"
    assert confidence >= 0.9


def test_catalog_emits_only_locations_for_source_references():
    catalog = build_catalog()
    for entry in catalog["entries"]:
        for ref in entry["references"]:
            assert set(ref) == {"source", "line"}
    assert catalog["open_questions"]


def test_external_root_relative_imports_and_fixture_inventory(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    sources = {'app/db.py': 'value = 1', 'app/service.py': 'from .db import value',
               'webapp/cards.py': 'from . import transactions', 'webapp/transactions.py': 'value = 1',
               'tests/test_service.py': 'from app import service',
               'tools/entry.py': '# deploy CUSTOMER_SENTINEL\ntext = "delete CUSTOMER_SENTINEL"'}
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    result = build_catalog(tmp_path)
    rows = {x['path']: x for x in result['entries']}
    assert result['errors'] == []
    assert [x['target'] for x in rows['app/service.py']['dependencies']] == ['app/db.py']
    assert [x['target'] for x in rows['webapp/cards.py']['dependencies']] == ['webapp/transactions.py']
    assert rows['tests/test_service.py']['classification'] == 'TEST_FIXTURE'
    assert rows['tools/entry.py']['classification'] == 'UNKNOWN'
    import json
    assert 'CUSTOMER_SENTINEL' not in json.dumps(result)


def test_no_active_claim_from_process_call_or_comment(tmp_path):
    for source in ('# deploy delete', 'subprocess.run(["synthetic"])', 'conn.commit()'):
        assert classify(tmp_path / 'tools' / 'entry.py', source, tmp_path)[0] == 'UNKNOWN'


def test_unknown_is_retained_without_a_promotion_config():
    assert classify(Path('tools/entry.py'), 'import subprocess\nsubprocess.run(["python", "x.py"])')[0] == 'UNKNOWN'


def test_missing_broken_and_invalid_utf8_are_diagnostics(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    folder = tmp_path / 'tools'
    folder.mkdir()
    for name in ('missing.py', 'broken.py', 'encoding.py'):
        (folder / name).write_text('pass', encoding='utf-8')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    (folder / 'missing.py').unlink()
    (folder / 'broken.py').write_text('def broken(:\n', encoding='utf-8')
    (folder / 'encoding.py').write_bytes(b'\xff')
    result = build_catalog(tmp_path)
    assert {x['code'] for x in result['errors']} == {'SOURCE_READ_ERROR', 'SYNTAX_ERROR'}
    assert len(result['errors']) == 3


def test_all_reference_locations_retained_without_silent_cap(tmp_path):
    from tools.runtime_dependency_catalog import refs
    assert len(refs(tmp_path / 'entry.py', '\n'.join('# worker' for _ in range(45)), tmp_path)) == 45
