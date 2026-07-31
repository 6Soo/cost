"""Read-only, deterministic reference namespace census (stdout only)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPOSITORY_ROOT / "ledger" / "data"
FILES = ("fixes.json", "matched_uids.json", "matched_fresh.json", "ota_event_links_verified.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _keys(path: Path) -> list[str]:
    def pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"reference_duplicate_uid:{path.name}")
        return dict(pairs)
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if isinstance(value, dict):
        keys = list(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError(f"reference_uid_invalid:{path.name}")
        return keys
    if isinstance(value, list):
        if any(not isinstance(row, dict) or not isinstance(row.get("uid"), str) or not row["uid"] for row in value):
            raise ValueError(f"reference_uid_invalid:{path.name}")
        keys = [row["uid"] for row in value]
        if len(keys) != len(set(keys)):
            raise ValueError(f"reference_duplicate_uid:{path.name}")
        return keys
    raise ValueError(f"reference_not_object_or_list:{path.name}")


def build_report(data_dir: Path = DATA_DIR) -> dict[str, object]:
    data_dir = data_dir.resolve()
    v14 = data_dir / "classified_v14.csv"
    with v14.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "uid" not in reader.fieldnames:
            raise ValueError("v14_uid_header_missing")
        rows = list(reader)
    v14_keys = [str(row["uid"]) for row in rows]
    if any(not key for key in v14_keys) or len(v14_keys) != len(set(v14_keys)):
        raise ValueError("v14_uid_invalid_or_duplicate")
    current = set(v14_keys)
    v14_sha = _sha(v14)
    references: dict[str, object] = {}
    for name in FILES:
        path = data_dir / name
        keys = _keys(path)
        unique = set(keys)
        absent = sorted(unique - current)
        absent_sha = hashlib.sha256(("\n".join(absent) + "\n").encode()).hexdigest()
        try:
            source_path = path.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            source_path = path.name
        references[name] = {
            "source_path": source_path,
            "source_sha256": _sha(path),
            "reference_count": len(keys),
            "reference_unique_count": len(unique),
            "reference_duplicate_count": len(keys) - len(unique),
            "current_count": len(current),
            "absent_from_current_count": len(absent),
            "absent_from_current_sample": absent[:10],
            "absent_key_set_sha256": absent_sha,
            "v14_sha256": v14_sha,
        }
    return {"format_version": 1, "v14_sha256": v14_sha, "references": references}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output is not None:
        parser.error("--output is not supported; report is stdout-only")
    payload = json.dumps(build_report(args.data_dir.resolve()), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"reference_namespace_report_error:{exc}", file=sys.stderr)
        raise SystemExit(2)
