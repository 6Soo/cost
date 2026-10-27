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
            if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in group["paths"]):
                selected.update(group["tests"])
                matched = True
        if not matched:
            unknown.append(normalized)
    return sorted(selected), sorted(set(unknown))


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
        if impact_map.get("schema") != "cost-test-impact-map-v1":
            raise ValueError("unsupported impact map schema")
        paths = changed_paths(args.base)
        document_paths = [p for p in paths if p.lower().endswith(('.md', '.tsv')) and
                          (p.startswith('docs/') or '/' not in p)]
        code_paths = [p for p in paths if p not in document_paths]
        targets, unknown = select_targets(code_paths, impact_map["groups"])
        if unknown:
            targets = sorted(set(targets) | set(impact_map['safe_fallback_tests']))
        for target in targets:
            if not target.endswith('.py') or not (ROOT / target).resolve().is_relative_to(ROOT) or not (ROOT / target).is_file():
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
