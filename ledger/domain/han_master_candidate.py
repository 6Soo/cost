"""External-only HAN master rebuild and exact direct equality artifact."""
from __future__ import annotations
import csv, hashlib, io, json, os, shutil, sqlite3, stat, tempfile
from pathlib import Path
import argparse
from typing import Iterable

from ledger import cardindex, ingest
from ledger.domain.han_normalizer import (HAN_NORMALIZER_CONTRACT_SHA256,
    HAN_NORMALIZER_VERSION, is_han_transaction, normalize_han_components,
    normalize_han_identity_text, parse_han_amounts, validate_han_header)
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _install_noreplace
from ledger.domain.direct_projection import build_source_inventory,code_bundle_descriptor,_git_head
from ledger.domain.transition_gates_v2 import candidate_semantic_sha256,input_manifest_sha256 as compute_input_manifest_sha256

ARTIFACT_TYPE="han-master-candidate-equality-v1"
FILES=("candidate_master.csv","private_mapping.csv","summary.json","manifest.json")
MAPPING_FIELDS=("private_identity","raw_row_sha256","old_key","target_key","before_row_sha256","after_row_sha256",
 "preserved_fields_sha256","role","transaction_type")
REVIEW_FIELDS=("기록여부","워크북참조","비고","적재일")
PARSER_FIELDS=("카드사","카드4","구분","승인일","매입일","가맹점","현지금액","통화","승인번호","취소여부","출처")
APPROVED_CONTRACT_SHA256="2a0575154a206db99cbdabf4f8f6a9eaa78f5d4b4f7660417ce93d21b79bad0d"
APPROVED_LEGACY_MASTER_SHA256="c161cc1f91ae0cbbe2207007d61d0c8ab9ed0196d17aa565fb64b95a3a5e0d19"
APPROVED_TARGET_MASTER_SHA256="e68359d51970e45bc5959e4e3025b40ffef273f9341d95cab2c1ec60ebad952e"
APPROVED_G_SHA256="f90ae46f217b2694c3d2fb012bf9550f0b7e395a785f7d19b8e83d5ca9060bb0"
APPROVED_H_SHA256="e719a4b5468ae529663118cc2ac3dffc80094d75687d6e868655a7de4f82b9b0"
AUTHORITY_PATH=Path(__file__).with_name("han_master_authority.json")

def _sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def _json(x:object)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _set_sha(values:Iterable[str])->str:return _sha(_json(sorted(values)))
def _read_regular_nofollow(path:Path,*,mode:int|None=None)->bytes:
    flags=os.O_RDONLY|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0)
    try:fd=os.open(path,flags)
    except OSError as exc:raise ValueError("r39_regular_file_open_failed") from exc
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or (mode is not None and stat.S_IMODE(st.st_mode)!=mode):
            raise ValueError("r39_regular_file_invalid")
        chunks=[]
        while True:
            chunk=os.read(fd,1024*1024)
            if not chunk:break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:os.close(fd)
def _write_all(fd:int,data:bytes)->None:
    view=memoryview(data)
    while view:view=view[os.write(fd,view):]
def _authority(expected_sha256:str):
    raw=_read_regular_nofollow(AUTHORITY_PATH)
    if len(expected_sha256)!=64 or _sha(raw)!=expected_sha256:raise ValueError("r39_authority_sha256_mismatch")
    try:value=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise ValueError("r39_authority_invalid") from exc
    required={"format_version":1,"policy":"r39-han-master-candidate-v1","normalizer_contract_sha256":APPROVED_CONTRACT_SHA256,
      "legacy_master_sha256":APPROVED_LEGACY_MASTER_SHA256,"target_master_sha256":APPROVED_TARGET_MASTER_SHA256,
      "G_sha256":APPROVED_G_SHA256,"H_sha256":APPROVED_H_SHA256,"allowed_run_status":["building"],
      "schema_version":"p07-direct-v3","parser_version":"direct-source-v4"}
    if value!=required:raise ValueError("r39_authority_policy_mismatch")
    return value,_sha(raw)
