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


def test_explicit_runtime_reference_classifies_only_with_existing_source_location(tmp_path):
    import hashlib, json, subprocess
    from tools.runtime_dependency_catalog import build_catalog
    bodies = {'tools/entry.py': 'pass\n', 'run_candidate.py': 'import tools.entry\n'}
    for name, body in bodies.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
    hashes = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in bodies}
    config = tmp_path / 'config' / 'runtime-dependency-evidence.json'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({'schema': 'runtime-dependency-evidence/v1', 'evidence': [{
        'path': 'tools/entry.py', 'classification': 'ACTIVE_SAFE_READ',
        'source': 'run_candidate.py', 'line': 1, 'reason': 'fixed launcher imports entry',
        'target_sha256': hashes['tools/entry.py'], 'source_sha256': hashes['run_candidate.py']}]}), encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    result = build_catalog(tmp_path)
    entry = next(row for row in result['entries'] if row['path'] == 'tools/entry.py')
    assert entry['classification'] == 'ACTIVE_SAFE_READ'
    assert 'run_candidate.py:1' in entry['evidence']


def test_active_write_guarded_requires_explicit_guard(tmp_path):
    import hashlib, json, subprocess
    from tools.runtime_dependency_catalog import load_evidence
    config = tmp_path / 'config' / 'runtime-dependency-evidence.json'
    config.parent.mkdir()
    contents = {'tools/a.py': 'pass\n', 'run_candidate.py': 'import tools.a\n'}
    for name, body in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    digests = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in contents}
    evidence = {'path': 'tools/a.py', 'source': 'run_candidate.py', 'line': 1,
        'classification': 'ACTIVE_WRITE_GUARDED', 'reason': 'verified controls', 'guard': True,
        'target_sha256': digests['tools/a.py'], 'source_sha256': digests['run_candidate.py']}
    config.write_text(json.dumps({'schema': 'runtime-dependency-evidence/v1',
        'evidence': [evidence, {**evidence, 'path': 'tools/b.py', 'guard': 'auth+backup'}]}), encoding='utf-8')
    assert set(load_evidence(tmp_path)) == {'tools/a.py'}


def test_evidence_fails_closed_for_malformed_paths_lines_and_nonreferences(tmp_path):
    import hashlib, json, subprocess
    from tools.runtime_dependency_catalog import load_evidence
    files = {'tools/entry.py': 'pass\n', 'run_candidate.py': 'print("tools/entry.py")\n'}
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    base = {'path': 'tools/entry.py', 'classification': 'ACTIVE_SAFE_READ',
            'source': 'run_candidate.py', 'reason': 'claim',
            'target_sha256': hashlib.sha256(files['tools/entry.py'].encode()).hexdigest(),
            'source_sha256': hashlib.sha256(files['run_candidate.py'].encode()).hexdigest()}
    for line in (0, -1, True, 1):
        config = tmp_path / 'config' / 'runtime-dependency-evidence.json'
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({'schema': 'runtime-dependency-evidence/v1',
            'evidence': [{**base, 'line': line}]}), encoding='utf-8')
        assert load_evidence(tmp_path) == {}
    config.write_text('[]', encoding='utf-8')
    assert load_evidence(tmp_path) == {}
    config.write_text(json.dumps({'schema': 'runtime-dependency-evidence/v1',
        'evidence': [{**base, 'line': 1, 'source': '../outside.py'}]}), encoding='utf-8')
    assert load_evidence(tmp_path) == {}


def test_write_guard_is_not_freeform_and_source_digest_is_binding(tmp_path):
    import hashlib, json, subprocess
    from tools.runtime_dependency_catalog import load_evidence
    bodies = {'tools/write.py': 'pass\n', 'run_candidate.py': 'import tools.write\n'}
    for name, body in bodies.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    config = tmp_path / 'config' / 'runtime-dependency-evidence.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'schema': 'runtime-dependency-evidence/v1', 'evidence': [{
        'path': 'tools/write.py', 'source': 'run_candidate.py', 'line': 1,
        'classification': 'ACTIVE_WRITE_GUARDED', 'reason': 'verified', 'guard': 'auth and backup',
        'target_sha256': hashlib.sha256((tmp_path / 'tools/write.py').read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256((tmp_path / 'run_candidate.py').read_bytes()).hexdigest()}]}), encoding='utf-8')
    assert load_evidence(tmp_path) == {}


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
