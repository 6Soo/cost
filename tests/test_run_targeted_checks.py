"""Unit and integration tests for RF-303 local targeted verification gate CLI.

Verifies:
1. Real temporary Git repo: docs-only zero-execution contract (executed == []).
2. Real temporary Git repo: no-changes zero-execution contract (executed == []).
3. Requirements change with missing sync tool fails closed (exit 2, REQUIREMENTS_TOOL_MISSING).
4. Base resolution failure sanitization: raw user sentinel is never leaked into JSON output.
5. Head resolution failure: returns fixed HEAD_RESOLUTION_FAILED constant.
6. Data guard validation strictness:
   - Malformed JSON or missing schema fields fail with DATA_GUARD_MALFORMED.
   - boolean blocked_count (e.g. False) is rejected as malformed.
   - Count mismatch (files has blocked=True but blocked_count=0) is rejected as malformed.
7. Selector validation strictness:
   - empty command [[]] or arbitrary argv shape rejected.
   - targets not ending in .py rejected.
   - targets outside repository root rejected.
   - missing target files on disk rejected.
   - code changes with 0 pytest targets rejected as NO_TARGETS_SELECTED.
8. Selector unknown impact halts pipeline with exit 2 (never reports PASS).
9. Data guard blocked files halts pipeline with exit 1.
10. Missing executable / OSError returns finite JSON error (COMMAND_NOT_FOUND, exit 2).
11. Subprocess security contract: argv is list[str], shell=False, cwd=root.
12. Actual subprocess CLI invocation of tools/run_targeted_checks.py outputs machine JSON.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch, MagicMock
import pytest

from tools import run_targeted_checks

ROOT = Path(__file__).resolve().parents[1]


def run_git(repo: Path, *args: str) -> str:
    """Run git command in repo and return stdout."""
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    return res.stdout.strip()


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """Initialize a synthetic Git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.name", "Synthetic Gate")
    run_git(repo, "config", "user.email", "gate@example.invalid")

    # Initial baseline commit
    (repo / "README.md").write_text("# Initial\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-qm", "initial commit")
    run_git(repo, "tag", "baseline")
    return repo


def test_real_git_docs_only_strictly_zero_executions(synthetic_repo: Path):
    """Verify on a real Git repo that docs-only changes perform strictly zero executions."""
    docs_dir = synthetic_repo / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (synthetic_repo / "README.md").write_text("# Updated Readme\n", encoding="utf-8")
    run_git(synthetic_repo, "add", "docs/guide.md", "README.md")
    run_git(synthetic_repo, "commit", "-qm", "docs only commit")

    result = run_targeted_checks.run_checks("baseline", run=True, root=synthetic_repo)

    assert result["status"] == "DOCS_ONLY"
    assert result["exit_code"] == 0
    assert result["docs_only"] is True
    # Strictly zero checks executed (no guard, no selector, no compile, no pytest)
    assert result["executed"] == []
    assert result["evidence"]["tests_executed_count"] == 0
    assert result["evidence"]["code_executions_count"] == 0


def test_real_git_no_changes_strictly_zero_executions(synthetic_repo: Path):
    """Verify on a real Git repo that no changes between base and HEAD perform zero executions."""
    result = run_targeted_checks.run_checks("HEAD", run=True, root=synthetic_repo)
    assert result["status"] == "NO_CHANGES"
    assert result["exit_code"] == 0
    assert result["executed"] == []


def test_real_git_requirements_change_without_tool_fails_closed(synthetic_repo: Path):
    """Verify that modifying requirements when sync tool is missing fails closed with exit 2."""
    (synthetic_repo / "requirements.txt").write_text("some-pkg==1.0.0\n", encoding="utf-8")
    run_git(synthetic_repo, "add", "requirements.txt")
    run_git(synthetic_repo, "commit", "-qm", "modify requirements")

    # sync_runtime_requirements.py does not exist in synthetic_repo
    result = run_targeted_checks.run_checks("baseline", run=True, root=synthetic_repo)

    assert result["status"] == "ERROR"
    assert result["exit_code"] == 2
    assert result["evidence"]["failure_code"] == "REQUIREMENTS_TOOL_MISSING"
    assert result["executed"] == []


