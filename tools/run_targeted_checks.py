"""Local targeted verification gate CLI (RF-303).

Orchestrates verification checks based on git diff against a required baseline:
1. Resolves base revision to full 40-hex commit SHA and validates HEAD SHA.
2. Identifies changed paths safely without exposing raw git stderr or customer text.
3. Enforces docs-only / no-changes contract: executed checks count is strictly 0.
4. Manages runtime requirements declaration sync (fail-closed if tool missing).
5. Queries targeted pytest targets via test-impact-map.json, recording planning calls.
6. Strictly validates data guard JSON schema and blocked count (no fail-open).
7. Validates selector returncode, status consistency, and targets (code change requires pytest).
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

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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
    base: str,
    base_sha: str | None = None,
    head_sha: str | None = None,
    docs_only: bool = False,
    plan: list[dict] | None = None,
    planning_calls: list[dict] | None = None,
    executed: list[dict] | None = None,
    failure_code: str | None = None,
    evidence: dict | None = None,
) -> dict:
    """Construct unified verification result payload."""
    ev = dict(evidence or {})
    if failure_code:
        ev["failure_code"] = failure_code
    return {
        "schema_version": 1,
        "status": status,
        "base": base,
        "base_sha": base_sha,
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
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
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
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    if proc.returncode != 0:
        raise ValueError("HEAD_RESOLUTION_FAILED")
    sha = proc.stdout.strip()
    if not is_valid_sha(sha):
        raise ValueError("INVALID_HEAD_SHA_FORMAT")
    return sha


def get_changed_paths(base_sha: str, root: Path = ROOT) -> list[str]:
    """Retrieve list of paths modified, added, renamed, or deleted between base and HEAD."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRD", f"{base_sha}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("GIT_DIFF_FAILED")
    return [p for p in proc.stdout.split("\0") if p]


def validate_guard_output(stdout: str) -> int:
    """Strictly validate data guard JSON schema and return blocked_count.

    Raises ValueError on malformed JSON or invalid schema.
    """
    try:
        data = json.loads(stdout)
    except Exception as exc:
        raise ValueError("DATA_GUARD_MALFORMED") from exc

    if not isinstance(data, dict):
        raise ValueError("DATA_GUARD_MALFORMED")

    if "schema_version" not in data or "files" not in data or "blocked_count" not in data:
        raise ValueError("DATA_GUARD_MALFORMED")

    blocked_count = data["blocked_count"]
    if not isinstance(blocked_count, int) or blocked_count < 0:
        raise ValueError("DATA_GUARD_MALFORMED")

    if not isinstance(data["files"], list):
        raise ValueError("DATA_GUARD_MALFORMED")

    return blocked_count


def validate_selector_output(
    stdout: str, returncode: int, has_code_changes: bool
) -> tuple[str, list[str], list[list[str]]]:
    """Strictly validate test selector output, returncode, and targets.

    Returns (status, unknown_files, pytest_commands).
    Raises ValueError on malformed output, invalid returncode/status combination,
    or when code changes exist but 0 pytest targets were selected.
    """
    if returncode not in (0, 2):
        raise ValueError("SELECTOR_PROCESS_FAILED")

    try:
        data = json.loads(stdout)
    except Exception as exc:
        raise ValueError("SELECTOR_MALFORMED") from exc

    if not isinstance(data, dict):
        raise ValueError("SELECTOR_MALFORMED")

    status = data.get("status")
    if not isinstance(status, str):
        raise ValueError("SELECTOR_MALFORMED")

    unknown_files = data.get("unknown_files", [])
    if not isinstance(unknown_files, list) or not all(isinstance(x, str) for x in unknown_files):
        raise ValueError("SELECTOR_MALFORMED")

    pytest_commands = data.get("pytest_commands", [])
    if not isinstance(pytest_commands, list):
        raise ValueError("SELECTOR_MALFORMED")

    for cmd in pytest_commands:
        if not isinstance(cmd, list) or not all(isinstance(arg, str) for arg in cmd):
            raise ValueError("SELECTOR_MALFORMED")

    if returncode == 2:
        if status in ("UNKNOWN_IMPACT", "ERROR"):
            return status, unknown_files, []
        raise ValueError("SELECTOR_RC_STATUS_MISMATCH")

    if returncode == 0:
        if status not in ("SELECTED", "DOCS_ONLY", "NO_CHANGES"):
            raise ValueError("SELECTOR_UNEXPECTED_STATUS")
        if has_code_changes and not pytest_commands:
            raise ValueError("NO_TARGETS_SELECTED")

    return status, unknown_files, pytest_commands


