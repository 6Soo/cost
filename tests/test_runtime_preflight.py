import json
from pathlib import Path

from tools.runtime_preflight import check, validate_args


def fixture_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ops_entrypoints.json").write_text(json.dumps({
        "schema_version": 1,
        "entrypoints": [{"path": "tools/read.py", "guard": "read_only", "source_data": False}],
    }), encoding="utf-8")
    return tmp_path


def test_preflight_requires_absolute_data_root_and_feature_flags_stay_out():
    assert "data_root_unset" in check(env={})["checks"]
    assert "data_root_not_absolute" in check(env={"COST_DATA_ROOT": "relative"})["checks"]
    ready = check(env={"COST_DATA_ROOT": "C:/synthetic"})
    assert ready["status"] == "READY"
    assert ready["metadata_only"] is True


def test_preflight_classifies_duplicate_and_source_paths(tmp_path):
    root = fixture_root(tmp_path)
    manifest = json.loads((root / "config" / "ops_entrypoints.json").read_text())
    manifest["entrypoints"].append({"path": "TOOLS/READ.PY", "guard": "unknown", "source_data": True})
    (root / "config" / "ops_entrypoints.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = check(root, env={"COST_DATA_ROOT": "C:/synthetic"})
    assert {"duplicate_entrypoint", "unclassified_guard", "source_data_not_excluded"} <= set(result["checks"])


def test_preflight_detects_secret_env_presence_without_disclosing_value(tmp_path):
    result = check(fixture_root(tmp_path), env={"COST_DATA_ROOT": "C:/synthetic", "API_TOKEN": "sentinel"})
    assert result["checks"] == ["secret_environment_present"]
    assert "sentinel" not in json.dumps(result)


def test_live_and_preflight_cli_flags_conflict():
    try:
        validate_args(["--live", "--preflight"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("conflicting invocation accepted")
