"""R44 external-only complete Trip lodging purchase/refund lifecycle evidence."""
from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import date, timedelta
from pathlib import Path

from ledger.domain import direct_document_acquisition_census as r42
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_narrow_service_classification as r37
from ledger.domain import direct_structured_lodging_evidence as r38
from ledger.domain import direct_trip_cancel_provenance as auth
from ledger.domain.direct_external_manual_evidence import _build_package as build25
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _install_noreplace, build_annex
from ledger.domain.direct_original_approval_relation import BOOKING_RELATIONS, EXPECTED_BOOKING_NEW, EXPECTED_OTA_NEW, MANUAL

ARTIFACT_TYPE = "r44-trip-cancel-complete-lifecycle-v1"
RULE_VERSION = "r44-p2-c2-unordered-atomic-netzero-v1"
FILES = ("manifest.json", "groups.csv", "proposals.csv", "exclusions.csv")
EXPECTED_CURRENT = "de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93"
EXPECTED_SCOPE = "22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"
EXPECTED_RESIDUAL = "f52cc4accd1afaf66150a96e375aee76167227170e87c9aa7ce7db00f7ab8b47"
EXPECTED_R42_PACKAGE = "0a93576180668b8793237ca4f9bb471021ce2acbbf8ffe192ce3627138235ea7"
EXPECTED_FRONTIER24 = "ab199a1614713567304b19deaeb0871e849b8e7d813b6a3449d2ad3d393f5d16"
A0_POLICY_SHA256 = "23559a536c66243d0024794f740605a9eaa7f9700726f14f963e7468e09bae59"
TRIPS_SHA256 = "0a9fdd6b4835d2cf889391b00e2567977858b77376d3d3071023e81609e51969"
PURCHASE_SET = "16bc4809935368f8693fbbcbffa5e3b680e7c1c1e34f3bc567f41f2faf0e6e6d"
CANCEL_SET = "745dd3069a8b73c9d70cb76dc0016c35d65298f35860966243011204a3c6bee7"
SELECTED_SET = "43af8f7c79e7b89d1d5c0439a9f5bf779c2a78d4d15c367dd1f30d1bc40a64af"
EVENTS = {
    "card:998610daf88a3cc9ec8c5fb725bfbde58e35cc751066fe7b133594106f1780c6#single": ("purchase", "c79d4b61085e653a5b3254698697d62880cdcfa95eef00fcb724b37f4a29c59d"),
    "card:a0dd5013531975e69b74fb7345521f8efabe8a4743c98abe209f14726710aee3#single": ("purchase", "53d234b5fd56f8232cb2f1910ca65c4b0b4a82b6b3e0768ee9b9d7b2a7b1a1b9"),
    "card:b785b3e1ca7a69974ca7cf457efb672e6941a34a267a4217773bc88f22c9a5cc#single": ("cancellation", "16a64c546766bff0c1db1b9c32f645cd30ee3aef6c1a619946692da543feba8b"),
    "card:bed1246eecc0f66864a441063c77188520fad4ee6f4855dbed24692fb73fe065#single": ("cancellation", "0eab126b11a9f405dc84d23c3b6023e7bf34db1e87baab9c2e79d25bccf58b49"),
}
ACCOUNT, COST_TYPE, VAT_TAG = "숙박비", "여행원가", "불공제_해외"
POSTING_BUCKET, TRIP_TARGET = "취소환불(net0)", "10월_도고"
AUTHORITY = ("unattested", "blocked", 0, 0, False)
GROUP_FIELDS = ("group_id", "member_set_sha256", "purchase_set_sha256", "cancellation_set_sha256",
                "member_count", "purchase_count", "cancellation_count", "provenance_commitment_sha256",
                "trip_target", "posting_bucket", "relation_kind", "bijection_asserted",
                "individual_relation_count", "permutation_invariant", "disposition", "authority_status",
                "posting_status", "confirmed_count", "gate5_credit", "applied")
PROPOSAL_FIELDS = ("proposal_id", "event_key_sha256", "current_event_sha256", "current_source_sha256",
                   "current_source_locator_sha256", "current_payload_sha256", "transaction_type", "group_id",
                   "account", "cost_type", "vat_tag", "trip_target", "posting_bucket", "relation_kind",
                   "bijection_asserted", "individual_relation_count", "atomic_group_required", "atomic_member_count", "disposition", "authority_status",
                   "posting_status", "confirmed_count", "gate5_credit", "applied")
