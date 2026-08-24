"""R36 external-only, non-authoritative manual-group taxonomy evidence.

The artifact proves group-level bucket support only.  It never pairs an individual
manual row with an individual card event and never applies a classification.
"""
from __future__ import annotations

import argparse
from ledger.domain.staged_inputs import staged
import csv
import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
from collections import defaultdict
from pathlib import Path

from ledger.domain.direct_external_manual_evidence import (
    _build_package as _build_r25,
    _context,
    _install_noreplace,
    _manual,
)
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.direct_merchant_taxonomy_support import _build as _build_r34, _event_set_sha

ARTIFACT_TYPE = "r36-manual-group-taxonomy-evidence-v1"
RULE_VERSION = "r36-exact-signed-equal-cardinality-group-v1"
FILES = ("manifest.json", "groups.csv", "bucket_support.csv", "classifications.csv")
DEFAULT_MANUAL_CSV = staged("cost-r25-manual-v4.csv")
MANUAL_SHA256 = "2c6d7486458a0921186311780cb2fab26950c13b369d8cf876a5ad04cac10489"
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
CURRENT_EVENT_SET_SHA256 = "de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93"
DECISION_SCOPE_SHA256 = "22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"
PRIOR_UNION_SET_SHA256 = "426b4ec226f804dcfb2f87c8b6f1f8915352169ef401e241945f8c52ee75fc8c"
RESIDUAL_SET_SHA256 = "9963d7104c17151cd5c4d89fb8b4454f30f3f4c177df1e43dd2feab5325a6b21"
R34_SET_SHA256 = "4fd5c0aa99539cf5913ed0584ee979462a692f5dc958230dc3d87c86a96584c9"
R34_SEMANTIC_SHA256 = "1cce4d8542af6c31928b4fbbc269841e2eeda089d7b5ca40e1ac409c635267d7"
BUCKET_SET_SHA256 = "36eb0e2e639d7612281b9b57f49f0fcf4467c6b28545bead8b4edff83a3f72b6"
BUCKET_SEMANTIC_SHA256 = "b90177e4ee958e962b61bab50750d08784e43b1bbf097b0b8fb1ec8272ed53b4"
FULL_SET_SHA256 = "ebe327afacbb9cad91f109dc2e9d5a0c2a3d7fc6608a24ccc679f6b78a17c88b"
FULL_SEMANTIC_SHA256 = "99a61ff658bb66687d5fc078c234dca3814124c7761b3bfc2617975554c84384"
GROUP_PARTITION_SHA256 = "20a516f624254ab5626eeba4b78a71a12a616f47f090a3940c454a416bd73d4c"
GROUP_ID_SET_SHA256 = "5bce525a5f8a2c6de3f7c8432d718475406287ea370a7d7bfc821334f97f563b"
EXCLUDED_MISMATCH_SET_SHA256 = "f4f03ca5967d39215cc0d643f6f307157be6f0da0bcdc593d2f6fa82661cb26b"
AUTHORITY = ("unattested", "blocked", 0, 0, False)
ADVERSE = ("확인", "미정", "검토", "추정")
ISSUERS = {"국민": ("KBD", "KBO"), "하나": ("HAN",), "기업": ("CORP",)}

class PublicationDurabilityError(OSError):
    """The package was published, but its parent directory fsync failed."""
    def __init__(self, output: Path, expected_package_sha256: str) -> None:
        super().__init__("r36_published_but_parent_fsync_failed")
        self.output = output
        self.expected_package_sha256 = expected_package_sha256
        self.published = True
        self.parent_fsync = False

GROUP_COLUMNS = (
    "group_id", "compound_key_sha256", "current_member_set_sha256", "current_member_count",
    "current_source_locator_set_sha256", "manual_locator_set_sha256", "manual_row_set_sha256",
    "manual_member_count", "bucket", "trip_row_sha256",
    "bijection_asserted", "relation_kind", "disposition", "authority_status", "posting_status",
    "confirmed_count", "gate5_credit", "applied",
)
CLASSIFICATION_COLUMNS = (
    "proposal_id", "direct_event_key", "current_event_sha256", "current_source_locator_sha256",
    "group_id", "group_member_set_sha256", "bucket", "r34_proposal_id",
    "r34_taxonomy_key_sha256", "r34_rule_contract_sha256", "account", "cost_type", "vat_tag",
    "transaction_type", "relation_kind", "disposition", "authority_status",
    "posting_status", "confirmed_count", "gate5_credit", "applied",
)
BUCKET_COLUMNS = (
    "proposal_id", "direct_event_key", "current_event_sha256", "current_source_locator_sha256",
    "group_id", "group_member_set_sha256", "bucket", "relation_kind", "disposition",
    "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied",
    "bijection_asserted",
)

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()

