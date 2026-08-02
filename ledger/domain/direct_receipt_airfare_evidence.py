"""Strict external-only R43 airfare receipt evidence for six pinned PDFs.

Raw PDFs, extracted text, provenance and identifiers stay in a restricted directory.
Only privacy-safe group-level review proposals are published.
"""
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
from datetime import datetime
from pathlib import Path

from ledger.domain import direct_document_acquisition_census as r42
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_receipt_airfare_provenance as r43auth
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _install_noreplace

ARTIFACT_TYPE = "r43-receipt-airfare-evidence-v1"
RULE_VERSION = "r43-six-pinned-airfare-receipts-v1"
EXTRACTOR_CONTRACT = r43auth.EXTRACTOR_CONTRACT
EXTRACTOR_CONTRACT_SHA256 = r43auth.EXTRACTOR_CONTRACT_SHA256
A0_POLICY_SHA256 = "d4ebe4b7fc0584b72f51e2d3a883f55c4bf7c1f5e6f2dbd46da2df8df5e7837c"
FILES = ("manifest.json", "documents.csv", "groups.csv", "proposals.csv")
EXPECTED_UNION = 1528
EXPECTED_RESIDUAL = 3800
EXPECTED_R36_PACKAGE = "f7574ecc81fae0b9d05ff75bfb2bdaf69be1c652099a62dcb3ef26bd15a0b530"
EXPECTED_R38_PACKAGE = "fe98ee996188b46ddbf934626c64d036dd1d9a1da3f8cbd3c2ff93f7c10ad868"
EXPECTED_R42_PACKAGE = "6b384c2d39ee66c9e0d4032fd1da235106011aac86c4d4bd754227a38e25afe7"
EXPECTED_FRONTIER = "ab199a1614713567304b19deaeb0871e849b8e7d813b6a3449d2ad3d393f5d16"

class PublicationDurabilityError(OSError):
    def __init__(self,output:Path,package_set_sha256:str):
        super().__init__("r43_published_durability_unknown");self.output=output;self.package_set_sha256=package_set_sha256;self.published=True

class PublicationIntegrityError(OSError):
    def __init__(self,output:Path,package_set_sha256:str):
        super().__init__("r43_published_integrity_invalid");self.output=output;self.package_set_sha256=package_set_sha256;self.published=True

GROUPS = {
    "1a5034f2897878b0b396a544d9337886eac85815729504400066152bb6905fc6": {
        "member_sha": "dbba027693b8aacd945551d61d301d7895a90147a76bc0168b52622e9c20d887",
        "bucket": "0712_몽골", "aliases": ("mytrip_a", "mytrip_b"),
        "provider": "mytrip_gotogate",
        "service_tokens": ("Ulaanbaatar International Airport", "26. 7.", "12.", "16.", "항공편"),
        "parts": (673969, 119700),
    },
    "fe0992319dd7cd96d6c1aa4134d4ec4ff04496d72351583d3c5aa1d24cc2cc29": {
        "member_sha": "1778c638956cedc316683879ec1072da135d4df4fc199d4aa89750610b63c1e6",
        "bucket": "0924_야마구치", "aliases": ("mytrip_c", "mytrip_d"),
        "provider": "mytrip_gotogate",
        "service_tokens": ("후쿠오카", "26. 9. 24.", "26. 10. 1.", "항공편"),
        "parts": (275867, 86057),
    },
    "4792823347ceedb9e764952351c187ede6be26c03592e9d85d9551e729ba23a5": {
        "member_sha": "618073eac93beedb695f5681ace201b25ed384fcbd9a2700d7a2f20ebba4f68e",
        "bucket": "5월_유럽", "aliases": ("trip_a", "trip_b"),
        "provider": "tripcom",
        "service_tokens": ("Istanbul - Prague", "May 15, 2026", "Flights"),
        "parts": (70600, 127800, 10000),
    },
}

