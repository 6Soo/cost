from __future__ import annotations

import json
from pathlib import Path

from .contracts import ContractError, sha256_file

DESCRIPTOR_VERSION = 1
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
REPORT_RUN_ID_KEYS = ("run_id", "runId")
REPORT_SEMANTIC_KEYS = (
    "candidate_semantic_sha256",
    "semantic_sha256",
    "candidateSemanticSha256",
)


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ContractError(f"expected JSON object in {path}")
    return data


def _first_key(data: dict, keys) -> str | None:
    for key in keys:
        if key in data and isinstance(data[key], str) and data[key]:
            return data[key]
    return None


def seal_snapshot(
    db_path,
    gate_report_path=None,
    run_report_path=None,
    output_path=None,
) -> dict:
    db_path = Path(db_path)
    if not db_path.is_file():
        raise ContractError(f"missing candidate db: {db_path}")
    for suffix in SIDECAR_SUFFIXES:
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            raise ContractError(
                f"unsealed sqlite sidecar present: {sidecar.name}; "
                "checkpoint/close the writer before sealing"
            )
    gate_report_path = Path(gate_report_path) if gate_report_path else None
    run_report_path = Path(run_report_path) if run_report_path else None
    gate_data = _load_json(gate_report_path) if gate_report_path else {}
    run_data = _load_json(run_report_path) if run_report_path else {}
    run_id = _first_key(gate_data, REPORT_RUN_ID_KEYS) or _first_key(
        run_data, REPORT_RUN_ID_KEYS
    )
    semantic = _first_key(gate_data, REPORT_SEMANTIC_KEYS) or _first_key(
        run_data, REPORT_SEMANTIC_KEYS
    )
    descriptor = {
        "descriptor_version": DESCRIPTOR_VERSION,
        "run_id": run_id,
        "candidate_db": {
            "path": db_path.name,
            "sha256": sha256_file(db_path),
            "size_bytes": db_path.stat().st_size,
        },
        "gate_report": (
            {"path": gate_report_path.name, "sha256": sha256_file(gate_report_path)}
            if gate_report_path
            else None
        ),
        "run_report": (
            {"path": run_report_path.name, "sha256": sha256_file(run_report_path)}
            if run_report_path
            else None
        ),
        "candidate_semantic_sha256": semantic,
        "sealed_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
    target = Path(output_path) if output_path else db_path.with_suffix(".snapshot.json")
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(descriptor, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        __import__("os").fsync(handle.fileno())
    __import__("os").replace(tmp, target)
    descriptor["descriptor_path"] = str(target)
    return descriptor


def verify_snapshot(descriptor) -> dict:
    base_dir = None
    if isinstance(descriptor, (str, Path)):
        source_path = Path(descriptor)
        with open(source_path, "r", encoding="utf-8") as handle:
            descriptor = json.load(handle)
        base_dir = source_path.parent
    problems: list[str] = []
    if descriptor.get("descriptor_version") != DESCRIPTOR_VERSION:
        problems.append("unsupported descriptor_version")
    db_info = descriptor.get("candidate_db") or {}
    if base_dir is None:
        base_dir = Path(descriptor.get("base_dir", "."))
    db_path = base_dir / db_info.get("path", "")
    if not db_path.is_file():
        problems.append(f"missing candidate db file: {db_info.get('path')}")
    else:
        for suffix in SIDECAR_SUFFIXES:
            if Path(str(db_path) + suffix).exists():
                problems.append(f"unexpected sidecar present: {suffix}")
        actual = sha256_file(db_path)
        if actual != db_info.get("sha256"):
            problems.append("candidate db sha256 mismatch")
        size = db_path.stat().st_size
        if size != db_info.get("size_bytes"):
            problems.append("candidate db size mismatch")
    for section in ("gate_report", "run_report"):
        info = descriptor.get(section)
        if not info:
            continue
        path = base_dir / info.get("path", "")
        if not path.is_file():
            problems.append(f"missing {section}: {info.get('path')}")
        elif sha256_file(path) != info.get("sha256"):
            problems.append(f"{section} sha256 mismatch")
    if not problems and not descriptor.get("candidate_semantic_sha256"):
        problems.append("descriptor lacks candidate_semantic_sha256 binding")
    return {"ok": not problems, "problems": problems, "descriptor": descriptor}