def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: str(row.get(key, "")).lower() if isinstance(row.get(key), bool)
                         else row.get(key, "") for key in columns})
    return stream.getvalue().encode()

def _strict_json(raw: bytes, code: str) -> object:
    def hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError(f"{code}_duplicate_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=hook,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError(f"{code}_nonfinite")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{code}_invalid") from exc

def _regular_single(path: Path, code: str) -> None:
    try: info = path.lstat()
    except OSError as exc: raise ValueError(code) from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ValueError(code)

def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try: os.fsync(descriptor)
    finally: os.close(descriptor)

def _source_locator_sha(event: dict[str, object]) -> str:
    return _sha(_json({"kind": event["current_source_kind"], "key": event["current_source_key"],
                       "source_sha256": event["current_source_sha256"]}))

def _semantic_sha(rows: list[dict[str, object]]) -> str:
    values = [{"event": r["direct_event_key"], "bucket": r["bucket"], "account": r["account"],
               "cost_type": r["cost_type"], "vat_tag": r["vat_tag"]} for r in rows]
    values.sort(key=lambda item: item["event"])
    return _sha(_json(values))

def _bucket_semantic_sha(rows: list[dict[str, object]]) -> str:
    values = [{"event": r["direct_event_key"], "group_id": r["group_id"],
               "group_member_set_sha256": r["group_member_set_sha256"],
               "bucket": r["bucket"]} for r in rows]
    values.sort(key=lambda item: item["event"])
    return _sha(_json(values))

RULE_SHA256 = _sha(_json({
    "artifact_type": ARTIFACT_TYPE, "version": RULE_VERSION,
    "identity": ["source_system", "occurred_on", "signed_amount_krw"],
    "cardinality": "current=manual>1", "signed_totals_equal": True,
    "manual_tab": "single_nonblank_declared_trip", "prior_excluded": True,
    "bijection_asserted": False, "full": "bucket44 intersection r34 strict259",
    "adverse_tokens": ADVERSE, "group_columns": GROUP_COLUMNS, "bucket_columns": BUCKET_COLUMNS,
    "classification_columns": CLASSIFICATION_COLUMNS, "authority": AUTHORITY,
    "manual_sha256": MANUAL_SHA256, "trips_sha256": TRIPS_SHA256,
    "current": CURRENT_EVENT_SET_SHA256, "scope": DECISION_SCOPE_SHA256,
    "prior": PRIOR_UNION_SET_SHA256, "residual": RESIDUAL_SET_SHA256,
    "r34_set": R34_SET_SHA256, "r34_semantic": R34_SEMANTIC_SHA256,
    "bucket_set": BUCKET_SET_SHA256, "bucket_semantic": BUCKET_SEMANTIC_SHA256,
    "full_set": FULL_SET_SHA256,
    "full_semantic": FULL_SEMANTIC_SHA256, "partition": GROUP_PARTITION_SHA256,
}))

def _validate_inputs(ledger_dir: Path, manual_csv: Path) -> tuple[list[dict[str, object]], dict[str, dict[str, object]], bytes]:
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve(): raise ValueError("r36_noncanonical_ledger")
    if manual_csv.resolve() != DEFAULT_MANUAL_CSV.resolve(): raise ValueError("r36_noncanonical_manual")
    _regular_single(manual_csv, "r36_manual_file_invalid")
    if _sha(manual_csv.read_bytes()) != MANUAL_SHA256: raise ValueError("r36_manual_hash_mismatch")
    trips_path = ledger_dir / "data/trips.json"; _regular_single(trips_path, "r36_trips_file_invalid")
    trips_raw = trips_path.read_bytes()
    if _sha(trips_raw) != TRIPS_SHA256: raise ValueError("r36_trips_hash_mismatch")
    trips = _strict_json(trips_raw, "r36_trips")
    if not isinstance(trips, list) or len(trips) != 34: raise ValueError("r36_trips_schema_invalid")
    by_tab = {}
    for row in trips:
        if not isinstance(row, dict) or set(row) != {"tab", "mm", "dd", "region", "window"}: raise ValueError("r36_trips_schema_invalid")
        tab = row.get("tab")
        if not isinstance(tab, str) or not tab or tab in by_tab: raise ValueError("r36_trip_tab_invalid")
        by_tab[tab] = row
    return trips, by_tab, trips_raw

