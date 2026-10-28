"""Unit tests for RF-303 local targeted verification gate CLI (tools/run_targeted_checks.py).

Verifies orchestration contracts using stubbed subprocess calls:
1. Docs-only diff: code compile / pytest execution count is strictly 0, success exit 0.
2. Preview mode (default without --run): generates plan without executing any checks.
3. Unknown selector impact: unmapped files halt pipeline with nonzero exit (never reported as PASS).
4. Selector error: selector failure halts pipeline with exit code 2.
5. Data guard failure: blocked tracked data stops pipeline with exit code 1.
6. Python compile failure: syntax error in changed file halts pipeline with exit code 1 before pytest.
7. Pytest failure: test failure records failed evidence and exits 1.
8. Full successful orchestration: data_guard -> compile -> targeted tests pass with exit 0.
9. Requirements sync drift: requirements declaration drift halts pipeline with exit code 1.
10. CLI validation: missing base or unresolvable git revision exits cleanly with code 2.
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
DUMMY_BASE = "0123456789abcdef0123456789abcdef01234567"
DUMMY_HEAD = "abcdef0123456789abcdef0123456789abcdef01"


def test_base_resolution_failure():
    """Verify that an invalid or unresolvable Git revision causes exit code 2."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: Needed a single revision")
        result = run_targeted_checks.run_checks("non_existent_revision", run=False, root=ROOT)
        assert result["exit_code"] == 2
        assert result["status"] == "ERROR"
        assert "fatal" in result["evidence"]["error"]


def test_preview_mode_generates_plan_with_zero_executions():
    """Verify that preview mode (run=False) constructs the execution plan but executes 0 checks."""
    changed = ["webapp/ledger_design.py", "docs/test.md"]
    selector_payload = {
        "status": "SELECTED",
        "unknown_files": [],
        "pytest_commands": [[sys.executable, "-m", "pytest", "tests/test_review_ui.py", "-q"]],
    }

    def fake_subprocess_run(cmd, **kwargs):
        assert isinstance(cmd, list), "Commands must be list of strings"
        assert kwargs.get("shell") is False, "shell must be False"
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(selector_payload), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = run_targeted_checks.run_checks("main", run=False, root=ROOT)
        assert result["exit_code"] == 0
        assert result["status"] == "PREVIEW"
        assert len(result["plan"]) > 0
        assert result["executed"] == []  # Strictly 0 executed checks
        assert result["evidence"]["changed_paths_count"] == 2


def test_docs_only_contract_strictly_zero_code_and_pytest_executions():
    """Verify that docs-only changes result in 0 compile, 0 pytest, and 0 browser executions."""
    docs_changed = ["docs/specs/finance.md", "README.md", "docs/operations.tsv"]
    selector_payload = {
        "status": "DOCS_ONLY",
        "unknown_files": [],
        "document_only_files": docs_changed,
        "pytest_commands": [],
    }

    executed_commands = []

    def fake_subprocess_run(cmd, **kwargs):
        assert isinstance(cmd, list)
        assert kwargs.get("shell") is False
        executed_commands.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(docs_changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps({"blocked_count": 0}), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(selector_payload), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 0
        assert result["status"] == "DOCS_ONLY"
        assert result["docs_only"] is True

        # Ensure no py_compile and no pytest was executed
        assert not any("py_compile" in str(cmd) for cmd in executed_commands)
        assert not any("pytest" in str(cmd) for cmd in executed_commands)
        assert result["evidence"]["tests_executed_count"] == 0
        assert result["evidence"]["code_paths_count"] == 0


def test_unknown_selector_impact_blocks_pipeline_and_exits_nonzero():
    """Verify that unmapped changed files halt pipeline immediately with code 2 and never report PASS."""
    changed = ["unknown_new_module.py"]
    selector_payload = {
        "status": "UNKNOWN_IMPACT",
        "unknown_files": ["unknown_new_module.py"],
        "fallback_selected": True,
        "pytest_commands": [[sys.executable, "-m", "pytest", "tests/test_safe_fallback.py", "-q"]],
    }

    executed_commands = []

    def fake_subprocess_run(cmd, **kwargs):
        executed_commands.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps({"blocked_count": 0}), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=2, stdout=json.dumps(selector_payload), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 2
        assert result["status"] == "UNKNOWN_IMPACT"
        assert "unknown_new_module.py" in result["evidence"]["selector_unknown_files"]
        # Ensure pytest was NOT executed
        assert not any("pytest" in str(cmd) for cmd in executed_commands if "select_targeted_tests" not in str(cmd))


def test_data_guard_failure_blocks_execution():
    """Verify that blocked files in data guard immediately halt execution with exit code 1."""
    changed = ["data/secret_dump.csv"]

    def fake_subprocess_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=1, stdout=json.dumps({"blocked_count": 1, "files": [{"path": "data/secret_dump.csv", "blocked": True}]}), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 1
        assert result["status"] == "DATA_GUARD_BLOCKED"
        assert "blocked file" in result["evidence"]["failure_reason"]


def test_python_compile_failure_blocks_pytest_execution():
    """Verify that a syntax error in changed Python file halts pipeline before pytest runs."""
    changed = ["webapp/broken.py"]
    selector_payload = {
        "status": "SELECTED",
        "unknown_files": [],
        "pytest_commands": [[sys.executable, "-m", "pytest", "tests/test_broken.py", "-q"]],
    }

    executed_commands = []

    def fake_subprocess_run(cmd, **kwargs):
        executed_commands.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps({"blocked_count": 0}), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(selector_payload), stderr="")
        if "py_compile" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="SyntaxError: invalid syntax")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch.object(Path, "is_file", return_value=True):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 1
        assert result["status"] == "COMPILE_FAILED"
        # Pytest must NOT have been executed
        assert not any("test_broken.py" in str(cmd) for cmd in executed_commands)


