"""Unit and integration tests for RF-303 local targeted verification gate CLI.

Verifies:
1. Real temporary Git repo: docs-only zero-execution contract (executed == []).
2. Real temporary Git repo: no-changes zero-execution contract (executed == []).
3. Requirements change with missing sync tool fails closed (exit 2, REQUIREMENTS_TOOL_MISSING).
4. Base and HEAD resolution failure (invalid revision or malformed SHA).
5. Strict Data guard validation: malformed JSON or missing schema fails (DATA_GUARD_MALFORMED).
6. Strict Selector validation: unmapped code changes without targets fail (NO_TARGETS_SELECTED).
7. Selector unknown impact halts pipeline with exit 2 (never reports PASS).
8. Data guard blocked files halts pipeline with exit 1.
9. Subprocess security contract: argv is list[str], shell=False, cwd=root.
10. Actual subprocess CLI invocation of tools/run_targeted_checks.py outputs machine JSON.
"""
from __future__ import annotations

import json
from pathlib import Path
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
    # Commit docs-only changes
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


def test_base_resolution_failure_sanitized_error():
    """Verify unresolvable base revision fails cleanly without leaking raw git stderr."""
    result = run_targeted_checks.run_checks("non_existent_revision_xyz_123", run=False, root=ROOT)
    assert result["exit_code"] == 2
    assert result["status"] == "ERROR"
    assert result["evidence"]["failure_code"] == "BASE_RESOLUTION_FAILED:INVALID_REVISION"
    assert result["base_sha"] is None


def test_head_resolution_failure():
    """Verify failure to resolve HEAD fails with sanitized HEAD_RESOLUTION_FAILED."""
    non_git_dir = ROOT / "non_existent_dir_abc"
    with patch("subprocess.run") as mock_run:
        # base succeeds, but head fails
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="a" * 40),
            MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo"),
        ]
        result = run_targeted_checks.run_checks("main", run=False, root=ROOT)
        assert result["exit_code"] == 2
        assert result["status"] == "ERROR"
        assert "HEAD_RESOLUTION_FAILED" in result["evidence"]["failure_code"]


def test_guard_json_validation_strictness():
    """Verify that malformed data guard outputs or bad blocked_count fail-closed."""
    # Malformed JSON
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output("{ not json")

    # Missing schema_version / files / blocked_count
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"files": []}))

    # Negative or non-integer blocked count
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"schema_version": 1, "files": [], "blocked_count": -1}))
    with pytest.raises(ValueError, match="DATA_GUARD_MALFORMED"):
        run_targeted_checks.validate_guard_output(json.dumps({"schema_version": 1, "files": [], "blocked_count": "zero"}))

    # Valid output
    valid = json.dumps({"schema_version": 1, "files": [], "blocked_count": 0})
    assert run_targeted_checks.validate_guard_output(valid) == 0


def test_selector_validation_no_targets_on_code_change_fails():
    """Verify that code changes with 0 pytest commands are rejected as NO_TARGETS_SELECTED."""
    empty_targets_json = json.dumps({"status": "SELECTED", "unknown_files": [], "pytest_commands": []})
    with pytest.raises(ValueError, match="NO_TARGETS_SELECTED"):
        run_targeted_checks.validate_selector_output(empty_targets_json, returncode=0, has_code_changes=True)


def test_selector_validation_unknown_impact():
    """Verify that unknown impact status and returncode 2 are validated cleanly."""
    unknown_json = json.dumps({"status": "UNKNOWN_IMPACT", "unknown_files": ["foo.py"], "pytest_commands": []})
    status, unknown, cmds = run_targeted_checks.validate_selector_output(unknown_json, returncode=2, has_code_changes=True)
    assert status == "UNKNOWN_IMPACT"
    assert unknown == ["foo.py"]
    assert cmds == []


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
        assert result["executed"] == []  # Halted during planning


def test_data_guard_blocked_files_halts_pipeline():
    """Verify blocked files in data guard halt pipeline with exit code 1."""
    dummy_base = "a" * 40
    dummy_head = "b" * 40
    selector_ok = json.dumps({"status": "SELECTED", "unknown_files": [], "pytest_commands": [["pytest", "tests/t.py"]]})
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


def test_subprocess_security_contracts():
    """Verify all subprocess invocations use list[str], shell=False, and fixed root cwd."""
    dummy_base = "a" * 40
    dummy_head = "b" * 40
    selector_ok = json.dumps({"status": "SELECTED", "unknown_files": [], "pytest_commands": [["pytest", "tests/test_t.py"]]})
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
        assert len(calls) >= 5  # rev-parse base, rev-parse head, diff, selector, guard, compile, pytest


def test_cli_actual_subprocess_preview_json():
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

    # 2. Against HEAD~1 (new tool/test files not in impact map): returns code 2 and UNKNOWN_IMPACT (fail-closed)
    proc_unmapped = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "run_targeted_checks.py"), "--base", "HEAD~1", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    assert proc_unmapped.returncode == 2
    payload_unmapped = json.loads(proc_unmapped.stdout)
    assert payload_unmapped["schema_version"] == 1
    assert payload_unmapped["status"] == "UNKNOWN_IMPACT"
    assert payload_unmapped["evidence"]["failure_code"] == "SELECTOR_UNKNOWN_FILES"
    assert "tests/test_run_targeted_checks.py" in payload_unmapped["evidence"]["selector_unknown_files"]
    assert "planning_read_only_calls" in payload_unmapped
    assert payload_unmapped["executed"] == []