DOCS = {
    "mytrip_a": ("7b1bd600567a58e2892027520ab0768959e0a5acc2565d6533a921accce71bf7", "f611c0a4b9eb19949bd9d6d5b52cf0b24c0a64f1f0623594f7b0d25b5a6c6ef7", 1),
    "mytrip_b": ("df3cb67b8ac196cfc3d22e2450d7192766d2b4052124718d206a2278f8fa3023", "f9aa66d2743e3146fc6fa88d672f33c917b4ffff234ffd0369f33580cf8742eb", 1),
    "mytrip_c": ("6b57164bd8f4725c96526f76fbe9340c5a50691f6eff8c58d0bd39939334e3d2", "37b57de534cc0dea95a8472ce35d3ec2375112939c8a95d31dc8459c6eaaf4b7", 1),
    "mytrip_d": ("5d3bcfc4936126f0a95759b7d2d6f93c88d79b3b3971303fbf35500cf27a378d", "f490a5f50e02fe0172059a49813dd6aeb308b503c6454c371ded8fd3efdf70e0", 1),
    "trip_a": ("71c9dbffaff92d6572f1ffd6014d616bf0d34c24443ac2b1c56d7185b3e22e22", "b02033db4c8147342724a7cd7823caad6ef7418ad9277ba6e4c419b757828d69", 2),
    "trip_b": ("e8b0087c7a245663d63edf392edcac233f5503520b7211f2385333d6b3f341e3", "0e84d350a0152b0d8b878e45f572bbd3312fbead5a976effc5114fd231435d0e", 2),
}

DOC_FIELDS = ("document_id", "provider", "pages", "coverage", "authority_status", "posting_status")
GROUP_FIELDS = ("group_id", "member_set_sha256", "document_set_sha256", "member_count", "document_count", "bucket", "bijection_asserted", "disposition", "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")
PROPOSAL_FIELDS = ("proposal_id", "event_key_sha256", "current_event_sha256", "current_source_sha256",
                   "current_source_locator_sha256", "current_payload_sha256", "group_id", "account",
                   "cost_type", "vat_tag", "bucket", "bijection_asserted", "disposition",
                   "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")

def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def _setsha(values) -> str: return _sha(_json(sorted(values)))
def _csv(fields, rows) -> bytes:
    s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
    for row in rows:w.writerow({k:(str(row.get(k, "")).lower() if isinstance(row.get(k),bool) else row.get(k,"")) for k in fields})
    return s.getvalue().encode()

def _read_private(directory: Path, name: str) -> bytes:
    try:
        dirfd=os.open(directory,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
    except OSError as exc:
        raise ValueError("r43_private_directory_invalid") from exc
    try:
        dst=os.fstat(dirfd)
        if not stat.S_ISDIR(dst.st_mode) or stat.S_IMODE(dst.st_mode)!=0o700 or dst.st_uid!=os.getuid():
            raise ValueError("r43_private_directory_invalid")
        try:
            fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),dir_fd=dirfd)
        except OSError as exc:
            raise ValueError("r43_private_file_invalid") from exc
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_uid!=os.getuid():
                raise ValueError("r43_private_file_invalid")
            chunks=[]
            while True:
                chunk=os.read(fd,1024*1024)
                if not chunk:break
                chunks.append(chunk)
            after=os.fstat(fd)
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                raise ValueError("r43_private_file_changed")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)

def _capture_package(directory: Path) -> dict[str,bytes]:
    try:return r42._capture_package(directory,FILES)
    except ValueError as exc:raise ValueError("r43_package_shape_invalid") from exc

