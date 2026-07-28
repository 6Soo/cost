#!/usr/bin/env python3
"""Create the superseding OTA-corrected canonical and its decision manifest."""
from __future__ import annotations

import copy
import csv
import json
import tempfile
from pathlib import Path

from ledger.domain.p0_release_guard import canonical_csv_census, file_sha256


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "ledger"
SOURCE = LEDGER / "data" / "classified_v14.csv"
OUTPUT = LEDGER / "data" / "classified_v15.csv"
DECISIONS = LEDGER / "data" / "ota_postfiling_corrections_20260728.json"
OLD_MANIFEST = (
    LEDGER
    / "baselines"
    / "p0_current_canonical_20260728"
    / "manifest.json"
)
NEW_MANIFEST = (
    LEDGER
    / "baselines"
    / "p0_current_canonical_20260728_v2"
    / "manifest.json"
)


def write_if_changed(path: Path, content: bytes) -> None:
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def build_rows() -> list[dict[str, str]]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))
    by_uid = {row["uid"]: row for row in rows}
    removed: set[str] = set()

    for correction in decisions["corrections"]:
        uid = correction["uid"]
        row = by_uid.get(uid)
        if row is None:
            raise RuntimeError(f"correction UID missing: {uid}")
        for field, expected in correction["expected"].items():
            if row.get(field) != expected:
                raise RuntimeError(
                    f"{uid} expected {field}={expected!r}, got {row.get(field)!r}"
                )
        if correction["operation"] == "update":
            row.update(correction["set"])
            appendix = correction["note_append"]
            if appendix not in row.get("note", ""):
                row["note"] = f"{row.get('note', '').strip()} | {appendix}".strip(
                    " |"
                )
        elif correction["operation"] == "remove_duplicate_lifecycle_shadow":
            represented = by_uid[correction["represented_by_uid"]]
            if (
                represented.get("src") != row.get("src")
                or represented.get("appr") != row.get("appr")
                or int(float(represented.get("krw") or 0)) != 0
                or "취소" not in represented.get("status", "")
            ):
                raise RuntimeError(f"invalid lifecycle representative for {uid}")
            removed.add(uid)
        else:
            raise RuntimeError(f"unknown correction operation: {correction}")

    result = [row for row in rows if row["uid"] not in removed]
    if len(result) != 1834 or len({row["uid"] for row in result}) != 1834:
        raise RuntimeError("superseding canonical census mismatch")

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)
        temporary = Path(handle.name)
    content = temporary.read_bytes()
    temporary.unlink()
    write_if_changed(OUTPUT, content)
    return result


def build_manifest() -> dict[str, object]:
    manifest = copy.deepcopy(
        json.loads(OLD_MANIFEST.read_text(encoding="utf-8"))
    )
    old_canonical = copy.deepcopy(manifest["canonical"])
    manifest["schema_version"] = 2
    manifest["status"] = "active_superseding_canonical"
    manifest["supersedes"] = {
        "manifest": str(OLD_MANIFEST.relative_to(ROOT)),
        "canonical_path": old_canonical["path"],
        "canonical_sha256": old_canonical["sha256"],
        "reason": "post-filing direct OTA evidence and duplicate lifecycle correction",
    }
    manifest["canonical"] = {
        "path": str(OUTPUT.relative_to(ROOT)),
        "sha256": file_sha256(OUTPUT),
        "bytes": OUTPUT.stat().st_size,
        "census": canonical_csv_census(OUTPUT),
    }

    old_inputs = manifest["input_contract"]["inputs"]
    old_entry = next(
        item for item in old_inputs if item["path"] == str(SOURCE.relative_to(ROOT))
    )
    old_entry["role"] = "superseded_canonical_reference"
    old_entry["stages"] = {"audit_snapshot": "required"}
    new_entry = {
        "path": str(OUTPUT.relative_to(ROOT)),
        "role": "current_canonical",
        "distribution": "tracked",
        "sha256": file_sha256(OUTPUT),
        "bytes": OUTPUT.stat().st_size,
        "record_count": 1834,
        "signed_amount_krw": sum(
            int(round(float(row.get("krw") or 0)))
            for row in csv.DictReader(
                OUTPUT.open(encoding="utf-8-sig", newline="")
            )
        ),
        "stages": {
            "canonical_rebuild": "required",
            "ota_pending_report": "required",
            "workbook_v76": "required",
            "audit_snapshot": "required",
        },
    }
    old_inputs.insert(old_inputs.index(old_entry), new_entry)
    content = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    write_if_changed(NEW_MANIFEST, content)
    return manifest


def main() -> int:
    build_rows()
    manifest = build_manifest()
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "sha256": manifest["canonical"]["sha256"],
                "census": manifest["canonical"]["census"],
                "manifest": str(NEW_MANIFEST.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
