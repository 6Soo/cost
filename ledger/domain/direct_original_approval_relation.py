"""R40 external-only exact original-approval relation annex."""
from __future__ import annotations
import csv,hashlib,io,json,os,re,shutil,stat,tempfile
from ledger.domain.staged_inputs import staged
from collections import Counter,defaultdict
from pathlib import Path
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_narrow_service_classification as r37
from ledger.domain import direct_structured_lodging_evidence as r38
from ledger.domain.han_normalizer import HAN_NORMALIZER_CONTRACT_SHA256,HAN_NORMALIZER_VERSION
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, build_annex, _install_noreplace
from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity
from ledger.domain.direct_external_manual_evidence import _build_package as build25
from ledger.domain.direct_verified_booking_evidence import EXPECTED_RELATIONS as BOOKING_RELATIONS
from ledger.domain.direct_repository_booking_evidence import EXPECTED_BOOKING_NEW,EXPECTED_OTA_NEW

ARTIFACT_TYPE="r40-exact-original-approval-relation-v1"
FILES=("manifest.json","relations.csv","exclusions.csv")
REL_FIELDS=("relation_id","event_key_sha256","target_event_key_sha256","event_content_sha256","target_content_sha256","source_system","event_source_kind","event_source_key_sha256","event_source_sha256","target_source_kind","target_source_key_sha256","target_source_sha256","event_payload_sha256","target_payload_sha256","orig_field_name","target_field_name","normalization_contract","relation_kind","disposition","authority_status","posting_status","confirmed_count","gate5_credit","applied")
EX_FIELDS=("event_key_sha256","event_content_sha256","source_system","event_source_kind","event_source_key_sha256","event_source_sha256","event_payload_sha256","orig_field_name","reason","normalization_contract")
EXPECTED_CURRENT="de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93"
EXPECTED_SCOPE="22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"
EXPECTED_RESIDUAL="f52cc4accd1afaf66150a96e375aee76167227170e87c9aa7ce7db00f7ab8b47"
EXPECTED_RELATIONS="ad1010e6e18fce331eafd5356f7cee5ba913823bb210210a0593e95cbd049cd8"
MANUAL=staged("cost-r25-manual-v4.csv")
NORMALIZATION_CONTRACTS={
 "HAN":{"version":"han-exact-parser-output-v2","inputs":{"ledger/newcard/conv/G.xlsx":"f90ae46f217b2694c3d2fb012bf9550f0b7e395a785f7d19b8e83d5ca9060bb0","ledger/newcard/conv/H.xlsx":"e719a4b5468ae529663118cc2ac3dffc80094d75687d6e868655a7de4f82b9b0"},"parser_version":"direct-source-v4","han_normalizer_version":"han-approval-sheet-v1","han_normalizer_contract_sha256":"2a0575154a206db99cbdabf4f8f6a9eaa78f5d4b4f7660417ce93d21b79bad0d","field_shape":{"card4":3,"approval":4,"source_rows_start":7,"adapter":"digits-only"},"matching":"trimmed-exact-ascii-digits"},
 "KBD":{"version":"kbd-exact-parser-output-v2","inputs":{"ledger/newcard/conv/F.xlsx":"e9f1656a297b76e6834ae5785755cfbffbf9c7ec64d7400db41f5e26440cf4a5"},"parser_version":"direct-source-v4","field_shape":{"card4":5,"approval":15,"status":16,"source_rows_start":2,"cancellation":"cancel_number(original_number)","adapter":"digits-only"},"matching":"trimmed-exact-ascii-digits"}}