def _parse(alias: str, text: str, cfg: dict) -> tuple[str,str,str,int]:
    if "�" in text or "\x00" in text: raise ValueError("r43_extractor_text_invalid")
    if cfg["provider"]=="mytrip_gotogate":
        required=("Gotogate Korea LLC","주문 번호:","예약 일자:","영수증","MASTERCARD Corporate")
        m=re.search(r"주문 번호:\s*([0-9]{4}-[0-9]{3}-[0-9]{3})",text)
        date_match=re.search(r"예약 일자:\s*([0-9]{2})\.\s*([0-9]{1,2})\.\s*([0-9]{1,2})\.",text)
        totals=[int(x.replace(",","")) for x in re.findall(r"총계\s*([0-9,]+)\s*KRW",text)]
        blocks=re.findall(r"(?m)^결제 정보 요약\n설명 가격 세금 및 수수료 합계\n[^\n]+\n[^\n]*성인\s*\n항공편\s+([0-9,]+)\s*KRW\s+([0-9,]+)\s*KRW\s+([0-9,]+)\s*KRW\n합계\s+([0-9,]+)\s*KRW\n총계\s+([0-9,]+)\s*KRW$",text)
    else:
        required=("Trip.com Travel Singapore Pte. Ltd.","Booking No.","Date of Booking:","Receipt","Kookmin Card")
        m=re.search(r"Booking No\.\s*([0-9]{16})",text)
        date_match=re.search(r"Date of Booking:\s*[0-9]{1,2}∶[0-9]{2}\s*(?:AM|PM),\s*([A-Z][a-z]+\s+[0-9]{1,2},\s+[0-9]{4})\s*\(GMT[+-][0-9]+\)",text)
        totals=[int(x.replace(",","")) for x in re.findall(r"Total .*?KRW\s*([0-9,]+)",text,re.S)]
        blocks=re.findall(r"(?m)^Flights\n(?:[^\n]*\n){4}Fare\nTaxes & fees\nTrip\.com booking fee\nKRW\s+([0-9,]+)\nKRW\s+([0-9,]+)\nKRW\s+([0-9,]+)\nTotal \(Kookmin Card \(credit\) [0-9*]+\) KRW\s+([0-9,]+)$",text)
        if text.count("Booking No.")!=1 or text.count("예약번호")!=1:raise ValueError("r43_tripcom_bilingual_contract_invalid")
    if not all(x in text for x in required) or not m or not date_match or len(blocks)!=1:raise ValueError("r43_provider_template_invalid")
    if not all(x in text for x in cfg["service_tokens"]):raise ValueError("r43_date_or_service_invalid")
    if len(totals)!=1 or totals[0]<=0:raise ValueError("r43_total_invalid")
    captured=tuple(int(x.replace(",","")) for x in blocks[0])
    expected=cfg["parts"]+((totals[0],totals[0],totals[0]) if cfg["provider"]=="mytrip_gotogate" else (totals[0],))
    if captured!=expected:raise ValueError("r43_component_missing")
    if sum(cfg["parts"])!=totals[0]:raise ValueError("r43_arithmetic_invalid")
    if re.search(r"(?i)\b(refund|cancelled|canceled|credit note|void)\b|환불|취소",text):raise ValueError("r43_lifecycle_conflict")
    if cfg["provider"]=="mytrip_gotogate":
        purchase_date=f"20{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    else:
        purchase_date=datetime.strptime(date_match.group(1),"%B %d, %Y").date().isoformat()
    return m.group(1),cfg["provider"],purchase_date,totals[0]

