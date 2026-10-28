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
    parser.add_argument("--live", action="store_true", help="explicitly request the protected live verifier")
    args = parser.parse_args(argv)
    if args.live and args.preflight:
        parser.error("--live and --preflight cannot be combined")
    return args


def check(root: Path = ROOT, *, env: dict[str, str] | None = None) -> dict:
    """Check declarations and environment without opening operational data."""
    env = os.environ if env is None else env
    problems: list[str] = []
    try:
        manifest = json.loads((root / "config" / "ops_entrypoints.json").read_text(encoding="utf-8"))
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
        if item.get("guard") not in {"read_only", "maintenance"}:
            problems.append("unclassified_guard")
        if item.get("source_data") is not False:
            problems.append("source_data_not_excluded")
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
    if args.live:
        if os.environ.get("COST_ALLOW_LIVE_RUNTIME") != "1":
            print(json.dumps({"status": "BLOCKED", "checks": ["live_feature_flag_required"]}))
            return 2
        result = check()
        if result["status"] != "READY":
            print(json.dumps(result))
            return 2
        return 0
    result = check()
    print(json.dumps(result))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