def _sha(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def _json(x)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(xs)->str:return r36._event_set_sha(set(xs))
class ApprovalError(ValueError):
    def __init__(self,reason):super().__init__(f"r40_{reason}");self.reason=reason
def normalize_approval(value,issuer:str)->tuple[str,str,str]:
    if value is None or str(value).strip()=="":raise ApprovalError("original_missing")
    if issuer not in NORMALIZATION_CONTRACTS:raise ApprovalError("issuer_contract_missing")
    if isinstance(value,bool) or not isinstance(value,(str,int)):raise ApprovalError("original_type_invalid")
    raw=str(value)
    if not re.fullmatch(r"\s*[0-9]+\s*",raw,re.ASCII):raise ApprovalError("original_format_invalid")
    digits=raw.strip()
    if len(digits)>32:raise ApprovalError("original_precision_invalid")
    if not digits.strip("0"):raise ApprovalError("original_all_zero")
    return raw,digits,NORMALIZATION_CONTRACTS[issuer]["version"]
def _csv(fields,rows):
    s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(rows);return s.getvalue().encode()
class PublicationDurabilityError(OSError):
    def __init__(self,output,package):super().__init__("r40_published_durability_unknown");self.output=output;self.package_set_sha256=package;self.published=True
class PublicationIntegrityError(OSError):
    def __init__(self,output,package):super().__init__("r40_published_integrity_invalid");self.output=output;self.package_set_sha256=package;self.published=True

def _validate_normalization_authority(ledger_dir:Path,inventory):
    if HAN_NORMALIZER_VERSION!=NORMALIZATION_CONTRACTS["HAN"]["han_normalizer_version"] or HAN_NORMALIZER_CONTRACT_SHA256!=NORMALIZATION_CONTRACTS["HAN"]["han_normalizer_contract_sha256"]:raise ValueError("r40_han_normalizer_authority_invalid")
    live={str(x["relative_path"]):x for x in inventory}
    for issuer,contract in NORMALIZATION_CONTRACTS.items():
        for path,digest in contract["inputs"].items():
            item=live.get(path)
            if item is None or item["raw_sha256"]!=digest or item["parser_version"]!=contract["parser_version"]:raise ValueError(f"r40_normalization_authority_invalid:{issuer}:{path}")
    return _sha(_json(NORMALIZATION_CONTRACTS))

def _capture_package(directory:Path,filenames=FILES)->dict[str,bytes]:
    try:dirfd=open_dir(directory)
    except OSError as exc:raise ValueError("r40_package_directory_invalid") from exc
    actual={}
    try:
        dm=os.fstat(dirfd)
        if not stat.S_ISDIR(dm.st_mode) or stat.S_IMODE(dm.st_mode)!=0o700 or (os.name=="posix" and dm.st_uid!=os.getuid()) or set(os.listdir(dirfd))!=set(filenames):raise ValueError("r40_package_shape_invalid")
        for name in filenames:
            try:fd=open_at(dirfd, name)
            except OSError as exc:raise ValueError("r40_package_file_invalid") from exc
            try:
                before=os.fstat(fd)
                verify_regular_single_link(fd, mode=0o600)
                if stat.S_IMODE(before.st_mode)!=0o600:raise ValueError("r40_package_file_invalid")
                chunks=[]
                while True:
                    chunk=os.read(fd,1024*1024)
                    if not chunk:break
                    chunks.append(chunk)
                after=os.fstat(fd)
                if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError("r40_package_changed_during_read")
                actual[name]=b"".join(chunks)
            except OSError as exc:raise ValueError("r40_package_file_invalid") from exc
            finally:os.close(fd)
    finally:os.close(dirfd)
    return actual

def _build(ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
    if ledger_dir.resolve()!=(REPOSITORY_ROOT/"ledger").resolve():raise ValueError("r40_noncanonical_ledger")
    manual_before=(MANUAL.stat(),MANUAL.read_bytes())
    with tempfile.TemporaryDirectory(prefix="r40-") as td:
        ctx=r36._context(ledger_dir,Path(td));db=ctx["db"];events={x["direct_event_key"]:x for x in ctx["events"]};payload={}
        for key,event in events.items():payload[key]=json.loads(db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(event["current_source_key"],)).fetchone()[0])
        db.close()
    authority_sha=_validate_normalization_authority(ledger_dir,ctx["inventory"])
    if (ctx["current_event_set_sha256"],ctx["decision_scope_sha256"])!=(EXPECTED_CURRENT,EXPECTED_SCOPE):raise ValueError("r40_current_context_invalid")
    r23=build_annex(ledger_dir=ledger_dir);m25,f25=build25(MANUAL,ledger_dir);m36,f36=r36._build(ledger_dir,r36.DEFAULT_MANUAL_CSV);m38,f38=r38._build(ledger_dir)
    p25=list(csv.DictReader(io.StringIO(f25["proposals.csv"].decode())));e25=list(csv.DictReader(io.StringIO(f25["evidence_sets.csv"].decode())))
    prior={str(x["direct_event_key"]) for x in r23["package"]["envelopes"] if x.get("historical_uid")}|{x["direct_event_key"] for x in p25}|{x["direct_event_key"] for x in e25 if x["evidence_tier"] in {"clean_110","typed_v14_65","portal_1"}}|{x[2] for x in BOOKING_RELATIONS}|{x[3] for x in EXPECTED_BOOKING_NEW}|{x[3] for x in EXPECTED_OTA_NEW}
    full36={x["direct_event_key"] for x in csv.DictReader(io.StringIO(f36["classifications.csv"].decode()))};accepted=prior|full36|set(r37.EXPECTED_EVENTS)|set(r38.EXPECTED_EVENTS);residual=set(events)-accepted
    if (len(accepted),len(residual),_setsha(residual))!=(1528,3800,EXPECTED_RESIDUAL):raise ValueError("r40_residual_invalid")
    purchases=defaultdict(list);raw_norms=defaultdict(set);invalid_purchase=Counter()
    for key,event in events.items():
        if event["transaction_type"]!="purchase":continue
        if not re.fullmatch(r"[0-9]{4}",str(event.get("card4") or ""),re.ASCII):invalid_purchase["card4_invalid"]+=1;continue
        issuer=str(event["source_system"]);value=event.get("approval_number") or payload[key].get("appr")
        try:raw,norm,_=normalize_approval(value,issuer)
        except ApprovalError as exc:invalid_purchase[exc.reason]+=1;continue
        idx=(issuer,str(event.get("card4") or ""),norm);purchases[idx].append((key,raw));raw_norms[idx].add(raw)
    relations=[];exclusions=[];selected=set();target_status=Counter()
    for key in sorted(residual):
        event=events[key]
        if event["transaction_type"] not in {"cancellation","refund"}:continue
        issuer=str(event["source_system"]);raw_value=payload[key].get("orig_appr")
        if not re.fullmatch(r"[0-9]{4}",str(event.get("card4") or ""),re.ASCII):
            exclusions.append({"event_key_sha256":_sha(key.encode()),"event_content_sha256":event["current_event_sha256"],"source_system":issuer,"event_source_kind":event["current_source_kind"],"event_source_key_sha256":_sha(event["current_source_key"].encode()),"event_source_sha256":event["current_source_sha256"],"event_payload_sha256":_sha(_json(payload[key])),"orig_field_name":"orig_appr","reason":"card4_invalid","normalization_contract":NORMALIZATION_CONTRACTS.get(issuer,{}).get("version","")});continue
        try:raw,norm,contract=normalize_approval(raw_value,issuer)
        except ApprovalError as exc:
            exclusions.append({"event_key_sha256":_sha(key.encode()),"event_content_sha256":event["current_event_sha256"],"source_system":issuer,"event_source_kind":event["current_source_kind"],"event_source_key_sha256":_sha(event["current_source_key"].encode()),"event_source_sha256":event["current_source_sha256"],"event_payload_sha256":_sha(_json(payload[key])),"orig_field_name":"orig_appr","reason":exc.reason,"normalization_contract":NORMALIZATION_CONTRACTS.get(issuer,{}).get("version","")});continue
        idx=(issuer,str(event.get("card4") or ""),norm);targets=purchases.get(idx,[])
        reason=None
        if len(targets)!=1:reason="target_missing" if not targets else "ambiguous_target"
        elif len(raw_norms[idx])!=1:reason="normalization_collision"
        if reason:
            exclusions.append({"event_key_sha256":_sha(key.encode()),"event_content_sha256":event["current_event_sha256"],"source_system":issuer,"event_source_kind":event["current_source_kind"],"event_source_key_sha256":_sha(event["current_source_key"].encode()),"event_source_sha256":event["current_source_sha256"],"event_payload_sha256":_sha(_json(payload[key])),"orig_field_name":"orig_appr","reason":reason,"normalization_contract":contract});continue
        target,target_raw=targets[0];selected.add(key);target_status["accepted" if target in accepted else "residual"]+=1
        target_event=events[target];base={"event_key_sha256":_sha(key.encode()),"target_event_key_sha256":_sha(target.encode()),"event_content_sha256":event["current_event_sha256"],"target_content_sha256":target_event["current_event_sha256"],"source_system":issuer,"event_source_kind":event["current_source_kind"],"event_source_key_sha256":_sha(event["current_source_key"].encode()),"event_source_sha256":event["current_source_sha256"],"target_source_kind":target_event["current_source_kind"],"target_source_key_sha256":_sha(target_event["current_source_key"].encode()),"target_source_sha256":target_event["current_source_sha256"],"event_payload_sha256":_sha(_json(payload[key])),"target_payload_sha256":_sha(_json(payload[target])),"orig_field_name":"orig_appr","target_field_name":"approval_number" if target_event.get("approval_number") else "appr","normalization_contract":contract,"relation_kind":"issuer_original_approval_exact","disposition":"exact_original_approval_relation_proposal","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False}
        base["relation_id"]=_sha(_json(base));relations.append(base)
    reasons=Counter(x["reason"] for x in exclusions);sources=Counter(events[x]["source_system"] for x in selected)
    original_invalid=sum(v for k,v in reasons.items() if k.startswith("original_") or k in {"card4_invalid","issuer_contract_missing"})
    if (len(selected),_setsha(selected),sources,target_status,reasons["target_missing"],original_invalid,sum(reasons[x] for x in ("ambiguous_target","normalization_collision")))!=(210,EXPECTED_RELATIONS,Counter({"KBD":128,"HAN":82}),Counter({"residual":187,"accepted":23}),29,147,0):raise ValueError(f"r40_exact_census_invalid:{len(selected)}:{sources}:{target_status}:{reasons}")
    relation_bytes=_csv(REL_FIELDS,relations);exclusion_bytes=_csv(EX_FIELDS,exclusions)
    independent_full=full36|set(r37.EXPECTED_EVENTS)|set(r38.EXPECTED_EVENTS)
    if any(target in independent_full for relation in relations for target in events if _sha(target.encode())==relation["target_event_key_sha256"]):raise ValueError("r40_independent_full_target_drift")
    rule_sha=_sha(_json({"artifact":ARTIFACT_TYPE,"normalization_authority_sha256":authority_sha,"normalization_contracts":NORMALIZATION_CONTRACTS,"relation_fields":REL_FIELDS,"exclusion_fields":EX_FIELDS,"relation_only":True}))
    base={"format_version":1,"artifact_type":ARTIFACT_TYPE,"rule_contract_sha256":rule_sha,"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False,"contains_sensitive_raw_values":False,"full_classification_delta":0,"incomplete_residual":3800,"accepted_union":1528,"relation_resolved_residual":210,"relation_event_set_sha256":EXPECTED_RELATIONS,"current_event_set_sha256":EXPECTED_CURRENT,"decision_scope_sha256":EXPECTED_SCOPE,"residual_set_sha256":EXPECTED_RESIDUAL,"input_manifest_sha256":ctx["input_manifest_sha256"],"candidate_semantic_sha256":ctx["candidate_semantic_sha256"],"normalization_contracts":NORMALIZATION_CONTRACTS,"counts":{"relations":210,"HAN":82,"KBD":128,"target_accepted":23,"target_residual":187,"target_independent_full":0,"missing_target":29,"no_usable_original":147,"ambiguous":0,"collision":0},"upstream":{"r23_rule":r23["manifest"]["rule_contract_sha256"],"r23_package":r23["manifest"]["envelope_set_sha256"],"r25_rule":m25["rule_contract_sha256"],"r25_package":m25["package_set_sha256"],"r36_rule":m36["rule_contract_sha256"],"r36_package":m36["package_set_sha256"],"r37_rule":m38["r37_rule_contract_sha256"],"r37_package":m38["r37_package_set_sha256"],"r38_rule":m38["rule_contract_sha256"],"r38_package":m38["package_set_sha256"]},"files":{"relations.csv":{"sha256":_sha(relation_bytes),"rows":210},"exclusions.csv":{"sha256":_sha(exclusion_bytes),"rows":176}}}
    base["exclusion_reasons"]=dict(sorted(reasons.items()));base["purchase_exclusion_reasons"]=dict(sorted(invalid_purchase.items()));base["normalization_authority_sha256"]=authority_sha
    package=_sha(_json(base)+relation_bytes+exclusion_bytes);manifest={**base,"package_set_sha256":package}
    manual_after=(MANUAL.stat(),MANUAL.read_bytes())
    before_stat,after_stat=manual_before[0],manual_after[0]
    if manual_before[1]!=manual_after[1] or (before_stat.st_dev,before_stat.st_ino,before_stat.st_size,before_stat.st_mtime_ns)!=(after_stat.st_dev,after_stat.st_ino,after_stat.st_size,after_stat.st_mtime_ns):raise ValueError("r40_input_changed_during_build")
    return manifest,{"manifest.json":_json(manifest),"relations.csv":relation_bytes,"exclusions.csv":exclusion_bytes}

def build_original_approval_relation(output:Path|None=None,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
    manifest,files=_build(ledger_dir)
    if output is not None:
        if output.parent.is_symlink():raise ValueError("r40_output_parent_symlink")
        parent=output.parent.resolve(strict=True)
        try:parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:pass
        else:raise ValueError("r40_output_inside_repository")
        if os.path.lexists(output):raise FileExistsError("r40_output_exists")
        stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=parent));os.chmod(stage,0o700);published=False
        try:
            for name,data in files.items():
                p=stage/name;fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600)
                try:
                    view=memoryview(data)
                    while view:view=view[os.write(fd,view):]
                    os.fsync(fd)
                finally:os.close(fd)
            fd=open_dir(stage)
            try:os.fsync(fd)
            finally:os.close(fd)
            expected={name:data for name,data in files.items()}
            captured=_capture_package(stage)
            if captured!=expected:raise ValueError("r40_stage_verify_failed")
            _install_noreplace(stage,output)
            published=True
            try:
                if _capture_package(output)!=expected:raise ValueError("r40_post_install_bytes_mismatch")
            except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"]) from exc
            try:fd=open_dir(parent)
            except OSError as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
            try:
                try:os.fsync(fd)
                except OSError as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
            finally:os.close(fd)
            try:
                if _capture_package(output)!=expected:raise ValueError("r40_post_fsync_bytes_mismatch")
            except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"]) from exc
        except Exception:
            if not published and stage.exists():shutil.rmtree(stage)
            raise
    return {"manifest":manifest,"output":None if output is None else str(output)}

def reconcile_publication(error:PublicationDurabilityError|PublicationIntegrityError,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
    if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r40_reconcile_state_invalid")
    first=verify_original_approval_relation(error.output,ledger_dir)
    fd=open_dir(error.output.parent)
    try:os.fsync(fd)
    finally:os.close(fd)
    second=verify_original_approval_relation(error.output,ledger_dir)
    if first["package_set_sha256"]!=error.package_set_sha256 or second!=first:raise ValueError("r40_reconcile_package_mismatch")
    return {**second,"published":True,"durable":True}

def verify_original_approval_relation(directory:Path,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
    actual=_capture_package(directory)
    manifest,expected=_build(ledger_dir)
    if actual!=expected:raise ValueError("r40_package_semantics_mismatch")
    return {"status":"valid","relations":manifest["counts"]["relations"],"package_set_sha256":manifest["package_set_sha256"]}