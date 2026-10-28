"""Local targeted verification gate CLI (RF-303).

Orchestrates verification checks based on git diff against a required baseline:
1. Resolves base revision and HEAD to exact 40-hex commit SHAs (no raw base or unverified strings in output).
2. Identifies changed paths safely without exposing raw git stderr or customer text.
3. Enforces docs-only / no-changes contract: executed checks count is strictly 0.
4. Manages runtime requirements declaration sync (fail-closed if tool missing).
5. Queries targeted pytest targets via test-impact-map.json, recording planning calls.
6. Strictly validates data guard JSON schema, blocked count types, and item-count consistency (no fail-open).
7. Validates selector returncode, status consistency, and targets shape (code change requires valid targets).
8. Safely compiles changed Python files via py_compile without side-effects.
9. Executes targeted pytest batches.
10. Provides machine JSON output cleanly separating plan, planning_read_only_calls, executed, exit_code, and evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
FAILURE_CODES = frozenset({
    "INVALID_REVISION", "INVALID_SHA_FORMAT", "GIT_EXECUTION_FAILED",
    "HEAD_RESOLUTION_FAILED", "INVALID_HEAD_SHA_FORMAT", "GIT_DIFF_FAILED",
    "REQUIREMENTS_TOOL_MISSING", "REQUIREMENTS_DRIFT", "DATA_GUARD_MALFORMED",
    "DATA_GUARD_BLOCKED", "SELECTOR_PROCESS_FAILED", "SELECTOR_MALFORMED",
    "SELECTOR_RC_STATUS_MISMATCH", "SELECTOR_UNEXPECTED_STATUS",
    "SELECTOR_UNEXPECTED_UNKNOWN_FILES", "NO_TARGETS_SELECTED",
    "SELECTOR_INVALID_COMMAND_SHAPE", "SELECTOR_EMPTY_TARGETS",
    "SELECTOR_INVALID_TARGET_EXTENSION", "SELECTOR_INVALID_TARGET",
    "SELECTOR_TARGET_NOT_FOUND", "SELECTOR_TARGET_OUTSIDE_ROOT",
    "SELECTOR_UNKNOWN_FILES", "SELECTOR_ERROR", "COMMAND_NOT_FOUND",
    "EXECUTION_FAILED", "COMPILE_FAILED", "TESTS_FAILED",
})


def is_valid_sha(sha: str | None) -> bool:
    """Validate that sha is a 40-character hexadecimal string."""
    return bool(sha and SHA_RE.match(sha))


def is_document_path(path: str) -> bool:
    """Check if a path matches documentation-only criteria."""
    normalized = path.replace("\\", "/").removeprefix("./")
    return normalized.lower().endswith((".md", ".tsv")) and (normalized.startswith("docs/") or "/" not in normalized)


def is_requirements_path(path: str) -> bool:
    """Check if a path is one of the runtime requirements declaration files."""
    normalized = path.replace("\\", "/").removeprefix("./")
    return normalized in {"requirements.txt", "webapp/requirements.txt"}


def make_result(
    *,
    status: str,
    exit_code: int,
    base_sha: str | None = None,
    head_sha: str | None = None,
    docs_only: bool = False,
    plan: list[dict] | None = None,
    planning_calls: list[dict] | None = None,
    executed: list[dict] | None = None,
    failure_code: str | None = None,
    evidence: dict | None = None,
) -> dict:
    """Construct unified verification result payload with strictly sanitized fields."""
    ev = dict(evidence or {})
    if failure_code:
        ev["failure_code"] = failure_code if failure_code in FAILURE_CODES else "EXECUTION_FAILED"
    return {
        "schema_version": 1,
        "status": status,
        "base": base_sha,  # Only resolved 40-hex SHA or None
        "head_sha": head_sha,
        "docs_only": docs_only,
        "plan": plan or [],
        "planning_read_only_calls": planning_calls or [],
        "executed": executed or [],
        "exit_code": exit_code,
        "evidence": ev,
    }


def resolve_commit_sha(revision: str, root: Path = ROOT) -> str:
    """Resolve a Git revision string to an exact 40-character commit SHA.

    Raises ValueError with a sanitized error code on failure (no raw git stderr).
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
            cwd=root,
            capture_output=True,
            text=True,
            shell=False,
        )
    except OSError:
        raise ValueError("GIT_EXECUTION_FAILED")

    if proc.returncode != 0:
        raise ValueError("INVALID_REVISION")
    sha = proc.stdout.strip()
    if not is_valid_sha(sha):
        raise ValueError("INVALID_SHA_FORMAT")
    return sha


