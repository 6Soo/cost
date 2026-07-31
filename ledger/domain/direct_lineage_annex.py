"""R23A non-authoritative exact lineage proposal annex (temp output only)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import tempfile
import shutil
import uuid
import os
import errno
import ctypes
from pathlib import Path

from ledger.domain.direct_projection import (
    REPOSITORY_ROOT,
    _apply_schema,
    build_source_inventory,
    candidate_semantic_snapshot,
    project_card_payments,
)
from ledger.domain.direct_sources import import_all
from ledger.domain.source_adapters import stable_card_event_identity
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.transition_gates_v2 import REQUIRED_INPUTS, SCHEMA_VERSION, _current_direct_event_hashes, _decision_scope_sha256, input_manifest_sha256

ANNEX_VERSION = "r23a-lineage-proposal-v1"
RULE_CONTRACT_VERSION = "r23a-exact-compound-v2"
RULE_CONTRACT_SHA256 = ""
CLASSIFIED_SHA256 = "8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


RULE_CONTRACT_SHA256 = _sha((ANNEX_VERSION + "\n" + RULE_CONTRACT_VERSION + "\n").encode())


def _json(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _historical(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _key(source: str, date: object, amount: object, approval: object, card4: object) -> tuple[str, str, int, str, str]:
    digits = lambda value: "".join(char for char in str(value or "") if char.isdigit())
    return source, str(date or ""), int(amount), digits(approval), digits(card4)[-4:]


CSV_COLUMNS = ("direct_event_key", "current_event_sha256", "lineage_tier", "posted_date_exact", "merchant_exact", "collision_reason", "disposition", "historical_uid", "historical_file", "historical_file_sha256", "historical_row_sha256", "current_source_kind", "current_source_key", "current_source_sha256", "proposal_json")


def _events_bytes(envelopes: list[dict[str, object]]) -> bytes:
    import io
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for envelope in envelopes:
        values = []
        for name in CSV_COLUMNS[:-1]:
            value = envelope[name]
            values.append("" if value is None else str(value).lower() if isinstance(value, bool) else str(value))
        values.append(json.dumps(envelope["proposal"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
        writer.writerow(values)
    return stream.getvalue().encode("utf-8")


def _install_noreplace(stage: Path, target: Path) -> None:
    if os.path.lexists(target):
        raise FileExistsError("r23_output_exists")
    try:
        renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2")
    except AttributeError:
        renameat2 = None
    if renameat2 is not None:
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        parent_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            result = renameat2(parent_fd, os.fsencode(stage.name), parent_fd, os.fsencode(target.name), 1)
        finally:
            os.close(parent_fd)
        if result == 0:
            return
        if ctypes.get_errno() == errno.EEXIST:
            raise FileExistsError("r23_output_exists")
        raise OSError(ctypes.get_errno(), "renameat2")
    raise OSError("r23_atomic_noreplace_unsupported")


def _build_temp_db(ledger_dir: Path, temp_root: Path) -> tuple[sqlite3.Connection, str, list[dict[str, object]], str, str]:
    inventory = build_source_inventory(ledger_dir, REPOSITORY_ROOT)
    db = connect(temp_root / "r23.db"); initialize(db); _apply_schema(db)
    run_id = "analysis-temp"
    canonical_input_hash = input_manifest_sha256(inventory)
    db.execute("INSERT INTO direct_projection_runs(run_id,status,schema_version,input_manifest_sha256,code_commit,code_bundle_sha256) VALUES(?,?,?,?,?,?)", (run_id, "building", SCHEMA_VERSION, canonical_input_hash, "temp", "temp"))
    for item in inventory:
        db.execute("INSERT INTO direct_projection_inputs(run_id,source_kind,relative_path,raw_sha256,lf_sha256,byte_count,key_set_sha256,record_count,parser_version) VALUES(?,?,?,?,?,?,?,?,?)", (run_id, item["source_kind"], item["relative_path"], item["raw_sha256"], item["lf_sha256"], item["byte_count"], item["key_set_sha256"], item["record_count"], item["parser_version"]))
    import_all(db, ledger_dir, ledger_dir / "data/manual_v4.csv", ledger_dir / "data/ota_mail_index.json")
    project_card_payments(db, run_id)
    semantic = candidate_semantic_snapshot(db, run_id)
    db.execute("UPDATE direct_projection_runs SET candidate_semantic_sha256=? WHERE run_id=?", (semantic, run_id)); db.commit()
    hashes, eventset, scope = _current_direct_event_hashes(db, run_id)
    return db, run_id, inventory, eventset, scope, hashes


def build_annex(*, ledger_dir: Path = REPOSITORY_ROOT / "ledger", output: Path | None = None) -> dict[str, object]:
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
        raise ValueError("r23_noncanonical_ledger")
    with tempfile.TemporaryDirectory(prefix="r23a-") as dirname:
        db, run_id, inventory, eventset, scope, current_hashes = _build_temp_db(ledger_dir, Path(dirname))
        try:
            rows = db.execute("""
                SELECT d.card_event_id,d.event_role,p.source_system,p.occurred_on,d.amount_krw,
                       p.approval_number,pm.last4,p.external_key,s.payload_json,p.posted_on,p.merchant,s.source_kind,s.source_key,s.source_sha256
                FROM direct_payment_projection_links l JOIN payment_transactions p ON p.id=l.payment_id
                JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
                JOIN direct_source_records s ON s.id=d.source_record_id
                LEFT JOIN payment_methods pm ON pm.id=p.payment_method_id
                WHERE l.run_id=? ORDER BY d.card_event_id,d.event_role
            """, (run_id,)).fetchall()
            classified_path = ledger_dir / "data/classified_v14.csv"
            classified_sha = _sha(classified_path.read_bytes())
            if classified_sha != CLASSIFIED_SHA256:
                raise ValueError("r23_classified_hash_mismatch")
            historical = _historical(classified_path)
            groups: dict[tuple[str, str, int, str, str], list[dict[str, str]]] = {}
            for item in historical:
                try:
                    if item.get("src") not in {"KBD", "KBO", "HAN", "CORP"}: continue
                    amount = int(item.get("krw") or 0)
                    if item.get("src") in {"KBO", "CORP"} and str(item.get("cancel")).lower() == "true": amount = -abs(amount)
                    groups.setdefault(_key(item.get("src"), item.get("use_date"), amount, item.get("appr"), item.get("card4")), []).append(item)
                except (TypeError, ValueError): pass
            current_groups: dict[tuple[str, str, int, str, str], list[tuple]] = {}
            for row in rows:
                payload = json.loads(row[8]); current_groups.setdefault(_key(row[2], payload.get("use_date") or row[3], row[4], payload.get("appr") or row[5], payload.get("card4") or row[6]), []).append(row)
            strict_historical: dict[tuple, list[dict[str, str]]] = {}
            for item in historical:
                try:
                    if item.get("src") not in {"KBD", "KBO", "HAN", "CORP"}: continue
                    amount = int(item.get("krw") or 0)
                    if item.get("src") in {"KBO", "CORP"} and str(item.get("cancel")).lower() == "true": amount = -abs(amount)
                    strict_historical.setdefault(_key(item.get("src"), item.get("use_date"), amount, item.get("appr"), item.get("card4")) + (str(item.get("post_date") or ""), str(item.get("merchant") or "")), []).append(item)
                except (TypeError, ValueError): pass
            strict_current: dict[tuple, list[tuple]] = {}
            for row in rows:
                payload = json.loads(row[8]); strict_current.setdefault(_key(row[2], payload.get("use_date") or row[3], row[4], payload.get("appr") or row[5], payload.get("card4") or row[6]) + (str(payload.get("post_date") or ""), str(payload.get("merchant") or "")), []).append(row)
            independent_matches = [values[0] for key, values in strict_current.items() if len(values) == 1 and len(strict_historical.get(key, [])) == 1]
            isolated = [(key, values[0], strict_historical[key][0]) for key, values in strict_current.items() if len(values) == 1 and len(strict_historical.get(key, [])) == 1]
            independent_high = sum(1 for _, _, historical_row in isolated if historical_row.get("confidence") == "상" and historical_row.get("tax_conf") == "상")
            independent_high_complete = sum(1 for _, _, historical_row in isolated if historical_row.get("confidence") == "상" and historical_row.get("tax_conf") == "상" and all(str(historical_row.get(field) or "").strip() for field in ("bucket", "account", "cost_type")))
            envelopes = []; exact = 0; high = 0; source_counts = {source: 0 for source in ("KBD", "KBO", "HAN", "CORP")}; stable_count = 0; posted_merchant_count = 0; strongest_count = 0
            for row in rows:
                payload = json.loads(row[8]); card4 = payload.get("card4") or row[6]
                key = _key(row[2], payload.get("use_date") or row[3], row[4], payload.get("appr") or row[5], card4); candidates = groups.get(key, [])
                chosen = candidates[0] if len(candidates) == 1 and len(current_groups[key]) == 1 else None
                if chosen is not None:
                    exact += 1
                    source_counts[row[2]] = source_counts.get(row[2], 0) + 1
                    if chosen.get("confidence") == "상" and chosen.get("tax_conf") == "상" and all(chosen.get(field, "").strip() for field in ("bucket", "account", "cost_type")): high += 1
                posted_exact = bool(chosen and chosen.get("post_date") == payload.get("post_date"))
                merchant_exact = bool(chosen and (chosen.get("merchant") == payload.get("merchant") or chosen.get("merchant") == row[10]))
                if chosen and posted_exact and merchant_exact: posted_merchant_count += 1
                if chosen and posted_exact and merchant_exact and chosen.get("confidence") == "상" and chosen.get("tax_conf") == "상": strongest_count += 1
                stable = bool(chosen and stable_card_event_identity({**chosen, "raw_record_id": chosen.get("uid")}).card_event_id == row[0])
                if stable: stable_count += 1
                collision_reason = "current_duplicate" if len(current_groups[key]) > 1 else ("historical_duplicate" if len(candidates) > 1 else ("no_exact_candidate" if not candidates else None))
                envelopes.append({"direct_event_key": f"{row[0]}#{row[1]}", "current_event_sha256": current_hashes.get(f"{row[0]}#{row[1]}"), "lineage_tier": "stable_identity" if stable else ("compound_exact" if chosen else "unmatched"), "posted_date_exact": posted_exact, "merchant_exact": merchant_exact, "collision_reason": collision_reason, "disposition": "historical_high_complete_proposal" if chosen and chosen.get("confidence") == "상" and chosen.get("tax_conf") == "상" and all(chosen.get(field, "").strip() for field in ("bucket", "account", "cost_type")) else ("historical_proposal" if chosen else "evidence_blocked"), "historical_uid": chosen.get("uid") if chosen else None, "historical_file": "ledger/data/classified_v14.csv" if chosen else None, "historical_file_sha256": CLASSIFIED_SHA256 if chosen else None, "historical_row_sha256": _sha(_json(chosen)) if chosen else None, "proposal": {field: chosen.get(field) for field in ("bucket", "account", "cost_type", "vat_tag", "confidence", "tax_conf")} if chosen else None, "current_source_kind": row[11], "current_source_key": row[12], "current_source_sha256": row[13]})
            envelopes.sort(key=lambda item: item["direct_event_key"])
            input_hash = input_manifest_sha256(inventory); semantic_hash = candidate_semantic_snapshot(db, run_id)
            events_bytes = _events_bytes(envelopes)
            envelope_set_sha256 = _sha(events_bytes)
            analysis_run_id = _sha(_json({"annex_version": ANNEX_VERSION, "rule_contract_version": RULE_CONTRACT_VERSION, "rule_contract_sha256": RULE_CONTRACT_SHA256, "input_manifest_sha256": input_hash, "candidate_semantic_sha256": semantic_hash, "current_event_set_sha256": eventset, "decision_scope_sha256": scope, "classified_v14_sha256": CLASSIFIED_SHA256, "envelope_set_sha256": envelope_set_sha256}))
            current_collision_groups = sum(1 for values in current_groups.values() if len(values) > 1); current_collision_rows = sum(len(values) for values in current_groups.values() if len(values) > 1); historical_collision_groups = sum(1 for values in groups.values() if len(values) > 1); historical_collision_rows = sum(len(values) for values in groups.values() if len(values) > 1)
            manifest = {"format_version": 1, "artifact_type": ANNEX_VERSION, "authority_status": "unattested", "posting_status": "blocked", "confirmed_count": 0, "gate5_credit": 0, "analysis_run_id": analysis_run_id, "analysis_run_format": "content-addressed-r23a-v1", "rule_contract_version": RULE_CONTRACT_VERSION, "rule_contract_sha256": RULE_CONTRACT_SHA256, "envelope_set_sha256": envelope_set_sha256, "input_manifest_sha256": input_hash, "candidate_semantic_sha256": semantic_hash, "current_event_set_sha256": eventset, "decision_scope_sha256": scope, "classified_v14_sha256": CLASSIFIED_SHA256, "source_counts": source_counts, "counts": {"direct": len(envelopes), "exact_proposals": exact, "stable_identity": stable_count, "p0_high_complete": high, "other_proposals": exact - high, "unmatched": len(envelopes) - exact, "compound_posted_merchant_exact": posted_merchant_count, "compound_high_high_both_exact": strongest_count, "independent_posted_merchant_exact": len(independent_matches), "independent_high_high": independent_high, "independent_high_high_complete": independent_high_complete, "collision_current_groups": current_collision_groups, "collision_current_rows": current_collision_rows, "collision_historical_groups": historical_collision_groups, "collision_historical_rows": historical_collision_rows}}
            manifest["events_sha256"] = envelope_set_sha256; manifest["events_row_count"] = len(envelopes); manifest_bytes = _json(manifest)
            package = {"manifest": manifest, "envelopes": envelopes}
            result = {"manifest_sha256": _sha(manifest_bytes), "events_sha256": _sha(events_bytes), "manifest": manifest, "package": package}
            if output is not None:
                parent = output.parent.resolve(strict=True)
                try: parent.relative_to(REPOSITORY_ROOT.resolve())
                except ValueError: pass
                else: raise ValueError("r23_output_inside_repository")
                target = parent / output.name
                if os.path.lexists(target): raise FileExistsError("r23_output_exists")
                stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(parent)))
                try:
                    (stage / "manifest.json").write_bytes(manifest_bytes); (stage / "events.csv").write_bytes(events_bytes)
                    verify_annex(stage, current=False)
                    _install_noreplace(stage, target)
                except Exception: shutil.rmtree(stage, ignore_errors=True); raise
                result["output"] = target.as_posix()
            return result
        finally: db.close()


def verify_annex(directory: Path, *, current: bool = True) -> dict[str, object]:
    manifest_path = directory / "manifest.json"; events_path = directory / "events.csv"
    manifest_bytes = manifest_path.read_bytes(); events_bytes = events_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    required = {"format_version", "artifact_type", "authority_status", "posting_status", "confirmed_count", "gate5_credit", "analysis_run_id", "analysis_run_format", "rule_contract_version", "rule_contract_sha256", "envelope_set_sha256", "input_manifest_sha256", "candidate_semantic_sha256", "current_event_set_sha256", "decision_scope_sha256", "classified_v14_sha256", "source_counts", "counts", "events_sha256", "events_row_count"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("r23_manifest_schema_invalid")
    if manifest.get("format_version") != 1 or manifest.get("artifact_type") != ANNEX_VERSION or manifest.get("analysis_run_format") != "content-addressed-r23a-v1" or manifest.get("rule_contract_version") != RULE_CONTRACT_VERSION or manifest.get("rule_contract_sha256") != RULE_CONTRACT_SHA256:
        raise ValueError("r23_manifest_schema_invalid")
    hashes = ("analysis_run_id", "rule_contract_sha256", "envelope_set_sha256", "input_manifest_sha256", "candidate_semantic_sha256", "current_event_set_sha256", "decision_scope_sha256", "classified_v14_sha256", "events_sha256")
    if any(not isinstance(manifest.get(name), str) or len(manifest[name]) != 64 or any(c not in "0123456789abcdef" for c in manifest[name]) for name in hashes):
        raise ValueError("r23_manifest_hash_invalid")
    expected_run_id = _sha(_json({"annex_version": ANNEX_VERSION, "rule_contract_version": RULE_CONTRACT_VERSION, "rule_contract_sha256": manifest["rule_contract_sha256"], "input_manifest_sha256": manifest["input_manifest_sha256"], "candidate_semantic_sha256": manifest["candidate_semantic_sha256"], "current_event_set_sha256": manifest["current_event_set_sha256"], "decision_scope_sha256": manifest["decision_scope_sha256"], "classified_v14_sha256": manifest["classified_v14_sha256"], "envelope_set_sha256": manifest["envelope_set_sha256"]}))
    if manifest["analysis_run_id"] != expected_run_id:
        raise ValueError("r23_manifest_context_mismatch")
    if manifest["envelope_set_sha256"] != manifest["events_sha256"]:
        raise ValueError("r23_envelope_hash_mismatch")
    if not isinstance(manifest.get("source_counts"), dict) or not isinstance(manifest.get("counts"), dict):
        raise ValueError("r23_manifest_schema_invalid")
    if manifest.get("events_sha256") != _sha(events_bytes):
        raise ValueError("r23_events_hash_mismatch")
    if manifest.get("authority_status") != "unattested" or manifest.get("posting_status") != "blocked" or manifest.get("confirmed_count") != 0 or manifest.get("gate5_credit") != 0:
        raise ValueError("r23_authority_boundary_invalid")
    with events_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = ["direct_event_key", "current_event_sha256", "lineage_tier", "posted_date_exact", "merchant_exact", "collision_reason", "disposition", "historical_uid", "historical_file", "historical_file_sha256", "historical_row_sha256", "current_source_kind", "current_source_key", "current_source_sha256", "proposal_json"]
        if reader.fieldnames != expected:
            raise ValueError("r23_events_schema_invalid")
        rows = list(reader)
    if len(rows) != manifest.get("counts", {}).get("direct") or manifest.get("events_row_count") != len(rows):
        raise ValueError("r23_events_count_mismatch")
    keys = [row.get("direct_event_key") for row in rows]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError("r23_event_keys_invalid")
    for row in rows:
        if len(row["current_event_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["current_event_sha256"]):
            raise ValueError("r23_event_hash_invalid")
        if row["lineage_tier"] not in {"stable_identity", "compound_exact", "unmatched"}:
            raise ValueError("r23_event_tier_invalid")
        if row["posted_date_exact"] not in {"true", "false"} or row["merchant_exact"] not in {"true", "false"}:
            raise ValueError("r23_event_discrepancy_invalid")
        if row["collision_reason"] not in {"", "current_duplicate", "historical_duplicate", "no_exact_candidate"}:
            raise ValueError("r23_event_collision_invalid")
        try:
            proposal = json.loads(row["proposal_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("r23_event_proposal_invalid") from exc
        if proposal is not None and not isinstance(proposal, dict):
            raise ValueError("r23_event_proposal_invalid")
    if current:
        expected = build_annex()
        expected_manifest = _json(expected["manifest"])
        expected_events = _events_bytes(expected["package"]["envelopes"])
        if manifest_bytes != expected_manifest or events_bytes != expected_events:
            raise ValueError("r23_live_context_or_semantics_mismatch")
    return {"status": "valid", "manifest_sha256": _sha(manifest_bytes), "events_sha256": _sha(events_bytes), "row_count": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("--verify", type=Path); args = parser.parse_args()
    try:
        if args.verify is not None:
            result = verify_annex(args.verify); print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
        result = build_annex(output=args.output); summary = {key: value for key, value in result.items() if key != "package"}; print(json.dumps(summary, ensure_ascii=False, sort_keys=True)); return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False)); return 2


if __name__ == "__main__": raise SystemExit(main())