def _master_key(row:dict[str,object],amount:int)->str:
    approval=str(row["승인번호"] or "").removesuffix(".0").lstrip("0")
    if not approval: raise ValueError("r39_han_approval_missing")
    return f"하나|{row['카드4']}|A{approval}|{'취소' if row['취소여부']=='취소' else '정상'}|{abs(amount)}"
def _csv_bytes(fields,rows):
    s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n",extrasaction="raise");w.writeheader();w.writerows(rows)
    return s.getvalue().encode("utf-8-sig" if tuple(fields)==tuple(ingest.FIELDS) else "utf-8")
def _compare(expected:dict[str,tuple[int,str]],direct:dict[str,tuple[int,str]]):
    if len(expected)!=len(set(expected)) or len(direct)!=len(set(direct)):raise ValueError("r39_identity_collision")
    if set(expected)!=set(direct):raise ValueError("r39_identity_role_set_mismatch")
    mismatches=[x for x in expected if expected[x]!=direct[x]]
    if mismatches:raise ValueError("r39_amount_role_type_mismatch")
    if sum(x[0] for x in expected.values())!=sum(x[0] for x in direct.values()):raise ValueError("r39_total_mismatch")
    return {"count_equal":True,"signed_total_equal":True,"role_type_equal":True}

def _classify_state(index:set[str], changed) -> str:
    legacy=all(x[1] in index and x[2] not in index for x in changed)
    target=all(x[2] in index and x[1] not in index for x in changed)
    if legacy==target:raise ValueError("r39_mixed_or_unknown_master_state")
    return "LEGACY" if legacy else "TARGET"

def _han_targets(ledger_dir:Path):
    targets=[]
    for artifact in ("G","H"):
        rows=cardindex.load(artifact,ledger_dir=ledger_dir);columns=validate_han_header(rows[5] if len(rows)>5 else ())
        for row_number,row in enumerate(rows[6:],7):
            card=normalize_han_identity_text(row[3]) if len(row)>3 else "";approval=normalize_han_identity_text(row[4]) if len(row)>4 else ""
            if not (card or approval):continue
            amounts=parse_han_amounts(row,columns)
            if not is_han_transaction(amounts,identity_present=True):continue
            components=normalize_han_components(amounts)
            generated=ingest.norm(rows[:6]+[row],"하나승인","")
            if len(generated)!=len(components):raise ValueError("r39_consumer_component_count_mismatch")
            for record,component in zip(generated,components,strict=True):
                role=component.role;identity=f"HAN:{artifact}:{row_number}#{role}"
                old_amount=amounts.approval_amount if role in {"single","approval"} else -abs(amounts.cancel_amount)
                old_key=_master_key(record,old_amount);target_key=_master_key(record,component.signed_amount_krw)
                if record["거래키"]!=target_key or int(record["원화금액"])!=component.signed_amount_krw:
                    raise ValueError("r39_ingest_target_semantic_mismatch")
                targets.append((identity,old_key,target_key,component,record,_sha(_json(list(row)))))
    return targets

