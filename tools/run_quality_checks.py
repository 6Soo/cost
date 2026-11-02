"""Impact-based CI gate for COST changes.

This command builds a deterministic plan from BASE..HEAD. It reuses the
repository impact map and the existing fail-closed data/targeted-check gate.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "tools" / "select_targeted_tests.py"
GATE = ROOT / "tools" / "run_targeted_checks.py"
GLOBAL_UI_TESTS = [
    "webapp/tests/test_site_shell.py::test_browser_shell_tracks_system_theme_and_mobile_menu_keyboard",
    "webapp/tests/test_cards_all.py::test_browser_cards_all_fits_required_viewports_with_system_theme",
    "webapp/tests/test_card_flow_browser.py::CardFlowBrowserTests::test_cleanup_filters_save_stale_empty_and_responsive_browser_contract",
    "webapp/tests/test_site_shell_assets.py",
    "webapp/tests/test_manual_theme.py",
]
FINANCIAL_GUARD_TESTS = [
    "tests/card_pipeline/test_partial_refund.py",
    "tests/card_pipeline/test_ota_exact_gate.py",
    "tests/card_pipeline/test_ota_matching_refactor.py",
    "tests/card_pipeline/test_pipeline.py",
    "tests/card_pipeline/test_source_links.py",
    "tests/card_pipeline/test_google_tsv.py",
    "webapp/tests/test_refund_group_commit.py",
    "webapp/tests/test_cleanup_original_refund_status_contract.py",
    "webapp/tests/test_income_card_boundary.py",
]
GLOBAL_UI_PATTERNS = (
    "webapp/static/css/**", "webapp/static/js/site_*.js",
    "webapp/site_*.py", "webapp/templates/**",
)
QA_OWNED_PATHS = {
    "tools/run_quality_checks.py", "tests/test_quality_checks.py",
    ".github/workflows/quality.yml", "requirements-dev.txt",
}
DOC_SUFFIXES = (".md", ".tsv")


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
    docs = [p for p in normalized if p.lower().endswith(DOC_SUFFIXES)
            and (p.startswith("docs/") or "/" not in p)]
    code = [p for p in normalized if p not in docs]
    if not normalized:
        return {"status": "NO_CHANGES", "changed_paths": [], "steps": []}
    if not code:
        return {"status": "DOCS_ONLY", "changed_paths": normalized,
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
    qa_unknown = sorted(set(unknown) & QA_OWNED_PATHS)
    unknown = sorted(set(unknown) - QA_OWNED_PATHS)
    if qa_unknown:
        targets.add("tests/test_quality_checks.py")
    if unknown:
        # A declared broad suite is safer than silently passing an unmapped product path.
        broad = sorted(str(p.relative_to(root)).replace("\\", "/") for p in
                       (root / "tests", root / "webapp" / "tests")
                       for p in p.rglob("test_*.py") if p.is_file())
        if not broad:
            raise ValueError("UNKNOWN_PATH_WITHOUT_FALLBACK")
        targets.update(broad)
    if any(any(fnmatch.fnmatchcase(p, pattern) for pattern in GLOBAL_UI_PATTERNS) for p in code):
        targets.update(GLOBAL_UI_TESTS)
    # Every product-code change carries the non-weakening financial protection set.
    targets.update(FINANCIAL_GUARD_TESTS)

    missing = sorted(t for t in targets if not (root / t.split("::", 1)[0]).is_file())
    if missing:
        raise ValueError("MISSING_TARGET:" + ",".join(missing))
    return {"status": "UNKNOWN_BROAD" if unknown else "SELECTED",
            "changed_paths": normalized, "unknown_paths": unknown,
            "steps": ["tracked-data-guard", "selected-pytest"],
            "pytest_targets": sorted(targets), "browser_required": any("browser" in t for t in targets),
            "fallback": "all-existing-pytest-files" if unknown else None}


def plan(base: str, head: str, *, root: Path = ROOT) -> dict:
    base_sha = _git(["rev-parse", "--verify", f"{base}^{{commit}}"], root=root)
    head_sha = _git(["rev-parse", "--verify", f"{head}^{{commit}}"], root=root)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha) or not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise ValueError("INVALID_COMMIT_ID")
    paths = changed_paths(base_sha, head_sha, root=root)
    if not paths:
        return {"base_sha": base_sha, "head_sha": head_sha,
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
    return {"base_sha": base_sha, "head_sha": head_sha,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base commit/ref")
    parser.add_argument("--head", default="HEAD", help="head commit/ref")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan-json", action="store_true", help="print plan only")
    modes.add_argument("--check", action="store_true", help="validate the plan without running checks")
    modes.add_argument("--run", action="store_true", help="run data guard and planned pytest")
    args = parser.parse_args(argv)
    try:
        result = plan(args.base, args.head)
        if args.check and result["status"] not in {"DOCS_ONLY", "NO_CHANGES", "SELECTED", "UNKNOWN_BROAD"}:
            raise ValueError("PLAN_NOT_RUNNABLE")
        if args.run and result["status"] in {"SELECTED", "UNKNOWN_BROAD"}:
            targets = result["pytest_targets"]
            if result["status"] == "UNKNOWN_BROAD":
                guard = subprocess.run(
                    [sys.executable, str(ROOT / "tools/check_tracked_data.py"), "--mode", "base",
                     "--base", result["base_sha"], "--json"], cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False,
                )
                try:
                    guard_result = json.loads(guard.stdout)
                    blocked = guard_result["blocked_count"]
                    files = guard_result["files"]
                    valid_guard = (guard_result.get("schema_version") == 1
                                   and type(blocked) is int and blocked >= 0
                                   and isinstance(files, list)
                                   and sum(1 for item in files if isinstance(item, dict)
                                           and item.get("blocked") is True) == blocked)
                except (json.JSONDecodeError, KeyError, TypeError):
                    valid_guard, blocked = False, None
                if guard.returncode or not valid_guard or blocked:
                    print(json.dumps({"status": "DATA_GUARD_FAILED"}, ensure_ascii=False))
                    return 1
            else:
                # Existing gate runs the mapped targets and its tracked-data protection check.
                run = subprocess.run([sys.executable, str(GATE), "--base", result["base_sha"],
                                      "--run", "--json"], cwd=ROOT, shell=False)
                if run.returncode:
                    return run.returncode
                selector = subprocess.run(
                    [sys.executable, str(SELECTOR), "--base", result["base_sha"]], cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False,
                )
                try:
                    selected = {t for cmd in json.loads(selector.stdout)["pytest_commands"] for t in cmd[3:-1]}
                except (json.JSONDecodeError, KeyError, TypeError):
                    return 2
                targets = [t for t in targets if t not in selected]
            if targets:
                tests = subprocess.run([sys.executable, "-m", "pytest", *targets, "-q"],
                                       cwd=ROOT, shell=False)
                return tests.returncode
            return 0
        if args.run and result["status"] == "DOCS_ONLY":
            check_documentation(result["base_sha"], result["head_sha"], result["changed_paths"])
            print(json.dumps({"status": "DOCS_CHECKED", "tests_executed": 0}, ensure_ascii=False))
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
