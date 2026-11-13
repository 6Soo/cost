"""Impact-based CI gate for COST changes.

This command builds a deterministic plan from BASE..HEAD. It reuses the
repository impact map and the existing fail-closed data/targeted-check gate.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "tools" / "select_targeted_tests.py"
CORE_DIR = "core"
CARGO_STEPS = (
    ("cargo-fmt", ["fmt", "--all", "--check"]),
    ("cargo-clippy", ["clippy", "--workspace", "--all-targets", "--", "-D", "warnings"]),
    ("cargo-test", ["test", "--workspace"]),
)
# C: has little free space; keep Rust build output off it unless the caller chose a dir.
DEFAULT_WINDOWS_TARGET_DIR = Path("D:/cargo-target/cost")
QA_OWNED_PATHS = {
    "tools/run_quality_checks.py", "tests/test_quality_checks.py",
    "config/known-test-failures.txt", ".github/workflows/quality.yml", "requirements-dev.txt",
}


def _git(args: list[str], *, root: Path = ROOT) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", shell=False)
    if result.returncode:
        raise ValueError("GIT_COMMAND_FAILED")
    return result.stdout.strip()


def changed_paths(base: str, head: str, *, root: Path = ROOT) -> list[str]:
    # -z preserves unusual filenames; ACMRD includes deleted and renamed paths.
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRD", f"{base}...{head}"],
        cwd=root, capture_output=True, shell=False,
    )
    if result.returncode:
        raise ValueError("GIT_DIFF_FAILED")
    return [p.decode("utf-8", errors="replace") for p in result.stdout.split(b"\0") if p]


def build_plan(paths: list[str], selector_payload: dict, *, root: Path = ROOT) -> dict:
    normalized = sorted({p.replace("\\", "/").removeprefix("./") for p in paths})
    docs = [p for p in normalized if p.lower().endswith(".md")
            or (p.lower().endswith(".tsv") and (p.startswith("docs/") or "/" not in p))]
    code = [p for p in normalized if p not in docs]
    if not normalized:
        return {"status": "NO_CHANGES", "changed_paths": [], "steps": []}
    if not code:
        return {"status": "DOCS_ONLY", "changed_paths": normalized, "document_paths": docs,
                "steps": ["documentation-diff-and-links"]}

    unknown = selector_payload.get("unknown_files")
    commands = selector_payload.get("pytest_commands")
    if not isinstance(unknown, list) or not isinstance(commands, list):
        raise ValueError("SELECTOR_MALFORMED")
    if selector_payload.get("status") not in ("SELECTED", "UNKNOWN_IMPACT"):
        raise ValueError("SELECTOR_FAILED")

    targets: set[str] = set()
    for command in commands:
        if not isinstance(command, list) or len(command) < 5 or command[1:3] != ["-m", "pytest"]:
            raise ValueError("SELECTOR_COMMAND_INVALID")
        targets.update(command[3:-1])
    # A mapped test change can otherwise select only its impact group's other
    # tests, leaving the test modified by the PR unexecuted.
    targets.update(p for p in code
                   if (p.startswith("tests/") or p.startswith("webapp/tests/"))
                   and Path(p).name.startswith("test_") and p.endswith(".py")
                   and (root / p).is_file())
    qa_unknown = sorted(set(unknown) & QA_OWNED_PATHS)
    unknown = sorted(set(unknown) - QA_OWNED_PATHS)
    if unknown:
        # Unknown product changes require an explicit impact-map entry; never run
        # hundreds of unrelated tests or report a skipped route as a pass.
        raise ValueError(f"UNKNOWN_IMPACT:{len(unknown)}")
    rust_required = any(p.startswith(CORE_DIR + "/") for p in normalized)
    if qa_unknown:
        targets.add("tests/test_quality_checks.py")
    missing = sorted(t for t in targets if not (root / t.split("::", 1)[0]).is_file())
    if missing:
        raise ValueError("MISSING_TARGET:" + ",".join(missing))
    browser_tests = collect_browser_tests(sorted(targets), root=root)
    return {"status": "SELECTED",
            "changed_paths": normalized, "document_paths": docs, "unknown_paths": unknown,
            "steps": ["tracked-data-guard", "selected-pytest",
                      *([step for step, _ in CARGO_STEPS] if rust_required else [])],
            "pytest_targets": sorted(targets), "browser_required": bool(browser_tests),
            "browser_tests": browser_tests, "rust_required": rust_required,
            "fallback": None}


def _calls_playwright(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in {
                "sync_playwright", "async_playwright"}:
            return True
        if isinstance(child, ast.ImportFrom) and (child.module or "").startswith("playwright"):
            return True
        if isinstance(child, ast.Import) and any(alias.name.startswith("playwright") for alias in child.names):
            return True
    return False


def collect_browser_tests(targets: list[str], *, root: Path = ROOT) -> list[str]:
    cases: set[str] = set()
    for target in targets:
        file_part, _, node_part = target.partition("::")
        source_path = root / file_part
        if not source_path.is_file():
            continue
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, UnicodeError) as exc:
            if source_path.name.endswith("_browser.py"):
                raise ValueError(f"BROWSER_TEST_PARSE_FAILED:{file_part}") from exc
            continue
        requested_parts = node_part.split("::") if node_part else []
        module_name = file_part[:-3].replace("/", ".")
        browser_module = source_path.name.endswith("_browser.py")

        def visit(body: list[ast.stmt], class_path: tuple[str, ...] = (), inherited_browser: bool = False) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    is_browser_fixture = any(
                        (isinstance(base, ast.Name) and base.id.endswith("BrowserFixture"))
                        or (isinstance(base, ast.Attribute) and base.attr.endswith("BrowserFixture"))
                        for base in node.bases)
                    visit(node.body, (*class_path, node.name), inherited_browser or is_browser_fixture)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    if requested_parts and (requested_parts[-1] != node.name
                            or (len(requested_parts) > 1 and list(class_path) != requested_parts[:-1])):
                        continue
                    if browser_module or inherited_browser or _calls_playwright(node):
                        qualified = "::".join((module_name, *class_path, node.name))
                        cases.add(qualified)

        visit(tree.body)
    return sorted(cases)


def audit_plan(*, root: Path = ROOT) -> dict:
    try:
        impact_map = json.loads((root / "config/test-impact-map.json").read_text(encoding="utf-8"))
        audit_groups = impact_map["audit_groups"]
        groups = impact_map["groups"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("IMPACT_MAP_INVALID") from exc
    group_index = {group.get("name"): group for group in groups if isinstance(group, dict)}
    if (not isinstance(audit_groups, list) or not audit_groups
            or not all(isinstance(name, str) for name in audit_groups)
            or len(audit_groups) != len(set(audit_groups))
            or any(name not in group_index for name in audit_groups)):
        raise ValueError("IMPACT_MAP_AUDIT_GROUPS_INVALID")
    targets = set(impact_map.get("safe_fallback_tests", []))
    for name in audit_groups:
        targets.update(group_index[name]["tests"])
    missing = sorted(t for t in targets if not (root / t.split("::", 1)[0]).is_file())
    if missing:
        raise ValueError("MISSING_TARGET:" + ",".join(missing))
    browser_tests = collect_browser_tests(sorted(targets), root=root)
    return {"status": "AUDIT", "audit": True, "changed_paths": [], "document_paths": [],
            "steps": ["tracked-data-guard", "selected-pytest"],
            "pytest_targets": sorted(targets), "browser_required": bool(browser_tests),
            "browser_tests": browser_tests, "fallback": None}


def plan(base: str, head: str, *, audit: bool = False, root: Path = ROOT) -> dict:
    head_sha = _git(["rev-parse", "--verify", f"{head}^{{commit}}"], root=root)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise ValueError("INVALID_COMMIT_ID")
    checked_out_sha = _git(["rev-parse", "--verify", "HEAD^{commit}"], root=root)
    if checked_out_sha.lower() != head_sha.lower():
        raise ValueError("HEAD_MISMATCH")
    if audit:
        tree_sha = _git(["rev-parse", "--verify", f"{head_sha}^{{tree}}"], root=root)
        return {"base_sha": head_sha, "head_sha": head_sha, "head_tree_sha": tree_sha,
                **audit_plan(root=root)}
    base_sha = _git(["rev-parse", "--verify", f"{base}^{{commit}}"], root=root)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha):
        raise ValueError("INVALID_COMMIT_ID")
    paths = changed_paths(base_sha, head_sha, root=root)
    if not paths:
        tree_sha = _git(["rev-parse", "--verify", f"{head_sha}^{{tree}}"], root=root)
        return {"base_sha": base_sha, "head_sha": head_sha, "head_tree_sha": tree_sha,
                **build_plan([], {}, root=root)}
    selector = subprocess.run(
        [sys.executable, str(SELECTOR), "--base", base_sha], cwd=root,
        capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False,
    )
    try:
        payload = json.loads(selector.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("SELECTOR_MALFORMED") from exc
    if selector.returncode not in (0, 2):
        raise ValueError("SELECTOR_FAILED")
    tree_sha = _git(["rev-parse", "--verify", f"{head_sha}^{{tree}}"], root=root)
    return {"base_sha": base_sha, "head_sha": head_sha, "head_tree_sha": tree_sha,
            **build_plan(paths, payload, root=root)}


def check_documentation(base_sha: str, head_sha: str, paths: list[str], *, root: Path = ROOT) -> None:
    diff_check = subprocess.run(["git", "diff", "--check", f"{base_sha}...{head_sha}"],
                                cwd=root, capture_output=True, text=True, shell=False)
    if diff_check.returncode:
        raise ValueError("DOCUMENTATION_DIFF_CHECK_FAILED")
    markdown = [p for p in paths if p.lower().endswith(".md") and (root / p).is_file()]
    link_pattern = re.compile(r"!??\[[^\]]*\]\(([^)]+)\)")
    for file in markdown:
        content = (root / file).read_text(encoding="utf-8")
        for raw in link_pattern.findall(content):
            target = raw.split()[0].strip("<>").split("#", 1)[0]
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            resolved = ((root / target.lstrip("/")) if target.startswith("/")
                        else (root / file).parent / target).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                raise ValueError("DOCUMENTATION_LINK_BROKEN:" + file)


def _validate_guard(payload_text: str, returncode: int) -> None:
    try:
        guard = json.loads(payload_text)
        blocked = guard["blocked_count"]
        files = guard["files"]
        valid = (type(guard.get("schema_version")) is int and guard["schema_version"] == 1
                 and type(blocked) is int and blocked >= 0 and isinstance(files, list)
                 and all(isinstance(item, dict) and isinstance(item.get("path"), str)
                         and isinstance(item.get("blocked"), bool) for item in files)
                 and sum(1 for item in files if item["blocked"]) == blocked)
    except (json.JSONDecodeError, KeyError, TypeError):
        valid, blocked = False, None
    if returncode != 0 or not valid or blocked:
        raise ValueError("DATA_GUARD_FAILED")


def load_known_failures(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    names = (line.split("  # ", 1)[0].strip()
             for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#"))
    return {name for name in names if name}


def classify_known_failures(known: set[str], failed: set[str], executed: set[str]) -> dict:
    known_failed = sorted(known & failed)
    new_failures = sorted(failed - known)
    resolved = sorted((known & executed) - failed)
    return {"known_failed_test_cases": known_failed,
            "new_failed_test_cases": new_failures,
            "resolved_known_test_cases": resolved,
            "known_failure_count": len(known_failed)}


def _junit_node_id(case: ET.Element) -> str:
    classname = case.get("classname", "")
    name = case.get("name", "")
    parts = classname.split(".") if classname else []
    module_end = max((index for index, part in enumerate(parts) if part.startswith("test_")),
                     default=-1)
    if module_end < 0:
        return f"{classname}::{name}"
    module = "/".join(parts[:module_end + 1]) + ".py"
    classes = parts[module_end + 1:]
    return "::".join([module, *classes, name])


def summarize_junit(junit_path: Path, browser_tests: list[str]) -> dict:
    try:
        root = ET.parse(junit_path).getroot()
    except (OSError, ET.ParseError):
        return {"test_case_count": 0, "executed_case_count": 0,
                "browser_executed": [], "browser_skipped": list(browser_tests),
                "missing_browser_tests": list(browser_tests), "skipped_test_cases": [],
                "nonbrowser_skipped_test_cases": [], "skip_count": 0,
                "failed_test_cases": [], "executed_test_cases": [], "error_count": 0}
    cases = list(root.iter("testcase"))
    executed: set[str] = set()
    skipped: set[str] = set()
    executed_count = 0

    def matches_browser_case(case, target: str) -> bool:
        parts = target.split("::")
        module_name, function_name = parts[0], parts[-1]
        class_suffix = ".".join(parts[1:-1])
        case_name = case.get("name", "")
        return ((case_name == function_name or case_name.startswith(function_name + "["))
                and case.get("classname", "").startswith(module_name)
                and (not class_suffix or case.get("classname", "").endswith(class_suffix)))

    for target in browser_tests:
        matched = [case for case in cases if matches_browser_case(case, target)]
        if any(case.find("skipped") is None for case in matched):
            executed.add(target)
        if any(case.find("skipped") is not None for case in matched):
            skipped.add(target)
    executed_count = sum(1 for case in cases if case.find("skipped") is None)
    skipped_cases = [case for case in cases if case.find("skipped") is not None]
    failed_cases = [case for case in cases if case.find("failure") is not None]
    error_cases = [case for case in cases if case.find("error") is not None]
    skipped_test_cases = sorted(f"{case.get('classname', '')}::{case.get('name', '')}"
                                for case in skipped_cases)
    nonbrowser_skipped_test_cases = sorted(
        f"{case.get('classname', '')}::{case.get('name', '')}"
        for case in skipped_cases
        if not any(matches_browser_case(case, target) for target in browser_tests))
    return {"test_case_count": len(cases), "executed_case_count": executed_count,
            "browser_executed": sorted(executed),
            "browser_skipped": sorted(skipped),
            "missing_browser_tests": sorted(set(browser_tests) - executed),
            "skipped_test_cases": skipped_test_cases,
            "nonbrowser_skipped_test_cases": nonbrowser_skipped_test_cases,
            "skip_count": len(skipped_test_cases),
            "failed_test_cases": sorted(_junit_node_id(case) for case in failed_cases),
            "executed_test_cases": sorted(_junit_node_id(case) for case in cases
                                           if case.find("skipped") is None),
            "error_count": len(error_cases) + int(root.get("errors", "0"))}


def find_cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    exe = (Path(os.environ.get("USERPROFILE") or Path.home()) / ".cargo" / "bin"
           / ("cargo.exe" if os.name == "nt" else "cargo"))
    return str(exe) if exe.is_file() else None


def run_cargo_steps(log, *, root: Path = ROOT) -> dict:
    """Run fmt/clippy/test in core/. A missing cargo is a failure, never a skip."""
    cargo = find_cargo()
    if cargo is None:
        log.write("$ cargo\nCARGO_NOT_FOUND: install rustup (see core/README.md)\n")
        print("CARGO_NOT_FOUND: install rustup (see core/README.md)", file=sys.stderr)
        return {"status": "FAILED", "reason": "CARGO_NOT_FOUND", "steps": []}
    env = {**os.environ, "PATH": str(Path(cargo).parent) + os.pathsep + os.environ.get("PATH", "")}
    if (not env.get("CARGO_TARGET_DIR") and os.name == "nt"
            and Path(DEFAULT_WINDOWS_TARGET_DIR.drive + "/").exists()):
        env["CARGO_TARGET_DIR"] = str(DEFAULT_WINDOWS_TARGET_DIR)
    results = []
    for name, args in CARGO_STEPS:
        log.write(f"\n$ cargo {' '.join(args)}\n")
        log.flush()
        done = subprocess.run([cargo, *args], cwd=root / CORE_DIR, stdout=log,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", shell=False, env=env)
        results.append({"step": name, "exit_code": done.returncode})
    ok = all(item["exit_code"] == 0 for item in results)
    return {"status": "PASSED" if ok else "FAILED", "steps": results,
            "target_dir": env.get("CARGO_TARGET_DIR")}


def _write_run_artifacts(targets: list[str], browser_tests: list[str], base_sha: str,
                         head_sha: str, *, head_tree_sha: str | None = None,
                         rust_required: bool = False, root: Path = ROOT) -> int:
    artifact_dir = root / "quality-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_path = artifact_dir / "run-summary.json"
    log_path = artifact_dir / "pytest.log"
    junit_path = artifact_dir / "junit.xml"
    guard = subprocess.run(
        [sys.executable, str(root / "tools/check_tracked_data.py"), "--mode", "base",
         "--base", base_sha, "--json"], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", shell=False,
    )
    try:
        _validate_guard(guard.stdout, guard.returncode)
    except ValueError:
        summary_path.write_text(json.dumps({"status": "DATA_GUARD_FAILED", "base_sha": base_sha,
                                            "head_sha": head_sha}, indent=2), encoding="utf-8")
        log_path.write_text(guard.stdout + "\n" + guard.stderr, encoding="utf-8")
        print("DATA_GUARD_FAILED", file=sys.stderr)
        return 1

    py_targets = sorted(p for p in {t.split("::", 1)[0] for t in targets}
                        if p.endswith(".py") and (root / p).is_file())
    compile_result = subprocess.run([sys.executable, "-m", "py_compile", *py_targets],
                                    cwd=root, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", shell=False)
    command = [sys.executable, "-m", "pytest", *targets, "-q", "-ra", f"--junitxml={junit_path}"]
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n$ py_compile\n")
        log.write(compile_result.stdout + compile_result.stderr + "\n$ pytest\n")
        log.flush()
        # A redirected stdout is written by the child itself. The parent's
        # encoding= option does not control Python/pytest's Windows encoding.
        child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        tests = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", shell=False,
                               env=child_env)
        cargo_result = run_cargo_steps(log, root=root) if rust_required else None
    junit_result = summarize_junit(junit_path, browser_tests)
    known_failures = load_known_failures(root / "config" / "known-test-failures.txt")
    failure_classification = classify_known_failures(
        known_failures, set(junit_result["failed_test_cases"]),
        set(junit_result["executed_test_cases"]))
    browser_executed = junit_result["browser_executed"]
    browser_skipped = junit_result["browser_skipped"]
    nonbrowser_skipped = junit_result["nonbrowser_skipped_test_cases"]
    missing_browser = junit_result["missing_browser_tests"]
    case_count = junit_result["test_case_count"]
    executed_case_count = junit_result["executed_case_count"]
    known_failures_only = (tests.returncode == 1
                           and failure_classification["known_failure_count"] > 0
                           and not failure_classification["new_failed_test_cases"]
                           and junit_result["error_count"] == 0
                           and set(junit_result["failed_test_cases"])
                               == set(failure_classification["known_failed_test_cases"]))
    status = "PASSED" if ((tests.returncode == 0 or known_failures_only)
                          and compile_result.returncode == 0
                          and case_count > 0 and executed_case_count > 0
                          and not missing_browser and not browser_skipped
                          and not nonbrowser_skipped and not junit_result["error_count"]
                          and not failure_classification["new_failed_test_cases"]
                          and (cargo_result is None or cargo_result["status"] == "PASSED")
                          ) else "FAILED"
    if head_tree_sha is None:
        head_tree_sha = _git(["rev-parse", "--verify", f"{head_sha}^{{tree}}"], root=root)
    summary = {"status": status, "base_sha": base_sha, "head_sha": head_sha,
               "head_tree_sha": head_tree_sha,
               "test_case_count": case_count, "executed_case_count": executed_case_count,
               "browser_required": bool(browser_tests),
               "browser_tests": browser_tests, "browser_executed": sorted(browser_executed),
               "browser_skipped": sorted(browser_skipped), "missing_browser_tests": missing_browser,
               "skip_count": junit_result["skip_count"],
               "skipped_test_cases": junit_result["skipped_test_cases"],
               "nonbrowser_skipped_test_cases": nonbrowser_skipped,
               **failure_classification,
               "known_failures_configured": len(known_failures),
               "junit_error_count": junit_result["error_count"],
               "pytest_exit_code": tests.returncode, "compile_exit_code": compile_result.returncode,
               "pytest_targets": targets, "rust_required": rust_required,
               "cargo": cargo_result}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(log_path.read_text(encoding="utf-8"), end="")
    print(f"알려진 실패 {failure_classification['known_failure_count']}건")
    if failure_classification["resolved_known_test_cases"]:
        print(f"해소됨 {len(failure_classification['resolved_known_test_cases'])}건")
    if failure_classification["new_failed_test_cases"]:
        print(f"목록 밖 실패 {len(failure_classification['new_failed_test_cases'])}건")
    if status != "PASSED":
        print("QUALITY_RUN_FAILED: see quality-artifacts/run-summary.json and pytest.log", file=sys.stderr)
        return tests.returncode or compile_result.returncode or 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD", help="base commit/ref")
    parser.add_argument("--head", default="HEAD", help="head commit/ref")
    parser.add_argument("--audit", action="store_true", help="run the mapped synthetic business-protection audit")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan-json", action="store_true", help="print plan only")
    modes.add_argument("--check", action="store_true", help="validate the plan without running checks")
    modes.add_argument("--run", action="store_true", help="run data guard and planned pytest")
    args = parser.parse_args(argv)
    try:
        result = plan(args.base, args.head, audit=args.audit)
        if args.check and result["status"] not in {"DOCS_ONLY", "NO_CHANGES", "SELECTED", "AUDIT"}:
            raise ValueError("PLAN_NOT_RUNNABLE")
        if args.run and result["status"] in {"SELECTED", "AUDIT"}:
            if result.get("document_paths"):
                check_documentation(result["base_sha"], result["head_sha"], result["document_paths"])
            return _write_run_artifacts(result["pytest_targets"], result["browser_tests"],
                                        result["base_sha"], result["head_sha"],
                                        head_tree_sha=result["head_tree_sha"],
                                        rust_required=result.get("rust_required", False))
        if args.run and result["status"] == "DOCS_ONLY":
            check_documentation(result["base_sha"], result["head_sha"], result["document_paths"])
            print(json.dumps({"status": "DOCS_CHECKED", "tests_executed": 0}, ensure_ascii=False))
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