EXCLUSION_FIELDS = ("exclusion_id", "event_key_sha256", "current_event_sha256", "group_id",
                    "group_member_set_sha256", "reason_code", "disposition", "authority_status",
                    "posting_status", "confirmed_count", "gate5_credit", "applied")


class PublicationDurabilityError(OSError):
    def __init__(self, output: Path, package_set_sha256: str, parent_identity=None, target_identity=None):
        super().__init__("r44_published_durability_unknown"); self.output=output; self.package_set_sha256=package_set_sha256; self.published=True
        self.parent_path=output.parent;self.target_name=output.name;self.parent_identity=parent_identity;self.target_identity=target_identity


class PublicationIntegrityError(OSError):
    def __init__(self, output: Path, package_set_sha256: str, parent_identity=None, target_identity=None):
        super().__init__("r44_published_integrity_invalid"); self.output=output; self.package_set_sha256=package_set_sha256; self.published=True
        self.parent_path=output.parent;self.target_name=output.name;self.parent_identity=parent_identity;self.target_identity=target_identity


def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes: return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(values) -> str: return r36._event_set_sha(set(values))
def _csv(fields, rows) -> bytes:
    s=io.StringIO(); w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n"); w.writeheader()
    for row in rows:w.writerow({k:(str(row.get(k,"")).lower() if isinstance(row.get(k),bool) else row.get(k,"")) for k in fields})
    return s.getvalue().encode()


def _accepted_union(ledger_dir: Path) -> tuple[set[str],dict[str,bytes]]:
    r23=build_annex(ledger_dir=ledger_dir); _,f25=build25(MANUAL,ledger_dir); _,f36=r36._build(ledger_dir,r36.DEFAULT_MANUAL_CSV); _,f38=r38._build(ledger_dir)
    p25=list(csv.DictReader(io.StringIO(f25["proposals.csv"].decode())))
    e25=list(csv.DictReader(io.StringIO(f25["evidence_sets.csv"].decode())))
    prior={str(x["direct_event_key"]) for x in r23["package"]["envelopes"] if x.get("historical_uid")}
    prior|={x["direct_event_key"] for x in p25}
    prior|={x["direct_event_key"] for x in e25 if x["evidence_tier"] in {"clean_110","typed_v14_65","portal_1"}}
    prior|={x[2] for x in BOOKING_RELATIONS}|{x[3] for x in EXPECTED_BOOKING_NEW}|{x[3] for x in EXPECTED_OTA_NEW}
    full36={x["direct_event_key"] for x in csv.DictReader(io.StringIO(f36["classifications.csv"].decode()))}
    return prior|full36|set(r37.EXPECTED_EVENTS)|set(r38.EXPECTED_EVENTS),f38


def _trip_contract(ledger_dir: Path) -> str:
    policy=REPOSITORY_ROOT/"docs/비용분류_지시사항_원장.md"; trips_path=ledger_dir/"data/trips.json"
    if _sha(policy.read_bytes())!=A0_POLICY_SHA256 or _sha(trips_path.read_bytes())!=TRIPS_SHA256:
        raise ValueError("r44_a0_or_trips_drift")
    trips=json.loads(trips_path.read_bytes()); matches=[x for x in trips if x.get("tab")==TRIP_TARGET]
    if len(matches)!=1 or set(matches[0])!={"tab","mm","dd","region","window"}:
        raise ValueError("r44_trip_target_invalid")
    row=matches[0]; start=date(2026,int(row["mm"]),int(row["dd"])); end=start+timedelta(days=int(row["window"])-1)
    if not (start<=date(2026,10,6)<=date(2026,10,9)<=end):raise ValueError("r44_stay_outside_trip")
    return _sha(_json(row))


def _validate_residual(accepted:set[str],all_events:set[str]) -> set[str]:
    residual=all_events-accepted
    if (len(accepted)!=1528 or len(residual)!=3800 or _setsha(residual)!=EXPECTED_RESIDUAL or
            set(EVENTS)&accepted or not set(EVENTS)<residual):
        raise ValueError("r44_selected_not_exact_global_residual")
    return residual


