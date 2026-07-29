"""Run the p07 direct candidate and verify its coupled report/manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from ledger.domain.direct_projection import build_direct_candidate
from ledger.domain.transition_gates_v2 import (
    candidate_semantic_sha256,
    gate_report_sha256,
    input_manifest_sha256,
    validate_approved_transitions,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_code_bundle(
    files: object,
    repository_root: Path,
) -> list[dict[str, object]]:
    if not isinstance(files, list) or not files:
        raise ValueError("manifest_code_bundle_invalid")
    root = repository_root.resolve()
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(files):
        if not isinstance(raw, dict):
            raise ValueError(f"manifest_code_file_not_object:{index}")
        if {"relative_path", "raw_sha256"} - set(raw):
            raise ValueError(f"manifest_code_file_missing_provenance:{index}")
        relative_path = str(raw["relative_path"])
        if relative_path in seen:
            raise ValueError(f"manifest_code_file_duplicate:{relative_path}")
        seen.add(relative_path)
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("manifest_code_file_path_escape") from exc
        if not candidate.is_file():
            raise ValueError(f"manifest_code_file_missing:{relative_path}")
        if _sha256_file(candidate) != raw["raw_sha256"]:
            raise ValueError(f"manifest_code_file_hash_mismatch:{relative_path}")
        validated.append(dict(raw))
    return validated


def validate_comparator_object(
    comparator: dict[str, object],
    repository_root: Path,
) -> dict[str, object]:
    required = {"relative_path", "role", "raw_sha256"}
    missing = sorted(required - set(comparator))
    if missing:
        raise ValueError(f"comparator_missing_provenance:{','.join(missing)}")
    root = repository_root.resolve()
    candidate = (root / str(comparator["relative_path"])).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("comparator_path_escape") from exc
    if not candidate.is_file():
        raise ValueError("comparator_missing")
    actual = _sha256_file(candidate)
    if actual != comparator["raw_sha256"]:
        raise ValueError("comparator_hash_mismatch")
    return dict(comparator)


def verify_run_artifacts(
    report_dir: Path,
    *,
    repository_root: Path,
) -> dict[str, object]:
    run_dir = report_dir.resolve()
    report_path = run_dir / "gate_report.json"
    manifest_path = run_dir / "blocker_manifest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    calculated_report_hash = gate_report_sha256(report)
    if report.get("gate_report_sha256") != calculated_report_hash:
        raise ValueError("gate_report_self_hash_mismatch")
    cross_fields = (
        "format_version",
        "run_id",
        "input_manifest_sha256",
        "candidate_semantic_sha256",
        "gate_report_sha256",
        "code_commit",
        "code_bundle_sha256",
        "schema_version",
        "parser_version",
        "cutover_policy",
    )
    mismatches = {
        field: {
            "report": report.get(field),
            "manifest": manifest.get(field),
        }
        for field in cross_fields
        if report.get(field) != manifest.get(field)
    }
    if mismatches:
        raise ValueError(f"manifest_cross_hash_mismatch:{sorted(mismatches)}")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or not all(
        isinstance(item, dict) for item in inputs
    ):
        raise ValueError("manifest_inputs_invalid")
    calculated_input_hash = input_manifest_sha256(inputs)
    if calculated_input_hash != manifest.get("input_manifest_sha256"):
        raise ValueError("manifest_input_hash_mismatch")
    code_bundle = validate_code_bundle(
        manifest.get("code_bundle"),
        repository_root,
    )
    if (
        _canonical_json_sha256(code_bundle)
        != manifest.get("code_bundle_sha256")
    ):
        raise ValueError("manifest_code_bundle_hash_mismatch")
    comparators = [
        validate_comparator_object(item, repository_root)
        for item in manifest.get("historical_comparators", [])
    ]
    failed_gates = [
        str(gate["name"])
        for gate in report.get("gates", [])
        if not bool(gate["passed"])
    ]
    if manifest.get("failed_gates") != failed_gates:
        raise ValueError("manifest_failed_gates_mismatch")
    passed = bool(report["passed"])
    expected_state = (
        "candidate_ready_for_shadow" if passed else "not_published"
    )
    if manifest.get("artifact_state") != expected_state:
        raise ValueError("manifest_artifact_state_mismatch")
    gates_by_name = {
        str(gate["name"]): gate for gate in report.get("gates", [])
    }
    allocation_gate = gates_by_name.get(
        "allocation_and_decision_completeness"
    )
    semantic_gate = gates_by_name.get("semantic_regression")
    if not allocation_gate or not isinstance(allocation_gate.get("actual"), dict):
        raise ValueError("report_allocation_evidence_missing")
    expected_count = allocation_gate["actual"].get(
        "candidate_payment_count"
    )
    if manifest.get("candidate_payment_count") != expected_count:
        raise ValueError("manifest_candidate_count_mismatch")
    if not semantic_gate or not isinstance(semantic_gate.get("actual"), dict):
        raise ValueError("report_semantic_evidence_missing")
    expected_approvals = {
        "provided": semantic_gate["actual"].get("approvals_provided"),
        "mode": semantic_gate["actual"].get("approval_mode"),
    }
    if manifest.get("approved_transitions") != expected_approvals:
        raise ValueError("manifest_approval_summary_mismatch")
    if (
        semantic_gate["actual"].get("diagnostic_comparators")
        != comparators
    ):
        raise ValueError("manifest_comparator_report_mismatch")
    candidate_db = manifest.get("candidate_db")
    if not passed:
        if candidate_db is not None:
            raise ValueError("failed_manifest_must_not_reference_candidate")
    else:
        if not isinstance(candidate_db, dict):
            raise ValueError("passed_manifest_candidate_missing")
        if (
            candidate_db.get("candidate_semantic_sha256")
            != report.get("candidate_semantic_sha256")
        ):
            raise ValueError("candidate_db_semantic_hash_mismatch")
        candidate_path = Path(str(candidate_db.get("path", ""))).resolve()
        if not candidate_path.is_file():
            raise ValueError("candidate_db_missing")
        candidate = sqlite3.connect(
            f"file:{candidate_path.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            row = candidate.execute(
                """
                SELECT status, candidate_semantic_sha256,
                       gate_report_sha256
                FROM direct_projection_runs
                WHERE run_id=?
                """,
                (report["run_id"],),
            ).fetchone()
            expected_row = (
                "passed",
                report["candidate_semantic_sha256"],
                report["gate_report_sha256"],
            )
            if row != expected_row:
                raise ValueError("candidate_db_run_state_mismatch")
            recomputed_semantic = candidate_semantic_sha256(
                candidate,
                str(report["run_id"]),
            )
            if (
                recomputed_semantic
                != report.get("candidate_semantic_sha256")
            ):
                raise ValueError("candidate_db_semantic_content_mismatch")
            exposed = int(
                candidate.execute(
                    "SELECT COUNT(*) FROM direct_candidate_payments"
                ).fetchone()[0]
            )
            if exposed != expected_count:
                raise ValueError("candidate_db_count_mismatch")
        finally:
            candidate.close()
    validate_approved_transitions(None)
    return {
        "passed": passed,
        "run_id": report["run_id"],
        "gate_report_sha256": calculated_report_hash,
        "comparators": comparators,
        "manifest": manifest,
        "report": report,
    }


def run_p07(
    *,
    output_db: Path,
    output_dir: Path,
    ledger_dir: Path,
    manual_path: Path | None = None,
    ota_path: Path | None = None,
    code_commit: str | None = None,
) -> dict[str, object]:
    result = build_direct_candidate(
        output_db,
        ledger_dir,
        output_dir=output_dir,
        manual_path=manual_path,
        ota_path=ota_path,
        code_commit=code_commit,
    )
    verified = verify_run_artifacts(
        Path(str(result["report_dir"])),
        repository_root=ledger_dir.resolve().parent,
    )
    if bool(result["passed"]) != bool(verified["passed"]):
        raise ValueError("builder_report_pass_mismatch")
    return {
        **result,
        "verified_gate_report_sha256": verified["gate_report_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--manual", type=Path)
    parser.add_argument("--ota", type=Path)
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    result = run_p07(
        output_db=args.output_db,
        output_dir=args.output_dir,
        ledger_dir=args.ledger_dir,
        manual_path=args.manual,
        ota_path=args.ota,
        code_commit=args.code_commit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
