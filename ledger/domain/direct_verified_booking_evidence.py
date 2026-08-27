"""R26 content-bound, non-authoritative verified-booking relation proposals."""
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
import stat
from datetime import date
from collections import defaultdict
from pathlib import Path

from ledger.domain.direct_external_manual_evidence import _build_package as _build_r25
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _build_temp_db, _install_noreplace, build_annex
from ledger.domain.posix_publication import open_dir

ARTIFACT_TYPE = "r26-verified-booking-evidence-v1"
RULE_VERSION = "r26-booking-token-approval-family-v1"
FAMILY_MAP = {"KBD": "KB", "KBO": "KB", "HAN": "HAN", "CORP": "CORP"}
TARGET_REF = "1400824130566434"
TARGET_FACT = {"category": "숙박", "period": "0414_0415", "source": "Gmail Trip.com 고마가네 프리몬트 호텔 확정메일"}
TARGET_MAIL_FIELDS = {"messageId", "subject", "sentAt", "provider", "bookingRefs", "pnrs", "travelDates", "amounts", "messageHash", "redactionVersion"}
FILES = ("manifest.json", "relations.csv", "coverage.csv")
EXPECTED_RELATIONS = {
    ("TRIP-0084", "30095375", "card:cdebc3b430986730a6941f5e1250c1817df67cc6852de63114c85c0fa5bc231a#single"),
    ("TRIP-0085", "30096512", "card:dbc0afe41d26a956aff56dd79d29899fecaffe46a67398e23a8e04a4ae6da7ea#single"),
    ("TRIP-0086", "30096578", "card:6271671d95593384238ba844d311c928ea2105a6bd35948b2367cc676d3ba3ff#single"),
    ("TRIP-0087", "30096534", "card:2e42e2851beb4ee960e96c68a286bf8a679b5d65a6c6f19ae55f2cd441743435#single"),
    ("TRIP-0088", "30096556", "card:75190a9223bdd0e17027acf12bcea6eb3636a06076d1fbb05e7afe9d27f9c92a#single"),
    ("TRIP-0089", "30096590", "card:1894ba04b0d81f11e3b770f4a8768a5ef885815f5f5180992344e8fb61764b80#single"),
    ("TRIP-0090", "30098176", "card:1143abc7f9f86fd12de8d4904af204173a0cfa8c70ee60b781283f3808616ab3#single"),
}
EXPECTED_KOMAGANE_R25 = {row[2] for row in EXPECTED_RELATIONS if row[0] in {"TRIP-0084", "TRIP-0085", "TRIP-0086", "TRIP-0089"}}
EXPECTED_OTHER_R25 = {"card:32a6b494981491b2c33d06489d32c3139c6b232a35d9bece51b1260366d25068#single"}
RULE_SHA256 = hashlib.sha256(json.dumps({
    "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION, "family_mapping": FAMILY_MAP,
    "target_reference": TARGET_REF, "target_fact": TARGET_FACT, "target_mail_fields": sorted(TARGET_MAIL_FIELDS),
    "expected_relations": sorted(EXPECTED_RELATIONS), "expected_komagane_r25": sorted(EXPECTED_KOMAGANE_R25),
    "expected_other_r25": sorted(EXPECTED_OTHER_R25), "trip_0090_dates": ["2026-03-12", "2026-03-27"],
}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
RELATION_COLUMNS = (
    "relation_id", "booking_reference", "booking_category", "booking_period", "booking_fact_row_sha256",
    "mail_message_id", "mail_message_hash", "mail_redaction_version", "historical_uid", "historical_row_sha256",
    "historical_source", "historical_use_date", "historical_amount_krw", "historical_approval_raw",
    "approval_normalized", "issuer_family", "historical_cardinality", "current_cardinality", "direct_event_key",
    "current_event_sha256", "current_source_system", "current_use_date", "current_amount_krw", "current_source_kind",
    "current_source_key", "current_source_sha256", "issuer_subtype_mismatch", "date_conflict", "r25_union_member",
    "coverage_status", "relation_kind", "disposition", "authority_status", "posting_status", "confirmed_count",
    "gate5_credit", "booking_group_id",
)
COVERAGE_COLUMNS = ("booking_reference", "direct_event_key", "coverage_origin", "r25_union_member")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: str(row.get(name, "")).lower() if isinstance(row.get(name), bool) else row.get(name, "") for name in columns})
    return stream.getvalue().encode()