def _selected_payload(raw:object) -> dict[str,object]:
    data=raw.encode() if isinstance(raw,str) else raw
    if not isinstance(data,(bytes,bytearray)):raise ValueError("r44_selected_payload_invalid")
    parsed=r36._strict_json(bytes(data),"r44_selected_payload")
    if not isinstance(parsed,dict):raise ValueError("r44_selected_payload_invalid")
    return parsed


def _validate_selected_event(event:dict[str,object],payload:dict[str,object],role:str,content_sha:str) -> int:
    signed=int(event["signed_amount_krw"]);expected_dates=("2026-03-20","2026-03-23") if role=="purchase" else ("2026-04-07","2026-04-07")
    expected_cancel=role=="cancellation"
    if (event["current_event_sha256"]!=content_sha or event["source_system"]!="KBO" or
        event["current_source_kind"]!="card_raw" or event["event_role"]!="single" or
        event["transaction_type"]!=role or str(event.get("card4"))!="8835" or str(event.get("currency"))!="JPY" or
        str(event.get("foreign_amount")).replace(",","") not in {"92001","92001.0"} or
        signed!=(893170 if role=="purchase" else -893170) or str(event.get("merchant"))!="TRIP.COM" or
        (str(event.get("occurred_on")),str(event.get("posted_on")))!=expected_dates or
        payload.get("orig_appr") not in (None,"") or payload.get("appr") not in (None,"") or
        payload.get("biz")!="해외" or str(payload.get("merchant",""))!=str(event.get("merchant","")) or
        payload.get("cancel") is not expected_cancel):
        raise ValueError("r44_selected_event_contract_invalid")
    return signed


def _live(ledger_dir: Path):
    if ledger_dir.resolve()!=(REPOSITORY_ROOT/"ledger").resolve():raise ValueError("r44_noncanonical_ledger")
    if (r42.EXPECTED_CURRENT,r42.EXPECTED_SCOPE,r42.EXPECTED_RESIDUAL,r42.ACCEPTED_UNION_COUNT,
            r42.RESIDUAL_COUNT,r42.REMAINING24_SET_SHA256)!=(EXPECTED_CURRENT,EXPECTED_SCOPE,
            "f52cc4accd1afaf66150a96e375aee76167227170e87c9aa7ce7db00f7ab8b47",1528,3800,EXPECTED_FRONTIER24):
        raise ValueError("r44_r42_context_invalid")
    m42={"package_set_sha256":EXPECTED_R42_PACKAGE}
    with tempfile.TemporaryDirectory(prefix="r44-current-") as td:
        ctx=r36._context(ledger_dir,Path(td));db=ctx["db"];events={x["direct_event_key"]:x for x in ctx["events"]};bindings=[]
        try:
            if (ctx["current_event_set_sha256"],ctx["decision_scope_sha256"])!=(EXPECTED_CURRENT,EXPECTED_SCOPE):raise ValueError("r44_current_context_invalid")
            for key,(role,content_sha) in EVENTS.items():
                event=events.get(key)
                if event is None:raise ValueError("r44_selected_event_drift")
                raw=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(event["current_source_key"],)).fetchone()
                if raw is None:raise ValueError("r44_selected_payload_missing")
                payload=_selected_payload(raw[0]);signed=_validate_selected_event(event,payload,role,content_sha)
                bindings.append({"key":key,"event_key_sha256":_sha(key.encode()),"current_event_sha256":content_sha,
                    "current_source_sha256":event["current_source_sha256"],"current_source_locator_sha256":r36._source_locator_sha(event),
                    "current_payload_sha256":_sha(_json(payload)),"transaction_type":role,"amount":signed,
                    "foreign_signed":92001 if role=="purchase" else -92001})
        finally:db.close()
    if _setsha(EVENTS)!=SELECTED_SET or _setsha(k for k,v in EVENTS.items() if v[0]=="purchase")!=PURCHASE_SET or _setsha(k for k,v in EVENTS.items() if v[0]=="cancellation")!=CANCEL_SET:
        raise ValueError("r44_selected_set_invalid")
    accepted,f38=_accepted_union(ledger_dir);residual=_validate_residual(accepted,set(events))
    frontier=list(csv.DictReader(io.StringIO(f38["exclusions.csv"].decode())))
    frontier_keys={x["direct_event_key"] for x in frontier}; cancellation_keys={k for k,v in EVENTS.items() if v[0]=="cancellation"}
    if len(frontier)!=24 or frontier_keys&set(EVENTS)!=cancellation_keys:
        raise ValueError("r44_frontier_overlap_invalid")
    remaining=[x for x in frontier if x["direct_event_key"] not in cancellation_keys]
    if len(remaining)!=22:raise ValueError("r44_remaining22_invalid")
    return m42,bindings,residual,remaining


