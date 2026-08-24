"""R46 external-only KBO legacy cardinality-conflict support annex."""
from __future__ import annotations

import csv, ctypes, errno, hashlib, io, json, os, re, shutil, stat, tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE="r46-kbo-signature-cardinality-conflict-v1"
RULE_VERSION="raw-locator-cardinality-authority-group-support-v1"
FILES=("manifest.json","groups.csv","support.csv","conflicts.csv")
EXPECTED_CURRENT="de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93"
EXPECTED_SCOPE="22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"
EXPECTED_RESIDUAL="f52cc4accd1afaf66150a96e375aee76167227170e87c9aa7ce7db00f7ab8b47"
EXPECTED_SELECTED="6eeebc176506ad05e041c4f3deb55a46bdf56cd2213d543b5fda1d78dbf07b70"
EXPECTED_R45_TARGET3="a743559bb1568c35aa78cbe0320245810e4addc7ab0c5f6c4f1eadf559b77f7f"
INPUT_SHA={
 "newcard/conv/E.xlsx":"7db0f68cb4d01fb33f50694b04e4a28796079f67db09e35e6e4b75372cb3c16c",
 "data/classified_v14.csv":"8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989",
 "master_ledger.csv":"c161cc1f91ae0cbbe2207007d61d0c8ab9ed0196d17aa565fb64b95a3a5e0d19",
}
SELECTED_SOURCE_KEYS={"KBO:E:1017","KBO:E:1018"}
R45_SOURCE_KEYS={"KBO:E:1477","KBO:E:1478","KBO:E:1480"}
GROUP_FIELDS=("group_id","member_set_sha256","source_content_set_sha256","payload_content_set_sha256","raw_count","legacy_count","master_count","legacy_excess","semantic_set_sha256","semantic_unanimous","bijection_asserted","individual_relation_count","missing_dimensions","disposition","authority_status","posting_status","confirmed_count","gate5_credit","applied")
SUPPORT_FIELDS=("support_id","event_key_sha256","current_event_sha256","current_source_sha256","current_payload_sha256","group_id","bucket_present","account_present","cost_type_present","vat_tag_present","relation_kind","bijection_asserted","disposition","authority_status","posting_status","confirmed_count","gate5_credit","applied")
CONFLICT_FIELDS=("conflict_id","legacy_row_sha256","group_id","reason","raw_count","legacy_count","master_count","disposition","authority_status","posting_status","confirmed_count","gate5_credit","applied")

class PublicationDurabilityError(OSError):
 def __init__(self,output,package,parent_identity=None,target_identity=None):super().__init__("r46_published_durability_unknown");self.output=output;self.package_set_sha256=package;self.published=True;self.parent_identity=parent_identity;self.target_identity=target_identity
class PublicationIntegrityError(OSError):
 def __init__(self,output,package,parent_identity=None,target_identity=None):super().__init__("r46_published_integrity_invalid");self.output=output;self.package_set_sha256=package;self.published=True;self.parent_identity=parent_identity;self.target_identity=target_identity

def _sha(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def _json(x)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(xs)->str:return r36._event_set_sha(set(xs))
def _csv(fields,rows):
 s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
 for row in rows:w.writerow({k:(str(row.get(k,"")).lower() if isinstance(row.get(k),bool) else row.get(k,"")) for k in fields})
 return s.getvalue().encode()
def _semantic(row):
 return {k:str(row.get(k) or "") for k in ("bucket","account","cost_type","vat_tag")}

def _identity(st):return (st.st_dev,st.st_ino,st.st_mode,st.st_uid)
def _validate_member_sets(keys:set[str],r45keys:set[str]):
 if _setsha(keys)!=EXPECTED_SELECTED or _setsha(r45keys)!=EXPECTED_R45_TARGET3 or keys&r45keys:raise ValueError("r46_selected_or_r45_set_invalid")

def _select_live_events(by_source):
 selected=[by_source.get(x) for x in sorted(SELECTED_SOURCE_KEYS)];r45=[by_source.get(x) for x in sorted(R45_SOURCE_KEYS)]
 if any(x is None for x in selected+r45):raise ValueError("r46_source_locator_missing")
 _validate_member_sets({e["direct_event_key"] for e in selected},{e["direct_event_key"] for e in r45})
 return selected,r45

def _read_pinned(path:Path,digest:str):
 fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0))
 try:
  a=os.fstat(fd)
  if not stat.S_ISREG(a.st_mode) or a.st_nlink!=1:raise ValueError("r46_input_invalid")
  chunks=[]
  while True:
   b=os.read(fd,1<<20)
   if not b:break
   chunks.append(b)
  z=os.fstat(fd);data=b"".join(chunks)
  if (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)!=(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns) or _sha(data)!=digest:raise ValueError("r46_input_drift")
  return data,(a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)
 finally:os.close(fd)

