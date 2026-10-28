"""Print pytest targets selected by the COST test impact map."""

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "config" / "test-impact-map.json"


def select_targets(changed_paths, groups):
    selected = set()
    unknown = []
    for path in changed_paths:
        normalized = path.replace("\\", "/").removeprefix("./")
        matched = False
        for group in groups:
            if any(path_matches(normalized, pattern) for pattern in group["paths"]):
                selected.update(group["tests"])
                matched = True
        if not matched:
            unknown.append(normalized)
    return sorted(selected), sorted(set(unknown))


def path_matches(path, pattern):
    """Match repository-relative POSIX paths, with ** spanning directories."""
    normalized = pattern.replace("\\", "/").removeprefix("./")
    if ".." in Path(normalized).parts or normalized.startswith("/"):
        raise ValueError("invalid impact path pattern")
    if "**" not in normalized:
        return fnmatch.fnmatchcase(path, normalized)
    import re
    expression = "^" + re.escape(normalized).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]") + "$"
    return re.match(expression, path) is not None


def validate_impact_map(data):
    if not isinstance(data, dict) or data.get("schema") != "cost-test-impact-map-v1":
        raise ValueError("unsupported impact map schema")
    groups = data.get("groups")
    fallback = data.get("safe_fallback_tests")
    if not isinstance(groups, list) or not groups or not isinstance(fallback, list) or not fallback:
        raise ValueError("impact map groups and safe fallback are required")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str):
            raise ValueError("invalid impact group")
        paths, tests = group.get("paths"), group.get("tests")
        if not isinstance(paths, list) or not paths or not isinstance(tests, list) or not tests:
            raise ValueError("impact group paths and tests are required")
        for pattern in paths:
            if not isinstance(pattern, str) or not pattern:
                raise ValueError("invalid impact path pattern")
            path_matches("synthetic/path.py", pattern)
        for target in tests:
            validate_test_target(target)
    for target in fallback:
        validate_test_target(target)


def validate_test_target(target):
    if (not isinstance(target, str) or not target.endswith(".py")
            or "\\" in target or Path(target).is_absolute()
            or ".." in Path(target).parts or not target.startswith(("tests/", "webapp/tests/"))):
        raise ValueError("invalid pytest target")


def changed_paths(base):
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMRD", f"{base}...HEAD"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return [path for path in result.stdout.split('\0') if path]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True,
                        help="merge base reference used by git diff BASE...HEAD")
    args = parser.parse_args(argv)
    try:
        impact_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        validate_impact_map(impact_map)
        paths = changed_paths(args.base)
        document_paths = [p for p in paths if p.lower().endswith(('.md', '.tsv')) and
                          (p.startswith('docs/') or '/' not in p)]
        code_paths = [p for p in paths if p not in document_paths]
        targets, unknown = select_targets(code_paths, impact_map["groups"])
        if unknown:
            targets = sorted(set(targets) | set(impact_map['safe_fallback_tests']))
        all_targets = set(impact_map["safe_fallback_tests"])
        all_targets.update(target for group in impact_map["groups"] for target in group["tests"])
        for target in all_targets:
            if not (ROOT / target).resolve().is_relative_to(ROOT) or not (ROOT / target).is_file():
                raise ValueError('invalid or missing pytest target: ' + target)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    status = 'NO_CHANGES' if not paths else 'DOCS_ONLY' if not code_paths else "UNKNOWN_IMPACT" if unknown else "SELECTED"
    payload = {
        "status": status,
        "unknown_files": unknown,
        "document_only_files": document_paths,
        "fallback_selected": bool(unknown),
        "tests_executed": False,
        "pytest_commands": [[sys.executable, "-m", "pytest", *targets, "-q"]] if targets else [],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if unknown or (code_paths and not targets) else 0


if __name__ == "__main__":
    raise SystemExit(main())