def _permutation_sha(bindings: list[dict[str,object]]) -> str:
    p=[x for x in bindings if x["transaction_type"]=="purchase"];c=[x for x in bindings if x["transaction_type"]=="cancellation"]
    signatures=set()
    for pp in itertools.permutations(p):
        for cc in itertools.permutations(c):
            rows=[(x["event_key_sha256"],x["current_event_sha256"],x["current_source_sha256"],
                   x["current_source_locator_sha256"],x["current_payload_sha256"],x["transaction_type"],
                   ACCOUNT,COST_TYPE,VAT_TAG,TRIP_TARGET,POSTING_BUCKET) for x in (*pp,*cc)]
            signatures.add(_sha(_json(sorted(rows))))
    if len(signatures)!=1:raise ValueError("r44_permutation_invariance_failed")
    return signatures.pop()


def _validate_atomic_bindings(bindings:list[dict[str,object]]) -> None:
    if len(bindings)!=4 or {x["key"] for x in bindings}!=set(EVENTS):raise ValueError("r44_atomic_member_set_invalid")
    purchases={x["key"] for x in bindings if x["transaction_type"]=="purchase"}
    cancellations={x["key"] for x in bindings if x["transaction_type"]=="cancellation"}
    if (len(purchases)!=2 or _setsha(purchases)!=PURCHASE_SET or len(cancellations)!=2 or _setsha(cancellations)!=CANCEL_SET or
        sum(int(x["amount"]) for x in bindings if x["transaction_type"]=="purchase")!=1786340 or
        sum(int(x["amount"]) for x in bindings if x["transaction_type"]=="cancellation")!=-1786340 or
        sum(int(x["foreign_signed"]) for x in bindings if x["transaction_type"]=="purchase")!=184002 or
        sum(int(x["foreign_signed"]) for x in bindings if x["transaction_type"]=="cancellation")!=-184002):
        raise ValueError("r44_atomic_role_or_total_invalid")


def _privacy_scan(files: dict[str,bytes]) -> None:
    blob=b"".join(files.values()).decode()
    forbidden=(r"card:[0-9a-f]{64}#",r"@[A-Za-z0-9.-]+",r"https?://",r"(?<![0-9A-Za-z])1[0-9]{15}(?![0-9A-Za-z])",r"\b8835\b",r"\b92001\b",r"order_ref",r"target_event")
    if any(re.search(x,blob,re.I) for x in forbidden):raise ValueError("r44_public_privacy_violation")