def _recheck_pinned(path:Path,digest:str,identity):
 data,now=_read_pinned(path,digest)
 if now!=identity:raise ValueError("r46_input_changed_during_build")
 return data

def _capture(directory:Path):
 flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
 try:dfd=os.open(directory,flags)
 except OSError as exc:raise ValueError("r46_package_directory_invalid") from exc
 out={}
 try:
  dm=os.fstat(dfd)
  if not stat.S_ISDIR(dm.st_mode) or stat.S_IMODE(dm.st_mode)!=0o700 or dm.st_uid!=os.getuid() or set(os.listdir(dfd))!=set(FILES):raise ValueError("r46_package_shape_invalid")
  for name in FILES:
   try:fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=dfd)
   except OSError as exc:raise ValueError("r46_package_file_invalid") from exc
   try:
    a=os.fstat(fd)
    if not stat.S_ISREG(a.st_mode) or a.st_nlink!=1 or stat.S_IMODE(a.st_mode)!=0o600:raise ValueError("r46_package_file_invalid")
    chunks=[]
    while True:
     b=os.read(fd,1<<20)
     if not b:break
     chunks.append(b)
    z=os.fstat(fd)
    if (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)!=(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns):raise ValueError("r46_package_changed_during_read")
    out[name]=b"".join(chunks)
   finally:os.close(fd)
 finally:os.close(dfd)
 return out

def _capture_dirfd(dfd:int):
 dm=os.fstat(dfd)
 if not stat.S_ISDIR(dm.st_mode) or stat.S_IMODE(dm.st_mode)!=0o700 or dm.st_uid!=os.getuid() or set(os.listdir(dfd))!=set(FILES):raise ValueError("r46_package_shape_invalid")
 out={}
 for name in FILES:
  fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),dir_fd=dfd)
  try:
   a=os.fstat(fd)
   if not stat.S_ISREG(a.st_mode) or a.st_nlink!=1 or stat.S_IMODE(a.st_mode)!=0o600:raise ValueError("r46_package_file_invalid")
   chunks=[]
   while True:
    b=os.read(fd,1<<20)
    if not b:break
    chunks.append(b)
   z=os.fstat(fd)
   if (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)!=(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns):raise ValueError("r46_package_changed_during_read")
   out[name]=b"".join(chunks)
  finally:os.close(fd)
 return out

def _rename_noreplace_at(pfd:int,source:str,target:str):
 fn=getattr(ctypes.CDLL(None,use_errno=True),"renameat2",None)
 if fn is None:raise OSError("r46_atomic_noreplace_unsupported")
 fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
 if fn(pfd,os.fsencode(source),pfd,os.fsencode(target),1)==0:return
 err=ctypes.get_errno()
 if err==errno.EEXIST:raise FileExistsError("r46_output_exists")
 raise OSError(err,"r46_renameat2")

