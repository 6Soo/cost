"""Report-only, content-bound direct-card owner review package and dry-run CLI."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from ledger.domain.transition_gates_v2 import _current_direct_event_hashes
from ledger.domain.transition_gates_v2 import candidate_semantic_sha256, gate_report_sha256, input_manifest_sha256

_EVENT_FIELDS = (
    "direct_event_key", "event_sha256", "external_key", "source_event_id",
    "identity_fingerprint", "source_system", "occurred_on", "merchant",
    "approval_number", "amount_krw", "transaction_type", "card_event_id",
    "event_role", "source_kind", "source_key", "source_sha256",
)
_EDIT_FIELDS = (
    "decision_status", "allocation_items_json", "classification_items_json",
    "evidence_refs_json", "owner_rationale",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"confirmed", "needs_review", ""}
_NULL = "__R22_NULL__"
_NULL_ESC = _NULL + _NULL


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _source_context(report: dict[str, object], event_set: str, scope: str, count: int) -> dict[str, object]:
    gate5 = next((g for g in report.get("gates", []) if g.get("name") == "allocation_and_decision_completeness"), {})
    actual = gate5.get("actual", {}) if isinstance(gate5, dict) else {}
    required = ("decision_scope_format", "decision_scope_sha256", "decision_scope_count", "decision_scope_unique_count", "decision_scope_invalid_count", "decision_scope_duplicate_count")
    if any(field not in actual for field in required):
        raise ValueError("owner_review_gate5_scope_fields_missing")
    if actual["decision_scope_format"] != "direct-event-role-scope-v1":
        raise ValueError("owner_review_gate5_scope_format_invalid")
    gate5_scope = actual["decision_scope_sha256"]; gate5_count = actual["decision_scope_count"]
    if gate5_scope != scope:
        raise ValueError("owner_review_gate5_scope_mismatch")
    if int(gate5_count) != count or int(actual["decision_scope_unique_count"]) != count or int(actual["decision_scope_invalid_count"]) != 0 or int(actual["decision_scope_duplicate_count"]) != 0:
        raise ValueError("owner_review_gate5_scope_count_mismatch")
    gate6 = next((g for g in report.get("gates", []) if g.get("name") == "semantic_regression"), {})
    gate6_actual = gate6.get("actual", {}) if isinstance(gate6, dict) else {}
    if gate6_actual.get("current_event_set_sha256") != event_set or gate6_actual.get("current_decision_scope_sha256") != scope:
        raise ValueError("owner_review_gate6_scope_mismatch")
    return {
        "input_manifest_sha256": report.get("input_manifest_sha256"),
        "candidate_semantic_sha256": report.get("candidate_semantic_sha256"),
        "decision_scope_format": "direct-event-role-scope-v1",
        "decision_scope_sha256": scope,
        "decision_scope_count": count,
        "current_event_set_format": "direct-event-role-v1",
        "current_event_set_sha256": event_set,
        "gate5_resolved_count": int(actual.get("resolved_count", 0)),
    }


def _facts(db: object, run_id: str, hashes: dict[str, str]) -> list[dict[str, object]]:
    rows = db.execute("""
        SELECT d.card_event_id, d.event_role, p.external_key, p.source_event_id,
               p.identity_fingerprint, p.source_system, p.occurred_on, p.merchant,
               p.approval_number, d.amount_krw, d.transaction_type,
               s.source_kind, s.source_key, s.source_sha256
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE l.run_id=? ORDER BY d.card_event_id, d.event_role
    """, (run_id,)).fetchall()
    result = []
    for row in rows:
        key = f"{row[0]}#{row[1]}"
        fact = dict(zip(("card_event_id", "event_role", "external_key", "source_event_id",
                         "identity_fingerprint", "source_system", "occurred_on", "merchant",
                         "approval_number", "amount_krw", "transaction_type", "source_kind",
                         "source_key", "source_sha256"), row))
        fact.update({"direct_event_key": key, "event_sha256": hashes[key]})
        result.append({field: fact.get(field) for field in _EVENT_FIELDS} | {field: "" for field in _EDIT_FIELDS})
    return result


def build_owner_review(db: object, run_id: str, report: dict[str, object], *, provenance: dict[str, object]) -> dict[str, object]:
    hashes, event_set, scope = _current_direct_event_hashes(db, run_id)
    facts = _facts(db, run_id, hashes)
    context = _source_context(report, event_set, scope, len(facts))
    provenance = {
        "source_run_id": provenance.get("source_run_id", run_id),
        "code_commit": provenance.get("code_commit", ""),
        "code_bundle_sha256": provenance.get("code_bundle_sha256", ""),
        "gate_report_sha256": provenance.get("gate_report_sha256", ""),
        "source_inventory": provenance.get("source_inventory", []),
    }
    resolved_count = int(context["gate5_resolved_count"])
    manifest = {
        "format_version": 1, "artifact_type": "direct_owner_review_template",
        "source_run_id": run_id, "source_context": context, "provenance": dict(provenance),
        "authority_ready_count": 0, "gate5_resolved_count": resolved_count,
    }
    return {"manifest": manifest, "events": facts, "context": context, "provenance": dict(provenance)}


def serialize_owner_review(package: dict[str, object]) -> tuple[bytes, bytes]:
    manifest_bytes = _json_bytes(dict(package["manifest"])) + b"\n"
    columns = (*_EVENT_FIELDS, *_EDIT_FIELDS)
    output = [columns]
    for event in sorted(package["events"], key=lambda row: str(row.get("direct_event_key", ""))):
        output.append([json.dumps(event.get(field), ensure_ascii=False, separators=(",", ":")) for field in columns])
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(output)
    return manifest_bytes, stream.getvalue().encode("utf-8")


def write_owner_review(package: dict[str, object], output: Path, *, repository_root: Path) -> dict[str, object]:
    target = output.resolve()
    try:
        target.relative_to(repository_root.resolve())
    except ValueError:
        pass
    else:
        raise ValueError(f"owner_review_output_inside_repository:{target}")
    if target.exists():
        raise FileExistsError(f"owner_review_output_exists:{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes, events_bytes = serialize_owner_review(package)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(target.parent)))
    try:
        (staging / "manifest.json").write_bytes(manifest_bytes)
        (staging / "events.csv").write_bytes(events_bytes)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"path": target.as_posix(), "manifest_sha256": _sha(manifest_bytes), "events_sha256": _sha(events_bytes)}


def _strict_json(value: object, field: str) -> object:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"owner_review_{field}_json_invalid")
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"owner_review_{field}_json_invalid") from exc


def _validate_edits(row: dict[str, object], fact: dict[str, object], refs: set[tuple[str, str]]) -> bool:
    status = row.get("decision_status", "")
    if status not in _STATUSES:
        raise ValueError("owner_review_decision_status_invalid")
    allocations = row.get("allocation_items_json", "")
    classifications = row.get("classification_items_json", "")
    evidence = row.get("evidence_refs_json", "")
    nonblank = any(row.get(field, "") not in (None, "") for field in _EDIT_FIELDS)
    if not nonblank:
        return False
    if status == "":
        raise ValueError("owner_review_decision_status_invalid")
    items = _strict_json(allocations, "allocation_items")
    if not isinstance(items, list):
        raise ValueError("owner_review_allocation_items_json_invalid")
    targets: set[str] = set(); total = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {"target_code", "amount_krw"} or not isinstance(item["target_code"], str) or not item["target_code"].strip() or type(item["amount_krw"]) is not int:
            raise ValueError("owner_review_allocation_item_invalid")
        if item["target_code"] in targets:
            raise ValueError("owner_review_allocation_target_duplicate")
        targets.add(item["target_code"]); total += item["amount_krw"]
    if total != int(fact["amount_krw"]):
        raise ValueError("owner_review_allocation_sum_mismatch")
    dimensions: set[str] = set(); classes = _strict_json(classifications, "classification_items")
    if not isinstance(classes, list):
        raise ValueError("owner_review_classification_items_json_invalid")
    for item in classes:
        if (not isinstance(item, dict) or set(item) != {"dimension", "value"}
                or not isinstance(item["dimension"], str) or not item["dimension"].strip()
                or not isinstance(item["value"], str) or not item["value"].strip()
                or item["dimension"] not in {"account", "cost_type", "allocation_target"}
                or item["dimension"] in dimensions):
            raise ValueError("owner_review_classification_item_invalid")
        dimensions.add(item["dimension"])
    refs_value = _strict_json(evidence, "evidence_refs")
    if not isinstance(refs_value, list):
        raise ValueError("owner_review_evidence_refs_json_invalid")
    seen_refs: set[tuple[str, str, str]] = set()
    for ref in refs_value:
        if not isinstance(ref, dict) or set(ref) != {"source_kind", "source_key", "source_sha256"}:
            raise ValueError("owner_review_evidence_ref_unresolved")
        if not all(isinstance(ref.get(field), str) and ref[field].strip() for field in ("source_kind", "source_key", "source_sha256")) or not _SHA256.fullmatch(ref["source_sha256"]):
            raise ValueError("owner_review_evidence_ref_malformed")
        ref_key = (ref["source_kind"], ref["source_key"], ref["source_sha256"])
        if ref_key not in refs:
            raise ValueError("owner_review_evidence_ref_unresolved")
        if ref_key in seen_refs:
            raise ValueError("owner_review_evidence_ref_duplicate")
        seen_refs.add(ref_key)
    if not isinstance(row.get("owner_rationale"), str) or not row["owner_rationale"].strip():
        raise ValueError("owner_review_owner_rationale_invalid")
    return status == "confirmed"


def _validate_hash_context(context: object) -> None:
    if not isinstance(context, dict):
        raise ValueError("owner_review_context_invalid")
    for field in ("input_manifest_sha256", "candidate_semantic_sha256", "decision_scope_sha256", "current_event_set_sha256"):
        if not _SHA256.fullmatch(str(context.get(field, ""))):
            raise ValueError(f"owner_review_context_hash_invalid:{field}")


def validate_owner_review(package: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    if not isinstance(package, dict):
        raise ValueError("owner_review_package_schema_invalid")
    if set(package) != {"manifest", "context", "provenance", "events"}:
        raise ValueError("owner_review_package_schema_invalid")
    manifest = package.get("manifest")
    if not isinstance(manifest, dict) or not isinstance(package.get("provenance"), dict) or not isinstance(manifest.get("provenance"), dict):
        raise ValueError("owner_review_manifest_invalid")
    if set(manifest) != {"format_version", "artifact_type", "source_run_id", "source_context", "provenance", "authority_ready_count", "gate5_resolved_count"}:
        raise ValueError("owner_review_manifest_schema_invalid")
    if type(manifest["format_version"]) is not int or manifest["format_version"] != 1 or manifest["artifact_type"] != "direct_owner_review_template":
        raise ValueError("owner_review_manifest_header_invalid")
    if (manifest["authority_ready_count"] != 0
            or type(manifest["gate5_resolved_count"]) is not int
            or manifest["gate5_resolved_count"] < 0
            or manifest["gate5_resolved_count"] != manifest["source_context"].get("gate5_resolved_count")):
        raise ValueError("owner_review_authority_fields_invalid")
    if package.get("context") != manifest.get("source_context"):
        raise ValueError("owner_review_manifest_context_mismatch")
    if package.get("provenance") != manifest.get("provenance"):
        raise ValueError("owner_review_manifest_provenance_mismatch")
    if (not isinstance(manifest.get("source_run_id"), str) or not manifest["source_run_id"].strip()
            or not isinstance(manifest["provenance"].get("source_run_id"), str)
            or not manifest["provenance"]["source_run_id"].strip()
            or manifest["source_run_id"] != manifest["provenance"]["source_run_id"]):
        raise ValueError("owner_review_source_run_binding_invalid")
    if set(package["provenance"]) != {"source_run_id", "code_commit", "code_bundle_sha256", "gate_report_sha256", "source_inventory"}:
        raise ValueError("owner_review_provenance_schema_invalid")
    context = package.get("context", package.get("manifest", {}).get("source_context"))
    current_context = current.get("context")
    _validate_hash_context(context); _validate_hash_context(current_context)
    if context != current_context:
        raise ValueError("owner_review_source_context_mismatch")
    rows = package.get("events"); current_rows = current.get("events", [])
    if not isinstance(rows, list) or len(rows) != len(current_rows):
        raise ValueError("owner_review_event_rows_invalid")
    expected_keys = [str(row["direct_event_key"]) for row in current_rows]
    actual_keys = [str(row.get("direct_event_key")) for row in rows if isinstance(row, dict)]
    if actual_keys != expected_keys:
        raise ValueError("owner_review_event_order_invalid")
    current_by_key = dict(zip(expected_keys, current_rows))
    refs = {(str(row.get("source_kind")), str(row.get("source_key")), str(row.get("source_sha256"))) for row in current_rows}
    records = current.get("source_records", [])
    if isinstance(records, list):
        refs.update((str(item.get("source_kind")), str(item.get("source_key")), str(item.get("source_sha256"))) for item in records if isinstance(item, dict))
    covered = complete = 0
    for row, key in zip(rows, expected_keys):
        if not isinstance(row, dict) or set(row) != set(_EVENT_FIELDS) | set(_EDIT_FIELDS):
            raise ValueError("owner_review_row_shape_invalid")
        for field in _EVENT_FIELDS:
            if row.get(field) != current_by_key[key].get(field):
                raise ValueError(f"owner_review_immutable_field:{field}")
        if any(row.get(field, "") not in (None, "") for field in _EDIT_FIELDS):
            covered += 1
            if _validate_edits(row, current_by_key[key], refs):
                complete += 1
    result = {
        "status": "template_valid" if covered == 0 else "dry_run_structurally_valid_not_authorized",
        "total_count": len(rows), "covered_count": covered, "blank_count": len(rows) - covered,
        "needs_review_count": len(rows) - complete, "structurally_complete_count": complete,
        "invalid_count": 0, "authority_ready_count": 0,
        "gate5_resolved_count": int(manifest["gate5_resolved_count"]),
    }
    provenance = package.get("provenance", package.get("manifest", {}).get("provenance", {}))
    current_provenance = current.get("provenance", {})
    if "source_inventory" in current_provenance and package["provenance"].get("source_inventory") != current_provenance.get("source_inventory"):
        raise ValueError("owner_review_inventory_mismatch")
    result["same_export_run"] = manifest.get("source_run_id") == current_provenance.get("source_run_id")
    result["same_source_context"] = context == current_context
    result["context_drift"] = {field: {"package": provenance.get(field), "current": current_provenance.get(field)} for field in ("source_run_id", "code_commit", "code_bundle_sha256", "gate_report_sha256") if provenance.get(field) != current_provenance.get(field)}
    return result


def dry_run_owner_review(db: object, run_id: str, report: dict[str, object], *, provenance: dict[str, object], owner_payload: dict[str, object] | None = None) -> dict[str, object]:
    package = build_owner_review(db, run_id, report, provenance=provenance)
    current = {"context": package["context"], "events": package["events"], "provenance": provenance, "source_inventory": provenance.get("source_inventory", [])}
    return {"package": package, **validate_owner_review(owner_payload or package, current)}


def _load_package(manifest_path: Path, events_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("owner_review_manifest_invalid")
    if set(manifest) != {"format_version", "artifact_type", "source_run_id", "source_context", "provenance", "authority_ready_count", "gate5_resolved_count"}:
        raise ValueError("owner_review_manifest_schema_invalid")
    with events_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [*_EVENT_FIELDS, *_EDIT_FIELDS]:
            raise ValueError("owner_review_csv_schema_invalid")
        rows = list(reader)
    for row in rows:
        if set(row) != set(_EVENT_FIELDS) | set(_EDIT_FIELDS):
            raise ValueError("owner_review_csv_row_schema_invalid")
        for field in (*_EVENT_FIELDS, *_EDIT_FIELDS):
            try:
                row[field] = json.loads(row[field])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("owner_review_csv_scalar_invalid") from exc
        if type(row["amount_krw"]) is not int:
            raise ValueError("owner_review_csv_amount_type_invalid")
    return {"manifest": manifest, "context": manifest.get("source_context"), "provenance": manifest.get("provenance", {}), "events": rows}


def load_owner_review(manifest_path: Path, events_path: Path, *, db: object, run_id: str, report: dict[str, object], provenance: dict[str, object]) -> dict[str, object]:
    if str(report.get("run_id")) != run_id or report.get("gate_report_sha256") != gate_report_sha256(report):
        raise ValueError("owner_review_report_binding_invalid")
    package = _load_package(manifest_path, events_path)
    hashes, event_set, scope = _current_direct_event_hashes(db, run_id)
    stored = db.execute("SELECT input_manifest_sha256, candidate_semantic_sha256, code_commit, code_bundle_sha256, gate_report_sha256 FROM direct_projection_runs WHERE run_id=?", (run_id,)).fetchone()
    if stored is None or stored[1] != candidate_semantic_sha256(db, run_id) or report.get("input_manifest_sha256") != stored[0] or report.get("candidate_semantic_sha256") != stored[1]:
        raise ValueError("owner_review_stored_provenance_mismatch")
    inventory_probe = [dict(zip(("source_kind", "relative_path", "raw_sha256", "lf_sha256", "byte_count", "key_set_sha256", "record_count", "parser_version"), row)) for row in db.execute("SELECT source_kind, relative_path, raw_sha256, lf_sha256, byte_count, key_set_sha256, record_count, parser_version FROM direct_projection_inputs WHERE run_id=? ORDER BY source_kind, relative_path", (run_id,)).fetchall()]
    if input_manifest_sha256(inventory_probe) != stored[0]:
        raise ValueError("owner_review_inventory_hash_mismatch")
    if any(report.get(field) != stored[index] for field, index in (("code_commit", 2), ("code_bundle_sha256", 3), ("gate_report_sha256", 4))):
        raise ValueError("owner_review_authoritative_provenance_mismatch")
    inventory = [dict(zip(("source_kind", "relative_path", "raw_sha256", "lf_sha256", "byte_count", "key_set_sha256", "record_count", "parser_version"), row)) for row in db.execute("SELECT source_kind, relative_path, raw_sha256, lf_sha256, byte_count, key_set_sha256, record_count, parser_version FROM direct_projection_inputs WHERE run_id=? ORDER BY source_kind, relative_path", (run_id,)).fetchall()]
    if input_manifest_sha256(inventory) != stored[0]:
        raise ValueError("owner_review_inventory_hash_mismatch")
    current_provenance = {**provenance, "source_run_id": run_id, "code_commit": stored[2], "code_bundle_sha256": stored[3], "gate_report_sha256": stored[4], "source_inventory": inventory}
    records = [dict(zip(("source_kind", "source_key", "source_sha256"), row)) for row in db.execute("SELECT source_kind, source_key, source_sha256 FROM direct_source_records ORDER BY source_kind, source_key, source_sha256")]
    current = {"context": _source_context(report, event_set, scope, len(hashes)), "events": _facts(db, run_id, hashes), "provenance": current_provenance, "source_inventory": inventory, "source_records": records}
    return {"package": package, **validate_owner_review(package, current)}


def main() -> int:
    parser = argparse.ArgumentParser(description="validate a direct-card owner review template")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--rebuild-current", action="store_true")
    parser.add_argument("--ledger-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.rebuild_current:
            if args.ledger_dir is None:
                raise ValueError("rebuild_current_ledger_required")
            from ledger.domain.direct_projection import REPOSITORY_ROOT
            if args.ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
                raise ValueError("rebuild_current_noncanonical_ledger")
            from ledger.domain.direct_projection import build_direct_candidate
            with tempfile.TemporaryDirectory(prefix="r22-rebuild-") as dirname:
                base = Path(dirname)
                result = build_direct_candidate(
                    base / "candidate.db", args.ledger_dir,
                    output_dir=base / "artifacts",
                    owner_review_manifest=args.manifest,
                    owner_review_events=args.events,
                )
                from ledger.domain.p07_manifest import verify_run_artifacts
                verified = verify_run_artifacts(Path(str(result["report_dir"])), repository_root=REPOSITORY_ROOT,
                  expected_activation_pointer_sha256=result.get("activation_pointer_sha256"))
                if bool(verified.get("passed")) != bool(result.get("passed")):
                    raise ValueError("owner_review_verified_run_mismatch")
                summary = {key: value for key, value in result.items() if key not in {"owner_review", "report"}}
                validation = result.get("owner_review")
                if isinstance(validation, dict):
                    summary["owner_review"] = {key: value for key, value in validation.items() if key != "package"}
                exit_code = 0 if isinstance(validation, dict) and validation.get("status") in {"template_valid", "dry_run_structurally_valid_not_authorized"} else 2
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return exit_code
        if args.db is None or args.run_id is None or args.report is None:
            raise ValueError("authoritative_current_required")
        import sqlite3
        db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            report = json.loads(args.report.read_text(encoding="utf-8"))
            result = load_owner_review(args.manifest, args.events, db=db, run_id=args.run_id, report=report, provenance={
                "source_run_id": args.run_id,
                "code_commit": report.get("code_commit"),
                "code_bundle_sha256": report.get("code_bundle_sha256"),
                "gate_report_sha256": report.get("gate_report_sha256"),
            })
        finally:
            db.close()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