def _privacy_scan(files: dict[str,bytes]) -> None:
    blob=b"".join(files.values()).decode("utf-8")
    patterns=(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",r"\b1[0-9]{15}\b",r"\b[0-9]{3}-[0-9]{9,}\b",r"https?://",r"558526",r"card:[0-9a-f]{64}#")
    if any(re.search(p,blob,re.I) for p in patterns):raise ValueError("r43_public_privacy_violation")

def _provider_from_live(event: dict, payload: dict) -> str:
    merchant=str(payload.get("merchant") or event.get("merchant") or "")
    if "고투게이트" in merchant:return "mytrip_gotogate"
    if "트립닷컴" in merchant:return "tripcom"
    raise ValueError("r43_live_provider_invalid")

def _live_context():
    manifest, files=r42._build()
    if manifest.get("package_set_sha256")!=EXPECTED_R42_PACKAGE:raise ValueError("r43_r42_hash_invalid")
    if manifest["accepted_union"]!=1528 or manifest["incomplete_residual"]!=3800 or manifest["frontier_counts"]["remaining24_events"]!=24:raise ValueError("r43_upstream_count_invalid")
    if manifest["frontier_counts"]["remaining24_events_sha256"]!=EXPECTED_FRONTIER:raise ValueError("r43_frontier_invalid")
    if manifest["upstream"].get("r36_package")!=EXPECTED_R36_PACKAGE or manifest["upstream"].get("r38_package")!=EXPECTED_R38_PACKAGE:raise ValueError("r43_upstream_hash_invalid")
    rows={x["group_id"]:x for x in csv.DictReader(io.StringIO(files["frontier_groups.csv"].decode()))}
    for gid,cfg in GROUPS.items():
        if gid not in rows or rows[gid]["member_set_sha256"]!=cfg["member_sha"] or rows[gid]["bucket"]!=cfg["bucket"] or int(rows[gid]["member_count"])!=2:raise ValueError("r43_group_context_invalid")
    r36_manifest,r36_files=r36._build(REPOSITORY_ROOT/"ledger",r36.DEFAULT_MANUAL_CSV)
    if r36_manifest.get("package_set_sha256")!=EXPECTED_R36_PACKAGE:raise ValueError("r43_r36_hash_invalid")
    support=list(csv.DictReader(io.StringIO(r36_files["bucket_support.csv"].decode())))
    selected={gid:[x for x in support if x["group_id"]==gid] for gid in GROUPS}
    with tempfile.TemporaryDirectory(prefix="r43-current-") as dirname:
        context=r36._context(REPOSITORY_ROOT/"ledger",Path(dirname));db=context["db"]
        events={x["direct_event_key"]:x for x in context["events"]};bindings={}
        try:
            for gid,cfg in GROUPS.items():
                members=selected[gid]
                if len(members)!=2 or r36._event_set_sha({x["direct_event_key"] for x in members})!=cfg["member_sha"]:
                    raise ValueError("r43_live_group_members_invalid")
                bound=[]
                for support_row in members:
                    event=events.get(support_row["direct_event_key"])
                    if event is None:raise ValueError("r43_live_event_missing")
                    raw=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(event["current_source_key"],)).fetchone()
                    if raw is None:raise ValueError("r43_live_payload_missing")
                    payload=json.loads(raw[0]);payload_sha=_sha(_json(payload));locator_sha=r36._source_locator_sha(event)
                    if (event["current_event_sha256"]!=support_row["current_event_sha256"] or
                        locator_sha!=support_row["current_source_locator_sha256"] or
                        event["source_system"]!="KBD" or event["current_source_kind"]!="card_raw" or
                        event["transaction_type"]!="purchase" or event["event_role"]!="single" or
                        str(event.get("currency"))!="KRW" or int(event["signed_amount_krw"])<=0):
                        raise ValueError("r43_live_purchase_contract_invalid")
                    bound.append({"event_key_sha256":_sha(event["direct_event_key"].encode()),
                        "current_event_sha256":event["current_event_sha256"],
                        "current_source_sha256":event["current_source_sha256"],
                        "current_source_locator_sha256":locator_sha,"current_payload_sha256":payload_sha,
                        "purchase_date":str(event["occurred_on"]),"amount":int(event["signed_amount_krw"]),
                        "provider":_provider_from_live(event,payload)})
                if len({x["event_key_sha256"] for x in bound})!=2:raise ValueError("r43_live_event_identity_invalid")
                bindings[gid]=bound
        finally:db.close()
    return manifest,bindings

