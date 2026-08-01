"""R38 external-only evidence for one exact, complete lodging group.

The artifact is review evidence only: it never confirms, posts, applies, or
asserts a row-level pairing between the two card events and two manual rows.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_narrow_service_classification as r37
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _install_noreplace

ARTIFACT_TYPE = "r38-structured-lodging-evidence-v1"
RULE_VERSION = "r38-complete-group-booking-info-lodging-v1"
FILES = ("manifest.json", "groups.csv", "proposals.csv", "exclusions.csv")
AUTHORITY = ("unattested", "blocked", 0, 0, False)
ACCOUNT, COST_TYPE, VAT_TAG = "숙박비", "여행원가", "불공제_해외"
GROUP_ID = "40319d742d280c667f2cf24987b8fe4688665ac21c92049f11e8f20fe0b89f5d"
SELECTED_SET_SHA256 = "a9028357c44eb89e9bbd554a7afa08663968f9f809012091de8da43e836a7578"
SEMANTIC_SHA256 = "df45ad8aaf42471b185a3e3220cd32939d99b700c697f69234f59814e0902d4b"
R37_DEFERRED_SHA256 = "21b547424d55929029ff41bf94773d485ee75aad90d4185607979668493e936e"
REMAINING_SET_SHA256 = "ab199a1614713567304b19deaeb0871e849b8e7d813b6a3449d2ad3d393f5d16"
BOOKING_INFO_SHA256 = "1e456ecd17fc5d078141d9645d7179d24d912b0b857e710a5e1019d7d4047549"
REFERENCE_SET_SHA256 = "da80e393d22620a33b2281400c3f0162f53479a10591c222cb6b600312c6a2e2"
BOOKING_ROW_SHA256 = "ab7bbc6361a4118a5d0a34beba39dabbd17d04b190447e97ecd7efb491a927fc"
PERIOD_SET_SHA256 = "056acb404c864c1ec214a4991bdfca49ce8f03cb4ef7cefa8cc0e47d07ebf2eb"
EXCLUSION_SEMANTIC_SHA256 = "ee443cb1e0eca18d19ee208b3f6f27a2b1cf0fd56aa4e00439a2c80940c54ebc"
R37_RULE_SHA256 = "6884b0ec2f29402ea9aa3a6adc6270c7ada52798f0aea4210c9773503029ad69"
R37_PACKAGE_SHA256 = "cc94a804d0a4c48ec185963e4196a7f29d23704de599791380ae09aa34ef083f"
R36_RULE_SHA256 = "8d387e86bcf2ef4688ec633a154034eae70948845197d9418f7a821ebc34d966"
R36_PACKAGE_SHA256 = "1ed12e9188bc4c4b09eff2176cbda5f4006d0b332652deadd782e065ba52c6de"
GROUP_FACTS = {"compound_key_sha256": "7da8d444454151fcd1dd6a554389815c382166d5459486583225e57f74e5c7f0",
 "current_source_locator_set_sha256": "b2673c421f6e9f7b28ef4dabbb2b9b7496b5fdc821604bef433755e4298e52a3",
 "manual_locator_set_sha256": "fc48d29334d8c721860eacd107b2f2864d6cd2045b70e8c106599c71f88dc8aa",
 "manual_row_set_sha256": "29658aa8fadfbb4e1b915d179cb8bb2d11cafc0a3d975ef26baa62ead042a386",
 "bucket": "0613_북해도", "trip_row_sha256": "6b4d4e6c52d640f0c1ed30e9f76af9949c912dbabd89090532d2f24ad62a4fea"}
EXPECTED_EVENTS = {
 "card:9f448b8dd1f3e86a8be75e94706a3ba12eb8d6aeb94dfdb0283610f00493d5e4#single":
  ("794a426b83378e32007f59c4264ab38a63decda36b20475db2f20f2463a5bc7b", "58dc6d5a32c7b018bb2885a273ed837f57564b931bc3b8782e09ac50515b7ad3", "62abf55ed66e59c0557a5456ef253430f6794925e0b3d9fc628a926d5c8862f6", "5f2f4e246299344842bd48ce01a8354795d8a3f7b785486be32b21fad26f1e4c"),
 "card:f6924a2fc2e020c902f653368df0e7ba94e9dd0d7bb054476190524a5ac72b7d#single":
  ("ff4b887446707963e7f3a752a98a47d147fc8ba360a040b9816d07258b041cf7", "8523064013714e009d71fd3425ae20f49268c670cd6ffb82060f41d232718a8b", "f8179239193cb935d1bfc44fa9f4fec00525a0705b0cbd052dc06b07071cfc3f", "b8c3cf14af3f9be79248dd76fd3a14f621c0c03862e68e18384918bf4acd476e")}

GROUP_COLUMNS = ("group_id", "member_set_sha256", "member_count", "compound_key_sha256",
 "current_source_locator_set_sha256", "manual_locator_set_sha256", "manual_row_set_sha256", "bucket", "trip_row_sha256",
 "manual_member_count", "booking_reference_set_sha256", "booking_row_set_sha256",
 "booking_member_count", "relation_kind", "bijection_asserted", "disposition",
 "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")
PROPOSAL_COLUMNS = ("proposal_id", "direct_event_key", "current_event_sha256",
 "current_source_locator_sha256", "group_id", "group_member_set_sha256", "account",
 "cost_type", "vat_tag", "bucket", "trip_row_sha256", "evidence_family_sha256", "relation_kind", "bijection_asserted",
 "disposition", "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")

class PublicationDurabilityError(OSError):
    def __init__(self, output: Path, expected_package_sha256: str) -> None:
        super().__init__("r38_published_but_parent_fsync_failed"); self.output = output
        self.expected_package_sha256 = expected_package_sha256; self.published = True; self.parent_fsync = False
EXCLUSION_COLUMNS = ("exclusion_id", "direct_event_key", "current_event_sha256",
 "current_source_locator_sha256", "group_id", "group_member_set_sha256", "reason_code",
 "disposition", "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")

def _csv(columns: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: str(row.get(k, "")).lower() if isinstance(row.get(k), bool) else row.get(k, "") for k in columns})
    return stream.getvalue().encode()

def _semantic(rows: list[dict[str, object]]) -> str:
    values = sorted(({"event": x["direct_event_key"], "account": x["account"],
                      "cost_type": x["cost_type"], "vat_tag": x["vat_tag"]} for x in rows),
                    key=lambda x: x["event"])
    return r36._sha(r36._json(values))

def _trip_bounds(trip: dict[str, object]) -> tuple[date, date]:
    window = trip["window"]
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("r38_trip_window_invalid")
    try:
        start = date(2026, int(trip["mm"]), int(trip["dd"]))
        return start, start + timedelta(days=window - 1)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("r38_trip_window_invalid") from exc

def _build(ledger_dir: Path, manual_csv: Path = r36.DEFAULT_MANUAL_CSV,
           booking_info: Path | None = None) -> tuple[dict[str, object], dict[str, bytes]]:
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
        raise ValueError("r38_noncanonical_ledger")
    canonical_booking = ledger_dir / "data" / "booking_info.json"
    booking_info = canonical_booking if booking_info is None else booking_info
    if booking_info.is_symlink() or booking_info.resolve() != canonical_booking.resolve():
        raise ValueError("r38_noncanonical_booking_info")
    r36._regular_single(booking_info, "r38_booking_info_not_regular_single")
    booking_raw = booking_info.read_bytes()
    if r36._sha(booking_raw) != BOOKING_INFO_SHA256:
        raise ValueError("r38_booking_info_drift")
    bookings = r36._strict_json(booking_raw, "r38_booking_info")
    if not isinstance(bookings, dict) or not bookings: raise ValueError("r38_booking_info_schema_invalid")
    for ref, value in bookings.items():
        if not isinstance(ref, str) or not re.fullmatch(r"[0-9]{6,20}", ref) or not isinstance(value, dict) \
                or set(value) != {"label", "period"} or any(not isinstance(value[k], str) or not value[k].strip() for k in value):
            raise ValueError("r38_booking_info_schema_invalid")

    r37_manifest, r37_files = r37._build(ledger_dir, manual_csv)
    expected37 = (R37_RULE_SHA256, R37_PACKAGE_SHA256, r36.CURRENT_EVENT_SET_SHA256,
        r36.DECISION_SCOPE_SHA256, r36.PRIOR_UNION_SET_SHA256, r36.RESIDUAL_SET_SHA256,
        r37.STRICT_SET_SHA256, r37.STRICT_SEMANTIC_SHA256, R37_DEFERRED_SHA256,
        R36_RULE_SHA256, R36_PACKAGE_SHA256, r36.MANUAL_SHA256, r36.TRIPS_SHA256,
        r36.GROUP_PARTITION_SHA256, r36.GROUP_ID_SET_SHA256)
    actual37 = (r37_manifest.get("rule_contract_sha256"), r37_manifest.get("package_set_sha256"),
        r37_manifest.get("current_event_set_sha256"), r37_manifest.get("decision_scope_sha256"),
        r37_manifest.get("prior_union_set_sha256"), r37_manifest.get("residual_set_sha256"),
        r37_manifest.get("strict_event_set_sha256"), r37_manifest.get("strict_semantic_set_sha256"),
        r37_manifest.get("deferred_event_set_sha256"), r37_manifest.get("r36_rule_contract_sha256"),
        r37_manifest.get("r36_package_set_sha256"), r37_manifest.get("manual_raw_sha256"),
        r37_manifest.get("trips_raw_sha256"), r37_manifest.get("r36_group_partition_sha256"),
        r37_manifest.get("r36_group_id_set_sha256"))
    if actual37 != expected37: raise ValueError("r38_r37_upstream_contract_invalid")
    deferred = list(csv.DictReader(io.StringIO(r37_files["exclusions.csv"].decode())))
    deferred_ids = {x["direct_event_key"] for x in deferred}
    if len(deferred) != 26 or r36._event_set_sha(deferred_ids) != R37_DEFERRED_SHA256:
        raise ValueError("r38_r37_deferred_invalid")
    selected = [x for x in deferred if x["group_id"] == GROUP_ID]
    selected_ids = {x["direct_event_key"] for x in selected}
    if len(selected) != 2 or r36._event_set_sha(selected_ids) != SELECTED_SET_SHA256:
        raise ValueError("r38_exact_group_invalid")
    if set(selected_ids) != set(EXPECTED_EVENTS) or any(x["reason_code"] != "generic_ota_product_unbound" or
       (x["current_event_sha256"], x["current_source_locator_sha256"]) !=
       (EXPECTED_EVENTS[x["direct_event_key"]][0], EXPECTED_EVENTS[x["direct_event_key"]][2]) for x in selected):
        raise ValueError("r38_selected_exclusion_semantic_invalid")

    r36_manifest, r36_files = r36._build(ledger_dir, manual_csv)
    if (r36_manifest.get("rule_contract_sha256"), r36_manifest.get("package_set_sha256"),
        r36_manifest.get("group_partition_sha256"), r36_manifest.get("group_id_set_sha256"),
        r36_manifest.get("manual_raw_sha256"), r36_manifest.get("trips_raw_sha256")) != (
        R36_RULE_SHA256, R36_PACKAGE_SHA256, r36.GROUP_PARTITION_SHA256, r36.GROUP_ID_SET_SHA256,
        r36.MANUAL_SHA256, r36.TRIPS_SHA256): raise ValueError("r38_r36_upstream_contract_invalid")
    group36 = next((x for x in csv.DictReader(io.StringIO(r36_files["groups.csv"].decode())) if x["group_id"] == GROUP_ID), None)
    if group36 is None or group36["current_member_set_sha256"] != SELECTED_SET_SHA256 or \
       int(group36["current_member_count"]) != 2 or int(group36["manual_member_count"]) != 2 or \
       any(group36.get(k) != v for k, v in GROUP_FACTS.items()):
        raise ValueError("r38_r36_group_semantic_invalid")

    trips_raw = (ledger_dir / "data" / "trips.json").read_bytes()
    trips = r36._strict_json(trips_raw, "r38_trips")
    trip = next((x for x in trips if isinstance(x, dict) and x.get("tab") == GROUP_FACTS["bucket"]), None) if isinstance(trips, list) else None
    if trip is None or set(trip) != {"tab", "mm", "dd", "region", "window"} or \
       r36._sha(r36._json(trip)) != GROUP_FACTS["trip_row_sha256"]:
        raise ValueError("r38_trip_row_invalid")
    trip_start, trip_end = _trip_bounds(trip)

    _r25_manifest, r25_files = r36._build_r25(manual_csv, ledger_dir)
    source_groups = list(csv.DictReader(io.StringIO(r25_files["groups.csv"].decode())))
    source = next((x for x in source_groups if x["group_id"] == GROUP_ID), None)
    if source is None or source["group_type"] != "both_duplicate" or int(source["current_cardinality"]) != 2 \
            or int(source["manual_cardinality"]) != 2 or source["current_event_keys_json"] != json.dumps(sorted(selected_ids), separators=(",", ":")):
        raise ValueError("r38_manual_complete_group_invalid")
    references = json.loads(source["manual_locators_json"])
    _raw, manual_rows, malformed = r36._manual(manual_csv)
    by_locator = {str(x["locator"]): x for x in manual_rows}
    rows = [by_locator.get(str(x)) for x in references]
    if len(references) != 2 or len(set(references)) != 2 or any(x is None for x in rows) or len(malformed) != 2:
        raise ValueError("r38_manual_complete_group_invalid")
    booking_refs = [str(x.get("book", "")).strip() for x in rows]
    if len(set(booking_refs)) != 2 or r36._event_set_sha(set(booking_refs)) != REFERENCE_SET_SHA256:
        raise ValueError("r38_booking_reference_coverage_invalid")
    booking_rows = []; periods = []
    for ref in booking_refs:
        value = bookings.get(ref)
        if not isinstance(value, dict) or set(value) != {"label", "period"}:
            raise ValueError("r38_booking_reference_missing")
        if "숙박" not in str(value["period"]) or not any(x in str(value["label"]).upper() for x in ("호텔", "HOTEL", "온센")):
            raise ValueError("r38_booking_lodging_class_invalid")
        match = re.fullmatch(r"숙박_([0-1][0-9][0-3][0-9])_([0-1][0-9][0-3][0-9])", value["period"])
        if not match: raise ValueError("r38_booking_period_invalid")
        try:
            start = date(2026, int(match.group(1)[:2]), int(match.group(1)[2:])); end = date(2026, int(match.group(2)[:2]), int(match.group(2)[2:]))
        except ValueError as exc: raise ValueError("r38_booking_period_invalid") from exc
        if start > end or start < trip_start or end > trip_end: raise ValueError("r38_booking_period_outside_trip")
        periods.append((start.isoformat(), end.isoformat()))
        row_sha = r36._sha(r36._json(value))
        if row_sha != BOOKING_ROW_SHA256: raise ValueError("r38_booking_row_drift")
        booking_rows.append(row_sha)
    if len(set(periods)) != 1: raise ValueError("r38_booking_period_mismatch")
    if r36._sha(r36._json(sorted(periods))) != PERIOD_SET_SHA256: raise ValueError("r38_booking_period_semantic_drift")

    with tempfile.TemporaryDirectory(prefix="r38-current-") as dirname:
        context = r36._context(ledger_dir, Path(dirname)); db = context["db"]
        current_evidence = []
        try:
            events = {x["direct_event_key"]: x for x in context["events"]}
            for event_id in sorted(selected_ids):
                event = events.get(event_id); expected = EXPECTED_EVENTS[event_id]
                if event is None: raise ValueError("r38_current_event_missing")
                raw = db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?", (event["current_source_key"],)).fetchone()
                if not raw: raise ValueError("r38_current_payload_missing")
                payload = r36._strict_json(raw[0].encode() if isinstance(raw[0], str) else raw[0], "r38_current_payload")
                facts = (event["current_event_sha256"], event["current_source_sha256"], r36._source_locator_sha(event), r36._sha(r36._json(payload)))
                if facts != expected: raise ValueError("r38_current_source_drift")
                currency = str(payload.get("currency") or event.get("currency") or "").strip().upper()
                foreign = payload.get("foreign") or event.get("foreign_amount")
                try: positive = Decimal(str(foreign).replace(",", "")) > 0
                except (InvalidOperation, ValueError): positive = False
                if event.get("transaction_type") != "purchase" or event.get("event_role") != "single" or event.get("current_source_kind") != "card_raw" \
                   or not re.fullmatch(r"[A-Z]{3}", currency) or currency == "KRW" or not positive or payload.get("biz") != "해외" \
                   or payload.get("cancel") is not False or str(payload.get("merchant", "")) != str(event.get("merchant", "")):
                    raise ValueError("r38_foreign_purchase_invalid")
                current_evidence.append({"event": event_id, "event_sha": facts[0], "source_sha": facts[1],
                    "source_locator_sha": facts[2], "payload_sha": facts[3], "currency_sha": r36._sha(r36._json(currency))})
        finally: db.close()
    evidence = {"group": GROUP_ID, "events": sorted(selected_ids),
                "manual_rows": sorted(str(x["row_sha256"]) for x in rows),
                "booking_reference_set_sha256": REFERENCE_SET_SHA256,
                "booking_rows": sorted(booking_rows), "periods": sorted(periods),
                "trip_row_sha256": GROUP_FACTS["trip_row_sha256"], "current": current_evidence}
    evidence_sha = r36._sha(r36._json(evidence))

    proposals = []
    for old in sorted(selected, key=lambda x: x["direct_event_key"]):
        item = {"direct_event_key": old["direct_event_key"], "current_event_sha256": old["current_event_sha256"],
            "current_source_locator_sha256": old["current_source_locator_sha256"], "group_id": GROUP_ID,
            "group_member_set_sha256": SELECTED_SET_SHA256, "account": ACCOUNT, "cost_type": COST_TYPE,
            "vat_tag": VAT_TAG, "bucket": GROUP_FACTS["bucket"], "trip_row_sha256": GROUP_FACTS["trip_row_sha256"],
            "evidence_family_sha256": evidence_sha,
            "relation_kind": "complete_group_external_booking_lodging_support", "bijection_asserted": False,
            "disposition": "full_classification_review_proposal", "authority_status": AUTHORITY[0],
            "posting_status": AUTHORITY[1], "confirmed_count": 0, "gate5_credit": 0, "applied": False}
        item["proposal_id"] = r36._sha(r36._json({"artifact": ARTIFACT_TYPE, "event": item["direct_event_key"], "evidence": evidence_sha}))
        proposals.append(item)
    if _semantic(proposals) != SEMANTIC_SHA256: raise ValueError("r38_semantic_set_invalid")

    remaining = [x for x in deferred if x["direct_event_key"] not in selected_ids]
    if len(remaining) != 24 or r36._event_set_sha({x["direct_event_key"] for x in remaining}) != REMAINING_SET_SHA256:
        raise ValueError("r38_remaining_set_invalid")
    exclusions = []
    for old in sorted(remaining, key=lambda x: x["direct_event_key"]):
        item = {k: old[k] for k in ("direct_event_key", "current_event_sha256", "current_source_locator_sha256", "group_id", "group_member_set_sha256")}
        item.update({"reason_code": old["reason_code"], "disposition": "deferred_insufficient_independent_evidence",
                     "authority_status": AUTHORITY[0], "posting_status": AUTHORITY[1], "confirmed_count": 0,
                     "gate5_credit": 0, "applied": False})
        item["exclusion_id"] = r36._sha(r36._json({"artifact": ARTIFACT_TYPE, "event": item["direct_event_key"], "reason": item["reason_code"]}))
        exclusions.append(item)
    exclusion_semantic = r36._sha(r36._json(sorted(({k: x[k] for k in ("direct_event_key", "group_id", "reason_code",
        "current_event_sha256", "current_source_locator_sha256")} for x in exclusions), key=lambda x: x["direct_event_key"])))
    if exclusion_semantic != EXCLUSION_SEMANTIC_SHA256: raise ValueError("r38_remaining_exclusion_semantic_invalid")
    manual_row_set = r36._event_set_sha({str(x["row_sha256"]) for x in rows})
    if manual_row_set != GROUP_FACTS["manual_row_set_sha256"]:
        raise ValueError("r38_manual_row_set_invalid")
    booking_row_set = r36._event_set_sha(set(booking_rows))
    group = {"group_id": GROUP_ID, "member_set_sha256": SELECTED_SET_SHA256, "member_count": 2,
        "compound_key_sha256": GROUP_FACTS["compound_key_sha256"],
        "current_source_locator_set_sha256": GROUP_FACTS["current_source_locator_set_sha256"],
        "manual_locator_set_sha256": GROUP_FACTS["manual_locator_set_sha256"],
        "manual_row_set_sha256": manual_row_set, "bucket": GROUP_FACTS["bucket"],
        "trip_row_sha256": GROUP_FACTS["trip_row_sha256"], "manual_member_count": 2,
        "booking_reference_set_sha256": REFERENCE_SET_SHA256, "booking_row_set_sha256": booking_row_set,
        "booking_member_count": 2, "relation_kind": "complete_group_external_booking_lodging_support",
        "bijection_asserted": False, "disposition": "group_classification_review_proposal",
        "authority_status": AUTHORITY[0], "posting_status": AUTHORITY[1], "confirmed_count": 0,
        "gate5_credit": 0, "applied": False}
    group_bytes = _csv(GROUP_COLUMNS, [group]); proposal_bytes = _csv(PROPOSAL_COLUMNS, proposals); exclusion_bytes = _csv(EXCLUSION_COLUMNS, exclusions)
    rule_sha = r36._sha(r36._json({"artifact": ARTIFACT_TYPE, "version": RULE_VERSION, "authority": AUTHORITY,
        "selected": SELECTED_SET_SHA256, "semantic": SEMANTIC_SHA256, "remaining": REMAINING_SET_SHA256,
        "booking_info": BOOKING_INFO_SHA256, "booking_schema": "numeric-ref-to-exact-label-period-v1",
        "r37_rule": R37_RULE_SHA256, "r37_package": R37_PACKAGE_SHA256,
        "r36_rule": R36_RULE_SHA256, "r36_package": R36_PACKAGE_SHA256,
        "current": r36.CURRENT_EVENT_SET_SHA256, "scope": r36.DECISION_SCOPE_SHA256,
        "prior": r36.PRIOR_UNION_SET_SHA256, "residual": r36.RESIDUAL_SET_SHA256,
        "manual": r36.MANUAL_SHA256, "trips": r36.TRIPS_SHA256, "group_partition": r36.GROUP_PARTITION_SHA256,
        "group_facts": GROUP_FACTS, "expected_events": EXPECTED_EVENTS, "exclusion_semantic": exclusion_semantic,
        "bijection_asserted": False, "historical_classification_seed": False}))
    base = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION, "rule_contract_sha256": rule_sha,
        "authority_status": AUTHORITY[0], "posting_status": AUTHORITY[1], "confirmed_count": 0,
        "gate5_credit": 0, "applied": False, "bijection_asserted": False, "contains_sensitive_raw_values": False,
        "booking_info_sha256": BOOKING_INFO_SHA256, "selected_event_set_sha256": SELECTED_SET_SHA256,
        "semantic_set_sha256": SEMANTIC_SHA256, "remaining_event_set_sha256": REMAINING_SET_SHA256,
        "remaining_exclusion_semantic_sha256": exclusion_semantic,
        "r37_rule_contract_sha256": R37_RULE_SHA256, "r37_package_set_sha256": R37_PACKAGE_SHA256,
        "r36_rule_contract_sha256": R36_RULE_SHA256, "r36_package_set_sha256": R36_PACKAGE_SHA256,
        "current_event_set_sha256": r36.CURRENT_EVENT_SET_SHA256, "decision_scope_sha256": r36.DECISION_SCOPE_SHA256,
        "prior_union_set_sha256": r36.PRIOR_UNION_SET_SHA256, "residual_set_sha256": r36.RESIDUAL_SET_SHA256,
        "manual_raw_sha256": r36.MANUAL_SHA256, "manual_canonical_rows_sha256": r36_manifest["manual_canonical_rows_sha256"],
        "trips_raw_sha256": r36.TRIPS_SHA256, "trips_row_set_sha256": r36_manifest["trips_row_set_sha256"],
        "r36_group_partition_sha256": r36.GROUP_PARTITION_SHA256, "r36_group_id_set_sha256": r36.GROUP_ID_SET_SHA256,
        "evidence_family_sha256": evidence_sha, "counts": {"r37_deferred": 26, "proposals": 2, "remaining": 24,
        "confirmed": 0, "gate5_credit": 0}, "files": {
        "groups.csv": {"sha256": r36._sha(group_bytes), "rows": 1},
        "proposals.csv": {"sha256": r36._sha(proposal_bytes), "rows": 2},
        "exclusions.csv": {"sha256": r36._sha(exclusion_bytes), "rows": 24}}}
    package = r36._sha(r36._json(base) + group_bytes + proposal_bytes + exclusion_bytes)
    manifest = {**base, "package_set_sha256": package,
        "analysis_run_id": r36._sha(r36._json({"artifact": ARTIFACT_TYPE, "rule": rule_sha, "package": package,
            "r37_package": R37_PACKAGE_SHA256, "current": r36.CURRENT_EVENT_SET_SHA256, "scope": r36.DECISION_SCOPE_SHA256}))}
    return manifest, {"manifest.json": r36._json(manifest), "groups.csv": group_bytes,
                      "proposals.csv": proposal_bytes, "exclusions.csv": exclusion_bytes}

def verify_structured_lodging_evidence(directory: Path, *, ledger_dir: Path = REPOSITORY_ROOT / "ledger",
        manual_csv: Path = r36.DEFAULT_MANUAL_CSV, booking_info: Path | None = None, current: bool = True) -> dict[str, object]:
    if directory.is_symlink() or not directory.is_dir() or sorted(x.name for x in directory.iterdir()) != sorted(FILES):
        raise ValueError("r38_package_shape_invalid")
    actual = {}
    for name in FILES: r37._regular_0600(directory / name, "r38_package_file_invalid"); actual[name] = (directory / name).read_bytes()
    parsed = r36._strict_json(actual["manifest.json"], "r38_manifest")
    if not isinstance(parsed, dict) or (parsed.get("authority_status"), parsed.get("posting_status"),
       parsed.get("confirmed_count"), parsed.get("gate5_credit"), parsed.get("applied"),
       parsed.get("bijection_asserted"), parsed.get("contains_sensitive_raw_values")) != (*AUTHORITY, False, False):
        raise ValueError("r38_authority_boundary_invalid")
    manifest, expected = _build(ledger_dir, manual_csv, booking_info)
    if actual != expected: raise ValueError("r38_live_context_or_package_mismatch" if current else "r38_staging_mismatch")
    return {"status": "valid", "analysis_run_id": manifest["analysis_run_id"], "proposals": 2,
            "remaining": 24, "confirmed_count": 0, "gate5_credit": 0}

def reconcile_publication_durability(error: PublicationDurabilityError, *, ledger_dir: Path = REPOSITORY_ROOT / "ledger",
        manual_csv: Path = r36.DEFAULT_MANUAL_CSV, booking_info: Path | None = None) -> dict[str, object]:
    if not isinstance(error, PublicationDurabilityError) or not error.published or error.parent_fsync:
        raise ValueError("r38_publication_state_invalid")
    def check():
        result = verify_structured_lodging_evidence(error.output, ledger_dir=ledger_dir,
            manual_csv=manual_csv, booking_info=booking_info)
        manifest = r36._strict_json((error.output / "manifest.json").read_bytes(), "r38_manifest")
        if not isinstance(manifest, dict) or manifest.get("package_set_sha256") != error.expected_package_sha256:
            raise ValueError("r38_publication_package_mismatch")
        return result
    check(); r37._fsync_dir(error.output.parent.resolve(strict=True)); result = check()
    return {**result, "published": True, "parent_fsync": True,
            "package_set_sha256": error.expected_package_sha256}

def build_structured_lodging_evidence(*, output: Path | None = None, ledger_dir: Path = REPOSITORY_ROOT / "ledger",
        manual_csv: Path = r36.DEFAULT_MANUAL_CSV, booking_info: Path | None = None) -> dict[str, object]:
    manifest, files = _build(ledger_dir, manual_csv, booking_info)
    if output is not None:
        if output.parent.is_symlink(): raise ValueError("r38_output_parent_symlink")
        parent = output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r38_output_inside_repository")
        if os.path.lexists(output): raise FileExistsError("r38_output_exists")
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(parent))); published = False
        try:
            os.chmod(stage, 0o700)
            for name, data in files.items(): r37._write_file(stage / name, data)
            r37._fsync_dir(stage)
            verify_structured_lodging_evidence(stage, ledger_dir=ledger_dir, manual_csv=manual_csv, booking_info=booking_info, current=False)
            _install_noreplace(stage, output); published = True
            try: r37._fsync_dir(parent)
            except Exception as exc: raise PublicationDurabilityError(output, manifest["package_set_sha256"]) from exc
        except Exception:
            if not published: shutil.rmtree(stage, ignore_errors=True)
            raise
    return {"manifest": manifest, "manifest_sha256": r36._sha(files["manifest.json"]),
            "output": None if output is None else str(output)}

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path); parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        result = verify_structured_lodging_evidence(args.verify) if args.verify else build_structured_lodging_evidence(output=args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
    except PublicationDurabilityError as exc:
        print(json.dumps({"status": "published_but_parent_fsync_failed", "published": True,
            "parent_fsync": False, "output": str(exc.output),
            "expected_package_sha256": exc.expected_package_sha256}, ensure_ascii=False, sort_keys=True)); return 3
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, sort_keys=True)); return 2

if __name__ == "__main__": raise SystemExit(main())