def _digits(value: object) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"[0-9]+", text) and set(text) != {"0"} else ""


def _booking_tokens(note: object) -> set[str]:
    """Extract explicit 예약-number tokens; never use substring containment."""
    return set(re.findall(r"예약(?:번호|코드)?\s*([0-9]{8,19})(?![0-9])", str(note or "")))


def _resolve_approval(
    historical_groups: dict[tuple[str, str], list[dict[str, object]]],
    current_groups: dict[tuple[str, str], list[dict[str, object]]],
    family: str | None,
    approval: str,
) -> dict[str, object] | None:
    if not family or not approval:
        return None
    historical = historical_groups.get((family, approval), [])
    current = current_groups.get((family, approval), [])
    return current[0] if len(historical) == len(current) == 1 else None


def _load_json(path: Path) -> tuple[object, bytes]:
    raw = path.read_bytes()
    def strict_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("r26_json_duplicate_key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("r26_json_nonfinite"))), raw


def _fsync_directory(path: Path) -> None:
    descriptor = open_dir(path)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _validate_fact(reference: object, value: object) -> None:
    if not isinstance(reference, str) or not reference or not re.fullmatch(r"[0-9]{8,19}", reference):
        raise ValueError("r26_booking_reference_invalid")
    if not isinstance(value, dict) or set(value) != {"category", "period", "source"}:
        raise ValueError("r26_booking_fact_schema_invalid")
    if any(not isinstance(value[name], str) or not value[name].strip() for name in value):
        raise ValueError("r26_booking_fact_type_invalid")
    if value["category"] not in {"숙박", "렌트"}:
        raise ValueError("r26_booking_category_invalid")
    match = re.fullmatch(r"([0-1][0-9])([0-3][0-9])_([0-1][0-9])([0-3][0-9])", value["period"])
    if not match: raise ValueError("r26_booking_period_invalid")
    try:
        start = date(2026, int(match[1]), int(match[2])); end = date(2026, int(match[3]), int(match[4]))
    except ValueError as exc:
        raise ValueError("r26_booking_period_invalid") from exc
    if end < start: raise ValueError("r26_booking_period_invalid")


def _validate_target_message(message: object) -> None:
    if not isinstance(message, dict) or set(message) != TARGET_MAIL_FIELDS:
        raise ValueError("r26_target_mail_schema_invalid")
    for name in ("subject", "sentAt", "provider"):
        if not isinstance(message[name], str) or not message[name].strip(): raise ValueError("r26_target_mail_type_invalid")
    if not isinstance(message["messageId"], str) or not re.fullmatch(r"[0-9a-f]{16}", message["messageId"]): raise ValueError("r26_target_mail_id_invalid")
    if not isinstance(message["messageHash"], str) or not re.fullmatch(r"[0-9a-f]{64}", message["messageHash"]): raise ValueError("r26_target_mail_hash_invalid")
    if message["redactionVersion"] != "ota-allowlist-v1" or message["provider"] != "trip": raise ValueError("r26_target_mail_contract_invalid")
    if not isinstance(message["bookingRefs"], list) or any(not isinstance(x, str) or not x for x in message["bookingRefs"]): raise ValueError("r26_target_mail_type_invalid")
    if message["bookingRefs"].count(TARGET_REF) != 1: raise ValueError("r26_target_mail_booking_invalid")
    if not isinstance(message["pnrs"], list) or any(not isinstance(x, str) for x in message["pnrs"]): raise ValueError("r26_target_mail_type_invalid")
    if not isinstance(message["travelDates"], list) or any(not isinstance(x, str) or not re.fullmatch(r"[0-1][0-9][0-3][0-9]", x) for x in message["travelDates"]): raise ValueError("r26_target_mail_type_invalid")
    if not {"0414", "0415"} <= set(message["travelDates"]): raise ValueError("r26_target_mail_dates_invalid")
    if not isinstance(message["amounts"], list) or any(isinstance(x, bool) or not isinstance(x, int) for x in message["amounts"]): raise ValueError("r26_target_mail_type_invalid")


def _build(
    *, booking_periods: Path, ota_mail: Path, manual_csv: Path, ledger_dir: Path
) -> tuple[dict[str, object], dict[str, bytes]]:
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
        raise ValueError("r26_noncanonical_ledger")
    if booking_periods.resolve() != (ledger_dir / "data/booking_periods_verified.json").resolve():
        raise ValueError("r26_noncanonical_booking_periods")
    if ota_mail.resolve() != (ledger_dir / "data/ota_mail_index.json").resolve():
        raise ValueError("r26_noncanonical_ota_mail")
    facts, facts_raw = _load_json(booking_periods); mail, mail_raw = _load_json(ota_mail)
    if not isinstance(facts, dict) or len(facts) != 13:
        raise ValueError("r26_booking_facts_schema_invalid")
    for reference, value in facts.items(): _validate_fact(reference, value)
    if facts.get(TARGET_REF) != TARGET_FACT: raise ValueError("r26_target_fact_contract_invalid")
    if not isinstance(mail, dict) or set(mail) != {"generatedAt", "records"} or not isinstance(mail.get("records"), list):
        raise ValueError("r26_mail_schema_invalid")
    messages = [r for r in mail["records"] if TARGET_REF in [str(x) for x in r.get("bookingRefs", [])]]
    if len(messages) != 1 or not messages[0].get("messageId") or not messages[0].get("messageHash"):
        raise ValueError("r26_target_mail_not_isolated")
    message = messages[0]; _validate_target_message(message)

    r23_result = build_annex(ledger_dir=ledger_dir); r23 = r23_result["package"]["envelopes"]
    r23_candidates: dict[str, list[str]] = defaultdict(list)
    for item in r23:
        if item.get("historical_uid"):
            r23_candidates[str(item["historical_uid"])].append(str(item["direct_event_key"]))
    r23_by_uid = {uid: values[0] for uid, values in r23_candidates.items() if len(values) == 1}
    if any(len(values) != 1 for values in r23_candidates.values()):
        raise ValueError("r26_r23_uid_cardinality_invalid")
    r25_manifest, r25_files = _build_r25(manual_csv, ledger_dir)
    proposals = list(csv.DictReader(io.StringIO(r25_files["proposals.csv"].decode())))
    evidence = list(csv.DictReader(io.StringIO(r25_files["evidence_sets.csv"].decode())))
    r25_union = {r["direct_event_key"] for r in proposals}
    r25_union |= {r["direct_event_key"] for r in evidence if r["evidence_tier"] in {"clean_110", "typed_v14_65", "portal_1"}}
    if len(r25_union) != 272: raise ValueError("r26_r25_union_size_invalid")
    r25_booking_candidates: dict[str, set[str]] = defaultdict(set)
    for row in proposals:
        ref = str(row.get("booking_reference") or "")
        if ref: r25_booking_candidates[ref].add(str(row["direct_event_key"]))
    r25_booking = {ref: next(iter(events)) for ref, events in r25_booking_candidates.items() if len(events) == 1}

    classified_path = ledger_dir / "data" / "classified_v14.csv"; classified_raw = classified_path.read_bytes()
    classified = list(csv.DictReader(io.StringIO(classified_raw.decode("utf-8-sig"))))
    refs = set(facts)
    hist_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in classified:
        approval = _digits(row.get("appr")); family = FAMILY_MAP.get(str(row.get("src")))
        if approval and family: hist_groups[(family, approval)].append(row)

    with tempfile.TemporaryDirectory(prefix="r26-") as dirname:
        db, run_id, _inventory, _eventset, _scope, current_hashes = _build_temp_db(ledger_dir, Path(dirname))
        rows = db.execute("""
            SELECT d.card_event_id||'#'||d.event_role,p.source_system,d.amount_krw,p.occurred_on,
                   p.approval_number,s.payload_json,s.source_kind,s.source_key,s.source_sha256
            FROM direct_payment_projection_links l JOIN payment_transactions p ON p.id=l.payment_id
            JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
            JOIN direct_source_records s ON s.id=d.source_record_id WHERE l.run_id=? ORDER BY 1
        """, (run_id,)).fetchall(); db.close()
    current_groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        payload = json.loads(row[5]); approval = _digits(payload.get("appr") or row[4]); family = FAMILY_MAP.get(str(row[1]))
        event = {"direct_event_key": row[0], "source_system": row[1], "amount": row[2], "date": payload.get("use_date") or row[3], "approval": approval, "source_kind": row[6], "source_key": row[7], "source_sha": row[8]}
        if approval and family: current_groups[(family, approval)].append(event)

    coverage: list[dict[str, object]] = []; relations: list[dict[str, object]] = []; ambiguities: list[dict[str, object]] = []
    seen_coverage: set[tuple[str, str]] = set()
    for historical in classified:
        matched_refs = sorted(refs & _booking_tokens(historical.get("note")))
        for ref in matched_refs:
            event_id = r23_by_uid.get(str(historical["uid"])); origin = "r23_existing"
            if event_id is None and ref in r25_booking:
                event_id = r25_booking[ref]; origin = "r25_existing"
            if event_id is None:
                approval = _digits(historical.get("appr")); family = FAMILY_MAP.get(str(historical.get("src")))
                resolved = _resolve_approval(hist_groups, current_groups, family, approval)
                if resolved is not None:
                    event_id = str(resolved["direct_event_key"]); origin = "approval_family_relation"
                elif ref == TARGET_REF:
                    ambiguities.append({"uid": historical["uid"], "approval": approval, "historical_cardinality": len(hist_groups.get((family, approval), [])), "current_cardinality": len(current_groups.get((family, approval), []))})
            if event_id is None: continue
            key = (ref, event_id)
            if key not in seen_coverage:
                coverage.append({"booking_reference": ref, "direct_event_key": event_id, "coverage_origin": origin, "r25_union_member": event_id in r25_union}); seen_coverage.add(key)
            if ref != TARGET_REF or origin != "approval_family_relation": continue
            approval = _digits(historical["appr"]); family = str(FAMILY_MAP[historical["src"]]); current = current_groups[(family, approval)][0]
            fact_hash = _sha(_json({"booking_reference": ref, **facts[ref]})); hist_hash = _sha(_json(historical))
            relation_id = _sha(_json({"rule": RULE_SHA256, "fact": fact_hash, "historical": hist_hash, "event": event_id}))
            relations.append({
                "relation_id": relation_id, "booking_reference": ref, "booking_category": facts[ref]["category"], "booking_period": facts[ref]["period"], "booking_fact_row_sha256": fact_hash,
                "mail_message_id": message["messageId"], "mail_message_hash": message["messageHash"], "mail_redaction_version": message.get("redactionVersion", ""),
                "historical_uid": historical["uid"], "historical_row_sha256": hist_hash, "historical_source": historical["src"], "historical_use_date": historical["use_date"], "historical_amount_krw": historical["krw"], "historical_approval_raw": historical["appr"],
                "approval_normalized": approval, "issuer_family": family, "historical_cardinality": 1, "current_cardinality": 1,
                "direct_event_key": event_id, "current_event_sha256": current_hashes[event_id], "current_source_system": current["source_system"], "current_use_date": current["date"], "current_amount_krw": current["amount"], "current_source_kind": current["source_kind"], "current_source_key": current["source_key"], "current_source_sha256": current["source_sha"],
                "issuer_subtype_mismatch": historical["src"] != current["source_system"], "date_conflict": historical["use_date"] != current["date"], "r25_union_member": event_id in r25_union, "coverage_status": "r25_overlap" if event_id in r25_union else "r26_only",
                "relation_kind": "booking_support", "disposition": "booking_relation_proposal", "authority_status": "unattested", "posting_status": "blocked", "confirmed_count": 0, "gate5_credit": 0,
            })
    relations.sort(key=lambda x: str(x["direct_event_key"])); coverage.sort(key=lambda x: (str(x["booking_reference"]), str(x["direct_event_key"])))
    refs_by_event: dict[str, set[str]] = defaultdict(set)
    for row in coverage: refs_by_event[str(row["direct_event_key"])].add(str(row["booking_reference"]))
    ambiguities.extend({"direct_event_key": event, "booking_references": sorted(values)} for event, values in refs_by_event.items() if len(values) > 1)
    coverage_events = {str(row["direct_event_key"]) for row in coverage}
    relation_events = {str(row["direct_event_key"]) for row in relations}
    r23_events = {str(row["direct_event_key"]) for row in coverage if row["coverage_origin"] == "r23_existing"}
    coverage_r25_overlap = coverage_events & r25_union
    relation_r25_overlap = relation_events & r25_union
    r26_only = relation_events - r25_union
    if (len(coverage_events), len(r23_events), len(coverage_r25_overlap), len(relation_events), len(relation_r25_overlap), len(r26_only)) != (19, 11, 5, 7, 4, 3):
        raise ValueError("r26_binding_counts_mismatch")
    actual_relations = {(str(r["historical_uid"]), str(r["approval_normalized"]), str(r["direct_event_key"])) for r in relations}
    if actual_relations != EXPECTED_RELATIONS or relation_r25_overlap != EXPECTED_KOMAGANE_R25 or coverage_r25_overlap != EXPECTED_KOMAGANE_R25 | EXPECTED_OTHER_R25:
        raise ValueError("r26_exact_mapping_mismatch")
    if ambiguities: raise ValueError("r26_ambiguity_detected")
    date_pairs = {str(r["historical_uid"]): (str(r["historical_use_date"]), str(r["current_use_date"])) for r in relations}
    if date_pairs.get("TRIP-0090") != ("2026-03-12", "2026-03-27") or sum(bool(r["date_conflict"]) for r in relations) != 1:
        raise ValueError("r26_date_conflict_contract_invalid")
    group_id = _sha(_json({"rule": RULE_SHA256, "booking": TARGET_REF, "events": [r["direct_event_key"] for r in relations]}))
    for row in relations: row["booking_group_id"] = group_id
    relation_bytes = _csv_bytes(RELATION_COLUMNS, relations); coverage_bytes = _csv_bytes(COVERAGE_COLUMNS, coverage)
    remaining_before = int(r25_manifest["counts"]["remaining_after_individual_proposal_union"])
    counts = {"facts": len(facts), "linked_unique_events": len(coverage_events), "r23_duplicate": len(r23_events), "r25_union_overlap": len(coverage_r25_overlap), "r26_only_events": len(r26_only), "new_booking_relations": len(relation_events), "ambiguous": len(ambiguities), "remaining_before": remaining_before, "remaining_after": remaining_before-len(r26_only)}
    if remaining_before != 3829 or counts["remaining_after"] != 3826: raise ValueError("r26_remaining_count_invalid")
    expected_set_sha = _sha(_json(sorted(EXPECTED_RELATIONS)))
    base = {"format_version": 1, "artifact_type": ARTIFACT_TYPE, "authority_status": "unattested", "posting_status": "blocked", "confirmed_count": 0, "gate5_credit": 0, "rule_contract_version": RULE_VERSION, "rule_contract_sha256": RULE_SHA256, "family_mapping": FAMILY_MAP, "expected_relation_set_sha256": expected_set_sha, "booking_periods_sha256": _sha(facts_raw), "ota_mail_sha256": _sha(mail_raw), "target_mail_row_sha256": _sha(_json(message)), "classified_v14_sha256": _sha(classified_raw), "manual_raw_sha256": _sha(manual_csv.read_bytes()), "input_manifest_sha256": r25_manifest["input_manifest_sha256"], "candidate_semantic_sha256": r25_manifest["candidate_semantic_sha256"], "current_event_set_sha256": r25_manifest["current_event_set_sha256"], "decision_scope_sha256": r25_manifest["decision_scope_sha256"], "r23_rule_contract_sha256": r23_result["manifest"]["rule_contract_sha256"], "r23_envelope_set_sha256": r23_result["manifest"]["envelope_set_sha256"], "r25_package_set_sha256": r25_manifest["package_set_sha256"], "booking_group_id": group_id, "counts": counts, "files": {"relations.csv": {"sha256": _sha(relation_bytes), "rows": len(relations)}, "coverage.csv": {"sha256": _sha(coverage_bytes), "rows": len(coverage)}}}
    package_sha = _sha(_json(base) + relation_bytes + coverage_bytes)
    manifest = {**base, "package_set_sha256": package_sha, "analysis_run_id": _sha(_json({"artifact_type": ARTIFACT_TYPE, "package_set_sha256": package_sha, "current_event_set_sha256": base["current_event_set_sha256"]}))}
    return manifest, {"manifest.json": _json(manifest), "relations.csv": relation_bytes, "coverage.csv": coverage_bytes}


def build_verified_booking_evidence(*, booking_periods: Path, ota_mail: Path, manual_csv: Path, ledger_dir: Path = REPOSITORY_ROOT / "ledger", output: Path | None = None) -> dict[str, object]:
    if output is not None:
        parent = output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r26_output_inside_repository")
        if os.path.lexists(output): raise FileExistsError("r26_output_exists")
    manifest, files = _build(booking_periods=booking_periods.resolve(strict=True), ota_mail=ota_mail.resolve(strict=True), manual_csv=manual_csv.resolve(strict=True), ledger_dir=ledger_dir)
    if output is not None:
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(parent)))
        try:
            for name, data in files.items():
                with (stage / name).open("wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
            _fsync_directory(stage)
            verify_verified_booking_evidence(stage, booking_periods=booking_periods, ota_mail=ota_mail, manual_csv=manual_csv, ledger_dir=ledger_dir, current=False)
            _install_noreplace(stage, output)
            _fsync_directory(parent)
        except Exception: shutil.rmtree(stage, ignore_errors=True); raise
    return {"manifest": manifest, "manifest_sha256": _sha(files["manifest.json"]), "output": None if output is None else str(output)}


def verify_verified_booking_evidence(directory: Path, *, booking_periods: Path, ota_mail: Path, manual_csv: Path, ledger_dir: Path = REPOSITORY_ROOT / "ledger", current: bool = True) -> dict[str, object]:
    if directory.is_symlink() or not directory.is_dir() or sorted(x.name for x in directory.iterdir()) != sorted(FILES): raise ValueError("r26_package_shape_invalid")
    if any((directory / name).is_symlink() or not (directory / name).is_file() or not stat.S_ISREG((directory / name).stat().st_mode) or (directory / name).stat().st_nlink != 1 for name in FILES): raise ValueError("r26_package_file_invalid")
    actual = {name: (directory / name).read_bytes() for name in FILES}; manifest = json.loads(actual["manifest.json"])
    if (manifest.get("authority_status"), manifest.get("posting_status"), manifest.get("confirmed_count"), manifest.get("gate5_credit")) != ("unattested", "blocked", 0, 0): raise ValueError("r26_authority_boundary_invalid")
    expected_manifest, expected = _build(booking_periods=booking_periods.resolve(strict=True), ota_mail=ota_mail.resolve(strict=True), manual_csv=manual_csv.resolve(strict=True), ledger_dir=ledger_dir)
    if actual != expected: raise ValueError("r26_live_context_or_semantics_mismatch" if current else "r26_staging_semantics_mismatch")
    return {"status": "valid", "analysis_run_id": expected_manifest["analysis_run_id"], "relations": 7, "r26_only_events": 3}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--booking-periods", type=Path, required=True); parser.add_argument("--ota-mail", type=Path, required=True); parser.add_argument("--manual-csv", type=Path, required=True); parser.add_argument("--output", type=Path); parser.add_argument("--verify", type=Path); args = parser.parse_args()
    try:
        result = verify_verified_booking_evidence(args.verify, booking_periods=args.booking_periods, ota_mail=args.ota_mail, manual_csv=args.manual_csv) if args.verify else build_verified_booking_evidence(booking_periods=args.booking_periods, ota_mail=args.ota_mail, manual_csv=args.manual_csv, output=args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())