def resolve_head_sha(root: Path = ROOT) -> str:
    """Resolve current HEAD commit SHA.

    Raises ValueError on failure (no fail-open UNKNOWN fallback).
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=root,
            capture_output=True,
            text=True,
            shell=False,
        )
    except OSError:
        raise ValueError("GIT_EXECUTION_FAILED")

    if proc.returncode != 0:
        raise ValueError("HEAD_RESOLUTION_FAILED")
    sha = proc.stdout.strip()
    if not is_valid_sha(sha):
        raise ValueError("INVALID_HEAD_SHA_FORMAT")
    return sha


def get_changed_paths(base_sha: str, root: Path = ROOT) -> list[str]:
    """Retrieve list of paths modified, added, renamed, or deleted between base and HEAD."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRD", f"{base_sha}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            shell=False,
        )
    except OSError:
        raise RuntimeError("GIT_EXECUTION_FAILED")

    if proc.returncode != 0:
        raise RuntimeError("GIT_DIFF_FAILED")
    return [p for p in proc.stdout.split("\0") if p]


def validate_guard_output(stdout: str) -> int:
    """Strictly validate data guard JSON schema, types, and count consistency.

    Raises ValueError on malformed JSON or schema violation.
    """
    try:
        data = json.loads(stdout)
    except Exception:
        raise ValueError("DATA_GUARD_MALFORMED")

    if not isinstance(data, dict):
        raise ValueError("DATA_GUARD_MALFORMED")

    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("DATA_GUARD_MALFORMED")

    blocked_count = data.get("blocked_count")
    # In Python, isinstance(False, int) is True, so explicitly disallow bool!
    if isinstance(blocked_count, bool) or not isinstance(blocked_count, int) or blocked_count < 0:
        raise ValueError("DATA_GUARD_MALFORMED")

    files = data.get("files")
    if not isinstance(files, list):
        raise ValueError("DATA_GUARD_MALFORMED")

    computed_blocked = 0
    for entry in files:
        if not isinstance(entry, dict) or "path" not in entry or "blocked" not in entry:
            raise ValueError("DATA_GUARD_MALFORMED")
        if not isinstance(entry["path"], str):
            raise ValueError("DATA_GUARD_MALFORMED")
        if not isinstance(entry["blocked"], bool):
            raise ValueError("DATA_GUARD_MALFORMED")
        if entry["blocked"] is True:
            computed_blocked += 1

    if computed_blocked != blocked_count:
        raise ValueError("DATA_GUARD_MALFORMED")

    return blocked_count