def test_pytest_failure_reports_failed_status_and_exit_nonzero():
    """Verify that a failing pytest target is reported as failure with exit code 1."""
    changed = ["webapp/logic.py"]
    selector_payload = {
        "status": "SELECTED",
        "unknown_files": [],
        "pytest_commands": [[sys.executable, "-m", "pytest", "tests/test_logic.py", "-q"]],
    }

    def fake_subprocess_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps({"blocked_count": 0}), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(selector_payload), stderr="")
        if "py_compile" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "test_logic.py" in str(cmd):
            return MagicMock(returncode=1, stdout="1 failed", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch.object(Path, "is_file", return_value=True):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 1
        assert result["status"] == "TESTS_FAILED"
        assert result["evidence"]["tests_executed_count"] == 1


def test_successful_full_orchestration():
    """Verify successful end-to-end orchestration passes and records all evidence cleanly."""
    changed = ["webapp/logic.py"]
    selector_payload = {
        "status": "SELECTED",
        "unknown_files": [],
        "pytest_commands": [[sys.executable, "-m", "pytest", "tests/test_logic.py", "-q"]],
    }

    def fake_subprocess_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps({"blocked_count": 0}), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(selector_payload), stderr="")
        if "py_compile" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "test_logic.py" in str(cmd):
            return MagicMock(returncode=0, stdout="1 passed", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch.object(Path, "is_file", return_value=True):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 0
        assert result["status"] == "PASSED"
        assert len(result["executed"]) >= 3  # data_guard, py_compile, pytest_batch_1
        assert all(step["status"] == "PASSED" for step in result["executed"])
        assert result["evidence"]["tests_executed_count"] == 1


def test_requirements_sync_drift_failure():
    """Verify that requirements drift halts pipeline when requirements.txt changes."""
    changed = ["requirements.txt"]
    selector_payload = {
        "status": "SELECTED",
        "unknown_files": [],
        "pytest_commands": [],
    }

    def fake_subprocess_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=DUMMY_BASE, stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="\0".join(changed), stderr="")
        if "check_tracked_data.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps({"blocked_count": 0}), stderr="")
        if "sync_runtime_requirements.py" in str(cmd):
            return MagicMock(returncode=1, stdout=json.dumps({"status": "DRIFT"}), stderr="")
        if "select_targeted_tests.py" in str(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(selector_payload), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch.object(Path, "is_file", return_value=True):
        result = run_targeted_checks.run_checks("main", run=True, root=ROOT)
        assert result["exit_code"] == 1
        assert result["status"] == "REQUIREMENTS_DRIFT"


def test_cli_main_entrypoint(capsys):
    """Verify CLI main entrypoint outputs valid JSON and correct exit code."""
    with patch("tools.run_targeted_checks.run_checks") as mock_run:
        mock_run.return_value = {
            "schema_version": 1,
            "status": "PREVIEW",
            "exit_code": 0,
            "plan": [],
            "executed": [],
            "evidence": {},
        }
        exit_code = run_targeted_checks.main(["--base", "HEAD~1", "--json"])
        assert exit_code == 0
        out, _ = capsys.readouterr()
        data = json.loads(out)
        assert data["status"] == "PREVIEW"