def execute_step(command: list[str], root: Path) -> tuple[int, str, str, float]:
    """Execute a single subprocess step with time measurement."""
    start = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    duration = round(time.monotonic() - start, 3)
    return proc.returncode, proc.stdout, proc.stderr, duration


def run_checks(base: str, *, run: bool = False, root: Path = ROOT) -> dict:
    """Orchestrate verification checks in preview or run mode with fail-closed safety."""
    # 1. Base resolution
    try:
        base_sha = resolve_commit_sha(base, root)
    except ValueError as exc:
        return make_result(
            status="ERROR",
            failure_code=f"BASE_RESOLUTION_FAILED:{exc}",
            exit_code=2,
            base=base,
        )

    # 2. Head resolution
    try:
        head_sha = resolve_head_sha(root)
    except ValueError as exc:
        return make_result(
            status="ERROR",
            failure_code=f"HEAD_RESOLUTION_FAILED:{exc}",
            exit_code=2,
            base=base,
            base_sha=base_sha,
        )

    # 3. Changed paths
    try:
        changed_paths = get_changed_paths(base_sha, root)
    except RuntimeError:
        return make_result(
            status="ERROR",
            failure_code="GIT_DIFF_FAILED",
            exit_code=2,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
        )

    doc_paths = [p for p in changed_paths if is_document_path(p)]
    code_paths = [p for p in changed_paths if not is_document_path(p)]
    py_paths = [p for p in code_paths if p.endswith(".py") and (root / p).is_file()]
    is_docs_only = bool(changed_paths) and not code_paths

    # 4. Requirements sync tool availability check (fail-closed if modified but tool missing)
    has_req_changes = any(is_requirements_path(p) for p in changed_paths)
    req_tool = root / "tools" / "sync_runtime_requirements.py"
    if has_req_changes and not req_tool.is_file():
        return make_result(
            status="ERROR",
            failure_code="REQUIREMENTS_TOOL_MISSING",
            exit_code=2,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            evidence={
                "changed_paths_count": len(changed_paths),
                "requirements_changed": True,
            },
        )

    # 5. Check if Docs-Only or No-Changes
    # Per contract: for docs-only and no-changes, code compile, pytest, guard, selector = 0 executions
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
        return make_result(
            status=overall_status,
            exit_code=0,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            plan=[],
            planning_calls=[],
            executed=[],
            evidence=evidence,
        )

    # 6. Planning for Code Changes
    plan: list[dict] = []
    planning_calls: list[dict] = []

    # Plan Step: Data Guard
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

    # Plan Step: Requirements Sync (if modified and tool exists)
    req_cmd = [sys.executable, str(req_tool)] if (has_req_changes and req_tool.is_file()) else None
    if req_cmd:
        plan.append({
            "name": "requirements_sync",
            "command": req_cmd,
            "description": "Verify root and webapp requirements declarations match",
        })

    # Plan Step: Targeted Test Selection Query
    selector_cmd = [sys.executable, str(root / "tools" / "select_targeted_tests.py"), "--base", base_sha]
    plan.append({
        "name": "test_selection",
        "command": selector_cmd,
        "description": "Select pytest targets from test-impact-map.json",
    })

    # Query selector during planning to build the pytest execution plan
    sel_rc, sel_out, sel_err, sel_dur = execute_step(selector_cmd, root)
    planning_calls.append({
        "name": "test_selection_query",
        "command": selector_cmd,
        "duration_seconds": sel_dur,
    })

    try:
        selector_status, selector_unknown, pytest_commands = validate_selector_output(
            sel_out, sel_rc, has_code_changes=bool(code_paths)
        )
    except ValueError as exc:
        return make_result(
            status="ERROR",
            failure_code=str(exc),
            exit_code=2,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            plan=plan,
            planning_calls=planning_calls,
            executed=[],
            evidence={
                "changed_paths_count": len(changed_paths),
                "code_paths_count": len(code_paths),
            },
        )

    # Plan Step: Python compile
    compile_cmd = [sys.executable, "-m", "py_compile", *py_paths] if py_paths else None
    if compile_cmd:
        plan.append({
            "name": "py_compile",
            "command": compile_cmd,
            "description": f"Compile {len(py_paths)} changed Python files",
        })

    # Plan Step: Pytest batches
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

    # If selector identified unknown files during planning:
    if selector_status in ("UNKNOWN_IMPACT", "ERROR") or selector_unknown:
        return make_result(
            status="UNKNOWN_IMPACT" if selector_unknown else "SELECTOR_ERROR",
            failure_code="SELECTOR_UNKNOWN_FILES" if selector_unknown else "SELECTOR_ERROR",
            exit_code=2,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            plan=plan,
            planning_calls=planning_calls,
            executed=[],
            evidence=evidence,
        )

    # Preview Mode (run=False): return plan without executing checks
    if not run:
        return make_result(
            status="PREVIEW",
            exit_code=0,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            plan=plan,
            planning_calls=planning_calls,
            executed=[],
            evidence=evidence,
        )

    # 7. Run Mode Execution
    executed: list[dict] = []

    # Step A: Data Guard
    rc, out, err, dur = execute_step(data_guard_cmd, root)
    try:
        blocked_count = validate_guard_output(out)
    except ValueError as exc:
        executed.append({
            "name": "data_guard",
            "command": data_guard_cmd,
            "exit_code": rc,
            "status": "MALFORMED",
            "duration_seconds": dur,
        })
        return make_result(
            status="ERROR",
            failure_code=str(exc),
            exit_code=2,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            plan=plan,
            planning_calls=planning_calls,
            executed=executed,
            evidence=evidence,
        )

    passed_guard = (rc == 0 and blocked_count == 0)
    executed.append({
        "name": "data_guard",
        "command": data_guard_cmd,
        "exit_code": rc,
        "status": "PASSED" if passed_guard else "FAILED",
        "duration_seconds": dur,
        "blocked_count": blocked_count,
    })
    if not passed_guard:
        return make_result(
            status="DATA_GUARD_BLOCKED",
            failure_code="DATA_GUARD_BLOCKED_FILES",
            exit_code=1,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            docs_only=is_docs_only,
            plan=plan,
            planning_calls=planning_calls,
            executed=executed,
            evidence=evidence,
        )

    # Step B: Requirements Sync (if planned)
    if req_cmd:
        rc, out, err, dur = execute_step(req_cmd, root)
        executed.append({
            "name": "requirements_sync",
            "command": req_cmd,
            "exit_code": rc,
            "status": "PASSED" if rc == 0 else "FAILED",
            "duration_seconds": dur,
        })
        if rc != 0:
            return make_result(
                status="REQUIREMENTS_DRIFT",
                failure_code="REQUIREMENTS_DECLARATION_DRIFT",
                exit_code=1,
                base=base,
                base_sha=base_sha,
                head_sha=head_sha,
                docs_only=is_docs_only,
                plan=plan,
                planning_calls=planning_calls,
                executed=executed,
                evidence=evidence,
            )

    # Step C: Safe Python Compile
    if compile_cmd:
        rc, out, err, dur = execute_step(compile_cmd, root)
        executed.append({
            "name": "py_compile",
            "command": compile_cmd,
            "exit_code": rc,
            "status": "PASSED" if rc == 0 else "FAILED",
            "duration_seconds": dur,
        })
        if rc != 0:
            return make_result(
                status="COMPILE_FAILED",
                failure_code="PYTHON_COMPILE_ERROR",
                exit_code=1,
                base=base,
                base_sha=base_sha,
                head_sha=head_sha,
                docs_only=is_docs_only,
                plan=plan,
                planning_calls=planning_calls,
                executed=executed,
                evidence=evidence,
            )

    # Step D: Targeted Pytest Batches
    tests_run_count = 0
    for idx, cmd in enumerate(pytest_commands):
        batch_name = f"pytest_batch_{idx + 1}"
        rc, out, err, dur = execute_step(cmd, root)
        executed.append({
            "name": batch_name,
            "command": cmd,
            "exit_code": rc,
            "status": "PASSED" if rc == 0 else "FAILED",
            "duration_seconds": dur,
        })
        tests_run_count += 1
        if rc != 0:
            evidence["tests_executed_count"] = tests_run_count
            return make_result(
                status="TESTS_FAILED",
                failure_code="TARGETED_PYTEST_FAILED",
                exit_code=1,
                base=base,
                base_sha=base_sha,
                head_sha=head_sha,
                docs_only=is_docs_only,
                plan=plan,
                planning_calls=planning_calls,
                executed=executed,
                evidence=evidence,
            )

    evidence["tests_executed_count"] = tests_run_count

    return make_result(
        status="PASSED",
        exit_code=0,
        base=base,
        base_sha=base_sha,
        head_sha=head_sha,
        docs_only=is_docs_only,
        plan=plan,
        planning_calls=planning_calls,
        executed=executed,
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
        print(f"Base SHA: {result.get('base_sha')} -> Head SHA: {result.get('head_sha')}")
        print(f"Planned checks: {len(result.get('plan', []))}, Executed: {len(result.get('executed', []))}")
        if result.get("evidence", {}).get("failure_code"):
            print(f"Failure code: {result['evidence']['failure_code']}")

    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