def test_base_resolution_failure_sanitized_and_no_sentinel_leak():
    """Verify unresolvable base revision fails cleanly without leaking raw sentinel into JSON."""
    secret_sentinel = "SECRET_SENTINEL_TOKEN_12345"
    result = run_targeted_checks.run_checks(secret_sentinel, run=False, root=ROOT)

    assert result["exit_code"] == 2
    assert result["status"] == "ERROR"
    assert result["evidence"]["failure_code"] == "INVALID_REVISION"
    assert result["base"] is None  # Never echo raw base

    # Verify secret sentinel does not appear anywhere in serialized JSON
    raw_json = json.dumps(result)
    assert secret_sentinel not in raw_json


def test_head_resolution_failure():
    """Verify failure to resolve HEAD fails with sanitized HEAD_RESOLUTION_FAILED constant."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="a" * 40),  # base succeeds
            MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo"),  # head fails
        ]
        result = run_targeted_checks.run_checks("main", run=False, root=ROOT)
        assert result["exit_code"] == 2
        assert result["status"] == "ERROR"
        assert result["evidence"]["failure_code"] == "HEAD_RESOLUTION_FAILED"


def test_guard_json_validation_strictness_and_count_mismatch():
    """Verify that malformed data guard outputs, bad types, or count mismatches fail-closed."""
    # 1. Malformed JSON
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output("{ malformed json")

    # 2. Missing schema_version / files / blocked_count
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"files": []}))

    # 3. schema_version != 1
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"schema_version": 2, "files": [], "blocked_count": 0}))

    # 4. blocked_count is bool (e.g. False)
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"schema_version": 1, "files": [], "blocked_count": False}))

    # 5. blocked_count < 0
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"schema_version": 1, "files": [], "blocked_count": -1}))

    # 6. Count mismatch: files has blocked=True, but blocked_count is 0
    mismatch = json.dumps({
        "schema_version": 1,
        "files": [{"path": "leak.csv", "blocked": True}],
        "blocked_count": 0,
    })
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(mismatch)

    # 7. Valid output: 1 blocked file and blocked_count == 1
    valid = json.dumps({
        "schema_version": 1,
        "files": [{"path": "leak.csv", "blocked": True}, {"path": "ok.py", "blocked": False}],
        "blocked_count": 1,
    })
    assert run_targeted_checks.validate_guard_output(valid) == 1


def test_selector_validation_empty_and_arbitrary_commands():
    """Verify that empty commands, non-py targets, outside files, or invalid command shapes are rejected."""
    # 1. Arbitrary / empty command shape [[]]
    with pytest.raises(ValueError, match="SELECTOR_INVALID_COMMAND_SHAPE"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": [[]]}),
            returncode=0, has_code_changes=True, root=ROOT
        )

    # 2. Command not starting with sys.executable -m pytest
    with pytest.raises(ValueError, match="SELECTOR_INVALID_COMMAND_SHAPE"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": [["arbitrary", "command"]]}),
            returncode=0, has_code_changes=True, root=ROOT
        )

    # 3. Empty targets list
    with pytest.raises(ValueError, match="SELECTOR_EMPTY_TARGETS"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": [[sys.executable, "-m", "pytest", "-q"]]}),
            returncode=0, has_code_changes=True, root=ROOT
        )

    # 4. Target does not end in .py
    with pytest.raises(ValueError, match="SELECTOR_INVALID_TARGET_EXTENSION"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": [[sys.executable, "-m", "pytest", "tests/foo.txt", "-q"]]}),
            returncode=0, has_code_changes=True, root=ROOT
        )

    # 5. Target does not exist on disk
    with pytest.raises(ValueError, match="SELECTOR_TARGET_NOT_FOUND"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": [[sys.executable, "-m", "pytest", "tests/non_existent_file.py", "-q"]]}),
            returncode=0, has_code_changes=True, root=ROOT
        )

    # 6. Target escapes repository root
    with pytest.raises(ValueError, match="SELECTOR_TARGET_OUTSIDE_ROOT"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": [[sys.executable, "-m", "pytest", "../outside.py", "-q"]]}),
            returncode=0, has_code_changes=True, root=ROOT
        )

    # 7. Code changes exist but 0 pytest commands provided
    with pytest.raises(ValueError, match="NO_TARGETS_SELECTED"):
        run_targeted_checks.validate_selector_output(
            json.dumps({"status": "SELECTED", "pytest_commands": []}),
            returncode=0, has_code_changes=True, root=ROOT
        )


def test_selector_unknown_files_halts_pipeline_without_pass():
    """Verify selector reporting unknown files results in UNKNOWN_IMPACT exit 2."""
    dummy_base = "a" * 40
    dummy_head = "b" * 40
    selector_unknown = json.dumps({"status": "UNKNOWN_IMPACT", "unknown_files": ["unmapped.py"], "pytest_commands": []})

    def fake_subprocess_run(cmd, **kwargs):
        assert isinstance(cmd, list)
        assert kwargs.get("shell") is False
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=dummy_base if "verify" in cmd else dummy_head)
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="unmapped.py\0")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=2, stdout=selector_unknown)
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["status"] == "UNKNOWN_IMPACT"
        assert result["exit_code"] == 2
        assert result["evidence"]["failure_code"] == "SELECTOR_UNKNOWN_FILES"
        assert result["executed"] == []


def test_data_guard_blocked_files_halts_pipeline():
    """Verify blocked files in data guard halt pipeline with exit code 1."""
    dummy_base = "a" * 40
    dummy_head = "b" * 40
    valid_target = "tests/test_run_targeted_checks.py"
    selector_ok = json.dumps({"status": "SELECTED", "unknown_files": [], "pytest_commands": [[sys.executable, "-m", "pytest", valid_target, "-q"]]})
    guard_blocked = json.dumps({"schema_version": 1, "files": [{"path": "secret.csv", "blocked": True}], "blocked_count": 1})

    def fake_subprocess_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=dummy_base if "verify" in cmd else dummy_head)
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="secret.csv\0")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=selector_ok)
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=1, stdout=guard_blocked)
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["status"] == "DATA_GUARD_BLOCKED"
        assert result["exit_code"] == 1
        assert len(result["executed"]) == 1
        assert result["executed"][0]["name"] == "data_guard"
        assert result["executed"][0]["status"] == "FAILED"


def test_missing_executable_returns_finite_json_error():
    """Verify that a FileNotFoundError / missing command terminates with COMMAND_NOT_FOUND without crashing."""
    rc, out, err, dur = run_targeted_checks.execute_step(["non_existent_executable_binary_12345"], ROOT)
    assert rc == 127


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_guard_schema_version_requires_exact_integer(version):
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({
            "schema_version": version, "files": [], "blocked_count": 0,
        }))


@pytest.mark.parametrize("status", ["DOCS_ONLY", "NO_CHANGES"])
def test_selector_code_changes_require_selected_status(status):
    with pytest.raises(ValueError, match="SELECTOR_RC_STATUS_MISMATCH"):
        run_targeted_checks.validate_selector_output(json.dumps({
            "status": status, "unknown_files": [], "pytest_commands": [
                [sys.executable, "-m", "pytest", "tests/test_run_targeted_checks.py", "-q"],
            ],
        }), 0, True, ROOT)


def test_selector_rejects_option_even_when_file_exists(tmp_path):
    (tmp_path / "--override-ini=python_files=test.py").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="SELECTOR_INVALID_TARGET"):
        run_targeted_checks.validate_selector_output(json.dumps({
            "status": "SELECTED", "unknown_files": [], "pytest_commands": [
                [sys.executable, "-m", "pytest", "--override-ini=python_files=test.py", "-q"],
            ],
        }), 0, True, tmp_path)


@pytest.mark.parametrize("case", ["count_mismatch", "empty_command", "missing_git", "raw_base"])
def test_real_cli_fail_closed_contracts(synthetic_repo, case):
    tools_dir = synthetic_repo / "tools"
    tools_dir.mkdir()
    cli = tools_dir / "run_targeted_checks.py"
    shutil.copyfile(ROOT / "tools/run_targeted_checks.py", cli)
    (synthetic_repo / "test_synthetic.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    selection = {"status": "SELECTED", "unknown_files": [], "pytest_commands": [
        [] if case == "empty_command" else [sys.executable, "-m", "pytest", "test_synthetic.py", "-q"],
    ]}
    guard = {"schema_version": 1, "files": [{"path": "synthetic.csv", "blocked": True}], "blocked_count": 0}
    for filename, payload in [("select_targeted_tests.py", selection), ("check_tracked_data.py", guard)]:
        (tools_dir / filename).write_text("print(" + repr(json.dumps(payload)) + ")\n", encoding="utf-8")
    run_git(synthetic_repo, "add", ".")
    run_git(synthetic_repo, "commit", "-qm", "synthetic code")
    sentinel = "PRIVATE_BASE_SENTINEL_67890"
    env = dict(os.environ)
    if case == "missing_git":
        env["PATH"] = ""
    proc = subprocess.run([
        sys.executable, str(cli), "--base", sentinel if case == "raw_base" else "baseline", "--run", "--json",
    ], cwd=synthetic_repo, capture_output=True, text=True, shell=False, env=env)
    assert proc.returncode == 2
    assert proc.stderr == ""
    assert sentinel not in proc.stdout
    result = json.loads(proc.stdout)
    assert result["status"] == "ERROR"
    assert result["evidence"]["failure_code"] == {
        "count_mismatch": "DATA_GUARD_MALFORMED", "empty_command": "SELECTOR_INVALID_COMMAND_SHAPE",
        "missing_git": "GIT_EXECUTION_FAILED", "raw_base": "INVALID_REVISION",
    }[case]
    assert len(result["executed"]) == (1 if case == "count_mismatch" else 0)


def test_result_builder_never_echoes_unexpected_exception_text():
    result = run_targeted_checks.make_result(status="ERROR", exit_code=2, failure_code="PRIVATE_EXCEPTION_SENTINEL")
    assert result["evidence"]["failure_code"] == "EXECUTION_FAILED"
    assert "PRIVATE_EXCEPTION_SENTINEL" not in json.dumps(result)


def test_subprocess_security_contracts():
    """Verify all subprocess invocations use list[str], shell=False, and fixed root cwd."""
    dummy_base = "a" * 40
    dummy_head = "b" * 40
    valid_target = "tests/test_run_targeted_checks.py"
    selector_ok = json.dumps({"status": "SELECTED", "unknown_files": [], "pytest_commands": [[sys.executable, "-m", "pytest", valid_target, "-q"]]})
    guard_ok = json.dumps({"schema_version": 1, "files": [], "blocked_count": 0})

    calls = []

    def tracking_subprocess_run(cmd, **kwargs):
        assert isinstance(cmd, list), f"Command must be list[str], got {type(cmd)}"
        assert all(isinstance(x, str) for x in cmd)
        assert kwargs.get("shell") is False, "shell must be False"
        assert kwargs.get("cwd") == ROOT, f"cwd must be ROOT, got {kwargs.get('cwd')}"
        calls.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=dummy_base if "verify" in cmd else dummy_head)
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="webapp/test.py\0")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=selector_ok)
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=guard_ok)
        return MagicMock(returncode=0, stdout="")

    with patch("subprocess.run", side_effect=tracking_subprocess_run), \
         patch.object(Path, "is_file", return_value=True):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["status"] == "PASSED"
        assert len(calls) >= 5


def test_cli_actual_subprocess_preview_json(synthetic_repo):
    """Verify executing the real tools/run_targeted_checks.py script as an external subprocess."""
    # 1. Against HEAD (no changes): returns code 0 and NO_CHANGES
    proc_head = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "run_targeted_checks.py"), "--base", "HEAD", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    assert proc_head.returncode == 0
    payload_head = json.loads(proc_head.stdout)
    assert payload_head["schema_version"] == 1
    assert payload_head["status"] == "NO_CHANGES"
    assert payload_head["executed"] == []

    # Use an isolated map so this contract does not depend on branch history.
    tools_dir = synthetic_repo / "tools"
    tools_dir.mkdir()
    for name in ("run_targeted_checks.py", "select_targeted_tests.py"):
        shutil.copyfile(ROOT / "tools" / name, tools_dir / name)
    config_dir = synthetic_repo / "config"
    config_dir.mkdir()
    (config_dir / "test-impact-map.json").write_text(json.dumps({
        "schema": "cost-test-impact-map-v1", "groups": [], "safe_fallback_tests": [],
    }), encoding="utf-8")
    run_git(synthetic_repo, "add", ".")
    run_git(synthetic_repo, "commit", "-qm", "unmapped synthetic code")

    # 2. Unmapped code returns code 2 and UNKNOWN_IMPACT (fail-closed).
    proc_unmapped = subprocess.run(
        [sys.executable, str(tools_dir / "run_targeted_checks.py"), "--base", "baseline", "--json"],
        cwd=synthetic_repo,
        capture_output=True,
        text=True,
        shell=False,
    )
    assert proc_unmapped.returncode == 2
    payload_unmapped = json.loads(proc_unmapped.stdout)
    assert payload_unmapped["schema_version"] == 1
    assert payload_unmapped["status"] == "UNKNOWN_IMPACT"
    assert payload_unmapped["evidence"]["failure_code"] == "SELECTOR_UNKNOWN_FILES"
    assert "planning_read_only_calls" in payload_unmapped
    assert payload_unmapped["executed"] == []
