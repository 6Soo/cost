import json
from pathlib import Path
import subprocess

from tools.runtime_preflight import check, validate_args


def fixture_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ops_entrypoints.json").write_text(json.dumps({
        "schema_version": 1,
        "data_root_env": "WEBLEDGER_DATA_ROOT",
        "secret_handling": {"model": "runtime_file_arguments",
                            "entrypoint": "tools/launch_web_ledger.py",
                            "arguments": ["--oauth-file", "--session-secret-file"],
                            "preflight_reads_secret_values": False},
        "entrypoints": [
            {"path": "tools/read.py", "guard": "read_only"},
            {"path": "tools/launch_web_ledger.py", "guard": "protected_write"},
        ],
    }), encoding="utf-8")
    (tmp_path / "config" / "tracked-data-policy.json").write_text(json.dumps({
        "schema_version": 1, "protected_prefixes": ["customer/"],
        "denied_names": ["*.pem"], "data_extensions": [".sqlite"],
        "synthetic_allowlist": [], "max_blob_bytes": 100000,
    }), encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "read.py").write_text("# synthetic", encoding="utf-8")
    (tmp_path / "tools" / "launch_web_ledger.py").write_text("# synthetic", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "config", "tools"], cwd=tmp_path, check=True)
    return tmp_path


def test_preflight_requires_absolute_data_root_and_feature_flags_stay_out(tmp_path):
    root = fixture_root(tmp_path)
    assert "data_root_unset" in check(root, env={})["checks"]
    assert "data_root_not_absolute" in check(root, env={"WEBLEDGER_DATA_ROOT": "relative"})["checks"]
    ready = check(root, env={"WEBLEDGER_DATA_ROOT": "C:/synthetic"})
    assert ready["status"] == "READY"
    assert ready["metadata_only"] is True
    assert ready["inventory_source"] == "git_index_and_tracked_data_policy"


def test_preflight_classifies_duplicate_and_source_paths(tmp_path):
    root = fixture_root(tmp_path)
    manifest = json.loads((root / "config" / "ops_entrypoints.json").read_text())
    manifest["entrypoints"].append({"path": "tools/read.py", "guard": "unknown"})
    (root / "config" / "ops_entrypoints.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = check(root, env={"WEBLEDGER_DATA_ROOT": "C:/synthetic"})
    assert {"duplicate_entrypoint", "unclassified_guard"} <= set(result["checks"])


def test_preflight_does_not_block_normal_secret_environment(tmp_path):
    result = check(fixture_root(tmp_path), env={"WEBLEDGER_DATA_ROOT": "C:/synthetic",
                                                "WEBLEDGER_GOOGLE_CLIENT_SECRET": "sentinel"})
    assert result["status"] == "READY"
    assert "sentinel" not in json.dumps(result)


def test_preflight_parser_has_explicit_mode():
    try:
        validate_args(["--unknown-mode"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("unknown invocation accepted")


def test_invalid_schema_paths_and_alias_types_fail_closed(tmp_path):
    root = fixture_root(tmp_path)
    path = root / "config" / "ops_entrypoints.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 2
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "invalid_manifest_schema" in check(root, env={})["checks"]

    manifest["schema_version"] = 1
    manifest["entrypoints"][0]["path"] = "C:\\tools\\read.py"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "unsafe_entry_path" in check(root, env={})["checks"]

    manifest["entrypoints"][0]["path"] = "tools/read.py"
    manifest["entrypoints"][0]["aliases"] = "not-a-list"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "invalid_alias_contract" in check(root, env={})["checks"]


def test_tracked_data_policy_exclusions_apply_to_release_paths(tmp_path):
    root = fixture_root(tmp_path)
    protected = root / "customer"
    protected.mkdir()
    source = protected / "export.sqlite"
    source.write_text("synthetic", encoding="utf-8")
    subprocess.run(["git", "add", "customer/export.sqlite"], cwd=root, check=True)
    path = root / "config" / "ops_entrypoints.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["entrypoints"][0]["path"] = "customer/export.sqlite"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = check(root, env={})
    assert "entrypoint_excluded_by_data_policy" in result["checks"]


def test_secret_file_preflight_checks_metadata_only(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    root = fixture_root(checkout)
    secret_dir = tmp_path / "outside-secrets"
    secret_dir.mkdir()
    oauth = secret_dir / "oauth.json"
    session = secret_dir / "session.txt"
    oauth.write_text("synthetic secret content", encoding="utf-8")
    session.write_text("synthetic secret content", encoding="utf-8")
    result = check(root, env={"WEBLEDGER_DATA_ROOT": "C:/synthetic"},
                   oauth_file=str(oauth), session_secret_file=str(session))
    assert result["status"] == "READY"
    assert result["secret_file_metadata_checks"] == 2
    assert "synthetic secret content" not in json.dumps(result)


def test_secret_file_preflight_rejects_relative_and_incomplete_arguments(tmp_path):
    root = fixture_root(tmp_path)
    assert "incomplete_secret_file_pair" in check(root, env={}, oauth_file="relative")["checks"]
    result = check(root, env={}, oauth_file="relative", session_secret_file="relative")
    assert "secret_file_path_not_absolute" in result["checks"]