def _public_allowlist(files:dict[str,bytes]) -> None:
    expected={"groups.csv":GROUP_FIELDS,"proposals.csv":PROPOSAL_FIELDS,"exclusions.csv":EXCLUSION_FIELDS}
    for name,fields in expected.items():
        rows=list(csv.DictReader(io.StringIO(files[name].decode())))
        actual_fields=tuple(rows[0].keys()) if rows else tuple(files[name].decode().splitlines()[0].split(","))
        if actual_fields!=fields:raise ValueError("r44_public_schema_invalid")
        for row in rows:
            for key,value in row.items():
                if key.endswith(("_sha256","_id")) and value and not re.fullmatch(r"[0-9a-f]{64}",value):raise ValueError("r44_public_value_invalid")
            if row.get("authority_status")!="unattested" or row.get("posting_status")!="blocked" or row.get("applied")!="false":raise ValueError("r44_public_authority_invalid")
    manifest=json.loads(files["manifest.json"])
    forbidden_keys=re.compile(r"(?:message|order|gmail|approval|refund_locator|pdf_sha|text_sha)",re.I)
    def walk(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if forbidden_keys.search(str(key)):raise ValueError("r44_public_manifest_key_invalid")
                walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(manifest)


def _build(documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
    authenticated=auth.verify_provenance(documents_dir,provenance_path,key_path,pypdf_python)
    provenance=authenticated["provenance"]
    if provenance.get("relevant_lifecycle_count")!=2 or len(provenance.get("lifecycles",[]))!=2:raise ValueError("r44_provenance_lifecycle_invalid")
    m42,bindings,residual,remaining=_live(ledger_dir);_validate_atomic_bindings(bindings);trip_sha=_trip_contract(ledger_dir);permutation_sha=_permutation_sha(bindings)
    group_id=_sha(_json({"artifact":ARTIFACT_TYPE,"selected":SELECTED_SET,"provenance":authenticated["provenance_sha256"]}))
    group={"group_id":group_id,"member_set_sha256":SELECTED_SET,"purchase_set_sha256":PURCHASE_SET,"cancellation_set_sha256":CANCEL_SET,
        "member_count":4,"purchase_count":2,"cancellation_count":2,"provenance_commitment_sha256":authenticated["provenance_sha256"],
        "trip_target":TRIP_TARGET,"posting_bucket":POSTING_BUCKET,"relation_kind":"complete_group_provider_lifecycle_lodging_support",
        "bijection_asserted":False,"individual_relation_count":0,"permutation_invariant":True,
        "disposition":"atomic_all_four_support_only_capture_claim_unverified","authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],
        "confirmed_count":0,"gate5_credit":0,"applied":False}
    proposals=[]
    for event in sorted(bindings,key=lambda x:x["event_key_sha256"]):
        item={k:v for k,v in event.items() if k not in {"key","amount","foreign_signed"}}
        item.update({"group_id":group_id,"account":ACCOUNT,"cost_type":COST_TYPE,"vat_tag":VAT_TAG,"trip_target":TRIP_TARGET,
            "posting_bucket":POSTING_BUCKET,"relation_kind":"complete_group_provider_lifecycle_lodging_support","bijection_asserted":False,
            "individual_relation_count":0,"atomic_group_required":True,"atomic_member_count":4,
            "disposition":"atomic_all_four_support_only_capture_claim_unverified","authority_status":AUTHORITY[0],
            "posting_status":AUTHORITY[1],"confirmed_count":0,"gate5_credit":0,"applied":False})
        item["proposal_id"]=_sha(_json({"group":group_id,"event":item["event_key_sha256"],"content":item["current_event_sha256"]}))
        proposals.append(item)
    if (len(proposals)!=4 or len({x["group_id"] for x in proposals})!=1 or
            {x["atomic_member_count"] for x in proposals}!={4} or
            {x["event_key_sha256"] for x in proposals}!={_sha(x.encode()) for x in EVENTS}):
        raise ValueError("r44_atomic_or_netzero_invalid")
    exclusions=[]
    for old in remaining:
        item={"event_key_sha256":_sha(old["direct_event_key"].encode()),"current_event_sha256":old["current_event_sha256"],
              "group_id":old["group_id"],"group_member_set_sha256":old["group_member_set_sha256"],"reason_code":old["reason_code"],
              "disposition":"deferred_insufficient_independent_evidence","authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],
              "confirmed_count":0,"gate5_credit":0,"applied":False}
        item["exclusion_id"]=_sha(_json(item));exclusions.append(item)
    payload={"groups.csv":_csv(GROUP_FIELDS,[group]),"proposals.csv":_csv(PROPOSAL_FIELDS,proposals),
             "exclusions.csv":_csv(EXCLUSION_FIELDS,sorted(exclusions,key=lambda x:x["event_key_sha256"]))}
    base={"artifact_type":ARTIFACT_TYPE,"rule_version":RULE_VERSION,"authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],
        "confirmed_count":0,"gate5_credit":0,"applied":False,"contains_sensitive_raw_values":False,"atomic_all_four":True,
        "full_classification_delta":0,"selection_census_authority":"capture_claim_unverified",
        "bijection_asserted":False,"individual_relation_count":0,"accepted_union":1528,"review_candidate_count":4,
        "global_residual":3800,
        "supported_global_set_sha256":SELECTED_SET,"frontier_authoritative":24,"supported_frontier":2,
        "unsupported_frontier_set_sha256":_setsha(x["direct_event_key"] for x in remaining),"selected_set_sha256":SELECTED_SET,
        "purchase_set_sha256":PURCHASE_SET,"cancellation_set_sha256":CANCEL_SET,"permutation_semantic_sha256":permutation_sha,
        "posting_bucket":POSTING_BUCKET,"trip_target":TRIP_TARGET,"trip_row_sha256":trip_sha,"a0_policy_sha256":A0_POLICY_SHA256,
        "trips_raw_sha256":TRIPS_SHA256,"provenance_sha256":authenticated["provenance_sha256"],
        "capture_claims":provenance["capture_claims"],
        "extractor_contract_sha256":auth.EXTRACTOR_CONTRACT_SHA256,"r42_package_set_sha256_pinned":m42["package_set_sha256"],
        "current_event_set_sha256":EXPECTED_CURRENT,"decision_scope_sha256":EXPECTED_SCOPE,
        "state_semantics":"support-only; capture completeness unauthenticated; no accepted or residual change authorized",
        "files":{k:{"sha256":_sha(v),"rows":len(v.splitlines())-1} for k,v in payload.items()}}
    base["package_set_sha256"]=_sha(_json(base)+b"".join(payload[k] for k in sorted(payload)))
    files={"manifest.json":_json(base),**payload};_privacy_scan(files);_public_allowlist(files)
    return base,files


def _capture(directory:Path):
    try:return r42._capture_package(directory,FILES)
    except ValueError as exc:raise ValueError("r44_package_shape_invalid") from exc


def _fs_identity(st):return (st.st_dev,st.st_ino)


def _capture_dirfd(dirfd:int):
    dst=os.fstat(dirfd)
    if not stat.S_ISDIR(dst.st_mode) or stat.S_IMODE(dst.st_mode)!=0o700 or dst.st_uid!=os.getuid() or set(os.listdir(dirfd))!=set(FILES):raise ValueError("r44_package_shape_invalid")
    result={}
    for name in FILES:
        fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),dir_fd=dirfd)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_uid!=os.getuid():raise ValueError("r44_package_shape_invalid")
            chunks=[]
            while True:
                chunk=os.read(fd,1024*1024)
                if not chunk:break
                chunks.append(chunk)
            after=os.fstat(fd)
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError("r44_package_changed_during_read")
            result[name]=b"".join(chunks)
        finally:os.close(fd)
    return result


