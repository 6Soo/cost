"""R37 external-only narrow-service classification evidence.

Only the complete two-event highway-toll group accepted by the independent
R37 design reviews is emitted.  Nothing here confirms, posts, or applies data.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _install_noreplace

ARTIFACT_TYPE="r37-narrow-service-classification-v1"
RULE_VERSION="r37-complete-group-positive-highway-toll-v1"
FILES=("manifest.json","groups.csv","proposals.csv","exclusions.csv")
AUTHORITY=("unattested","blocked",0,0,False)
ACCOUNT="통행료";COST_TYPE="여행원가";VAT_TAG="불공제_해외"
BUCKET_ONLY_SET_SHA256="406356af76d65d0cb48d00d22cc1ce61cdd38a072f1bbef085658d6ad411bab9"
STRICT_GROUP_ID="6f8b1d814c1f675d9b97e925debfae25aa9cbabf9367f25fd9b5731cd0f244cf"
STRICT_SET_SHA256="6f5bc4eca38285a5978b2048a6661dc94f4bfaee11c5a241d40a2d9ec0b14ffc"
STRICT_SEMANTIC_SHA256="288de0cb103a571521f225f1e3d022d4b35e9d69ed737fa2ff25aaf65b1bc196"
DEFERRED_SET_SHA256="21b547424d55929029ff41bf94773d485ee75aad90d4185607979668493e936e"
EXCLUSION_SEMANTIC_SHA256="401a9a120f43873faaaab32477a8a2d5993dd0a10c8a63dbc533309fa79496ab"
SELECTOR_EVIDENCE_SHA256="b776b7ce4cba401d2022d170f4d69845f92a6b86016f6f05692fa991a83f041d"
R36_RULE_SHA256="dcaa6762b489c9a8d1131c34b05f461c2c9805d35c4dbaae11737dff11139c0f"
R36_PACKAGE_SHA256="60a49ff3ac56be37c1a35003f72d795a4f86bde057b52b7cf4508652a2328a31"
GROUP_FACTS={
    "compound_key_sha256":"c088b14885d37a39669a601c8bc06dcf4b90a248d6fcd7f24501661e094664d2",
    "current_source_locator_set_sha256":"aeba34e315861af3b0130b8c29e235bf2a00e36da7fb62e969301297e0e3f5f6",
    "manual_locator_set_sha256":"fe1911886c01850f8396679d321ded928b6206eb092a17261f78b8b5df40a2b1",
    "manual_row_set_sha256":"03e954d53911e113c54791f492dc00602bf09ecd435832a92b720e74bb59474b",
    "trip_row_sha256":"924eb8cf50e759327e0b146983b45121682cb3c05bfa0ea6e48c740e679a7b02",
    "bucket":"0404_에히메",
}
EXPECTED_EVENTS={
 "card:0da2ce684ccf552f99c3bc074fa11cfa0382424e9ca6ec0c871f2b491903fd24#single":{
  "event_sha":"9e83a861a798a14f64dc8625eafb685d3e232c65b957d352986c482c3bed235b",
  "source_sha":"f842543a8590f42f710f37ee202f4d10d6c0e1f1d82b49259487f81c50607581",
  "source_locator_sha":"7cbc63de2fc2872e15754834e8e61583fd433d79e9739a8f408b7f7cb1f33e32",
  "payload_sha":"0c0c08ff13ad27acc059df9b7fb9d1f405e635257b33f2dd5bbbcd4475ac7e5e"},
 "card:c49a859730838938007ac7afbb28f2332b2faa98adc3ca84b49b6060848d8755#single":{
  "event_sha":"015b31a3727f83dedbd7a5b46c0acad02fc021fd3c947b6392bedc894623abbc",
  "source_sha":"4170d56e69517c79be5b82af14ca156c08ee67f9b3c406e4d6f0a6c97743088c",
  "source_locator_sha":"5c1ee6afa50f1b2d6bd3dead437991268ec9152bbc4e132c57d23ca7c2021730",
  "payload_sha":"2c1774317c22dc41ccc1eaecbdd21d6ed94e13c3edde93750d8f81d2303890e7"},
}
MANUAL_ITEM_HASH="a7d6db0f833330d4085540caf0b261eb0f93880dce6035a96ee3e77a30c73c92"
MANUAL_DESCRIPTION_HASH="838e3700c2cf7a4a5d80cb7e3baa7ad7cc7eb6e042b95cdb31817d4dc029e864"
MERCHANT_HASH=MANUAL_ITEM_HASH
BIZ_HASH="32314a4d6b1c38b4346a62b1ea681e694b94dae6de4a7785a073d1af60308fe0"
CURRENCY_HASH="11b0f54507228614947c3557e1c7b70167981c6e2deb0b9665ac32441221da5e"
REASON_BY_GROUP={
 "0ab757512fc96692a6ea43ee723fbb6a034010008a260fa4daee535c1701153f":"cancellation_without_original",
 "1a5034f2897878b0b396a544d9337886eac85815729504400066152bb6905fc6":"vague_manual_and_raw",
 "17c6ec4e0978aa75133bf6212b35092b9687876fa3d38d317342bb7a8c8d60c3":"generic_ota_product_unbound",
 "30c2a3ee46370f58ed296c6498ca02158f4a863bfc90c7c83b5ed1d6d9cd41bb":"generic_ota_product_unbound",
 "40319d742d280c667f2cf24987b8fe4688665ac21c92049f11e8f20fe0b89f5d":"generic_ota_product_unbound",
 "8388faaa9d4fe0d9e9a413950bce38fa07ee135031a2e1a189ad65dc383a98fa":"generic_ota_product_unbound",
 "9dc3cbac36971774a098106664ea23c33896c6400f40e31a46626d99bec14215":"generic_ota_product_unbound",
 "c49da023f2d8e4972c83106ed3141fb3db60baddba20acb620cb49cd8838fe02":"generic_ota_product_unbound",
 "4792823347ceedb9e764952351c187ede6be26c03592e9d85d9551e729ba23a5":"airfare_raw_support_absent",
 "fe0992319dd7cd96d6c1aa4134d4ec4ff04496d72351583d3c5aa1d24cc2cc29":"airfare_raw_support_absent",
 "e59cc732df1c71a48f7d4b3073c77cbeeadea8f22f337bd4c1c0a7adfb4320d2":"manual_raw_category_conflict",
 "f2748b44db370dc3ca0a5551dc4ece05fa71376a060226a2cad94d4029589784":"vat_foreign_basis_unbound",
}
REASONS=frozenset(REASON_BY_GROUP.values())

GROUP_COLUMNS=("group_id","compound_key_sha256","current_member_set_sha256","current_member_count",
 "current_source_locator_set_sha256","manual_locator_set_sha256","manual_row_set_sha256","manual_member_count",
 "bucket","trip_row_sha256","selector_evidence_set_sha256","bijection_asserted","relation_kind","disposition",
 "authority_status","posting_status","confirmed_count","gate5_credit","applied")
PROPOSAL_COLUMNS=("proposal_id","direct_event_key","current_event_sha256","current_source_locator_sha256",
 "group_id","group_member_set_sha256","bucket","account","cost_type","vat_tag","transaction_type",
 "rule_contract_sha256","evidence_family_sha256","relation_kind","disposition","authority_status",
 "posting_status","confirmed_count","gate5_credit","applied")
EXCLUSION_COLUMNS=("exclusion_id","direct_event_key","current_event_sha256","current_source_locator_sha256",
 "group_id","group_member_set_sha256","bucket","reason_code","counterexample_contract_sha256",
 "disposition","authority_status","posting_status","confirmed_count","gate5_credit","applied")
SENSITIVE=("amount","date","merchant","biz","currency","card","approval","booking","manual_locator",
 "item","description","desc","guest","passenger","pnr","pin","email","url","token","source_key")

def _norm(value: object) -> str:
    return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",str(value or "")).strip().upper())

def _norm_hash(value: object) -> str:
    return r36._sha((_norm(value)+"\n").encode())

def _manual_toll(value: object) -> bool:
    text=_norm(value)
    adverse=("취소","환불","숙박","항공","OTA","AGODA","BOOKING","TRIP.COM","PG")
    positive=(("HIGHWAY" in text and "TOLL" in text) or "통행료" in text or "유료도로" in text or
              ("고속도로" in text and ("요금" in text or "통행" in text)))
    return bool(positive and not any(token in text for token in adverse))

def _merchant_toll(value: object) -> bool:
    text=_norm(value)
    return "HIGHWAY" in text and "TOLL" in text and not any(x in text for x in ("AGODA","BOOKING","TRIP","KCP","INICIS"))

def _csv(columns: tuple[str,...], rows: list[dict[str,object]]) -> bytes:
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=columns,lineterminator="\n")
    writer.writeheader()
    for row in rows: writer.writerow({key:str(row.get(key,"")).lower() if isinstance(row.get(key),bool) else row.get(key,"") for key in columns})
    return stream.getvalue().encode()

def _semantic(rows: list[dict[str,object]]) -> str:
    values=[{"event":x["direct_event_key"],"account":x["account"],"cost_type":x["cost_type"],"vat_tag":x["vat_tag"]} for x in rows]
    values.sort(key=lambda x:x["event"]);return r36._sha(r36._json(values))

def _regular_0600(path: Path, code: str) -> None:
    r36._regular_single(path,code);mode=stat.S_IMODE(path.stat().st_mode)
    if mode!=0o600: raise ValueError(code)

RULE_SHA256=r36._sha(r36._json({"artifact":ARTIFACT_TYPE,"version":RULE_VERSION,"authority":AUTHORITY,
 "universe":"R36 bucket44 minus full16 complete groups","normalization":"NFKC uppercase whitespace",
 "manual_positive":"each item and description highway toll","merchant_positive":"HIGHWAY and TOLL",
 "biz":"corroboration only; exact source-bound","transaction_type":"purchase","currency":"non-KRW ISO and foreign amount",
 "dimensions":[ACCOUNT,COST_TYPE,VAT_TAG],"bucket_only":BUCKET_ONLY_SET_SHA256,"strict":STRICT_SET_SHA256,
 "semantic":STRICT_SEMANTIC_SHA256,"deferred":DEFERRED_SET_SHA256,"strict_group":STRICT_GROUP_ID,
 "exclusion_semantic":EXCLUSION_SEMANTIC_SHA256,"selector_evidence":SELECTOR_EVIDENCE_SHA256,
 "group_partition":r36.GROUP_PARTITION_SHA256,"manual":r36.MANUAL_SHA256,"trips":r36.TRIPS_SHA256,
 "r36_rule":R36_RULE_SHA256,"r36_package":R36_PACKAGE_SHA256,"group_columns":GROUP_COLUMNS,
 "proposal_columns":PROPOSAL_COLUMNS,"exclusion_columns":EXCLUSION_COLUMNS,"reasons":sorted(REASONS),
 "sensitive_denylist":SENSITIVE,"historical_classification_seed":False,"bijection_asserted":False}))
COUNTEREXAMPLE_SHA256=r36._sha(r36._json(REASON_BY_GROUP))

class PublicationDurabilityError(OSError):
    def __init__(self, output: Path, expected_package_sha256: str) -> None:
        super().__init__("r37_published_but_parent_fsync_failed");self.output=output
        self.expected_package_sha256=expected_package_sha256;self.published=True;self.parent_fsync=False

def _build(ledger_dir: Path, manual_csv: Path=r36.DEFAULT_MANUAL_CSV) -> tuple[dict[str,object],dict[str,bytes]]:
    if ledger_dir.resolve()!=(REPOSITORY_ROOT/"ledger").resolve(): raise ValueError("r37_noncanonical_ledger")
    r36_manifest,r36_files=r36._build(ledger_dir,manual_csv)
    if (r36_manifest["rule_contract_sha256"],r36_manifest["package_set_sha256"],
        r36_manifest["current_event_set_sha256"],r36_manifest["decision_scope_sha256"],
        r36_manifest["prior_union_set_sha256"],r36_manifest["residual_set_sha256"],
        r36_manifest["bucket_event_set_sha256"],r36_manifest["full_event_set_sha256"],
        r36_manifest["group_partition_sha256"],r36_manifest["counts"]["bucket_only"]) != (
        R36_RULE_SHA256,R36_PACKAGE_SHA256,r36.CURRENT_EVENT_SET_SHA256,r36.DECISION_SCOPE_SHA256,
        r36.PRIOR_UNION_SET_SHA256,r36.RESIDUAL_SET_SHA256,r36.BUCKET_SET_SHA256,r36.FULL_SET_SHA256,
        r36.GROUP_PARTITION_SHA256,28): raise ValueError("r37_r36_upstream_invalid")
    bucket=list(csv.DictReader(io.StringIO(r36_files["bucket_support.csv"].decode())))
    full={x["direct_event_key"] for x in csv.DictReader(io.StringIO(r36_files["classifications.csv"].decode()))}
    bucket_only={x["direct_event_key"] for x in bucket}-full
    support={x["direct_event_key"]:x for x in bucket if x["direct_event_key"] in bucket_only}
    if len(bucket_only)!=28 or r36._event_set_sha(bucket_only)!=BUCKET_ONLY_SET_SHA256:
        raise ValueError("r37_bucket_only_invalid")
    groups36={x["group_id"]:x for x in csv.DictReader(io.StringIO(r36_files["groups.csv"].decode()))}
    group_ids={support[x]["group_id"] for x in bucket_only}
    if len(group_ids)!=13 or set(REASON_BY_GROUP)|{STRICT_GROUP_ID}!=group_ids: raise ValueError("r37_group_universe_invalid")

    r25_manifest,r25_files=r36._build_r25(manual_csv,ledger_dir)
    manual_raw,manual_rows,malformed=r36._manual(manual_csv)
    if r36._sha(manual_raw)!=r36.MANUAL_SHA256 or len(manual_rows)!=1557 or len(malformed)!=2:
        raise ValueError("r37_manual_census_invalid")
    manual_by={str(x["locator"]):x for x in manual_rows}
    source_groups={x["group_id"]:x for x in csv.DictReader(io.StringIO(r25_files["groups.csv"].decode()))}
    source_group=source_groups.get(STRICT_GROUP_ID)
    event_ids=set(json.loads(source_group["current_event_keys_json"])) if source_group else set()
    locators=json.loads(source_group["manual_locators_json"]) if source_group else []
    if (event_ids!=set(EXPECTED_EVENTS) or source_group["group_type"]!="both_duplicate" or
        int(source_group["current_cardinality"])!=2 or int(source_group["manual_cardinality"])!=2 or
        int(source_group["current_signed_total"])!=int(source_group["manual_signed_total"]) or
        len(set(locators))!=2): raise ValueError("r37_complete_group_invalid")
    group=groups36[STRICT_GROUP_ID]
    if any(group[key]!=value for key,value in GROUP_FACTS.items()) or group["current_member_set_sha256"]!=STRICT_SET_SHA256:
        raise ValueError("r37_group_facts_invalid")
    selected_manual=[manual_by[x] for x in locators]
    compound=json.loads(source_group["compound_key_json"])
    if (not isinstance(compound,list) or len(compound)!=3 or
        any(str(compound[0]) not in r36.ISSUERS.get(str(x["card"]).strip(),()) or
            str(x["occurred_on"])!=str(compound[1]) or int(x["amount_krw"])!=int(compound[2])
            for x in selected_manual) or {str(x["tab"]) for x in selected_manual}!={GROUP_FACTS["bucket"]}):
        raise ValueError("r37_manual_group_identity_invalid")
    if ({x["row_sha256"] for x in selected_manual} and
        r36._event_set_sha({x["row_sha256"] for x in selected_manual})!=GROUP_FACTS["manual_row_set_sha256"]):
        raise ValueError("r37_manual_rows_invalid")
    if r36._event_set_sha(set(locators))!=GROUP_FACTS["manual_locator_set_sha256"]:
        raise ValueError("r37_manual_locators_invalid")
    if not all(_manual_toll(x["item"]) and _manual_toll(x["desc"]) for x in selected_manual):
        raise ValueError("r37_manual_class_invalid")
    if ({_norm_hash(x["item"]) for x in selected_manual}!={MANUAL_ITEM_HASH} or
        {_norm_hash(x["desc"]) for x in selected_manual}!={MANUAL_DESCRIPTION_HASH}):
        raise ValueError("r37_manual_semantic_drift")

    with tempfile.TemporaryDirectory(prefix="r37-current-") as dirname:
        context=r36._context(ledger_dir,Path(dirname));db=context["db"]
        events={x["direct_event_key"]:x for x in context["events"]}
        selected=[];evidence=[]
        try:
            for event_id in sorted(event_ids):
                event=events[event_id];expected=EXPECTED_EVENTS[event_id]
                raw=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(event["current_source_key"],)).fetchone()
                if not raw: raise ValueError("r37_source_payload_missing")
                payload=json.loads(raw[0]);payload_sha=r36._sha(r36._json(payload))
                currency=_norm(payload.get("currency") or event["currency"]);foreign=payload.get("foreign") or event["foreign_amount"]
                try: foreign_positive=Decimal(str(foreign).replace(",",""))>0
                except InvalidOperation: foreign_positive=False
                facts=(event["current_event_sha256"],event["current_source_sha256"],r36._source_locator_sha(event),payload_sha)
                if facts!=(expected["event_sha"],expected["source_sha"],expected["source_locator_sha"],expected["payload_sha"]):
                    raise ValueError("r37_current_source_drift")
                if (event["source_system"]!="KBO" or event["current_source_kind"]!="card_raw" or
                    event["transaction_type"]!="purchase" or event["event_role"]!="single"):
                    raise ValueError("r37_current_role_invalid")
                if not _merchant_toll(event["merchant"]) or _norm_hash(event["merchant"])!=MERCHANT_HASH:
                    raise ValueError("r37_merchant_class_invalid")
                if _norm_hash(payload.get("biz"))!=BIZ_HASH: raise ValueError("r37_biz_source_drift")
                if not re.fullmatch(r"[A-Z]{3}",currency) or currency=="KRW" or not foreign_positive or _norm_hash(currency)!=CURRENCY_HASH:
                    raise ValueError("r37_foreign_fact_invalid")
                selected.append((event_id,event));evidence.append({"event":event_id,"event_sha":facts[0],
                    "source_sha":facts[1],"source_locator_sha":facts[2],"payload_sha":facts[3],
                    "merchant_hash":_norm_hash(event["merchant"]),"biz_hash":_norm_hash(payload.get("biz")),
                    "currency_hash":_norm_hash(currency),"foreign_present":True})
        finally: db.close()
    evidence_sha=r36._sha(r36._json(evidence))
    if evidence_sha!=SELECTOR_EVIDENCE_SHA256: raise ValueError("r37_selector_evidence_invalid")
    proposals=[]
    for event_id,event in selected:
        item={"direct_event_key":event_id,"current_event_sha256":event["current_event_sha256"],
            "current_source_locator_sha256":r36._source_locator_sha(event),"group_id":STRICT_GROUP_ID,
            "group_member_set_sha256":STRICT_SET_SHA256,"bucket":GROUP_FACTS["bucket"],"account":ACCOUNT,
            "cost_type":COST_TYPE,"vat_tag":VAT_TAG,"transaction_type":"purchase","rule_contract_sha256":RULE_SHA256,
            "evidence_family_sha256":evidence_sha,"relation_kind":"complete_group_narrow_service_classification",
            "disposition":"full_classification_review_proposal","authority_status":AUTHORITY[0],
            "posting_status":AUTHORITY[1],"confirmed_count":0,"gate5_credit":0,"applied":False}
        item["proposal_id"]=r36._sha(r36._json({"rule":RULE_SHA256,"event":event_id,"event_sha":item["current_event_sha256"],
            "group":STRICT_GROUP_ID,"evidence":evidence_sha}));proposals.append(item)
    proposal_set={x["direct_event_key"] for x in proposals}
    if len(proposals)!=2 or proposal_set!=event_ids or r36._event_set_sha(proposal_set)!=STRICT_SET_SHA256 or _semantic(proposals)!=STRICT_SEMANTIC_SHA256:
        raise ValueError("r37_strict_set_or_semantic_invalid")
    if proposal_set & full or not proposal_set < bucket_only: raise ValueError("r37_universe_overlap_invalid")

    exclusions=[]
    for event_id in sorted(bucket_only-proposal_set):
        row=support[event_id];reason=REASON_BY_GROUP[row["group_id"]]
        item={"direct_event_key":event_id,"current_event_sha256":row["current_event_sha256"],
            "current_source_locator_sha256":row["current_source_locator_sha256"],"group_id":row["group_id"],
            "group_member_set_sha256":row["group_member_set_sha256"],"bucket":row["bucket"],"reason_code":reason,
            "counterexample_contract_sha256":COUNTEREXAMPLE_SHA256,"disposition":"deferred_insufficient_independent_evidence",
            "authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],"confirmed_count":0,"gate5_credit":0,"applied":False}
        item["exclusion_id"]=r36._sha(r36._json({"rule":RULE_SHA256,"event":event_id,"group":item["group_id"],"reason":reason}))
        exclusions.append(item)
    excluded_set={x["direct_event_key"] for x in exclusions}
    exclusion_semantic=r36._sha(r36._json(sorted([{"event":x["direct_event_key"],"group":x["group_id"],"reason":x["reason_code"]} for x in exclusions],key=lambda x:x["event"])))
    if (len(exclusions)!=26 or r36._event_set_sha(excluded_set)!=DEFERRED_SET_SHA256 or
        exclusion_semantic!=EXCLUSION_SEMANTIC_SHA256 or excluded_set|proposal_set!=bucket_only):
        raise ValueError("r37_deferred_set_invalid")
    group_row={"group_id":STRICT_GROUP_ID,"compound_key_sha256":GROUP_FACTS["compound_key_sha256"],
        "current_member_set_sha256":STRICT_SET_SHA256,"current_member_count":2,
        "current_source_locator_set_sha256":GROUP_FACTS["current_source_locator_set_sha256"],
        "manual_locator_set_sha256":GROUP_FACTS["manual_locator_set_sha256"],"manual_row_set_sha256":GROUP_FACTS["manual_row_set_sha256"],
        "manual_member_count":2,"bucket":GROUP_FACTS["bucket"],"trip_row_sha256":GROUP_FACTS["trip_row_sha256"],
        "selector_evidence_set_sha256":evidence_sha,"bijection_asserted":False,"relation_kind":"complete_group_narrow_service_support",
        "disposition":"group_classification_review_proposal","authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],
        "confirmed_count":0,"gate5_credit":0,"applied":False}
    group_bytes=_csv(GROUP_COLUMNS,[group_row]);proposal_bytes=_csv(PROPOSAL_COLUMNS,proposals);exclusion_bytes=_csv(EXCLUSION_COLUMNS,exclusions)
    counts={"current":5328,"prior_union":1508,"residual":3820,"r36_bucket_support":44,"r36_full":16,
        "bucket_only":28,"bucket_only_groups":13,"strict_groups":1,"proposals":2,"deferred_groups":12,"deferred":26,
        "confirmed":0,"gate5_credit":0,"reason_counts":dict(sorted(Counter(x["reason_code"] for x in exclusions).items()))}
    base={"format_version":1,"artifact_type":ARTIFACT_TYPE,"rule_contract_version":RULE_VERSION,
        "rule_contract_sha256":RULE_SHA256,"privacy_schema_sha256":r36._sha(r36._json({"groups":GROUP_COLUMNS,"proposals":PROPOSAL_COLUMNS,
            "exclusions":EXCLUSION_COLUMNS,"deny":SENSITIVE})),"contains_sensitive_raw_values":False,"bijection_asserted":False,
        "authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],"confirmed_count":0,"gate5_credit":0,"applied":False,
        "r36_rule_contract_sha256":R36_RULE_SHA256,"r36_package_set_sha256":R36_PACKAGE_SHA256,
        "input_manifest_sha256":r36_manifest["input_manifest_sha256"],"current_event_set_sha256":r36.CURRENT_EVENT_SET_SHA256,
        "decision_scope_sha256":r36.DECISION_SCOPE_SHA256,"prior_union_set_sha256":r36.PRIOR_UNION_SET_SHA256,
        "residual_set_sha256":r36.RESIDUAL_SET_SHA256,"r34_rule_contract_sha256":r36_manifest["r34_rule_contract_sha256"],
        "r34_package_set_sha256":r36_manifest["r34_package_set_sha256"],"manual_raw_sha256":r36.MANUAL_SHA256,
        "manual_canonical_rows_sha256":r25_manifest["manual_canonical_rows_sha256"],"trips_raw_sha256":r36.TRIPS_SHA256,
        "trips_row_set_sha256":r36_manifest["trips_row_set_sha256"],"r36_group_partition_sha256":r36.GROUP_PARTITION_SHA256,
        "r36_group_id_set_sha256":r36.GROUP_ID_SET_SHA256,"r36_bucket_event_set_sha256":r36.BUCKET_SET_SHA256,
        "r36_full_event_set_sha256":r36.FULL_SET_SHA256,"bucket_only_event_set_sha256":BUCKET_ONLY_SET_SHA256,
        "strict_group_id":STRICT_GROUP_ID,"strict_event_set_sha256":STRICT_SET_SHA256,"strict_semantic_set_sha256":STRICT_SEMANTIC_SHA256,
        "deferred_event_set_sha256":DEFERRED_SET_SHA256,"exclusion_semantic_set_sha256":exclusion_semantic,
        "selector_evidence_set_sha256":evidence_sha,"counterexample_contract_sha256":COUNTEREXAMPLE_SHA256,"counts":counts,
        "files":{"groups.csv":{"sha256":r36._sha(group_bytes),"rows":1},"proposals.csv":{"sha256":r36._sha(proposal_bytes),"rows":2},
                 "exclusions.csv":{"sha256":r36._sha(exclusion_bytes),"rows":26}}}
    package=r36._sha(r36._json(base)+group_bytes+proposal_bytes+exclusion_bytes)
    manifest={**base,"package_set_sha256":package,"analysis_run_id":r36._sha(r36._json({"artifact":ARTIFACT_TYPE,"rule":RULE_SHA256,
        "package":package,"strict":STRICT_SET_SHA256,"deferred":DEFERRED_SET_SHA256}))}
    return manifest,{"manifest.json":r36._json(manifest),"groups.csv":group_bytes,"proposals.csv":proposal_bytes,"exclusions.csv":exclusion_bytes}

def verify_narrow_service_classification(directory: Path, *, ledger_dir: Path=REPOSITORY_ROOT/"ledger",
        manual_csv: Path=r36.DEFAULT_MANUAL_CSV, current: bool=True) -> dict[str,object]:
    if directory.is_symlink() or not directory.is_dir() or sorted(x.name for x in directory.iterdir())!=sorted(FILES):
        raise ValueError("r37_package_shape_invalid")
    actual={}
    for name in FILES: _regular_0600(directory/name,"r37_package_file_invalid");actual[name]=(directory/name).read_bytes()
    parsed=r36._strict_json(actual["manifest.json"],"r37_manifest")
    if not isinstance(parsed,dict) or (parsed.get("authority_status"),parsed.get("posting_status"),parsed.get("confirmed_count"),
        parsed.get("gate5_credit"),parsed.get("applied"),parsed.get("bijection_asserted"),parsed.get("contains_sensitive_raw_values")) != (*AUTHORITY,False,False):
        raise ValueError("r37_authority_boundary_invalid")
    manifest,expected=_build(ledger_dir,manual_csv)
    if actual!=expected: raise ValueError("r37_live_context_or_package_mismatch" if current else "r37_staging_mismatch")
    return {"status":"valid","analysis_run_id":manifest["analysis_run_id"],"proposals":2,"deferred":26,"confirmed_count":0,"gate5_credit":0}

def _fsync_dir(path: Path) -> None:
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try: os.fsync(fd)
    finally: os.close(fd)

def _write_file(path: Path,data: bytes) -> None:
    with path.open("xb") as stream: stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.chmod(path,0o600)

def reconcile_publication_durability(error: PublicationDurabilityError, *, ledger_dir: Path=REPOSITORY_ROOT/"ledger",
        manual_csv: Path=r36.DEFAULT_MANUAL_CSV) -> dict[str,object]:
    if not isinstance(error,PublicationDurabilityError) or not error.published or error.parent_fsync:
        raise ValueError("r37_publication_state_invalid")
    def check():
        result=verify_narrow_service_classification(error.output,ledger_dir=ledger_dir,manual_csv=manual_csv)
        manifest=r36._strict_json((error.output/"manifest.json").read_bytes(),"r37_manifest")
        if not isinstance(manifest,dict) or manifest.get("package_set_sha256")!=error.expected_package_sha256:
            raise ValueError("r37_publication_package_mismatch")
        return result
    check();_fsync_dir(error.output.parent.resolve(strict=True));result=check()
    return {**result,"published":True,"parent_fsync":True,"package_set_sha256":error.expected_package_sha256}

def build_narrow_service_classification(*, output: Path|None=None, ledger_dir: Path=REPOSITORY_ROOT/"ledger",
        manual_csv: Path=r36.DEFAULT_MANUAL_CSV) -> dict[str,object]:
    manifest,files=_build(ledger_dir,manual_csv)
    if output is not None:
        if output.parent.is_symlink(): raise ValueError("r37_output_parent_symlink")
        parent=output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r37_output_inside_repository")
        if os.path.lexists(output): raise FileExistsError("r37_output_exists")
        stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=str(parent)));published=False
        try:
            os.chmod(stage,0o700)
            for name,data in files.items(): _write_file(stage/name,data)
            _fsync_dir(stage);verify_narrow_service_classification(stage,ledger_dir=ledger_dir,manual_csv=manual_csv,current=False)
            _install_noreplace(stage,output);published=True
            try: _fsync_dir(parent)
            except Exception as exc: raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
        except Exception:
            if not published: shutil.rmtree(stage,ignore_errors=True)
            raise
    return {"manifest":manifest,"manifest_sha256":r36._sha(files["manifest.json"]),"output":None if output is None else str(output)}

def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--verify",type=Path)
    args=parser.parse_args()
    try:
        result=verify_narrow_service_classification(args.verify) if args.verify else build_narrow_service_classification(output=args.output)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except PublicationDurabilityError as exc:
        print(json.dumps({"status":"published_but_parent_fsync_failed","published":True,"parent_fsync":False,
            "output":str(exc.output),"expected_package_sha256":exc.expected_package_sha256},ensure_ascii=False,sort_keys=True));return 3
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"invalid","error":str(exc)},ensure_ascii=False,sort_keys=True));return 2

if __name__=="__main__": raise SystemExit(main())
