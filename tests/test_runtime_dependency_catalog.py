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