def _direct_snapshot(candidate_db:Path,run_id:str,input_sha:str,semantic_sha:str,authority,inventory,bundle,commit,verification_mode:str):
    if not run_id or len(input_sha)!=64 or len(semantic_sha)!=64:raise ValueError("r39_direct_context_invalid")
    sidecars=[Path(str(candidate_db)+suffix) for suffix in ("-wal","-shm","-journal")]
    if any(os.path.lexists(x) for x in sidecars):raise ValueError("r39_direct_db_sidecar_present")
    db_bytes=_read_regular_nofollow(candidate_db)
    with tempfile.TemporaryDirectory(prefix="r39-db-snapshot-") as td:
      snapshot=Path(td)/"candidate.db";fd=os.open(snapshot,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
      try:
        _write_all(fd,db_bytes);os.fsync(fd)
      finally:os.close(fd)
      db=sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1",uri=True);db.row_factory=sqlite3.Row
      try:
        if str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()!="delete":raise ValueError("r39_direct_journal_mode_invalid")
        if str(db.execute("PRAGMA integrity_check").fetchone()[0]).lower()!="ok":raise ValueError("r39_direct_integrity_invalid")
        row=db.execute("SELECT run_id,status,input_manifest_sha256,candidate_semantic_sha256 FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()
        if row is None or row["input_manifest_sha256"]!=input_sha or row["candidate_semantic_sha256"]!=semantic_sha:
            raise ValueError("r39_direct_run_context_mismatch")
        full=db.execute("SELECT status,schema_version,code_commit,code_bundle_sha256 FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()
        allowed={"building"} if verification_mode=="pending" else {"passed"} if verification_mode=="activated" else set()
        if full["status"] not in allowed:raise ValueError("r39_direct_status_invalid")
        if verification_mode=="activated":
            seal=db.execute("""SELECT r.activation_validation_sha256,v.validation_sha256 FROM direct_projection_runs r
              JOIN direct_projection_validations v ON v.run_id=r.run_id WHERE r.run_id=?""",(run_id,)).fetchone()
            if seal is None or seal[0]!=seal[1]:raise ValueError("r39_activation_validation_seal_invalid")
        if full["schema_version"]!=authority["schema_version"]:raise ValueError("r39_direct_schema_invalid")
        if full["code_commit"]!=commit:raise ValueError("r39_direct_commit_invalid")
        if full["code_bundle_sha256"]!=bundle["code_bundle_sha256"]:raise ValueError("r39_direct_bundle_invalid")
        db_inputs=[dict(x) for x in db.execute("SELECT source_kind,relative_path,raw_sha256,lf_sha256,byte_count,key_set_sha256,record_count,parser_version FROM direct_projection_inputs WHERE run_id=? ORDER BY source_kind,relative_path",(run_id,))]
        expected_inputs=sorted(inventory,key=lambda x:(x["source_kind"],x["relative_path"]))
        if db_inputs!=expected_inputs:raise ValueError("r39_direct_inputs_invalid")
        if candidate_semantic_sha256(db,run_id)!=semantic_sha:raise ValueError("r39_direct_semantic_content_mismatch")
        scope=int(db.execute("SELECT COUNT(*) FROM direct_payment_projection_links WHERE run_id=?",(run_id,)).fetchone()[0])
        if scope!=5328:raise ValueError("r39_direct_scope_invalid")
        direct={}
        rows=db.execute("""SELECT s.source_key,p.event_role,p.amount_krw,p.transaction_type
          FROM direct_payment_projection_links l
          JOIN direct_normalized_payments p ON p.id=l.direct_payment_id
          JOIN direct_source_records s ON s.id=p.source_record_id
          WHERE l.run_id=? AND s.source_key LIKE 'HAN:%'""",(run_id,))
        for source_key,role,amount,kind in rows:
            identity=f"{source_key}#{role}"
            if identity in direct:raise ValueError("r39_direct_identity_collision")
            direct[identity]=(int(amount),str(kind))
      finally:db.close()
    if _read_regular_nofollow(candidate_db)!=db_bytes:raise ValueError("r39_direct_db_changed_during_read")
    if any(os.path.lexists(x) for x in sidecars):raise ValueError("r39_direct_db_sidecar_present")
    logical={"run_id":run_id,"input_manifest_sha256":input_sha,"candidate_semantic_sha256":semantic_sha,
      "code_commit":commit,"code_bundle_sha256":bundle["code_bundle_sha256"],"inputs":inventory,"scope":scope}
    return direct,_sha(_json(logical)),scope

def _build(ledger_dir:Path,master_path:Path,*,candidate_db:Path,run_id:str,
           input_manifest_sha256:str,candidate_semantic_sha256_expected:str,authority_sha256_expected:str,
           verification_mode:str="pending"):
    if ledger_dir.resolve()!=(REPOSITORY_ROOT/"ledger").resolve():raise ValueError("r39_noncanonical_ledger")
    authority,authority_sha=_authority(authority_sha256_expected);raw=_read_regular_nofollow(master_path)
    raw_sha=_sha(raw)
    if raw_sha not in {authority["legacy_master_sha256"],authority["target_master_sha256"]}:raise ValueError("r39_unapproved_master_state")
    if HAN_NORMALIZER_CONTRACT_SHA256!=authority["normalizer_contract_sha256"]:raise ValueError("r39_unapproved_normalizer_contract")
    g_bytes=_read_regular_nofollow(ledger_dir/"newcard/conv/G.xlsx");h_bytes=_read_regular_nofollow(ledger_dir/"newcard/conv/H.xlsx")
    if (_sha(g_bytes),_sha(h_bytes))!=(authority["G_sha256"],authority["H_sha256"]):raise ValueError("r39_unapproved_han_inputs")
    with io.StringIO(raw.decode("utf-8-sig"),newline="") as s:
        reader=csv.DictReader(s)
        master_fields=tuple(reader.fieldnames or ())
        if master_fields[:len(ingest.FIELDS)]!=tuple(ingest.FIELDS) or len(master_fields)!=len(set(master_fields)):raise ValueError("r39_master_schema_invalid")
        old=list(reader)
    keys=[x["거래키"] for x in old]
    if len(old)!=5328 or len(keys)!=len(set(keys)):raise ValueError("r39_master_key_invalid")
    index={x["거래키"]:i for i,x in enumerate(old)}
    with tempfile.TemporaryDirectory(prefix="r39-input-snapshot-") as td:
        snap=Path(td);conv=snap/"newcard/conv";conv.mkdir(parents=True)
        for name,data in (("G.xlsx",g_bytes),("H.xlsx",h_bytes)):
            fd=os.open(conv/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:_write_all(fd,data);os.fsync(fd)
            finally:os.close(fd)
        targets=_han_targets(snap)
    if len(targets)!=2188 or len({x[0] for x in targets})!=2188:raise ValueError("r39_han_target_census_invalid")
    changed=[x for x in targets if x[1]!=x[2]]
    state=_classify_state(set(index),changed)
    candidate=[dict(x) for x in old];used_old=set();target_keys=set();mapping=[]
    for identity,old_key,target_key,component,generated,raw_row_sha in targets:
        source_key=old_key if state=="LEGACY" else target_key
        if source_key in used_old or source_key not in index:raise ValueError("r39_source_key_unmapped_or_ambiguous")
        if target_key in target_keys:raise ValueError("r39_target_key_collision")
        if state=="LEGACY" and target_key in index and target_key!=old_key:raise ValueError("r39_target_owned_by_unrelated_row")
        used_old.add(source_key);target_keys.add(target_key);position=index[source_key];source=old[position]
        expected_source_amount=int((old_key if state=="LEGACY" else target_key).rsplit("|",1)[1])*(-1 if source["취소여부"]=="취소" else 1)
        if source["카드사"]!="하나" or source["취소여부"]!=generated["취소여부"] or int(source["원화금액"])!=expected_source_amount:
            raise ValueError("r39_old_row_semantic_mismatch")
        if any(source[field] != str(generated[field]) for field in PARSER_FIELDS):raise ValueError("r39_old_row_identity_mismatch")
        migrated=dict(source);migrated["거래키"]=target_key;migrated["원화금액"]=str(component.signed_amount_krw)
        if any(migrated[x]!=source[x] for x in REVIEW_FIELDS):raise ValueError("r39_review_state_changed")
        candidate[position]=migrated
        preserved={k:source[k] for k in master_fields if k not in {"거래키","원화금액"}}
        if preserved!={k:migrated[k] for k in preserved}:raise ValueError("r39_per_lineage_preservation_failed")
        mapping.append({"private_identity":identity,"raw_row_sha256":raw_row_sha,"old_key":old_key,"target_key":target_key,
          "before_row_sha256":_sha(_json(source)),"after_row_sha256":_sha(_json(migrated)),
          "preserved_fields_sha256":_sha(_json(preserved)),"role":component.role,"transaction_type":component.transaction_type})
    if len(used_old)!=2188 or sum(x["카드사"]=="하나" for x in candidate)!=2188 or len({x["거래키"] for x in candidate})!=5328:
        raise ValueError("r39_candidate_census_invalid")
    migrated_count=sum(old_key!=target_key for _,old_key,target_key,_,_,_ in targets) if state=="LEGACY" else 0
    if migrated_count!=(1602 if state=="LEGACY" else 0):raise ValueError("r39_migration_count_invalid")
    for before,after in zip(old,candidate,strict=True):
        if before["카드사"]!="하나" and before!=after:raise ValueError("r39_non_han_changed")

    candidate_bytes=_csv_bytes(master_fields,candidate);mapping_bytes=_csv_bytes(MAPPING_FIELDS,mapping)
    parsed_candidate=list(csv.DictReader(io.StringIO(candidate_bytes.decode("utf-8-sig"),newline="")))
    parsed_mapping=list(csv.DictReader(io.StringIO(mapping_bytes.decode("utf-8"),newline="")))
    if len(parsed_candidate)!=5328 or len(parsed_mapping)!=2188:raise ValueError("r39_serialized_scope_invalid")
    candidate_by_key={x["거래키"]:x for x in parsed_candidate}
    if len(candidate_by_key)!=5328:raise ValueError("r39_serialized_candidate_key_collision")
    expected={}
    for item in parsed_mapping:
        if item["target_key"] not in candidate_by_key:raise ValueError("r39_mapping_target_missing")
        identity=item["private_identity"]
        if identity in expected:raise ValueError("r39_mapping_identity_collision")
        expected[identity]=(int(candidate_by_key[item["target_key"]]["원화금액"]),item["transaction_type"])
    inventory=build_source_inventory(ledger_dir,REPOSITORY_ROOT);live_input_sha=compute_input_manifest_sha256(inventory)
    if live_input_sha!=input_manifest_sha256:raise ValueError("r39_live_input_manifest_mismatch")
    if any(x["parser_version"]!=authority["parser_version"] for x in inventory):raise ValueError("r39_live_parser_version_invalid")
    bundle=code_bundle_descriptor(REPOSITORY_ROOT);commit=_git_head(REPOSITORY_ROOT)
    direct,direct_db_sha,direct_scope=_direct_snapshot(candidate_db,run_id,input_manifest_sha256,candidate_semantic_sha256_expected,authority,inventory,bundle,commit,verification_mode)
    if build_source_inventory(ledger_dir,REPOSITORY_ROOT)!=inventory:raise ValueError("r39_live_inventory_changed_during_build")
    if set(expected)!=set(direct):raise ValueError("r39_identity_role_set_mismatch")
    equality=_compare(expected,direct)
    semantic=[[x,expected[x][0],expected[x][1]] for x in sorted(expected)]
    summary={"artifact_type":ARTIFACT_TYPE,"authority_status":"unattested","posting_status":"blocked","applied":False,
      "normalizer_version":HAN_NORMALIZER_VERSION,"normalizer_contract_sha256":HAN_NORMALIZER_CONTRACT_SHA256,
      "authority_sha256":authority_sha,
      "source_master_sha256":_sha(raw),"candidate_master_sha256":_sha(candidate_bytes),
      "direct_candidate":{"run_id":run_id,"database_provenance_sha256":direct_db_sha,"input_manifest_sha256":input_manifest_sha256,
        "candidate_semantic_sha256":candidate_semantic_sha256_expected,"scope":direct_scope,"code_commit":commit,
        "code_bundle_sha256":bundle["code_bundle_sha256"]},
      "identity_role_set_sha256":_set_sha(expected),"amount_semantic_sha256":_sha(_json(semantic)),
      "input_state":state,"counts":{"master":5328,"non_han_preserved":3140,"han_physical":2097,"han_roles":2188,"migrated":migrated_count,"mismatch":0,"collision":0,"unmapped":0},
      "totals":equality,"status":"passed"}
    summary_bytes=_json(summary)
    base={"artifact_type":ARTIFACT_TYPE,"authority_status":"unattested","posting_status":"blocked","applied":False,
      "contains_sensitive_values":True,"package_classification":"private_sensitive","public_report_embedded":False,"private_inputs":{"master_sha256":_sha(raw),
      "G_sha256":_sha(g_bytes),"H_sha256":_sha(h_bytes),"authority_sha256":authority_sha},
      "files":{"candidate_master.csv":{"sha256":_sha(candidate_bytes),"rows":5328,"contains_sensitive_values":True},
      "private_mapping.csv":{"sha256":_sha(mapping_bytes),"rows":2188,"contains_sensitive_values":True},
      "summary.json":{"sha256":_sha(summary_bytes),"rows":1,"contains_sensitive_values":False}}}
    package=_sha(_json(base)+candidate_bytes+mapping_bytes+summary_bytes);manifest={**base,"package_set_sha256":package}
    return manifest,{"candidate_master.csv":candidate_bytes,"private_mapping.csv":mapping_bytes,"summary.json":summary_bytes,"manifest.json":_json(manifest)}

class PublicationDurabilityError(OSError):
    def __init__(self,output:Path,sha:str):super().__init__("r39_published_but_parent_fsync_failed");self.output=output;self.expected_package_sha256=sha;self.published=True;self.parent_fsync=False
def _fsync(path:Path):
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0));
    try:os.fsync(fd)
    finally:os.close(fd)
def verify_candidate(directory:Path,*,candidate_db:Path,run_id:str,input_manifest_sha256:str,candidate_semantic_sha256_expected:str,
                     authority_sha256_expected:str,ledger_dir:Path=REPOSITORY_ROOT/"ledger",master_path:Path|None=None,
                     verification_mode:str="pending"):
    flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0);fd=os.open(directory,flags)
    try:dst=os.fstat(fd)
    finally:os.close(fd)
    expected_dir_mode=0o700 if verification_mode=="pending" else 0o500
    expected_file_mode=0o600 if verification_mode=="pending" else 0o400
    if not stat.S_ISDIR(dst.st_mode) or stat.S_IMODE(dst.st_mode)!=expected_dir_mode or dst.st_uid!=os.getuid():raise ValueError("r39_package_directory_invalid")
    if directory.is_symlink() or {x.name for x in directory.iterdir()}!=set(FILES):raise ValueError("r39_package_shape_invalid")
    actual={}
    for name in FILES:
        path=directory/name
        actual[name]=_read_regular_nofollow(path,mode=expected_file_mode)
    manifest,expected=_build(ledger_dir,master_path or ledger_dir/"master_ledger.csv",candidate_db=candidate_db,run_id=run_id,
      input_manifest_sha256=input_manifest_sha256,candidate_semantic_sha256_expected=candidate_semantic_sha256_expected,
      authority_sha256_expected=authority_sha256_expected,verification_mode=verification_mode)
    if actual!=expected:raise ValueError("r39_package_or_live_context_mismatch")
    summary=json.loads(actual["summary.json"])
    envelope={"package_set_sha256":manifest["package_set_sha256"],"authority_sha256":authority_sha256_expected,
      "input_manifest_sha256":input_manifest_sha256,"candidate_semantic_sha256":candidate_semantic_sha256_expected,
      "candidate_master_sha256":summary["candidate_master_sha256"],"identity_role_set_sha256":summary["identity_role_set_sha256"],
      "amount_semantic_sha256":summary["amount_semantic_sha256"]}
    files_sha={name:_sha(data) for name,data in actual.items()}
    return {"status":"valid",**envelope,"validation_envelope":envelope,"verified_file_sha256":files_sha,
      "_verified_file_bytes":actual,"package_bytes_sha256":_sha(_json(files_sha)),"mismatch":0}
def _validation_pretransaction_hook(candidate_db:Path,directory:Path)->None:
    """Test seam for adversarial changes between preflight and DB locking."""
def install_han_equality_validation(directory:Path,*,candidate_db:Path,run_id:str,input_manifest_sha256:str,
    candidate_semantic_sha256_expected:str,authority_sha256_expected:str,ledger_dir:Path=REPOSITORY_ROOT/"ledger",
    master_path:Path|None=None):
    context=dict(candidate_db=candidate_db,run_id=run_id,input_manifest_sha256=input_manifest_sha256,
      candidate_semantic_sha256_expected=candidate_semantic_sha256_expected,authority_sha256_expected=authority_sha256_expected,
      ledger_dir=ledger_dir,master_path=master_path)
    verified=verify_candidate(directory,**context)
    package_snapshot={name:_read_regular_nofollow(directory/name,mode=0o600) for name in FILES}
    summary=json.loads(_read_regular_nofollow(directory/"summary.json",mode=0o600))
    payload={"run_id":run_id,"status":"passed","package_set_sha256":verified["package_set_sha256"],
      "authority_sha256":authority_sha256_expected,"input_manifest_sha256":input_manifest_sha256,
      "candidate_semantic_sha256":candidate_semantic_sha256_expected,"candidate_master_sha256":summary["candidate_master_sha256"],
      "identity_role_set_sha256":summary["identity_role_set_sha256"],"amount_semantic_sha256":summary["amount_semantic_sha256"]}
    validation_sha=_sha(_json(payload))
    values=(run_id,"passed",verified["package_set_sha256"],authority_sha256_expected,input_manifest_sha256,
      candidate_semantic_sha256_expected,summary["candidate_master_sha256"],summary["identity_role_set_sha256"],
      summary["amount_semantic_sha256"],validation_sha)
    _validation_pretransaction_hook(candidate_db,directory)
    db=sqlite3.connect(candidate_db)
    try:
        db.execute("BEGIN IMMEDIATE")
        run=db.execute("SELECT status,schema_version,input_manifest_sha256,candidate_semantic_sha256,code_commit,code_bundle_sha256 FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()
        authority,_=_authority(authority_sha256_expected);bundle=code_bundle_descriptor(REPOSITORY_ROOT);commit=_git_head(REPOSITORY_ROOT)
        if run!=("building",authority["schema_version"],input_manifest_sha256,candidate_semantic_sha256_expected,commit,bundle["code_bundle_sha256"]):raise ValueError("r39_validation_run_precondition_failed")
        if candidate_semantic_sha256(db,run_id)!=candidate_semantic_sha256_expected:raise ValueError("r39_validation_semantic_changed")
        live_inventory=build_source_inventory(ledger_dir,REPOSITORY_ROOT)
        if compute_input_manifest_sha256(live_inventory)!=input_manifest_sha256:raise ValueError("r39_validation_inputs_changed")
        if {name:_read_regular_nofollow(directory/name,mode=0o600) for name in FILES}!=package_snapshot:raise ValueError("r39_validation_package_changed")
        existing=db.execute("""SELECT run_id,status,package_set_sha256,authority_sha256,input_manifest_sha256,
          candidate_semantic_sha256,candidate_master_sha256,identity_role_set_sha256,amount_semantic_sha256,validation_sha256
          FROM direct_projection_validations WHERE run_id=?""",(run_id,)).fetchone()
        if existing is not None:
            if tuple(existing)!=values:raise ValueError("r39_validation_conflicting_duplicate")
            db.rollback();return {"status":"passed","installed":False,"idempotent":True,"package_set_sha256":values[2]}
        db.execute("""INSERT INTO direct_projection_validations(run_id,status,package_set_sha256,authority_sha256,
          input_manifest_sha256,candidate_semantic_sha256,candidate_master_sha256,identity_role_set_sha256,amount_semantic_sha256,validation_sha256)
          VALUES (?,?,?,?,?,?,?,?,?,?)""",values)
        db.commit()
        db.execute("PRAGMA journal_mode=DELETE")
    except Exception:
        db.rollback();raise
    finally:db.close()
    return {"status":"passed","installed":True,"idempotent":False,"package_set_sha256":values[2]}
def build_candidate(output:Path,*,candidate_db:Path,run_id:str,input_manifest_sha256:str,candidate_semantic_sha256_expected:str,
                    authority_sha256_expected:str,ledger_dir:Path=REPOSITORY_ROOT/"ledger",master_path:Path|None=None):
    context=dict(candidate_db=candidate_db,run_id=run_id,input_manifest_sha256=input_manifest_sha256,
      candidate_semantic_sha256_expected=candidate_semantic_sha256_expected,authority_sha256_expected=authority_sha256_expected)
    manifest,files=_build(ledger_dir,master_path or ledger_dir/"master_ledger.csv",**context)
    if output.parent.is_symlink():raise ValueError("r39_output_parent_symlink")
    parent=output.parent.resolve(strict=True)
    try:parent.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:pass
    else:raise ValueError("r39_output_inside_repository")
    if os.path.lexists(output):raise FileExistsError("r39_output_exists")
    stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=parent));published=False
    try:
        os.chmod(stage,0o700)
        for name,data in files.items():
            fd=os.open(stage/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                os.fchmod(fd,0o600);_write_all(fd,data)
                os.fsync(fd)
            finally:os.close(fd)
        _fsync(stage);verify_candidate(stage,ledger_dir=ledger_dir,master_path=master_path,**context)
        _install_noreplace(stage,output);published=True
        try:_fsync(parent)
        except Exception as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
    except Exception:
        if not published:shutil.rmtree(stage,ignore_errors=True)
        raise
    return {"output":str(output),"package_set_sha256":manifest["package_set_sha256"],"mismatch":0}
def reconcile_publication_durability(error:PublicationDurabilityError,**kwargs):
    if not isinstance(error,PublicationDurabilityError):raise ValueError("r39_publication_state_invalid")
    verify_candidate(error.output,**kwargs);_fsync(error.output.parent.resolve(strict=True));result=verify_candidate(error.output,**kwargs)
    if result["package_set_sha256"]!=error.expected_package_sha256:raise ValueError("r39_publication_package_mismatch")
    return {**result,"published":True,"parent_fsync":True}
def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);parser.add_argument("--candidate-db",type=Path,required=True)
    parser.add_argument("--run-id",required=True);parser.add_argument("--input-manifest-sha256",required=True);parser.add_argument("--candidate-semantic-sha256",required=True);parser.add_argument("--authority-sha256",required=True);args=parser.parse_args()
    try:result=build_candidate(args.output,candidate_db=args.candidate_db,run_id=args.run_id,input_manifest_sha256=args.input_manifest_sha256,
      candidate_semantic_sha256_expected=args.candidate_semantic_sha256,authority_sha256_expected=args.authority_sha256);print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0
    except PublicationDurabilityError as exc:
        print(json.dumps({"status":"published_but_parent_fsync_failed","published":True,"parent_fsync":False,
          "output":str(exc.output),"expected_package_sha256":exc.expected_package_sha256},sort_keys=True));return 3
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({"status":"invalid","error":str(exc)},ensure_ascii=False,sort_keys=True));return 2
if __name__=="__main__":raise SystemExit(main())