def _live(ledger_dir:Path):
 if ledger_dir.resolve()!=(REPOSITORY_ROOT/"ledger").resolve():raise ValueError("r46_noncanonical_ledger")
 pinned={rel:_read_pinned(ledger_dir/rel,digest) for rel,digest in INPUT_SHA.items()}
 with tempfile.TemporaryDirectory(prefix="r46-") as td:
  ctx=r36._context(ledger_dir,Path(td));db=ctx["db"];events={e["direct_event_key"]:e for e in ctx["events"]};by_source={e["current_source_key"]:e for e in events.values()}
  if (ctx["current_event_set_sha256"],ctx["decision_scope_sha256"])!=(EXPECTED_CURRENT,EXPECTED_SCOPE):raise ValueError("r46_context_drift")
  selected,r45=_select_live_events(by_source)
  keys={e["direct_event_key"] for e in selected};r45keys={e["direct_event_key"] for e in r45}
  _validate_member_sets(keys,r45keys)
  bindings=[]
  for e in selected:
   raw=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(e["current_source_key"],)).fetchone()
   if raw is None:raise ValueError("r46_payload_missing")
   payload=r36._strict_json(raw[0].encode(),"r46_payload")
   if (e["source_system"]!="KBO" or e["transaction_type"]!="cancellation" or e["event_role"]!="single" or
       str(e["card4"])!="8835" or str(e["currency"])!="JPY" or str(e["foreign_amount"]).replace(",","") not in {"21600","21600.0"} or
       int(e["signed_amount_krw"])!=-209498 or str(e["merchant"])!="AGODA.COM NEW AKAN H" or str(e["occurred_on"])!="2026-05-22" or
       not isinstance(payload,dict) or payload.get("cancel") is not True):raise ValueError("r46_selected_event_drift")
   bindings.append((e,payload))
  db.close()
 accepted,_=r44._accepted_union(ledger_dir);residual=set(events)-accepted
 if (len(accepted),len(residual),_setsha(residual))!=(1528,3800,EXPECTED_RESIDUAL) or not keys<=residual:raise ValueError("r46_residual_drift")
 legacy=list(csv.DictReader(io.StringIO(pinned["data/classified_v14.csv"][0].decode("utf-8-sig"))))
 legacy=[x for x in legacy if x.get("src")=="KBO" and x.get("use_date")=="2026-05-22" and x.get("card4")=="8835" and x.get("currency")=="JPY" and str(x.get("foreign")) in {"21600","21600.0"} and int(float(x.get("krw") or 0))==-209498 and x.get("merchant")=="AGODA.COM NEW AKAN H" and str(x.get("cancel")).lower()=="true"]
 master=list(csv.DictReader(io.StringIO(pinned["master_ledger.csv"][0].decode("utf-8-sig"))))
 master=[x for x in master if x.get("카드사")=="국민" and x.get("카드4")=="8835" and x.get("매입일")=="2026-05-22" and x.get("통화")=="JPY" and str(x.get("현지금액")) in {"21600","21600.0"} and int(float(x.get("원화금액") or 0))==-209498 and x.get("가맹점")=="AGODA.COM NEW AKAN H" and x.get("취소여부")=="취소"]
 semantics={json.dumps(_semantic(x),ensure_ascii=False,sort_keys=True) for x in legacy}
 expected_sem={"bucket":"전기예약_환불","account":"숙박비","cost_type":"","vat_tag":"불공제_해외"}
 refs={x.get("워크북참조") for x in master}
 if (len(bindings)!=2 or len(legacy)!=4 or len(master)!=2 or len(semantics)!=1 or _semantic(legacy[0])!=expected_sem or
     len({x.get("uid") for x in legacy})!=4 or len({x.get("거래키") for x in master})!=2 or len(refs)!=1 or not next(iter(refs),"")):
  raise ValueError("r46_cardinality_contract_drift")
 for rel,digest in INPUT_SHA.items():_recheck_pinned(ledger_dir/rel,digest,pinned[rel][1])
 return bindings,legacy,master,keys,r45keys

def _privacy(files):
 blob=b"".join(files.values()).decode()
 forbidden=(r"card:[0-9a-f]{64}#",r"KBO:E:",r"\b8835\b",r"\b21600\b",r"\b209498\b",r"AGODA",r"KBO-03[0-9]{2}",r"https?://",r"@[A-Za-z0-9.-]+")
 if any(re.search(x,blob,re.I) for x in forbidden):raise ValueError("r46_privacy_violation")