def _build(ledger_dir: Path, manual_csv: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    _trips, trips_by_tab, trips_raw = _validate_inputs(ledger_dir, manual_csv)
    r25_manifest, r25_files = _build_r25(manual_csv, ledger_dir)
    r34_manifest, r34_files = _build_r34(ledger_dir, manual_csv)
    if (r34_manifest["current_event_set_sha256"], r34_manifest["decision_scope_sha256"],
        r34_manifest["prior_union_set_sha256"], r34_manifest["selected_event_set_sha256"],
        r34_manifest["semantic_set_sha256"], r34_manifest["counts"]["remaining"]) != (
        CURRENT_EVENT_SET_SHA256, DECISION_SCOPE_SHA256, PRIOR_UNION_SET_SHA256,
        R34_SET_SHA256, R34_SEMANTIC_SHA256, 3820): raise ValueError("r36_upstream_context_invalid")

    manual_raw, manual_rows, malformed = _manual(manual_csv)
    if len(manual_rows) != 1557 or len(malformed) != 2 or _sha(manual_raw) != MANUAL_SHA256:
        raise ValueError("r36_manual_census_invalid")
    manual_by_locator = {str(row["locator"]): row for row in manual_rows}
    if len(manual_by_locator) != len(manual_rows): raise ValueError("r36_manual_locator_duplicate")

    with tempfile.TemporaryDirectory(prefix="r36-current-") as dirname:
        ctx = _context(ledger_dir, Path(dirname)); ctx["db"].close()
    if ctx["current_event_set_sha256"] != CURRENT_EVENT_SET_SHA256 or ctx["decision_scope_sha256"] != DECISION_SCOPE_SHA256:
        raise ValueError("r36_current_context_invalid")
    events = {str(row["direct_event_key"]): row for row in ctx["events"]}
    if len(events) != 5328: raise ValueError("r36_current_count_invalid")

    r34_rows = {row["direct_event_key"]: row for row in csv.DictReader(io.StringIO(r34_files["proposals.csv"].decode()))}
    if len(r34_rows) != 259 or _event_set_sha(set(r34_rows)) != R34_SET_SHA256: raise ValueError("r36_r34_set_invalid")

    # Prior is reconstructed from the exact component sets embedded and live-checked by R34.
    evidence = list(csv.DictReader(io.StringIO(r25_files["evidence_sets.csv"].decode())))
    proposals = list(csv.DictReader(io.StringIO(r25_files["proposals.csv"].decode())))
    from ledger.domain.direct_lineage_annex import build_annex
    from ledger.domain.direct_verified_booking_evidence import EXPECTED_RELATIONS
    from ledger.domain.direct_repository_booking_evidence import EXPECTED_BOOKING_NEW, EXPECTED_OTA_NEW
    r23 = {str(x["direct_event_key"]) for x in build_annex(ledger_dir=ledger_dir)["package"]["envelopes"] if x.get("historical_uid")}
    r25 = {x["direct_event_key"] for x in proposals} | {x["direct_event_key"] for x in evidence if x["evidence_tier"] in {"clean_110", "typed_v14_65", "portal_1"}}
    prior = r23 | r25 | {x[2] for x in EXPECTED_RELATIONS} | {x[3] for x in EXPECTED_BOOKING_NEW} | {x[3] for x in EXPECTED_OTA_NEW}
    residual = set(events) - prior
    if len(prior) != 1508 or _event_set_sha(prior) != PRIOR_UNION_SET_SHA256 or len(residual) != 3820 or _event_set_sha(residual) != RESIDUAL_SET_SHA256:
        raise ValueError("r36_prior_or_residual_invalid")

    current_groups = defaultdict(list)
    for event_id, event in events.items():
        current_groups[(event["source_system"], event["occurred_on"], int(event["signed_amount_krw"]))].append(event_id)
    manual_groups = defaultdict(list)
    for row in manual_rows:
        for source in ISSUERS.get(str(row["card"]).strip(), ()):
            manual_groups[(source, row["occurred_on"], int(row["amount_krw"]))].append(str(row["locator"]))

    source_groups = list(csv.DictReader(io.StringIO(r25_files["groups.csv"].decode())))
    excluded_mismatch = set()
    for source_group in source_groups:
        event_ids = set(json.loads(source_group["current_event_keys_json"]))
        if (source_group["group_type"] == "current_duplicate" and
            int(source_group["current_cardinality"]) == 2 and int(source_group["manual_cardinality"]) == 1 and
            event_ids & set(r34_rows)):
            excluded_mismatch |= event_ids & set(r34_rows)
    if len(excluded_mismatch) != 4 or _event_set_sha(excluded_mismatch) != EXCLUDED_MISMATCH_SET_SHA256:
        raise ValueError("r36_excluded_counterexample_set_invalid")

    groups = []; partition = []; bucket_events = set(); used_events = set(); used_locators = set()
    for source_group in source_groups:
        if source_group["group_type"] != "both_duplicate": continue
        compound = json.loads(source_group["compound_key_json"])
        event_ids = sorted(json.loads(source_group["current_event_keys_json"]))
        locators = sorted(json.loads(source_group["manual_locators_json"]))
        if not isinstance(compound, list) or len(compound) != 3: raise ValueError("r36_compound_invalid")
        key = (str(compound[0]), str(compound[1]), int(compound[2]))
        if sorted(current_groups.get(key, [])) != event_ids or sorted(manual_groups.get(key, [])) != locators:
            raise ValueError("r36_group_live_rebuild_mismatch")
        current_count = int(source_group["current_cardinality"]); manual_count = int(source_group["manual_cardinality"])
        if current_count != manual_count or current_count <= 1: continue
        if int(source_group["current_signed_total"]) != int(source_group["manual_signed_total"]): continue
        tabs = {str(manual_by_locator[x]["tab"]) for x in locators if x in manual_by_locator}
        if len(tabs) != 1: continue
        bucket = next(iter(tabs))
        if bucket not in trips_by_tab or set(event_ids) & prior: continue
        if len(event_ids) != current_count or len(locators) != manual_count: raise ValueError("r36_group_cardinality_mismatch")
        if used_events & set(event_ids) or used_locators & set(locators): raise ValueError("r36_group_reuse")
        used_events |= set(event_ids); used_locators |= set(locators); bucket_events |= set(event_ids)
        event_set_sha = _event_set_sha(set(event_ids)); locator_set_sha = _event_set_sha(set(locators))
        row_hash_set_sha = _event_set_sha({str(manual_by_locator[x]["row_sha256"]) for x in locators})
        source_locator_set_sha = _event_set_sha({_source_locator_sha(events[x]) for x in event_ids})
        compound_sha = _sha(_json(compound)); trip_sha = _sha(_json(trips_by_tab[bucket]))
        group_id = str(source_group["group_id"])
        groups.append({"group_id": group_id, "compound_key_sha256": compound_sha,
            "current_member_set_sha256": event_set_sha, "current_member_count": current_count,
            "current_source_locator_set_sha256": source_locator_set_sha,
            "manual_locator_set_sha256": locator_set_sha, "manual_row_set_sha256": row_hash_set_sha,
            "manual_member_count": manual_count, "bucket": bucket, "trip_row_sha256": trip_sha,
            "bijection_asserted": False,
            "relation_kind": "manual_group_bucket_support", "disposition": "group_bucket_support_proposal",
            "authority_status": AUTHORITY[0], "posting_status": AUTHORITY[1], "confirmed_count": 0,
            "gate5_credit": 0, "applied": False})
        partition.append({"group_id":group_id, "event_set_sha":event_set_sha,
            "locator_set_sha":locator_set_sha, "bucket":bucket,
            "compound_sha":_sha(source_group["compound_key_json"].encode())})
    groups.sort(key=lambda row: row["group_id"]); partition.sort(key=lambda row: row["group_id"])
    if len(groups) != 18 or len(bucket_events) != 44 or _event_set_sha(bucket_events) != BUCKET_SET_SHA256:
        raise ValueError("r36_bucket_group_set_invalid")
    if _sha(_json(partition)) != GROUP_PARTITION_SHA256 or _event_set_sha({x["group_id"] for x in groups}) != GROUP_ID_SET_SHA256:
        raise ValueError("r36_group_partition_invalid")

    # Build the map without any row pairing: membership comes only from the
    # complete current group member set.
    group_by_event = {}
    for group in groups:
        for source_group in source_groups:
            if source_group["group_id"] == group["group_id"]:
                for event_id in json.loads(source_group["current_event_keys_json"]): group_by_event[event_id] = group
                break

    bucket_support=[]
    for event_id in sorted(bucket_events):
        group=group_by_event[event_id]; event=events[event_id]
        item={"direct_event_key":event_id,"current_event_sha256":event["current_event_sha256"],
            "current_source_locator_sha256":_source_locator_sha(event),"group_id":group["group_id"],
            "group_member_set_sha256":group["current_member_set_sha256"],"bucket":group["bucket"],
            "relation_kind":"manual_group_bucket_support","disposition":"group_bucket_support_proposal",
            "authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],"confirmed_count":0,
            "gate5_credit":0,"applied":False,"bijection_asserted":False}
        item["proposal_id"]=_sha(_json({"rule":RULE_SHA256,"event":event_id,
            "event_sha":item["current_event_sha256"],"group":item["group_id"],"bucket":item["bucket"]}))
        bucket_support.append(item)
    bucket_semantic_sha=_bucket_semantic_sha(bucket_support)
    if (len(bucket_support)!=44 or len({x["direct_event_key"] for x in bucket_support})!=44 or
        len({x["group_id"] for x in bucket_support})!=18 or bucket_semantic_sha!=BUCKET_SEMANTIC_SHA256):
        raise ValueError("r36_bucket_semantic_invalid")

    full_events = bucket_events & set(r34_rows); classifications=[]
    for event_id in sorted(full_events):
        taxonomy = r34_rows[event_id]; group = group_by_event[event_id]; event = events[event_id]
        dimensions = [group["bucket"], taxonomy["account"], taxonomy["cost_type"], taxonomy["vat_tag"]]
        if any(not x or any(token in x for token in ADVERSE) for x in dimensions): continue
        if event["transaction_type"] != "purchase": raise ValueError("r36_nonpurchase_full_event")
        item = {"direct_event_key":event_id, "current_event_sha256":event["current_event_sha256"],
            "current_source_locator_sha256":_source_locator_sha(event), "group_id":group["group_id"],
            "group_member_set_sha256":group["current_member_set_sha256"], "bucket":group["bucket"],
            "r34_proposal_id":taxonomy["proposal_id"], "r34_taxonomy_key_sha256":taxonomy["taxonomy_key_sha256"],
            "r34_rule_contract_sha256":r34_manifest["rule_contract_sha256"], "account":taxonomy["account"],
            "cost_type":taxonomy["cost_type"], "vat_tag":taxonomy["vat_tag"],
            "transaction_type":event["transaction_type"],
            "relation_kind":"manual_group_plus_r34_taxonomy", "disposition":"full_classification_review_proposal",
            "authority_status":AUTHORITY[0], "posting_status":AUTHORITY[1], "confirmed_count":0,
            "gate5_credit":0, "applied":False}
        item["proposal_id"] = _sha(_json({"rule":RULE_SHA256,"event":event_id,"event_sha":item["current_event_sha256"],
            "group":item["group_id"],"r34":item["r34_proposal_id"]}))
        classifications.append(item)
    full_set={x["direct_event_key"] for x in classifications}; semantic_sha=_semantic_sha(classifications)
    if len(full_set)!=16 or _event_set_sha(full_set)!=FULL_SET_SHA256 or semantic_sha!=FULL_SEMANTIC_SHA256:
        raise ValueError("r36_full_set_or_semantic_invalid")
    if sum(int(events[x]["signed_amount_krw"]) for x in full_set)!=2215446: raise ValueError("r36_full_amount_invalid")
    if not full_set < {x["direct_event_key"] for x in bucket_support}: raise ValueError("r36_full_not_bucket_subset")

    group_bytes=_csv_bytes(GROUP_COLUMNS,groups); bucket_bytes=_csv_bytes(BUCKET_COLUMNS,bucket_support)
    class_bytes=_csv_bytes(CLASSIFICATION_COLUMNS,classifications)
    counts={"current":5328,"prior_union":1508,"residual":3820,"eligible_groups":18,
        "bucket_support":44,"full_groups":len({x["group_id"] for x in classifications}),"full_classification":16,
        "bucket_only":28,"excluded_mismatch_groups":2,"excluded_mismatch_events":4,"confirmed":0,"gate5_credit":0}
    base={"format_version":1,"artifact_type":ARTIFACT_TYPE,"rule_contract_version":RULE_VERSION,
        "rule_contract_sha256":RULE_SHA256,"authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],
        "confirmed_count":0,"gate5_credit":0,"applied":False,"bijection_asserted":False,
        "manual_raw_sha256":MANUAL_SHA256,"manual_canonical_rows_sha256":r25_manifest["manual_canonical_rows_sha256"],
        "trips_raw_sha256":_sha(trips_raw),"trips_row_set_sha256":_event_set_sha({_sha(_json(x)) for x in _trips}),
        "input_manifest_sha256":r25_manifest["input_manifest_sha256"],
        "candidate_semantic_sha256":r25_manifest["candidate_semantic_sha256"],
        "current_event_set_sha256":CURRENT_EVENT_SET_SHA256,"decision_scope_sha256":DECISION_SCOPE_SHA256,
        "r25_rule_contract_sha256":r25_manifest["rule_contract_sha256"],"r25_package_set_sha256":r25_manifest["package_set_sha256"],
        "r34_rule_contract_sha256":r34_manifest["rule_contract_sha256"],"r34_package_set_sha256":r34_manifest["package_set_sha256"],
        "r34_selected_event_set_sha256":R34_SET_SHA256,"r34_semantic_set_sha256":R34_SEMANTIC_SHA256,
        "component_set_sha256":r34_manifest["component_set_sha256"],"prior_union_set_sha256":PRIOR_UNION_SET_SHA256,
        "residual_set_sha256":RESIDUAL_SET_SHA256,"bucket_event_set_sha256":BUCKET_SET_SHA256,
        "bucket_semantic_set_sha256":bucket_semantic_sha,
        "full_event_set_sha256":FULL_SET_SHA256,"full_semantic_set_sha256":semantic_sha,
        "group_partition_sha256":GROUP_PARTITION_SHA256,"group_id_set_sha256":GROUP_ID_SET_SHA256,
        "excluded_mismatch_event_set_sha256":EXCLUDED_MISMATCH_SET_SHA256,"counts":counts,
        "files":{"groups.csv":{"sha256":_sha(group_bytes),"rows":len(groups)},
                 "bucket_support.csv":{"sha256":_sha(bucket_bytes),"rows":len(bucket_support)},
                 "classifications.csv":{"sha256":_sha(class_bytes),"rows":len(classifications)}}}
    package_sha=_sha(_json(base)+group_bytes+bucket_bytes+class_bytes)
    manifest={**base,"package_set_sha256":package_sha,
        "analysis_run_id":_sha(_json({"artifact":ARTIFACT_TYPE,"rule":RULE_SHA256,"package":package_sha,
            "current":CURRENT_EVENT_SET_SHA256,"prior":PRIOR_UNION_SET_SHA256,"r34":R34_SET_SHA256}))}
    return manifest,{"manifest.json":_json(manifest),"groups.csv":group_bytes,
        "bucket_support.csv":bucket_bytes,"classifications.csv":class_bytes}

def verify_manual_group_taxonomy_evidence(directory: Path, *, ledger_dir: Path=REPOSITORY_ROOT/"ledger",
                                           manual_csv: Path=DEFAULT_MANUAL_CSV, current: bool=True) -> dict[str, object]:
    if directory.is_symlink() or not directory.is_dir() or sorted(x.name for x in directory.iterdir())!=sorted(FILES):
        raise ValueError("r36_package_shape_invalid")
    actual={}
    for name in FILES:
        _regular_single(directory/name,"r36_package_file_invalid");actual[name]=(directory/name).read_bytes()
    parsed=_strict_json(actual["manifest.json"],"r36_manifest")
    if not isinstance(parsed,dict) or (parsed.get("authority_status"),parsed.get("posting_status"),
        parsed.get("confirmed_count"),parsed.get("gate5_credit"),parsed.get("applied"),parsed.get("bijection_asserted")) != (*AUTHORITY,False):
        raise ValueError("r36_authority_boundary_invalid")
    manifest,expected=_build(ledger_dir,manual_csv)
    if actual!=expected: raise ValueError("r36_live_context_or_package_mismatch" if current else "r36_staging_mismatch")
    return {"status":"valid","analysis_run_id":manifest["analysis_run_id"],"groups":18,"bucket_support":44,
            "full_classification":16,"confirmed_count":0,"gate5_credit":0}

def _write_file_fsync(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.chmod(path,0o600)

def reconcile_publication_durability(error: PublicationDurabilityError, *,
        ledger_dir: Path=REPOSITORY_ROOT/"ledger", manual_csv: Path=DEFAULT_MANUAL_CSV) -> dict[str, object]:
    """Verify the visible package and retry only the parent durability barrier."""
    if not isinstance(error,PublicationDurabilityError) or not error.published or error.parent_fsync:
        raise ValueError("r36_publication_state_invalid")
    def verify_expected() -> dict[str, object]:
        result=verify_manual_group_taxonomy_evidence(error.output,ledger_dir=ledger_dir,
                                                      manual_csv=manual_csv,current=True)
        raw=(error.output/"manifest.json").read_bytes();manifest=_strict_json(raw,"r36_manifest")
        if not isinstance(manifest,dict) or manifest.get("package_set_sha256")!=error.expected_package_sha256:
            raise ValueError("r36_publication_package_mismatch")
        return result
    verify_expected()
    _fsync_dir(error.output.parent.resolve(strict=True))
    # A competing writer can replace output during the fsync hook/window.  Only
    # report reconciliation success after the visible package is checked again.
    result=verify_expected()
    return {**result,"published":True,"parent_fsync":True,
            "package_set_sha256":error.expected_package_sha256}

def build_manual_group_taxonomy_evidence(*, output: Path|None=None, ledger_dir: Path=REPOSITORY_ROOT/"ledger",
                                         manual_csv: Path=DEFAULT_MANUAL_CSV) -> dict[str, object]:
    manifest,files=_build(ledger_dir,manual_csv)
    if output is not None:
        if output.parent.is_symlink(): raise ValueError("r36_output_parent_symlink")
        parent=output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r36_output_inside_repository")
        if os.path.lexists(output): raise FileExistsError("r36_output_exists")
        stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=str(parent)))
        published=False
        try:
            os.chmod(stage,0o700)
            for name,data in files.items():
                _write_file_fsync(stage/name,data)
            _fsync_dir(stage)
            verify_manual_group_taxonomy_evidence(stage,ledger_dir=ledger_dir,manual_csv=manual_csv,current=False)
            _install_noreplace(stage,output)
            published=True
            try:
                _fsync_dir(parent)
            except Exception as exc:
                # Once published, a path-based rollback can race with a process
                # replacing ``output`` and delete that process's directory.  Keep
                # the path untouched and report the exact reconciliation state.
                raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
        except Exception:
            if not published: shutil.rmtree(stage,ignore_errors=True)
            raise
    return {"manifest":manifest,"manifest_sha256":_sha(files["manifest.json"]),
            "output":None if output is None else str(output)}

def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--verify",type=Path)
    parser.add_argument("--manual-csv",type=Path,default=DEFAULT_MANUAL_CSV);args=parser.parse_args()
    try:
        result=verify_manual_group_taxonomy_evidence(args.verify,manual_csv=args.manual_csv) if args.verify else build_manual_group_taxonomy_evidence(output=args.output,manual_csv=args.manual_csv)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except PublicationDurabilityError as exc:
        print(json.dumps({"status":"published_but_parent_fsync_failed","published":True,
            "parent_fsync":False,"output":str(exc.output),
            "expected_package_sha256":exc.expected_package_sha256},ensure_ascii=False,sort_keys=True));return 3
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"invalid","error":str(exc)},ensure_ascii=False,sort_keys=True));return 2

if __name__=="__main__": raise SystemExit(main())
