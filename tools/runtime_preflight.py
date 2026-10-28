"""Fail-closed, metadata-only checks for operational command entrypoints."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "ops_entrypoints.json"


def validate_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true", help="metadata-only checks; default")
    args = parser.parse_args(argv)
    return args


def check(root: Path = ROOT, *, env: dict[str, str] | None = None) -> dict:
    """Check declarations and environment without opening operational data."""
    env = os.environ if env is None else env
    problems: list[str] = []
    try:
        manifest = json.loads((root / "config" / "ops_entrypoints.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "BLOCKED", "checks": ["manifest_unavailable"]}
    entries = manifest.get("entrypoints") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        problems.append("invalid_manifest")
        entries = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            problems.append("invalid_entry")
            continue
        path = item["path"].replace("\\", "/").lower()
        if path in seen:
            problems.append("duplicate_entrypoint")
        seen.add(path)
        if item.get("guard") not in {"read_only", "maintenance", "protected_write", "isolated_output"}:
            problems.append("unclassified_guard")
        if item.get("source_contents_included") is not False:
            problems.append("source_contents_not_excluded")
    canonical = {item.get("path") for item in entries if isinstance(item, dict) and item.get("canonical") is True}
    for item in entries:
        if isinstance(item, dict):
            for alias in item.get("aliases", []):
                alias_path = Path(alias)
                if alias_path.is_absolute() or ".." in alias_path.parts or not (root / alias_path).is_file():
                    problems.append("alias_path_invalid")
                if item.get("path") not in canonical or alias not in item.get("callers", []):
                    problems.append("duplicate_entrypoint_not_converged")
    data_root = env.get("COST_DATA_ROOT", "").strip()
    if not data_root:
        problems.append("data_root_unset")
    elif not Path(data_root).is_absolute():
        problems.append("data_root_not_absolute")
    if env.get("WEBLEDGER_MAINTENANCE") == "LIGHTWEIGHT":
        problems.append("maintenance_flag_forbidden_in_preflight")
    for key, value in env.items():
        if re.search(r"(SECRET|TOKEN|PASSWORD|PRIVATE_KEY)$", key, re.I) and value:
            problems.append("secret_environment_present")
            break
    return {"status": "READY" if not problems else "BLOCKED", "checks": sorted(set(problems)),
            "entrypoint_count": len(entries), "metadata_only": True}


def main(argv: list[str] | None = None) -> int:
    args = validate_args(argv)
    result = check()
    print(json.dumps(result))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
