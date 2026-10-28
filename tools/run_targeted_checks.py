"""Local targeted verification gate CLI (RF-303).

Orchestrates verification checks based on git diff against a required baseline:
1. Resolves base revision to full commit SHA.
2. Runs data guard policy check (tools/check_tracked_data.py).
3. Verifies runtime requirements synchronization when applicable.
4. Queries targeted pytest targets via test impact map (tools/select_targeted_tests.py).
5. Enforces docs-only contract: when diff is docs-only, code compile, pytest, and browser executions remain strictly 0.
6. Compiles changed Python files safely via py_compile without side-effects.
7. Executes selected pytest batches.

CLI:
- Default: Preview mode (generates and inspects plan; executes 0 checks).
- With --run: Executes gate checks sequentially.
- With --json: Outputs machine-readable payload with separate plan, executed, exit_code, and evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def resolve_base_sha(base: str, root: Path = ROOT) -> str:
    """Resolve a Git revision string to an exact 40-character commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        err = result.stderr.strip() or f"Cannot resolve '{base}' to a valid commit"
        raise ValueError(err)
    return result.stdout.strip()


def resolve_head_sha(root: Path = ROOT) -> str:
    """Resolve current HEAD commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        return "UNKNOWN"
    return result.stdout.strip()


def get_changed_paths(base_sha: str, root: Path = ROOT) -> list[str]:
    """Retrieve list of paths modified, added, renamed, or deleted between base and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRD", f"{base_sha}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        err = result.stderr.strip() or f"git diff failed between {base_sha} and HEAD"
        raise RuntimeError(err)
    return [p for p in result.stdout.split("\0") if p]


def is_document_path(path: str) -> bool:
    """Check if a path matches documentation-only criteria (same rule as select_targeted_tests)."""
    normalized = path.replace("\\", "/").removeprefix("./")
    return normalized.lower().endswith((".md", ".tsv")) and (normalized.startswith("docs/") or "/" not in normalized)


def is_requirements_path(path: str) -> bool:
    """Check if a path is one of the runtime requirements declaration files."""
    normalized = path.replace("\\", "/").removeprefix("./")
    return normalized in {"requirements.txt", "webapp/requirements.txt"}


def plan_checks(base_sha: str, changed_paths: list[str], root: Path = ROOT) -> dict:
    """Construct check execution plan without running any side-effecting tasks."""
    doc_paths = [p for p in changed_paths if is_document_path(p)]
    code_paths = [p for p in changed_paths if not is_document_path(p)]
    py_paths = [p for p in code_paths if p.endswith(".py") and (root / p).is_file()]
    is_docs_only = bool(changed_paths) and not code_paths

    # 1. Data guard command
    data_guard_script = root / "tools" / "check_tracked_data.py"
    data_guard_cmd = [
        sys.executable,
        str(data_guard_script),
        "--mode",
        "base",
        "--base",
        base_sha,
        "--json",
    ]

    # 2. Requirements sync command (only if declared requirements files changed AND sync tool exists)
    req_tool = root / "tools" / "sync_runtime_requirements.py"
    has_req_changes = any(is_requirements_path(p) for p in changed_paths)
    req_sync_cmd = [sys.executable, str(req_tool)] if (has_req_changes and req_tool.is_file()) else None

    # 3. Targeted test selection command
    selector_script = root / "tools" / "select_targeted_tests.py"
    selector_cmd = [sys.executable, str(selector_script), "--base", base_sha]

    # Query selector to obtain planned pytest targets
    selector_res = subprocess.run(
        selector_cmd,
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )

    selector_status = "UNKNOWN"
    selector_unknown_files: list[str] = []
    pytest_commands: list[list[str]] = []
    selector_error: str | None = None

    try:
        data = json.loads(selector_res.stdout)
        selector_status = data.get("status", "UNKNOWN")
        selector_unknown_files = data.get("unknown_files", [])
        if selector_status == "ERROR":
            selector_error = data.get("reason", "Unknown selector error")
        else:
            pytest_commands = data.get("pytest_commands", [])
    except Exception as exc:
        selector_error = f"Failed to parse selector JSON: {exc}"
        selector_status = "ERROR"

    plan: list[dict] = [
        {
            "name": "data_guard",
            "command": data_guard_cmd,
            "description": "Inspect tracked data policy violations against base",
        }
    ]

    if req_sync_cmd:
        plan.append(
            {
                "name": "requirements_sync",
                "command": req_sync_cmd,
                "description": "Verify root and webapp requirements.txt are in sync",
            }
        )

    plan.append(
        {
            "name": "test_selection",
            "command": selector_cmd,
            "description": "Select pytest targets from test-impact-map.json",
        }
    )

    compile_cmd = None
    if not is_docs_only and py_paths:
        compile_cmd = [sys.executable, "-m", "py_compile", *py_paths]
        plan.append(
            {
                "name": "py_compile",
                "command": compile_cmd,
                "description": f"Compile {len(py_paths)} changed Python files",
            }
        )

    if not is_docs_only and pytest_commands:
        for idx, cmd in enumerate(pytest_commands):
            plan.append(
                {
                    "name": f"pytest_batch_{idx + 1}",
                    "command": cmd,
                    "description": f"Execute targeted pytest batch {idx + 1}",
                }
            )

    return {
        "is_docs_only": is_docs_only,
        "doc_paths": doc_paths,
        "code_paths": code_paths,
        "py_paths": py_paths,
        "selector_status": selector_status,
        "selector_unknown_files": selector_unknown_files,
        "selector_error": selector_error,
        "pytest_commands": pytest_commands if not is_docs_only else [],
        "compile_cmd": compile_cmd,
        "plan": plan,
    }