def _rename_noreplace_at(parentfd:int,source:str,target:str):
    try:fn=getattr(ctypes.CDLL(None,use_errno=True),"renameat2")
    except AttributeError as exc:raise OSError("r44_atomic_noreplace_unsupported") from exc
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
    if fn(parentfd,os.fsencode(source),parentfd,os.fsencode(target),1)==0:return
    code=ctypes.get_errno()
    if code==errno.EEXIST:raise FileExistsError("r44_output_exists")
    raise OSError(code,"r44_renameat2")


def build_trip_cancel_lifecycle_evidence(documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path,output:Path|None=None):
    manifest,files=_build(documents_dir,provenance_path,key_path,pypdf_python)
    if output is None:return {"manifest":manifest,"files":files}
    if output.parent.is_symlink():raise ValueError("r44_output_parent_symlink")
    out=output.resolve();parent=out.parent.resolve(strict=True)
    if REPOSITORY_ROOT.resolve() in (out,*out.parents):raise ValueError("r44_output_inside_repository")
    if os.path.lexists(out):raise FileExistsError(out)
    parentfd=os.open(output.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0));parent_identity=_fs_identity(os.fstat(parentfd))
    if _fs_identity(os.stat(output.parent,follow_symlinks=False))!=parent_identity:os.close(parentfd);raise ValueError("r44_parent_identity_changed")
    stage_path=Path(tempfile.mkdtemp(prefix=".r44-stage-",dir=f"/proc/self/fd/{parentfd}"));stage_name=stage_path.name
    os.chmod(stage_path,0o700);stagefd=os.open(stage_name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=parentfd);published=False;targetfd=None;target_identity=None
    try:
        for name,data in files.items():
            fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600,dir_fd=stagefd)
            try:
                view=memoryview(data)
                while view:view=view[os.write(fd,view):]
                os.fsync(fd)
            finally:os.close(fd)
        os.fsync(stagefd)
        if _capture_dirfd(stagefd)!=files:raise ValueError("r44_stage_verify_failed")
        if (_fs_identity(os.fstat(parentfd))!=parent_identity or
                _fs_identity(os.stat(output.parent,follow_symlinks=False))!=parent_identity):raise ValueError("r44_parent_identity_changed")
        _rename_noreplace_at(parentfd,stage_name,out.name);published=True;os.close(stagefd);stagefd=None
        targetfd=os.open(out.name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=parentfd);target_identity=_fs_identity(os.fstat(targetfd))
        try:
            if _capture_dirfd(targetfd)!=files:raise ValueError("r44_post_install_bytes_mismatch")
        except Exception as exc:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity) from exc
        try:
            os.fsync(parentfd)
        except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"],parent_identity,target_identity) from exc
        if (_fs_identity(os.fstat(parentfd))!=parent_identity or _fs_identity(os.fstat(targetfd))!=target_identity or
                _fs_identity(os.stat(output.parent,follow_symlinks=False))!=parent_identity):raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity)
        try:
            if _capture_dirfd(targetfd)!=files:raise ValueError("r44_post_fsync_bytes_mismatch")
        except Exception as exc:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity) from exc
    finally:
        if targetfd is not None:os.close(targetfd)
        if stagefd is not None:os.close(stagefd)
        if not published and stage_path.exists():shutil.rmtree(stage_path)
        os.close(parentfd)
    return {"manifest":manifest,"output":str(out)}