def validate_selector_output(
    stdout: str, returncode: int, has_code_changes: bool, root: Path
) -> tuple[str, list[str], list[list[str]]]:
    """Strictly validate test selector output, returncode, targets shape, and disk existence.

    Returns (status, unknown_files, pytest_commands).
    Raises ValueError on malformed output, invalid returncode/status combination,
    or when code changes exist but 0 pytest targets were selected.
    """
    if returncode not in (0, 2):
        raise ValueError("SELECTOR_PROCESS_FAILED")

    try:
        data = json.loads(stdout)
    except Exception:
        raise ValueError("SELECTOR_MALFORMED")

    if not isinstance(data, dict):
        raise ValueError("SELECTOR_MALFORMED")

    status = data.get("status")
    if not isinstance(status, str):
        raise ValueError("SELECTOR_MALFORMED")

    unknown_files = data.get("unknown_files", [])
    if not isinstance(unknown_files, list) or not all(isinstance(x, str) for x in unknown_files):
        raise ValueError("SELECTOR_MALFORMED")

    if returncode == 2:
        if status in ("UNKNOWN_IMPACT", "ERROR"):
            return status, unknown_files, []
        raise ValueError("SELECTOR_RC_STATUS_MISMATCH")

    # If returncode == 0
    if status not in ("SELECTED", "DOCS_ONLY", "NO_CHANGES"):
        raise ValueError("SELECTOR_UNEXPECTED_STATUS")

    if has_code_changes and status != "SELECTED":
        raise ValueError("SELECTOR_RC_STATUS_MISMATCH")

    if unknown_files:
        raise ValueError("SELECTOR_UNEXPECTED_UNKNOWN_FILES")

    pytest_commands = data.get("pytest_commands", [])
    if not isinstance(pytest_commands, list):
        raise ValueError("SELECTOR_MALFORMED")

    if has_code_changes and not pytest_commands:
        raise ValueError("NO_TARGETS_SELECTED")

    # Validate exact shape and path constraints of each command
    validated_commands: list[list[str]] = []
    for cmd in pytest_commands:
        if not isinstance(cmd, list) or len(cmd) < 4:
            raise ValueError("SELECTOR_INVALID_COMMAND_SHAPE")
        if cmd[0] != sys.executable or cmd[1] != "-m" or cmd[2] != "pytest" or cmd[-1] != "-q":
            raise ValueError("SELECTOR_INVALID_COMMAND_SHAPE")
        targets = cmd[3:-1]
        if not targets:
            raise ValueError("SELECTOR_EMPTY_TARGETS")
        for target in targets:
            if not isinstance(target, str) or not target.endswith(".py"):
                raise ValueError("SELECTOR_INVALID_TARGET_EXTENSION")
            if target.startswith("-") or "\0" in target:
                raise ValueError("SELECTOR_INVALID_TARGET")
            target_path = root / target
            try:
                resolved = target_path.resolve()
            except OSError:
                raise ValueError("SELECTOR_TARGET_NOT_FOUND")
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError("SELECTOR_TARGET_OUTSIDE_ROOT")
            if not target_path.is_file():
                raise ValueError("SELECTOR_TARGET_NOT_FOUND")
        validated_commands.append(cmd)

    return status, unknown_files, validated_commands


