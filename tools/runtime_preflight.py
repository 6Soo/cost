"""Fail-closed, metadata-only checks for operational command entrypoints."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from pathlib import PurePosixPath, PureWindowsPath

from tools.check_tracked_data import index as tracked_index, load_policy, reasons

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "ops_entrypoints.json"


def validate_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true", help="metadata-only checks; default")
    parser.add_argument("--oauth-file", help="optional launcher secret file path; metadata only")
    parser.add_argument("--session-secret-file", help="optional launcher secret file path; metadata only")
    args = parser.parse_args(argv)
    return args


def check(root: Path = ROOT, *, env: dict[str, str] | None = None,
          oauth_file: str | None = None, session_secret_file: str | None = None) -> dict:
    """Check manifest and Git path metadata without opening source/data contents."""
    env = os.environ if env is None else env
    problems: list[str] = []
    root = root.resolve()
    try:
        manifest = json.loads((root / "config" / "ops_entrypoints.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "BLOCKED", "checks": ["manifest_unavailable"]}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return {"status": "BLOCKED", "checks": ["invalid_manifest_schema"]}
    if manifest.get("data_root_env") != "WEBLEDGER_DATA_ROOT":
        problems.append("invalid_data_root_contract")
    secret_contract = manifest.get("secret_handling")
    if (not isinstance(secret_contract, dict)
            or secret_contract.get("model") != "runtime_file_arguments"
            or secret_contract.get("entrypoint") != "tools/launch_web_ledger.py"
            or secret_contract.get("arguments") != ["--oauth-file", "--session-secret-file"]
            or secret_contract.get("preflight_reads_secret_values") is not False):
        problems.append("invalid_secret_handling_contract")
    entries = manifest.get("entrypoints")
    if not isinstance(entries, list) or not entries:
        problems.append("invalid_manifest")
        entries = []
    try:
        tracked = tracked_index(root)
        policy = load_policy(root / "config" / "tracked-data-policy.json")
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {"status": "BLOCKED", "checks": ["tracked_inventory_unavailable"]}
    tracked_by_fold = {name.casefold(): (name, info) for name, info in tracked.items()}
    seen: set[str] = set()
    normalized_entries = []
    checks_by_target: dict[str, list[str]] = {}

    def validate_path(raw: object) -> str | None:
        if not isinstance(raw, str) or not raw or raw != raw.strip():
            problems.append("invalid_entry_path")
            return None
        posix, windows = PurePosixPath(raw.replace("\\", "/")), PureWindowsPath(raw)
        if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts or ".." in windows.parts:
            problems.append("unsafe_entry_path")
            return None
        normalized = posix.as_posix()
        found = tracked_by_fold.get(normalized.casefold())
        if found is None:
            problems.append("entrypoint_not_tracked")
            return None
        actual, info = found
        if actual != normalized:
            problems.append("entrypoint_case_mismatch")
        if not (root / Path(*posix.parts)).is_file():
            problems.append("entrypoint_missing")
        markers = reasons(actual, info, policy)
        if markers:
            problems.append("entrypoint_excluded_by_data_policy")
            checks_by_target[normalized] = markers
        return normalized

    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            problems.append("invalid_entry")
            continue
        path = validate_path(item["path"])
        if path is None:
            continue
        folded = path.casefold()
        if folded in seen:
            problems.append("duplicate_entrypoint")
        seen.add(folded)
        normalized_entries.append((path, item))
        if item.get("guard") not in {"read_only", "maintenance", "protected_write", "isolated_output"}:
            problems.append("unclassified_guard")
    canonical = {path for path, item in normalized_entries if item.get("canonical") is True}
    for path, item in normalized_entries:
        aliases, callers = item.get("aliases", []), item.get("callers", [])
        if (not isinstance(aliases, list) or any(not isinstance(x, str) for x in aliases)
                or not isinstance(callers, list) or any(not isinstance(x, str) for x in callers)):
            problems.append("invalid_alias_contract")
            continue
        for alias in aliases:
            normalized_alias = validate_path(alias)
            if normalized_alias is None:
                continue
            if path not in canonical or normalized_alias not in callers:
                problems.append("duplicate_entrypoint_not_converged")
    if isinstance(secret_contract, dict) and secret_contract.get("entrypoint") not in {
            path for path, _ in normalized_entries}:
        problems.append("secret_launcher_not_registered")
    data_root = env.get("WEBLEDGER_DATA_ROOT", "").strip()
    if not data_root:
        problems.append("data_root_unset")
    elif not Path(data_root).is_absolute() and not PureWindowsPath(data_root).is_absolute():
        problems.append("data_root_not_absolute")
    if env.get("WEBLEDGER_MAINTENANCE") == "LIGHTWEIGHT":
        problems.append("maintenance_flag_forbidden_in_preflight")
    if bool(oauth_file) != bool(session_secret_file):
        problems.append("incomplete_secret_file_pair")
    secret_files_checked = 0
    if oauth_file and session_secret_file:
        for raw in (oauth_file, session_secret_file):
            candidate = Path(raw)
            if not candidate.is_absolute() and not PureWindowsPath(raw).is_absolute():
                problems.append("secret_file_path_not_absolute")
                continue
            try:
                if candidate.is_symlink():
                    problems.append("secret_file_metadata_invalid")
                    continue
                resolved = candidate.resolve(strict=True)
                if not resolved.is_file():
                    problems.append("secret_file_metadata_invalid")
                    continue
                try:
                    resolved.relative_to(root)
                except ValueError:
                    pass
                else:
                    problems.append("secret_file_inside_checkout")
                    continue
                secret_files_checked += 1
            except (OSError, RuntimeError):
                problems.append("secret_file_metadata_invalid")
    return {"status": "READY" if not problems else "BLOCKED", "checks": sorted(set(problems)),
            "entrypoint_count": len(entries), "metadata_only": True,
            "inventory_source": "git_index_and_tracked_data_policy",
            "excluded_paths": checks_by_target,
            "secret_file_metadata_checks": secret_files_checked}


def main(argv: list[str] | None = None) -> int:
    args = validate_args(argv)
    result = check(oauth_file=args.oauth_file, session_secret_file=args.session_secret_file)
    print(json.dumps(result))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