def _build(ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 bindings,legacy,master,keys,r45keys=_live(ledger_dir);sem=_semantic(legacy[0]);semsha=_sha(_json(sem));group_id=_sha(_json({"members":EXPECTED_SELECTED,"semantic":semsha,"raw":2,"legacy":4,"master":2}))
 source_set=_setsha(e["current_source_sha256"] for e,_ in bindings);payload_set=_setsha(_sha(_json(p)) for _,p in bindings)
 group={"group_id":group_id,"member_set_sha256":EXPECTED_SELECTED,"source_content_set_sha256":source_set,"payload_content_set_sha256":payload_set,"raw_count":2,"legacy_count":4,"master_count":2,"legacy_excess":2,"semantic_set_sha256":semsha,"semantic_unanimous":True,"bijection_asserted":False,"individual_relation_count":0,"missing_dimensions":"cost_type","disposition":"partial_group_support_cardinality_conflict","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False}
 support=[]
 for e,payload in sorted(bindings,key=lambda x:x[0]["current_source_key"]):
  base={"event_key_sha256":_sha(e["direct_event_key"].encode()),"current_event_sha256":e["current_event_sha256"],"current_source_sha256":e["current_source_sha256"],"current_payload_sha256":_sha(_json(payload)),"group_id":group_id,"bucket_present":bool(sem["bucket"]),"account_present":bool(sem["account"]),"cost_type_present":bool(sem["cost_type"]),"vat_tag_present":bool(sem["vat_tag"]),"relation_kind":"raw_member_to_unanimous_legacy_group_semantic","bijection_asserted":False,"disposition":"partial_support_not_classification","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False};base["support_id"]=_sha(_json(base));support.append(base)
 conflicts=[]
 for row in legacy:
  base={"legacy_row_sha256":_sha(_json(row)),"group_id":group_id,"reason":"legacy_cardinality_exceeds_raw_no_uid_bijection","raw_count":2,"legacy_count":4,"master_count":2,"disposition":"quarantined_legacy_uid","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False};base["conflict_id"]=_sha(_json(base));conflicts.append(base)
 gb=_csv(GROUP_FIELDS,[group]);sb=_csv(SUPPORT_FIELDS,support);cb=_csv(CONFLICT_FIELDS,conflicts)
 rule=_sha(_json({"artifact":ARTIFACT_TYPE,"version":RULE_VERSION,"fields":[GROUP_FIELDS,SUPPORT_FIELDS,CONFLICT_FIELDS],"input_sha":INPUT_SHA,"selected":EXPECTED_SELECTED,"r45_disjoint":EXPECTED_R45_TARGET3,"raw_cardinality_authority":True,"uid_bijection":False,"full_delta":0}))
 base={"format_version":1,"artifact_type":ARTIFACT_TYPE,"rule_contract_sha256":rule,"current_event_set_sha256":EXPECTED_CURRENT,"decision_scope_sha256":EXPECTED_SCOPE,"selected_event_set_sha256":EXPECTED_SELECTED,"r45_target3_set_sha256":EXPECTED_R45_TARGET3,"r45_intersection_count":len(keys&r45keys),"accepted_union":1528,"incomplete_residual":3800,"residual_set_sha256":EXPECTED_RESIDUAL,"full_classification_delta":0,"raw_count":2,"legacy_count":4,"master_count":2,"legacy_excess":2,"support_count":2,"conflict_count":4,"bijection_asserted":False,"individual_relation_count":0,"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False,"contains_sensitive_raw_values":False,"files":{"groups.csv":{"sha256":_sha(gb),"rows":1},"support.csv":{"sha256":_sha(sb),"rows":2},"conflicts.csv":{"sha256":_sha(cb),"rows":4}}}
 package=_sha(_json(base)+gb+sb+cb);manifest={**base,"package_set_sha256":package};files={"manifest.json":_json(manifest),"groups.csv":gb,"support.csv":sb,"conflicts.csv":cb};_privacy(files);return manifest,files

def verify_kbo_signature_cardinality_package(directory:Path,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 actual=_capture(directory);manifest,expected=_build(ledger_dir)
 if actual!=expected:raise ValueError("r46_package_live_rebuild_mismatch")
 return manifest

def reconcile_kbo_signature_cardinality(output:Path,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 """Verify an already-published package, fsync its pinned parent, then recapture."""
 parent=output.parent.resolve(strict=True);pfd=os.open(parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0));tfd=None
 try:
  parent_id=_identity(os.fstat(pfd));path_id=_identity(os.stat(output.parent,follow_symlinks=False));manifest,expected=_build(ledger_dir)
  try:tfd=os.open(output.name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd);target_id=_identity(os.fstat(tfd));actual=_capture_dirfd(tfd)
  except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"],parent_id) from exc
  if actual!=expected:raise PublicationIntegrityError(output,manifest["package_set_sha256"],parent_id,target_id)
  try:os.fsync(pfd)
  except OSError as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"],parent_id,target_id) from exc
  try:
   if _identity(os.fstat(pfd))!=parent_id or _identity(os.stat(output.parent,follow_symlinks=False))!=path_id or _identity(os.fstat(tfd))!=target_id or _capture_dirfd(tfd)!=expected:raise ValueError("r46_reconcile_mismatch")
  except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"],parent_id,target_id) from exc
  return manifest
 finally:
  if tfd is not None:os.close(tfd)
  os.close(pfd)

def build_kbo_signature_cardinality(output:Path|None=None,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 manifest,files=_build(ledger_dir)
 if output is None:return manifest,files
 if output.parent.is_symlink() or os.path.lexists(output):raise FileExistsError("r46_output_invalid")
 parent=output.parent.resolve(strict=True);pfd=os.open(parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0));parent_id=_identity(os.fstat(pfd));parent_path_id=_identity(os.stat(output.parent,follow_symlinks=False))
 try:parent.relative_to(REPOSITORY_ROOT.resolve())
 except ValueError:pass
 else:
  os.close(pfd);raise ValueError("r46_output_inside_repository")
 stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=f"/proc/self/fd/{pfd}"));stage_name=stage.name;stage_path=Path(f"/proc/self/fd/{pfd}")/stage_name;os.chmod(stage_path,0o700);published=False;target_id=None;targetfd=None
 try:
  for name,data in files.items():
   fd=os.open(stage_path/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600)
   try:
    view=memoryview(data)
    while view:
     n=os.write(fd,view)
     if n<=0:raise OSError("r46_short_write")
     view=view[n:]
    os.fsync(fd)
   finally:os.close(fd)
  sfd=os.open(stage_name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd);stage_id=_identity(os.fstat(sfd));os.fsync(sfd)
  if _capture_dirfd(sfd)!=files:raise ValueError("r46_stage_verify_failed")
  if _identity(os.fstat(pfd))!=parent_id or _identity(os.stat(output.parent,follow_symlinks=False))!=parent_path_id:raise ValueError("r46_publication_identity_changed")
  _rename_noreplace_at(pfd,stage_name,output.name);published=True
  try:
   targetfd=os.open(output.name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd);target_id=_identity(os.fstat(targetfd))
   if _identity(os.fstat(pfd))!=parent_id or _identity(os.stat(output.parent,follow_symlinks=False))!=parent_path_id or _capture_dirfd(targetfd)!=files:raise ValueError("r46_post_install_mismatch")
  except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"],parent_id,target_id) from exc
  try:os.fsync(pfd)
  except OSError as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"],parent_id,target_id) from exc
  try:
   if _identity(os.fstat(pfd))!=parent_id or _identity(os.stat(output.parent,follow_symlinks=False))!=parent_path_id or _identity(os.fstat(targetfd))!=target_id or _capture_dirfd(targetfd)!=files:raise ValueError("r46_post_fsync_mismatch")
  except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"],parent_id,target_id) from exc
 except Exception:
  if not published and stage_path.exists():shutil.rmtree(stage_path)
  raise
 finally:
  if targetfd is not None:os.close(targetfd)
  if 'sfd' in locals():os.close(sfd)
  os.close(pfd)
 return manifest,files