def execute_step(command: list[str], root: Path) -> tuple[int, str, str, float]:
    """Execute a single subprocess step with time measurement and safe OSError handling."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            shell=False,
        )
        duration = round(time.monotonic() - start, 3)
        return proc.returncode, proc.stdout, proc.stderr, duration
    except FileNotFoundError:
        duration = round(time.monotonic() - start, 3)
        return 127, "", "", duration
    except OSError:
        duration = round(time.monotonic() - start, 3)
        return 126, "", "", duration


def run_checks(base: str, *, run: bool = False, root: Path = ROOT) -> dict:
    """Orchestrate verification checks in preview or run mode with fail-closed safety."""
    state: dict = {}

    def finish(**fields) -> dict:
        return make_result(**(state | fields))

    # 1. Base resolution
    try:
        base_sha = resolve_commit_sha(base, root)
    except ValueError as exc:
        return finish(
            status="ERROR",
            failure_code=str(exc),
            exit_code=2,
        )

    state["base_sha"] = base_sha

    # 2. Head resolution
    try:
        head_sha = resolve_head_sha(root)
    except ValueError as exc:
        return finish(
            status="ERROR",
            failure_code=str(exc),
            exit_code=2,
        )

    state["head_sha"] = head_sha

    # 3. Changed paths
    try:
        changed_paths = get_changed_paths(base_sha, root)
    except RuntimeError as exc:
        return finish(
            status="ERROR",
            failure_code=str(exc),
            exit_code=2,
        )

    doc_paths = [p for p in changed_paths if is_document_path(p)]
    code_paths = [p for p in changed_paths if not is_document_path(p)]
    py_paths = [p for p in code_paths if p.endswith(".py") and (root / p).is_file()]
    is_docs_only = bool(changed_paths) and not code_paths

    state["docs_only"] = is_docs_only

    # 4. Requirements sync tool availability check (fail-closed if modified but tool missing)
    has_req_changes = any(is_requirements_path(p) for p in changed_paths)
    req_tool = root / "tools" / "sync_runtime_requirements.py"
    if has_req_changes and not req_tool.is_file():
        return finish(
            status="ERROR",
            failure_code="REQUIREMENTS_TOOL_MISSING",
            exit_code=2,
            evidence={
                "changed_paths_count": len(changed_paths),
                "requirements_changed": True,
            },
        )

    # 5. Check if Docs-Only or No-Changes (strictly 0 executions)
    if not changed_paths or is_docs_only:
        overall_status = "DOCS_ONLY" if is_docs_only else "NO_CHANGES"
        evidence = {
            "changed_paths_count": len(changed_paths),
            "code_paths_count": 0,
            "document_paths_count": len(doc_paths),
            "is_docs_only": is_docs_only,
            "tests_executed_count": 0,
            "code_executions_count": 0,
        }
        return finish(
            status=overall_status,
            exit_code=0,
            evidence=evidence,
        )

    # 6. Planning for Code Changes
    plan: list[dict] = []
    planning_calls: list[dict] = []
    state.update(plan=plan, planning_calls=planning_calls)

    # Step: Data Guard
    data_guard_cmd = [
        sys.executable,
        str(root / "tools" / "check_tracked_data.py"),
        "--mode",
        "base",
        "--base",
        base_sha,
        "--json",
    ]
    plan.append({
        "name": "data_guard",
        "command": data_guard_cmd,
        "description": "Inspect tracked data policy violations against base",
    })

    # Step: Requirements Sync (if modified and tool exists)
    req_cmd = [sys.executable, str(req_tool)] if (has_req_changes and req_tool.is_file()) else None
    if req_cmd:
        plan.append({
            "name": "requirements_sync",
            "command": req_cmd,
            "description": "Verify root and webapp requirements declarations match",
        })

    # Step: Targeted Test Selection Query
    selector_cmd = [sys.executable, str(root / "tools" / "select_targeted_tests.py"), "--base", base_sha]
    plan.append({
        "name": "test_selection",
        "command": selector_cmd,
        "description": "Select pytest targets from test-impact-map.json",
    })

    # Query selector during planning
    sel_rc, sel_out, sel_err, sel_dur = execute_step(selector_cmd, root)
    planning_calls.append({
        "name": "test_selection_query",
        "command": selector_cmd,
        "duration_seconds": sel_dur,
    })

    try:
        selector_status, selector_unknown, pytest_commands = validate_selector_output(
            sel_out, sel_rc, has_code_changes=bool(code_paths), root=root
        )
    except ValueError as exc:
        return finish(
            status="ERROR",
            failure_code=str(exc),
            exit_code=2,
            evidence={
                "changed_paths_count": len(changed_paths),
                "code_paths_count": len(code_paths),
            },
        )

    # Step: Python compile
    compile_cmd = [sys.executable, "-m", "py_compile", *py_paths] if py_paths else None
    if compile_cmd:
        plan.append({
            "name": "py_compile",
            "command": compile_cmd,
            "description": f"Compile {len(py_paths)} changed Python files",
        })

    # Step: Pytest batches
    for idx, cmd in enumerate(pytest_commands):
        plan.append({
            "name": f"pytest_batch_{idx + 1}",
            "command": cmd,
            "description": f"Execute targeted pytest batch {idx + 1}",
        })

    evidence = {
        "changed_paths_count": len(changed_paths),
        "code_paths_count": len(code_paths),
        "document_paths_count": len(doc_paths),
        "py_paths_count": len(py_paths),
        "is_docs_only": is_docs_only,
        "selector_status": selector_status,
        "selector_unknown_files": selector_unknown,
        "pytest_commands_count": len(pytest_commands),
    }

    # If selector identified unknown files during planning
    if selector_status in ("UNKNOWN_IMPACT", "ERROR") or selector_unknown:
        return finish(
            status="UNKNOWN_IMPACT" if selector_unknown else "SELECTOR_ERROR",
            failure_code="SELECTOR_UNKNOWN_FILES" if selector_unknown else "SELECTOR_ERROR",
            exit_code=2,
            evidence=evidence,
        )

    # Preview Mode (run=False)
    if not run:
        return finish(
            status="PREVIEW",
            exit_code=0,
            evidence=evidence,
        )

    # 7. Run Mode Pipeline Execution Loop
    def validate_guard_step(rc: int, out: str) -> tuple[bool, str | None]:
        if rc == 127:
            return False, "COMMAND_NOT_FOUND"
        if rc == 126:
            return False, "EXECUTION_FAILED"
        try:
            blocked = validate_guard_output(out)
        except ValueError as e:
            return False, str(e)
        if rc != 0 or blocked > 0:
            return False, "DATA_GUARD_BLOCKED"
        return True, None

    def validate_simple_step(fail_code: str) -> Callable[[int, str], tuple[bool, str | None]]:
        def validator(rc: int, out: str) -> tuple[bool, str | None]:
            if rc == 127:
                return False, "COMMAND_NOT_FOUND"
            if rc == 126:
                return False, "EXECUTION_FAILED"
            if rc != 0:
                return False, fail_code
            return True, None
        return validator

    steps_to_run = [
        ("data_guard", data_guard_cmd, validate_guard_step),
    ]
    if req_cmd:
        steps_to_run.append(("requirements_sync", req_cmd, validate_simple_step("REQUIREMENTS_DRIFT")))
    if compile_cmd:
        steps_to_run.append(("py_compile", compile_cmd, validate_simple_step("COMPILE_FAILED")))
    for idx, cmd in enumerate(pytest_commands):
        steps_to_run.append((f"pytest_batch_{idx + 1}", cmd, validate_simple_step("TESTS_FAILED")))

    executed: list[dict] = []
    state["executed"] = executed
    tests_run_count = 0

    for name, cmd, validator in steps_to_run:
        rc, out, err, dur = execute_step(cmd, root)
        passed, fail_code = validator(rc, out)
        step_record = {
            "name": name,
            "command": cmd,
            "exit_code": rc,
            "status": "PASSED" if passed else "FAILED",
            "duration_seconds": dur,
        }
        if name == "data_guard" and passed:
            step_record["blocked_count"] = 0
        executed.append(step_record)

        if name.startswith("pytest_batch_"):
            tests_run_count += 1

        if not passed:
            evidence["tests_executed_count"] = tests_run_count
            exit_code = 2 if fail_code in ("DATA_GUARD_MALFORMED", "COMMAND_NOT_FOUND", "EXECUTION_FAILED") else 1
            status = "ERROR" if exit_code == 2 else fail_code or "FAILED"
            return finish(
                status=status,
                failure_code=fail_code,
                exit_code=exit_code,
                evidence=evidence,
            )

    evidence["tests_executed_count"] = tests_run_count

    return finish(
        status="PASSED",
        exit_code=0,
        evidence=evidence,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="Git revision or commit SHA to compare against",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually execute the planned checks (default: preview mode)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    args = parser.parse_args(argv)

    result = run_checks(args.base, run=args.run, root=ROOT)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = result["status"]
        mode = "RUN" if args.run else "PREVIEW"
        print(f"Targeted Checks [{mode}]: {status} (exit_code={result['exit_code']})")
        print(f"Base SHA: {result.get('base')} -> Head SHA: {result.get('head_sha')}")
        print(f"Planned checks: {len(result.get('plan', []))}, Executed: {len(result.get('executed', []))}")
        if result.get("evidence", {}).get("failure_code"):
            print(f"Failure code: {result['evidence']['failure_code']}")

    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