def _build(documents_dir: Path, provenance_path: Path, key_path: Path,
           pypdf_python: Path):
    d=documents_dir.resolve();
    if REPOSITORY_ROOT.resolve() in (d,*d.parents):raise ValueError("r43_private_input_inside_repository")
    st=d.stat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o700 or d.is_symlink():raise ValueError("r43_private_directory_invalid")
    p=provenance_path.resolve()
    if REPOSITORY_ROOT.resolve() in (p,*p.parents):raise ValueError("r43_private_input_inside_repository")
    authenticated=r43auth.verify_authenticated_inputs(d,p,key_path,DOCS,pypdf_python)
    provenance=authenticated["provenance"]
    entries=provenance.get("documents")
    if not isinstance(entries,list) or {x.get("alias") for x in entries}!=set(DOCS):raise ValueError("r43_provenance_census_invalid")
    live,bindings=_live_context()
    docrows=[]; parsed={}; refs=set()
    for entry in entries:
        alias=entry["alias"]; pdf=_read_private(d,alias+".pdf"); txt=_read_private(d,alias+".txt")
        esha,tsha,pages=DOCS[alias]
        if (_sha(pdf),_sha(txt))!=(esha,tsha) or entry.get("pdf_sha256")!=esha or entry.get("text_sha256")!=tsha or not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]:raise ValueError("r43_document_bytes_invalid")
        gid=next(g for g,c in GROUPS.items() if alias in c["aliases"]);cfg=GROUPS[gid]
        ref,provider,purchase_date,total=_parse(alias,txt.decode("utf-8"),cfg)
        if ref in refs:raise ValueError("r43_duplicate_reference")
        refs.add(ref)
        parsed[alias]=(gid,ref,provider,purchase_date,total)
        docrows.append({"document_id":"doc_"+entry["document_id_hmac"][:32],"provider":cfg["provider"],"pages":pages,"coverage":"airfare|date|amount|arithmetic","authority_status":"unattested","posting_status":"blocked"})
    policy=REPOSITORY_ROOT/"docs/비용분류_지시사항_원장.md"
    if _sha(policy.read_bytes())!=A0_POLICY_SHA256:raise ValueError("r43_a0_policy_drift")
    grouprows=[];props=[]
    for gid,cfg in sorted(GROUPS.items()):
        aliases={a for a,(g,*_) in parsed.items() if g==gid}
        if aliases!=set(cfg["aliases"]):raise ValueError("r43_partial_or_swapped_group")
        receipt_facts={(parsed[a][2],parsed[a][3],parsed[a][4]) for a in aliases}
        live_facts={(x["provider"],x["purchase_date"],x["amount"]) for x in bindings[gid]}
        if len(receipt_facts)!=1 or receipt_facts!=live_facts:raise ValueError("r43_receipt_live_fact_mismatch")
        dset=_setsha("doc_"+next(x for x in entries if x["alias"]==a)["document_id_hmac"][:32] for a in aliases)
        grouprows.append({"group_id":gid,"member_set_sha256":cfg["member_sha"],"document_set_sha256":dset,"member_count":2,"document_count":2,"bucket":cfg["bucket"],"bijection_asserted":False,"disposition":"group_support_only_no_payment_locator","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False})
        for event in bindings[gid]:
            item={**event,"group_id":gid,"account":"항공료","cost_type":"여행원가","vat_tag":("불공제_해외" if cfg["provider"]=="tripcom" else "검토필요"),"bucket":cfg["bucket"],"bijection_asserted":False,"disposition":"support_only_no_payment_locator","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False}
            item.pop("purchase_date");item.pop("amount");item.pop("provider")
            item["proposal_id"]=_sha(_json({"group":gid,"event":item["event_key_sha256"],"content":item["current_event_sha256"]}))
            props.append(item)
    payload={"documents.csv":_csv(DOC_FIELDS,sorted(docrows,key=lambda x:x["document_id"])),"groups.csv":_csv(GROUP_FIELDS,grouprows),"proposals.csv":_csv(PROPOSAL_FIELDS,sorted(props,key=lambda x:x["event_key_sha256"]))}
    base={"artifact_type":ARTIFACT_TYPE,"rule_version":RULE_VERSION,"extractor_contract_sha256":EXTRACTOR_CONTRACT_SHA256,"a0_policy_sha256":A0_POLICY_SHA256,"r36_package_set_sha256":live["upstream"]["r36_package"],"r38_package_set_sha256":live["upstream"]["r38_package"],"r42_package_set_sha256":live["package_set_sha256"],"remaining24_set_sha256":EXPECTED_FRONTIER,"accepted_union":EXPECTED_UNION,"incomplete_residual":EXPECTED_RESIDUAL,"state_semantics":"live_accepted_union_unchanged;support_rows_are_not_accepted","full_classification_delta":0,"review_candidate_count":6,"groups":3,"documents":6,"proposals":6,"bijection_asserted":False,"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False,"contains_sensitive_raw_values":False,"files":{k:{"sha256":_sha(v),"rows":len(v.splitlines())-1} for k,v in payload.items()}}
    base["package_set_sha256"]=_sha(_json(base)+b"".join(payload[k] for k in sorted(payload)))
    files={"manifest.json":_json(base),**payload};_privacy_scan(files)
    return base,files

def build_receipt_airfare_evidence(documents_dir: Path, provenance_path: Path,
                                   key_path: Path, pypdf_python: Path,
                                   output: Path|None=None):
    manifest,files=_build(documents_dir,provenance_path,key_path,pypdf_python)
    if output is None:return {"manifest":manifest,"files":files}
    out=output.resolve()
    if REPOSITORY_ROOT.resolve() in (out,*out.parents):raise ValueError("r43_output_inside_repository")
    if os.path.lexists(out):raise FileExistsError(out)
    if out.parent.is_symlink():raise ValueError("r43_output_parent_symlink")
    parent=out.parent.resolve(strict=True)
    stage=Path(tempfile.mkdtemp(prefix=".r43-stage-",dir=out.parent));os.chmod(stage,0o700);published=False
    try:
        for name,data in files.items():
            fd=os.open(stage/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                view=memoryview(data)
                while view:view=view[os.write(fd,view):]
                os.fsync(fd)
            finally:os.close(fd)
        fd=os.open(stage,os.O_RDONLY|getattr(os,"O_DIRECTORY",0));os.fsync(fd);os.close(fd)
        if _capture_package(stage)!=files:raise ValueError("r43_stage_verify_failed")
        _install_noreplace(stage,out)
        published=True
        try:
            if _capture_package(out)!=files:raise ValueError("r43_post_install_bytes_mismatch")
        except Exception as exc:raise PublicationIntegrityError(out,manifest["package_set_sha256"]) from exc
        try:fd=os.open(parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
        except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"]) from exc
        try:
            try:os.fsync(fd)
            except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"]) from exc
        finally:os.close(fd)
        try:
            if _capture_package(out)!=files:raise ValueError("r43_post_fsync_bytes_mismatch")
        except Exception as exc:raise PublicationIntegrityError(out,manifest["package_set_sha256"]) from exc
    finally:
        if not published and stage.exists():shutil.rmtree(stage)
    return {"manifest":manifest,"output":str(out)}

def verify_receipt_airfare_evidence(directory: Path, documents_dir: Path,
                                    provenance_path: Path, key_path: Path,
                                    pypdf_python: Path):
    expected_manifest,expected=_build(documents_dir,provenance_path,key_path,pypdf_python)
    actual=_capture_package(directory)
    if actual!=expected:raise ValueError("r43_package_or_context_mismatch")
    return {"status":"valid","package_set_sha256":expected_manifest["package_set_sha256"],"proposals":6}

def reconcile_publication(error:PublicationDurabilityError|PublicationIntegrityError,documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path):
    if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r43_reconcile_state_invalid")
    first=verify_receipt_airfare_evidence(error.output,documents_dir,provenance_path,key_path,pypdf_python)
    try:fd=os.open(error.output.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
    except OSError as exc:raise PublicationDurabilityError(error.output,error.package_set_sha256) from exc
    try:
        try:os.fsync(fd)
        except OSError as exc:raise PublicationDurabilityError(error.output,error.package_set_sha256) from exc
    finally:os.close(fd)
    second=verify_receipt_airfare_evidence(error.output,documents_dir,provenance_path,key_path,pypdf_python)
    if first!=second or first["package_set_sha256"]!=error.package_set_sha256:raise ValueError("r43_reconcile_package_mismatch")
    return {**second,"published":True,"durable":True}

def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(description="Build or verify the external-only R43 airfare evidence package")
    sub=parser.add_subparsers(dest="command",required=True)
    for command in ("build","verify"):
        p=sub.add_parser(command)
        p.add_argument("--documents-dir",type=Path,required=True)
        p.add_argument("--provenance",type=Path,required=True)
        p.add_argument("--key-path",type=Path,required=True)
        p.add_argument("--pypdf-python",type=Path,required=True)
        p.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    result=(build_receipt_airfare_evidence(args.documents_dir,args.provenance,args.key_path,args.pypdf_python,args.output) if args.command=="build" else verify_receipt_airfare_evidence(args.output,args.documents_dir,args.provenance,args.key_path,args.pypdf_python))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,default=str))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