def execute_step(name: str, command: list[str], root: Path) -> tuple[int, str, str, float]:
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
    """Orchestrate verification checks in preview or run mode."""
    try:
        base_sha = resolve_base_sha(base, root)
    except Exception as exc:
        return {
            "schema_version": 1,
            "status": "ERROR",
            "base": base,
            "base_sha": None,
            "head_sha": resolve_head_sha(root),
            "docs_only": False,
            "plan": [],
            "executed": [],
            "exit_code": 2,
            "evidence": {
                "error": f"Base resolution failed: {exc}",
            },
        }

    head_sha = resolve_head_sha(root)

    try:
        changed_paths = get_changed_paths(base_sha, root)
    except Exception as exc:
        return {
            "schema_version": 1,
            "status": "ERROR",
            "base": base,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "docs_only": False,
            "plan": [],
            "executed": [],
            "exit_code": 2,
            "evidence": {
                "error": f"Failed to determine changed paths: {exc}",
            },
        }

    planning = plan_checks(base_sha, changed_paths, root)
    is_docs_only = planning["is_docs_only"]
    plan = planning["plan"]

    evidence: dict = {
        "changed_paths_count": len(changed_paths),
        "code_paths_count": len(planning["code_paths"]),
        "document_paths_count": len(planning["doc_paths"]),
        "py_paths_count": len(planning["py_paths"]),
        "is_docs_only": is_docs_only,
        "selector_status": planning["selector_status"],
        "selector_unknown_files": planning["selector_unknown_files"],
        "pytest_commands_count": len(planning["pytest_commands"]),
    }

    if planning["selector_error"]:
        evidence["selector_error"] = planning["selector_error"]

    if not run:
        # Preview Mode: never run any checks, return plan
        preview_status = (
            "NO_CHANGES"
            if not changed_paths
            else "DOCS_ONLY"
            if is_docs_only
            else "UNKNOWN_IMPACT"
            if planning["selector_unknown_files"] or planning["selector_status"] == "UNKNOWN_IMPACT"
            else "PREVIEW"
        )
        exit_code = 2 if planning["selector_status"] in ("UNKNOWN_IMPACT", "ERROR") else 0
        return {
            "schema_version": 1,
            "status": preview_status,
            "base": base,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "docs_only": is_docs_only,
            "plan": plan,
            "executed": [],
            "exit_code": exit_code,
            "evidence": evidence,
        }

    # Run Mode: execute gate steps
    executed: list[dict] = []
    overall_status = "PASSED"
    exit_code = 0

    # Step 1: Data Guard
    data_guard_item = next((item for item in plan if item["name"] == "data_guard"), None)
    if data_guard_item:
        rc, out, err, dur = execute_step("data_guard", data_guard_item["command"], root)
        blocked_count = 0
        try:
            guard_data = json.loads(out)
            blocked_count = guard_data.get("blocked_count", 0)
        except Exception:
            pass

        passed = (rc == 0 and blocked_count == 0)
        executed.append({
            "name": "data_guard",
            "command": data_guard_item["command"],
            "exit_code": rc,
            "status": "PASSED" if passed else "FAILED",
            "duration_seconds": dur,
            "blocked_count": blocked_count,
        })
        if not passed:
            overall_status = "DATA_GUARD_BLOCKED" if blocked_count > 0 else "DATA_GUARD_ERROR"
            exit_code = 1 if blocked_count > 0 else 2
            evidence["failure_reason"] = f"Data guard failed with {blocked_count} blocked file(s) (exit code {rc})"
            return {
                "schema_version": 1,
                "status": overall_status,
                "base": base,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "docs_only": is_docs_only,
                "plan": plan,
                "executed": executed,
                "exit_code": exit_code,
                "evidence": evidence,
            }

    # Step 2: Requirements Sync (if in plan)
    req_item = next((item for item in plan if item["name"] == "requirements_sync"), None)
    if req_item:
        rc, out, err, dur = execute_step("requirements_sync", req_item["command"], root)
        executed.append({
            "name": "requirements_sync",
            "command": req_item["command"],
            "exit_code": rc,
            "status": "PASSED" if rc == 0 else "FAILED",
            "duration_seconds": dur,
        })
        if rc != 0:
            overall_status = "REQUIREMENTS_DRIFT" if rc == 1 else "REQUIREMENTS_ERROR"
            exit_code = 1
            evidence["failure_reason"] = "Requirements declarations in root and webapp are out of sync"
            return {
                "schema_version": 1,
                "status": overall_status,
                "base": base,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "docs_only": is_docs_only,
                "plan": plan,
                "executed": executed,
                "exit_code": exit_code,
                "evidence": evidence,
            }

    # Step 3: Selector Validation
    if planning["selector_status"] in ("UNKNOWN_IMPACT", "ERROR") or planning["selector_unknown_files"]:
        overall_status = "UNKNOWN_IMPACT" if planning["selector_unknown_files"] else "SELECTOR_ERROR"
        exit_code = 2
        evidence["failure_reason"] = (
            f"Test selector identified unknown changed files: {planning['selector_unknown_files']}"
            if planning["selector_unknown_files"]
            else f"Test selector returned error: {planning.get('selector_error')}"
        )
        return {
            "schema_version": 1,
            "status": overall_status,
            "base": base,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "docs_only": is_docs_only,
            "plan": plan,
            "executed": executed,
            "exit_code": exit_code,
            "evidence": evidence,
        }

    # Step 4: Docs-Only Contract Check
    if is_docs_only or not changed_paths:
        # Guarantee: compile, pytest, install, browser execution = 0
        overall_status = "DOCS_ONLY" if is_docs_only else "NO_CHANGES"
        evidence["tests_executed_count"] = 0
        evidence["code_executions_count"] = 0
        return {
            "schema_version": 1,
            "status": overall_status,
            "base": base,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "docs_only": is_docs_only,
            "plan": plan,
            "executed": executed,
            "exit_code": 0,
            "evidence": evidence,
        }

    # Step 5: Safe Python Compile
    compile_item = next((item for item in plan if item["name"] == "py_compile"), None)
    if compile_item:
        rc, out, err, dur = execute_step("py_compile", compile_item["command"], root)
        executed.append({
            "name": "py_compile",
            "command": compile_item["command"],
            "exit_code": rc,
            "status": "PASSED" if rc == 0 else "FAILED",
            "duration_seconds": dur,
        })
        if rc != 0:
            overall_status = "COMPILE_FAILED"
            exit_code = 1
            evidence["failure_reason"] = f"py_compile failed on changed files (exit code {rc})"
            return {
                "schema_version": 1,
                "status": overall_status,
                "base": base,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "docs_only": is_docs_only,
                "plan": plan,
                "executed": executed,
                "exit_code": exit_code,
                "evidence": evidence,
            }

    # Step 6: Targeted Pytest Execution
    pytest_items = [item for item in plan if item["name"].startswith("pytest_batch_")]
    tests_run_count = 0
    for item in pytest_items:
        rc, out, err, dur = execute_step(item["name"], item["command"], root)
        executed.append({
            "name": item["name"],
            "command": item["command"],
            "exit_code": rc,
            "status": "PASSED" if rc == 0 else "FAILED",
            "duration_seconds": dur,
        })
        tests_run_count += 1
        if rc != 0:
            overall_status = "TESTS_FAILED"
            exit_code = 1
            evidence["failure_reason"] = f"Pytest batch {item['name']} failed (exit code {rc})"
            break

    evidence["tests_executed_count"] = tests_run_count

    return {
        "schema_version": 1,
        "status": overall_status,
        "base": base,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "docs_only": is_docs_only,
        "plan": plan,
        "executed": executed,
        "exit_code": exit_code,
        "evidence": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="Git revision or commit SHA to compare against (e.g. main, HEAD~1)",
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
        if result.get("evidence", {}).get("failure_reason"):
            print(f"Failure reason: {result['evidence']['failure_reason']}")

    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
