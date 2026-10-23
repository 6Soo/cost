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
        ["git", "diff", "--name-only", "--diff-filter=ACMRD", f"{base}...HEAD"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True,
                        help="merge base reference used by git diff BASE...HEAD")
    args = parser.parse_args(argv)
    try:
        impact_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        if impact_map.get("schema") != "cost-test-impact-map-v1":
            raise ValueError("unsupported impact map schema")
        targets, unknown = select_targets(changed_paths(args.base), impact_map["groups"])
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    status = "UNKNOWN_IMPACT" if unknown else "SELECTED"
    payload = {
        "status": status,
        "unknown_files": unknown,
        "pytest_commands": [[sys.executable, "-m", "pytest", *targets, "-q"]] if targets else [],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if unknown or not targets else 0


if __name__ == "__main__":
    raise SystemExit(main())
