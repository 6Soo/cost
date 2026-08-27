"""R27 content-bound, non-authoritative repository booking/OTA proposals."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
from collections import defaultdict
from pathlib import Path

from ledger.domain.direct_external_manual_evidence import _build_package as _build_r25
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _build_temp_db, _install_noreplace, build_annex
from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity
import ledger.domain.direct_verified_booking_evidence as r26_contract
from ledger.domain.direct_verified_booking_evidence import EXPECTED_RELATIONS as R26_RELATIONS, RULE_SHA256 as R26_RULE_SHA256

ARTIFACT_TYPE = "r27-repository-booking-evidence-v1"
RULE_VERSION = "r27-r23-uid-first-booking-ota-v1"
FILES = ("manifest.json", "relations.csv", "coverage.csv", "ambiguities.csv")
FAMILY_MAP = {"KBD": "KB", "KBO": "KB", "HAN": "HAN", "CORP": "CORP"}
BOOKING_SHA256 = "1e456ecd17fc5d078141d9645d7179d24d912b0b857e710a5e1019d7d4047549"
OTA_SHA256 = "2a3bc075b0d7596d5d99bef9dd7b9fda61a88428cf833e48042f55fbe6801b27"
CLASSIFIED_SHA256 = "8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989"
BOOKING_ROW_SET_SHA256 = "8faccd52420dac615d14858702664ccb5d7073f139d94332c8d4a6181d4e140a"
OTA_ROW_SET_SHA256 = "60f357304c4e8f31ec13dc329b0f474674f6b164c1bfb389f04cdb9c216c5f1d"
OTA_FIELD_SHAPE_COUNT = 21
OTA_FIELD_SHAPE_SHA256 = "5d07a1b9b69106097b926adbfe0c11c9deffa2c122096aaaf7691e75b012511d"
R26_BOOKING_PERIODS_SHA256 = "2c56525285c31f613708b76b7831fff1510ccb15ade8f97eb3d27adb3397955e"
R26_OTA_MAIL_SHA256 = "db258948ff2240b682d579422c4de3edbc5079e6425a8fd7c0a224f57c40cb11"
R26_RULE_SHA256_EXPECTED = "6be5e32d60828544ae35be23e5c73edb9ba0d268fce6611f2921aeffb81bae2c"
R26_RELATION_SET_SHA256_EXPECTED = "cf75a2f848d444d2c03ddf1e397157a7113baeb9f61057afffb0d0b5a85ee70c"
RELATION_KIND = "repository_booking_support"
DISPOSITION = "booking_ota_relation_proposal"
GROUP_IDS = ("hashidate", "pearl_city")
AUTHORITY = ("unattested", "blocked", 0, 0)
SENSITIVE_DENYLIST = frozenset({"guest", "passenger", "pnr", "card4", "reference_code", "pin", "url",
                                "access_token", "match_score", "match_reasons", "amount", "currency", "hotel"})

EXPECTED_BOOKING_NEW = {
    ("1400823535413714", "TRIP-0016", "30091900", "card:48e1e168a410c6f16201e9b4fab3ce5ed6d3df5fb550ae3bf750a58c986b7a0f#single"),
    ("1400823535395178", "TRIP-0020", "30091786", "card:02796fec16c1b63c4eb9fefa5c60886c4496e93ac99a60fee8a6af648236a0be#single"),
    ("1400823535402604", "TRIP-0021", "30091843", "card:49c5c61c8ad22acb1be8c124335765750149f81c7e086fd29fe30cf0890b7fbc#single"),
    ("1400823535393192", "TRIP-0022", "30091809", "card:bb18d6e8c87da9475b276ec659ac9c4671ed697f22d2b758e1e9bece54a259d6#single"),
}
EXPECTED_OTA_NEW = {
    ("TRIP-0024", "1400823535575464", "30091988", "card:bd7c68a00ca50a928f8b23ba7d022110f24c0c58660f29171f239821bea9d31f#single"),
    ("TRIP-0025", "1400823535575464", "30091966", "card:323d9d484e32ce2c1415fdd1346988369aefd189da446f8790eb1dc8eec90361#single"),
}
EXPECTED_BOOKING_AMBIGUITIES = {
    ("KBO-2652", "6851343288"), ("KBO-2883", "6474894255"),
    ("KBO-2884", "5437691600"), ("KBO-2951", "1738849062"),
    ("KBO-2949", "1696943284"), ("KBO-0376", "1723193688"),
    ("KBO-0377", "1723193688"),
}
EXPECTED_OTA_AMBIGUITIES = {"TRIP-0170", "TRIP-0102", "TRIP-0107", "TRIP-0113", "TRIP-0429"}
EXPECTED_COUNTS = {
    "booking_facts": 54, "ota_facts": 68, "booking_exact_token_edges": 60,
    "booking_resolved_via_r23_uid_edges": 40, "booking_approval_path_eligible_edges": 13,
    "booking_approval_path_ineligible_edges": 47, "booking_resolved_edges": 53,
    "booking_prior_overlap_events": 49, "booking_new_events": 4, "booking_unresolved_edges": 7,
    "ota_resolved_via_r23_uid": 23, "ota_resolved_via_approval": 40,
    "ota_resolved_events": 63, "ota_prior_overlap_events": 61, "ota_new_events": 2,
    "ota_unresolved_uids": 5, "r23_events": 1227, "r25_events": 272, "r26_events": 7,
    "prior_union": 1502, "r27_only": 6, "remaining_before": 3826, "remaining_after": 3820,
}

RELATION_COLUMNS = (
    "relation_id", "source_tier", "source_uid", "source_row_sha256", "booking_reference",
    "historical_uid", "historical_row_sha256", "historical_source", "historical_approval_raw",
    "approval_normalized", "issuer_family", "historical_cardinality", "current_cardinality",
    "direct_event_key", "current_event_sha256", "current_source_system", "current_source_kind",
    "current_source_key", "current_source_sha256", "resolution_origin", "prior_union_member",
    "issuer_subtype_mismatch", "group_id", "group_member_set_sha256", "relation_kind",
    "disposition", "authority_status", "posting_status", "confirmed_count", "gate5_credit",
)
COVERAGE_COLUMNS = (
    "source_tier", "source_uid", "source_row_sha256", "booking_reference", "historical_uid",
    "direct_event_key", "resolution_origin", "prior_union_member",
)
AMBIGUITY_COLUMNS = (
    "source_tier", "source_uid", "source_row_sha256", "booking_reference", "historical_uid", "reason_code",
    "historical_cardinality", "current_cardinality",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: str(row.get(name, "")).lower() if isinstance(row.get(name), bool) else row.get(name, "") for name in columns})
    return stream.getvalue().encode()


def _strict_json(path: Path) -> tuple[object, bytes]:
    raw = path.read_bytes()
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("r27_json_duplicate_key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=object_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("r27_json_nonfinite")))
    return value, raw


def _digits(value: object) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"[0-9]+", text) and set(text) != {"0"} else ""


def _booking_tokens(value: object) -> set[str]:
    return set(re.findall(r"예약(?:번호|코드)?\s*([0-9]{8,19})(?![0-9])", str(value or "")))


def _regular_single_link(path: Path, code: str) -> None:
    if path.is_symlink() or not path.is_file(): raise ValueError(code)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ValueError(code)


def _fsync_directory(path: Path) -> None:
    descriptor = open_dir(path)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _resolve_approval(hist_groups, current_groups, family: str | None, approval: str):
    historical = hist_groups.get((family, approval), []) if family and approval else []
    current = current_groups.get((family, approval), []) if family and approval else []
    return (current[0], len(historical), len(current)) if len(historical) == len(current) == 1 else (None, len(historical), len(current))


def _resolve_uid_first(uid: str, r23_by_uid, current_by_event, hist_groups, current_groups,
                       family: str | None, approval: str):
    if uid in r23_by_uid:
        event = current_by_event.get(r23_by_uid[uid])
        if event is None: raise ValueError("r27_r23_event_not_current")
        return event, "r23_uid_existing", 1, 1
    event, historical_cardinality, current_cardinality = _resolve_approval(
        hist_groups, current_groups, family, approval)
    return event, "approval_family_1x1" if event is not None else "", historical_cardinality, current_cardinality


RULE_SHA256 = _sha(_json({
    "artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION, "family_map": FAMILY_MAP,
    "booking_sha256": BOOKING_SHA256, "ota_sha256": OTA_SHA256, "classified_sha256": CLASSIFIED_SHA256,
    "expected_booking_new": sorted(EXPECTED_BOOKING_NEW), "expected_ota_new": sorted(EXPECTED_OTA_NEW),
    "expected_booking_ambiguities": sorted(EXPECTED_BOOKING_AMBIGUITIES),
    "expected_ota_ambiguities": sorted(EXPECTED_OTA_AMBIGUITIES), "expected_counts": EXPECTED_COUNTS,
    "relation_columns": RELATION_COLUMNS, "coverage_columns": COVERAGE_COLUMNS,
    "ambiguity_columns": AMBIGUITY_COLUMNS, "resolution_precedence": ["r23_exact_uid", "approval_family_1x1"],
    "booking_row_set_sha256": BOOKING_ROW_SET_SHA256, "ota_row_set_sha256": OTA_ROW_SET_SHA256,
    "ota_field_shape_count": OTA_FIELD_SHAPE_COUNT, "ota_field_shape_sha256": OTA_FIELD_SHAPE_SHA256,
    "relation_kind": RELATION_KIND, "disposition": DISPOSITION, "group_ids": GROUP_IDS,
    "sensitive_denylist": sorted(SENSITIVE_DENYLIST), "authority": AUTHORITY,
    "r26_booking_periods_sha256": R26_BOOKING_PERIODS_SHA256, "r26_ota_mail_sha256": R26_OTA_MAIL_SHA256,
    "r26_rule_contract_sha256": R26_RULE_SHA256_EXPECTED,
    "r26_exact_relation_set_sha256": R26_RELATION_SET_SHA256_EXPECTED,
}))


def _validate_inputs(booking_info: Path, ota_links: Path, manual_csv: Path, ledger_dir: Path):
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve(): raise ValueError("r27_noncanonical_ledger")
    if booking_info.resolve() != (ledger_dir / "data/booking_info.json").resolve(): raise ValueError("r27_noncanonical_booking_info")
    if ota_links.resolve() != (ledger_dir / "data/ota_event_links_verified.json").resolve(): raise ValueError("r27_noncanonical_ota_links")
    for path, code in ((booking_info, "r27_booking_file_invalid"), (ota_links, "r27_ota_file_invalid"),
                       (manual_csv, "r27_manual_file_invalid")):
        _regular_single_link(path, code)


def _validate_bound_file(path: Path, expected_path: Path, expected_sha256: str, code: str) -> str:
    if path.resolve() != expected_path.resolve(): raise ValueError(f"{code}_noncanonical")
    _regular_single_link(path, f"{code}_file_invalid")
    actual = _sha(path.read_bytes())
    if actual != expected_sha256: raise ValueError(f"{code}_hash_mismatch")
    return actual


def _validate_r26_upstream(ledger_dir: Path) -> dict[str, str]:
    periods = ledger_dir / "data/booking_periods_verified.json"
    ota_mail = ledger_dir / "data/ota_mail_index.json"
    periods_sha = _validate_bound_file(periods, REPOSITORY_ROOT / "ledger/data/booking_periods_verified.json",
                                       R26_BOOKING_PERIODS_SHA256, "r27_r26_booking_periods")
    ota_sha = _validate_bound_file(ota_mail, REPOSITORY_ROOT / "ledger/data/ota_mail_index.json",
                                   R26_OTA_MAIL_SHA256, "r27_r26_ota_mail")
    relation_sha = _sha(_json(sorted(r26_contract.EXPECTED_RELATIONS)))
    if r26_contract.RULE_SHA256 != R26_RULE_SHA256_EXPECTED or relation_sha != R26_RELATION_SET_SHA256_EXPECTED:
        raise ValueError("r27_r26_code_contract_drift")
    return {"booking_periods_sha256":periods_sha, "ota_mail_sha256":ota_sha,
            "rule_contract_sha256":r26_contract.RULE_SHA256, "relation_set_sha256":relation_sha}


def _build(*, booking_info: Path, ota_links: Path, manual_csv: Path, ledger_dir: Path):
    exported_names = set(RELATION_COLUMNS) | set(COVERAGE_COLUMNS) | set(AMBIGUITY_COLUMNS)
    if exported_names & SENSITIVE_DENYLIST:
        raise ValueError("r27_sensitive_schema_invalid")
    _validate_inputs(booking_info, ota_links, manual_csv, ledger_dir)
    r26_upstream = _validate_r26_upstream(ledger_dir)
    bookings, booking_raw = _strict_json(booking_info); ota, ota_raw = _strict_json(ota_links)
    if _sha(booking_raw) != BOOKING_SHA256: raise ValueError("r27_booking_hash_mismatch")
    if _sha(ota_raw) != OTA_SHA256: raise ValueError("r27_ota_hash_mismatch")
    if not isinstance(bookings, dict) or len(bookings) != 54: raise ValueError("r27_booking_schema_invalid")
    for ref, fact in bookings.items():
        if not isinstance(ref, str) or not re.fullmatch(r"[0-9]{8,19}", ref): raise ValueError("r27_booking_reference_invalid")
        if not isinstance(fact, dict) or set(fact) != {"label", "period"}: raise ValueError("r27_booking_fact_schema_invalid")
        if any(not isinstance(fact[x], str) or not fact[x].strip() for x in ("label", "period")): raise ValueError("r27_booking_fact_type_invalid")
    if not isinstance(ota, dict) or len(ota) != 68: raise ValueError("r27_ota_schema_invalid")
    for uid, fact in ota.items():
        if not isinstance(uid, str) or not uid or not isinstance(fact, dict): raise ValueError("r27_ota_fact_schema_invalid")
    booking_row_hashes = {ref:_sha(_json({"booking_reference":ref, **fact})) for ref, fact in bookings.items()}
    ota_row_hashes = {uid:_sha(_json({"uid":uid, **fact})) for uid, fact in ota.items()}
    booking_row_set_sha = _sha(_json(sorted(booking_row_hashes.items())))
    ota_row_set_sha = _sha(_json(sorted(ota_row_hashes.items())))
    ota_shapes = sorted({tuple(sorted(fact)) for fact in ota.values()})
    ota_shape_sha = _sha(_json(ota_shapes))
    if (booking_row_set_sha, ota_row_set_sha, len(ota_shapes), ota_shape_sha) != (
        BOOKING_ROW_SET_SHA256, OTA_ROW_SET_SHA256, OTA_FIELD_SHAPE_COUNT, OTA_FIELD_SHAPE_SHA256):
        raise ValueError("r27_source_row_or_schema_set_invalid")

    classified_path = ledger_dir / "data/classified_v14.csv"; classified_raw = classified_path.read_bytes()
    if _sha(classified_raw) != CLASSIFIED_SHA256: raise ValueError("r27_classified_hash_mismatch")
    classified = list(csv.DictReader(io.StringIO(classified_raw.decode("utf-8-sig"))))
    by_uid = defaultdict(list)
    hist_groups = defaultdict(list)
    for row in classified:
        by_uid[str(row["uid"])].append(row)
        approval = _digits(row.get("appr")); family = FAMILY_MAP.get(str(row.get("src")))
        if approval and family: hist_groups[(family, approval)].append(row)

    r23_result = build_annex(ledger_dir=ledger_dir); r23_rows = r23_result["package"]["envelopes"]
    r23_candidates = defaultdict(list)
    for item in r23_rows:
        if item.get("historical_uid"): r23_candidates[str(item["historical_uid"])].append(str(item["direct_event_key"]))
    if any(len(values) != 1 for values in r23_candidates.values()): raise ValueError("r27_r23_uid_cardinality_invalid")
    r23_by_uid = {uid: values[0] for uid, values in r23_candidates.items()}; r23_events = set(r23_by_uid.values())

    r25_manifest, r25_files = _build_r25(manual_csv, ledger_dir)
    r25_proposals = list(csv.DictReader(io.StringIO(r25_files["proposals.csv"].decode())))
    r25_evidence = list(csv.DictReader(io.StringIO(r25_files["evidence_sets.csv"].decode())))
    r25_events = {r["direct_event_key"] for r in r25_proposals}
    r25_events |= {r["direct_event_key"] for r in r25_evidence if r["evidence_tier"] in {"clean_110", "typed_v14_65", "portal_1"}}

    r26_events = {row[2] for row in R26_RELATIONS}
    if (len(r23_events), len(r25_events), len(r26_events), len(r23_events & r25_events),
        len(r23_events & r26_events), len(r25_events & r26_events)) != (1227, 272, 7, 0, 0, 4):
        raise ValueError("r27_prior_components_invalid")
    prior = r23_events | r25_events | r26_events
    if len(prior) != 1502: raise ValueError("r27_prior_union_invalid")

    with tempfile.TemporaryDirectory(prefix="r27-current-") as dirname:
        db, run_id, _inventory, event_set_sha, decision_scope_sha, current_hashes = _build_temp_db(ledger_dir, Path(dirname))
        rows = db.execute("""
            SELECT d.card_event_id||'#'||d.event_role,p.source_system,p.approval_number,s.payload_json,
                   s.source_kind,s.source_key,s.source_sha256
            FROM direct_payment_projection_links l JOIN payment_transactions p ON p.id=l.payment_id
            JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
            JOIN direct_source_records s ON s.id=d.source_record_id WHERE l.run_id=? ORDER BY 1
        """, (run_id,)).fetchall(); db.close()
    current_groups = defaultdict(list); current_by_event = {}
    for row in rows:
        payload = json.loads(row[3]); approval = _digits(payload.get("appr") or row[2]); family = FAMILY_MAP.get(str(row[1]))
        event = {"event": row[0], "source_system": row[1], "source_kind": row[4], "source_key": row[5], "source_sha": row[6]}
        current_by_event[str(row[0])] = event
        if approval and family: current_groups[(family, approval)].append(event)
    if len(rows) != 5328 or len(current_by_event) != 5328:
        raise ValueError("r27_current_event_set_size_invalid")
    if not r26_events <= set(current_by_event):
        raise ValueError("r27_r26_current_membership_invalid")

    coverage = []; ambiguities = []; resolved = []
    approval_eligible = 0; approval_ineligible = 0; booking_r23 = 0
    for historical in classified:
        for ref in sorted(set(bookings) & _booking_tokens(historical.get("note"))):
            uid = str(historical["uid"]); approval = _digits(historical.get("appr")); family = FAMILY_MAP.get(str(historical.get("src")))
            event, origin, hc, cc = _resolve_uid_first(uid, r23_by_uid, current_by_event, hist_groups,
                                                       current_groups, family, approval)
            if origin == "r23_uid_existing": booking_r23 += 1
            elif event is not None: approval_eligible += 1
            else:
                approval_ineligible += 1
                ambiguities.append({"source_tier":"booking_info", "source_uid":ref,
                    "source_row_sha256":booking_row_hashes[ref], "booking_reference":ref,
                    "historical_uid":uid, "reason_code":"approval_identity_unresolved", "historical_cardinality":hc,
                    "current_cardinality":cc})
            if event is not None:
                source_hash = booking_row_hashes[ref]
                item = {"source_tier":"booking_info", "source_uid":ref, "source_row_sha256":source_hash,
                    "booking_reference":ref, "historical_uid":uid, "historical":historical, "event":event,
                    "approval":approval, "family":family, "origin":origin}
                resolved.append(item); coverage.append({"source_tier":"booking_info", "source_uid":ref,
                    "source_row_sha256":source_hash, "booking_reference":ref, "historical_uid":uid,
                    "direct_event_key":event["event"], "resolution_origin":origin, "prior_union_member":event["event"] in prior})

    ota_r23 = 0; ota_approval = 0
    for uid, fact in ota.items():
        historical_rows = by_uid.get(uid, [])
        if len(historical_rows) != 1: raise ValueError("r27_ota_uid_cardinality_invalid")
        historical = historical_rows[0]; approval = _digits(historical.get("appr")); family = FAMILY_MAP.get(str(historical.get("src")))
        event, origin, hc, cc = _resolve_uid_first(uid, r23_by_uid, current_by_event, hist_groups,
                                                   current_groups, family, approval)
        if origin == "r23_uid_existing": ota_r23 += 1
        elif event is not None: ota_approval += 1
        else:
            ambiguities.append({"source_tier":"ota_event_links", "source_uid":uid,
                "source_row_sha256":ota_row_hashes[uid],
                "booking_reference":str(fact.get("booking_id") or ""), "historical_uid":uid,
                "reason_code":"approval_identity_unresolved", "historical_cardinality":hc,
                "current_cardinality":cc}); continue
        source_hash = ota_row_hashes[uid]; booking_ref = str(fact.get("booking_id") or "")
        item = {"source_tier":"ota_event_links", "source_uid":uid, "source_row_sha256":source_hash,
            "booking_reference":booking_ref, "historical_uid":uid, "historical":historical, "event":event,
            "approval":approval, "family":family, "origin":origin}
        resolved.append(item); coverage.append({"source_tier":"ota_event_links", "source_uid":uid,
            "source_row_sha256":source_hash, "booking_reference":booking_ref, "historical_uid":uid,
            "direct_event_key":event["event"], "resolution_origin":origin, "prior_union_member":event["event"] in prior})

    booking_resolved = [x for x in resolved if x["source_tier"] == "booking_info"]
    ota_resolved = [x for x in resolved if x["source_tier"] == "ota_event_links"]
    booking_new = [x for x in booking_resolved if x["event"]["event"] not in prior]
    ota_new = [x for x in ota_resolved if x["event"]["event"] not in prior]
    actual_booking_new = {(x["booking_reference"],x["historical_uid"],x["approval"],x["event"]["event"]) for x in booking_new}
    actual_ota_new = {(x["source_uid"],x["booking_reference"],x["approval"],x["event"]["event"]) for x in ota_new}
    actual_booking_ambiguities = {(x["historical_uid"],x["booking_reference"]) for x in ambiguities if x["source_tier"] == "booking_info"}
    actual_ota_ambiguities = {x["source_uid"] for x in ambiguities if x["source_tier"] == "ota_event_links"}
    if actual_booking_new != EXPECTED_BOOKING_NEW or actual_ota_new != EXPECTED_OTA_NEW:
        raise ValueError("r27_exact_new_set_invalid")
    if actual_booking_ambiguities != EXPECTED_BOOKING_AMBIGUITIES or actual_ota_ambiguities != EXPECTED_OTA_AMBIGUITIES:
        raise ValueError("r27_exact_ambiguity_set_invalid")
    if approval_ineligible != 7:
        raise ValueError("r27_approval_ineligible_count_invalid")

    counts = {
        "booking_facts":len(bookings), "ota_facts":len(ota), "booking_exact_token_edges":len(booking_resolved)+len(actual_booking_ambiguities),
        "booking_resolved_via_r23_uid_edges":booking_r23, "booking_approval_path_eligible_edges":approval_eligible,
        "booking_approval_path_ineligible_edges":booking_r23+len(actual_booking_ambiguities),
        "booking_resolved_edges":len(booking_resolved), "booking_prior_overlap_events":sum(x["event"]["event"] in prior for x in booking_resolved),
        "booking_new_events":len(booking_new), "booking_unresolved_edges":len(actual_booking_ambiguities),
        "ota_resolved_via_r23_uid":ota_r23, "ota_resolved_via_approval":ota_approval,
        "ota_resolved_events":len(ota_resolved), "ota_prior_overlap_events":sum(x["event"]["event"] in prior for x in ota_resolved),
        "ota_new_events":len(ota_new), "ota_unresolved_uids":len(actual_ota_ambiguities),
        "r23_events":len(r23_events), "r25_events":len(r25_events), "r26_events":len(r26_events), "prior_union":len(prior),
        "r27_only":len({x["event"]["event"] for x in booking_new+ota_new}), "remaining_before":5328-len(prior),
        "remaining_after":5328-len(prior)-len({x["event"]["event"] for x in booking_new+ota_new}),
    }
    if counts != EXPECTED_COUNTS: raise ValueError("r27_binding_counts_invalid")

    group_members = {
        "hashidate": sorted((x["source_uid"], x["event"]["event"]) for x in booking_new),
        "pearl_city": sorted((x["source_uid"], x["event"]["event"]) for x in ota_new),
    }
    group_hashes = {name:_sha(_json({"rule":RULE_SHA256,"group":name,"members":members})) for name,members in group_members.items()}
    relations = []
    for x in sorted(booking_new + ota_new, key=lambda z:(z["source_tier"],z["source_uid"],z["event"]["event"])):
        group = "hashidate" if x["source_tier"] == "booking_info" else "pearl_city"
        historical = x["historical"]; event = x["event"]
        hist_hash = _sha(_json(historical))
        relation_id = _sha(_json({"rule":RULE_SHA256,"source":x["source_row_sha256"],"historical":hist_hash,"event":event["event"]}))
        relations.append({"relation_id":relation_id, "source_tier":x["source_tier"], "source_uid":x["source_uid"],
            "source_row_sha256":x["source_row_sha256"], "booking_reference":x["booking_reference"],
            "historical_uid":x["historical_uid"], "historical_row_sha256":hist_hash,
            "historical_source":historical["src"], "historical_approval_raw":historical["appr"],
            "approval_normalized":x["approval"], "issuer_family":x["family"], "historical_cardinality":1,
            "current_cardinality":1, "direct_event_key":event["event"], "current_event_sha256":current_hashes[event["event"]],
            "current_source_system":event["source_system"], "current_source_kind":event["source_kind"],
            "current_source_key":event["source_key"], "current_source_sha256":event["source_sha"],
            "resolution_origin":x["origin"], "prior_union_member":False,
            "issuer_subtype_mismatch":historical["src"] != event["source_system"], "group_id":group,
            "group_member_set_sha256":group_hashes[group], "relation_kind":RELATION_KIND,
            "disposition":DISPOSITION, "authority_status":AUTHORITY[0], "posting_status":AUTHORITY[1],
            "confirmed_count":0, "gate5_credit":0})

    coverage.sort(key=lambda x:(x["source_tier"],x["source_uid"],x["historical_uid"],x["direct_event_key"]))
    ambiguities.sort(key=lambda x:(x["source_tier"],x["source_uid"],x["historical_uid"]))
    relation_bytes = _csv_bytes(RELATION_COLUMNS, relations); coverage_bytes = _csv_bytes(COVERAGE_COLUMNS, coverage)
    ambiguity_bytes = _csv_bytes(AMBIGUITY_COLUMNS, ambiguities)
    base = {"format_version":1, "artifact_type":ARTIFACT_TYPE, "rule_contract_version":RULE_VERSION,
        "rule_contract_sha256":RULE_SHA256, "authority_status":AUTHORITY[0], "posting_status":AUTHORITY[1],
        "confirmed_count":AUTHORITY[2], "gate5_credit":AUTHORITY[3], "booking_info_sha256":_sha(booking_raw),
        "ota_event_links_sha256":_sha(ota_raw), "classified_v14_sha256":_sha(classified_raw),
        "manual_raw_sha256":_sha(manual_csv.read_bytes()), "input_manifest_sha256":r25_manifest["input_manifest_sha256"],
        "candidate_semantic_sha256":r25_manifest["candidate_semantic_sha256"],
        "current_event_set_sha256":event_set_sha, "decision_scope_sha256":decision_scope_sha,
        "r23_rule_contract_sha256":r23_result["manifest"]["rule_contract_sha256"],
        "r23_envelope_set_sha256":r23_result["manifest"]["envelope_set_sha256"],
        "r25_package_set_sha256":r25_manifest["package_set_sha256"],
        "r26_rule_contract_sha256":r26_upstream["rule_contract_sha256"],
        "r26_exact_relation_set_sha256":r26_upstream["relation_set_sha256"],
        "r26_booking_periods_sha256":r26_upstream["booking_periods_sha256"],
        "r26_ota_mail_sha256":r26_upstream["ota_mail_sha256"],
        "booking_row_set_sha256":booking_row_set_sha, "ota_row_set_sha256":ota_row_set_sha,
        "ota_field_shape_count":len(ota_shapes), "ota_field_shape_sha256":ota_shape_sha,
        "relation_kind":RELATION_KIND, "disposition":DISPOSITION,
        "prior_union_set_sha256":_sha(_json(sorted(prior))),
        "expected_new_set_sha256":_sha(_json(sorted(EXPECTED_BOOKING_NEW | EXPECTED_OTA_NEW))),
        "expected_ambiguity_set_sha256":_sha(_json({"booking":sorted(EXPECTED_BOOKING_AMBIGUITIES),"ota":sorted(EXPECTED_OTA_AMBIGUITIES)})),
        "group_member_set_sha256":group_hashes, "counts":counts,
        "files":{"relations.csv":{"sha256":_sha(relation_bytes),"rows":len(relations)},
                 "coverage.csv":{"sha256":_sha(coverage_bytes),"rows":len(coverage)},
                 "ambiguities.csv":{"sha256":_sha(ambiguity_bytes),"rows":len(ambiguities)}}}
    package_sha = _sha(_json(base)+relation_bytes+coverage_bytes+ambiguity_bytes)
    manifest = {**base, "package_set_sha256":package_sha,
        "analysis_run_id":_sha(_json({"artifact_type":ARTIFACT_TYPE,"rule":RULE_SHA256,"package":package_sha,
                                      "event_set":event_set_sha,"scope":decision_scope_sha}))}
    return manifest, {"manifest.json":_json(manifest), "relations.csv":relation_bytes,
                      "coverage.csv":coverage_bytes, "ambiguities.csv":ambiguity_bytes}


def build_repository_booking_evidence(*, booking_info: Path, ota_links: Path, manual_csv: Path,
                                      ledger_dir: Path = REPOSITORY_ROOT / "ledger", output: Path | None = None):
    if output is not None:
        parent = output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r27_output_inside_repository")
        if os.path.lexists(output): raise FileExistsError("r27_output_exists")
    manifest, files = _build(booking_info=booking_info, ota_links=ota_links,
                             manual_csv=manual_csv, ledger_dir=ledger_dir)
    if output is not None:
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(parent)))
        try:
            os.chmod(stage, 0o700)
            for name, data in files.items():
                with (stage/name).open("wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.chmod(stage/name, 0o600)
            _fsync_directory(stage)
            verify_repository_booking_evidence(stage, booking_info=booking_info, ota_links=ota_links,
                                               manual_csv=manual_csv, ledger_dir=ledger_dir, current=False)
            _install_noreplace(stage, output); _fsync_directory(parent)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True); raise
    return {"manifest":manifest, "manifest_sha256":_sha(files["manifest.json"]),
            "output":None if output is None else str(output)}


def verify_repository_booking_evidence(directory: Path, *, booking_info: Path, ota_links: Path, manual_csv: Path,
                                       ledger_dir: Path = REPOSITORY_ROOT / "ledger", current: bool = True):
    if directory.is_symlink() or not directory.is_dir() or sorted(x.name for x in directory.iterdir()) != sorted(FILES):
        raise ValueError("r27_package_shape_invalid")
    for name in FILES: _regular_single_link(directory/name, "r27_package_file_invalid")
    actual = {name:(directory/name).read_bytes() for name in FILES}
    parsed, _ = _strict_json(directory/"manifest.json")
    if not isinstance(parsed, dict) or (parsed.get("authority_status"),parsed.get("posting_status"),
        parsed.get("confirmed_count"),parsed.get("gate5_credit")) != ("unattested","blocked",0,0):
        raise ValueError("r27_authority_boundary_invalid")
    expected_manifest, expected = _build(booking_info=booking_info, ota_links=ota_links,
                                         manual_csv=manual_csv, ledger_dir=ledger_dir)
    if actual != expected: raise ValueError("r27_live_context_or_semantics_mismatch" if current else "r27_staging_semantics_mismatch")
    return {"status":"valid", "analysis_run_id":expected_manifest["analysis_run_id"], "relations":6,
            "ambiguities":12, "remaining_after":3820}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--booking-info",type=Path,required=True)
    parser.add_argument("--ota-links",type=Path,required=True); parser.add_argument("--manual-csv",type=Path,required=True)
    parser.add_argument("--output",type=Path); parser.add_argument("--verify",type=Path); args=parser.parse_args()
    try:
        result = verify_repository_booking_evidence(args.verify,booking_info=args.booking_info,ota_links=args.ota_links,manual_csv=args.manual_csv) if args.verify else build_repository_booking_evidence(booking_info=args.booking_info,ota_links=args.ota_links,manual_csv=args.manual_csv,output=args.output)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"invalid","error":str(exc)},ensure_ascii=False,sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())