def verify_trip_cancel_lifecycle_evidence(directory:Path,documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path):
    manifest,expected=_build(documents_dir,provenance_path,key_path,pypdf_python);actual=_capture(directory)
    if actual!=expected:raise ValueError("r44_package_or_context_mismatch")
    return {"status":"valid","package_set_sha256":manifest["package_set_sha256"],"proposals":4,
            "frontier_authoritative":24,"supported_frontier":2,"full_classification_delta":0}


def reconcile_publication(error,documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path):
    if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r44_reconcile_state_invalid")
    if error.parent_identity is None or error.target_identity is None:raise ValueError("r44_reconcile_identity_missing")
    manifest,expected=_build(documents_dir,provenance_path,key_path,pypdf_python)
    parentfd=os.open(error.parent_path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
    try:
        if _fs_identity(os.fstat(parentfd))!=error.parent_identity:raise ValueError("r44_reconcile_parent_identity_mismatch")
        targetfd=os.open(error.target_name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=parentfd)
        try:
            if _fs_identity(os.fstat(targetfd))!=error.target_identity or _capture_dirfd(targetfd)!=expected:raise ValueError("r44_reconcile_target_identity_mismatch")
            os.fsync(parentfd)
            if (_fs_identity(os.fstat(parentfd))!=error.parent_identity or _fs_identity(os.fstat(targetfd))!=error.target_identity or
                    _capture_dirfd(targetfd)!=expected):raise ValueError("r44_reconcile_identity_changed")
        finally:os.close(targetfd)
    finally:os.close(parentfd)
    if manifest["package_set_sha256"]!=error.package_set_sha256:raise ValueError("r44_reconcile_package_mismatch")
    return {"status":"valid","package_set_sha256":manifest["package_set_sha256"],"proposals":4,"frontier_authoritative":24,"published":True,"durable":True}


def main(argv=None):
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest="command",required=True)
    for name in ("build","verify"):
        x=sp.add_parser(name);x.add_argument("--documents-dir",type=Path,required=True);x.add_argument("--provenance",type=Path,required=True)
        x.add_argument("--key-path",type=Path,required=True);x.add_argument("--pypdf-python",type=Path,required=True);x.add_argument("--output",type=Path,required=True)
    a=p.parse_args(argv);result=(build_trip_cancel_lifecycle_evidence(a.documents_dir,a.provenance,a.key_path,a.pypdf_python,a.output)
        if a.command=="build" else verify_trip_cancel_lifecycle_evidence(a.output,a.documents_dir,a.provenance,a.key_path,a.pypdf_python))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,default=str));return 0


if __name__=="__main__":raise SystemExit(main())
