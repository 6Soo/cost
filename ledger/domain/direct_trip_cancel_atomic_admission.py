"""R55 atomic admission of the complete R44 Trip.com purchase/refund group.

This is deliberately a new contract: R44 remains support-only.  R55 admits only the
four-member unordered group and never claims an order-to-card-event bijection.
"""
from __future__ import annotations

import csv, hashlib, io, json, os, re, shutil, stat, tempfile
from ledger.domain.staged_inputs import staged
from pathlib import Path

from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_kb_confirmation_evidence as r45
from ledger.domain import direct_agoda_customer_service_evidence as r49
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.posix_publication import open_dir, open_dir_at, open_nofollow, open_at, path_from_fd, verify_regular_single_link, fsync_dir, rename_noreplace_at, identity as posix_identity

ARTIFACT_TYPE="r55-trip-cancel-atomic4-full-v1"
RULE_VERSION="r55-raw-manual-provider-unordered-complete-group-v1"
FILES=("manifest.json","groups.csv","proposals.csv","exclusions.csv")
MANUAL=staged("cost-r25-manual-v4.csv")
MANUAL_SHA256="2c6d7486458a0921186311780cb2fab26950c13b369d8cf876a5ad04cac10489"
PRE_RESIDUAL_SHA256=r49.POST_RESIDUAL_SHA256
POST_ACCEPTED_SHA256="dde7132923defa559597946d22acf8f784e112066f499c5258cd9426f3b811da"
POST_RESIDUAL_SHA256="0c45fa0f80308dec5e5aa5b1398a077a921645225504f3d0dc6e65c86a2591f6"
ACCOUNT,COST_TYPE,VAT_TAG,TRIP_TARGET,POSTING_BUCKET="숙박비","여행원가","불공제_해외","10월_도고","취소환불(net0)"
GROUP_FIELDS=("group_id","member_set_sha256","member_count","purchase_count","cancellation_count","manual_group_sha256","manual_exclusion_sha256","provider_lifecycle_set_sha256","axis_authority_sha256","cancellation_axis_source","trip_target","posting_bucket","relation_kind","bijection_asserted","individual_relation_count","capture_claim_unverified","authority_status","posting_status","confirmed_count","gate5_credit","applied")
PROPOSAL_FIELDS=("proposal_id","event_key_sha256","current_event_sha256","current_source_sha256","current_payload_sha256","transaction_type","group_id","account","cost_type","vat_tag","trip_target","posting_bucket","atomic_group_required","atomic_member_count","bijection_asserted","individual_relation_count","authority_status","posting_status","confirmed_count","gate5_credit","applied")
EXCLUSION_FIELDS=("exclusion_id","exclusion_set_sha256","reason","authority_status","posting_status","applied")

def _sha(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def _json(x)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(xs)->str:return r36._event_set_sha(set(xs))
def _csv(fields,rows):
 s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
 for row in rows:w.writerow({k:(str(row.get(k,"")).lower() if isinstance(row.get(k),bool) else row.get(k,"")) for k in fields})
 return s.getvalue().encode()

def _read_manual(path:Path=MANUAL):
 if path.resolve()!=MANUAL.resolve():raise ValueError("r55_manual_pin_invalid")
 try:fd=open_nofollow(path)
 except OSError as exc:raise ValueError("r55_manual_file_invalid") from exc
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode):raise ValueError("r55_manual_file_invalid")
  if os.name=="posix" and (before.st_uid!=os.getuid() or before.st_nlink!=1 or
      stat.S_IMODE(before.st_mode) not in {0o600,0o644}):raise ValueError("r55_manual_file_invalid")
  chunks=[]
  while True:
   chunk=os.read(fd,1<<20)
   if not chunk:break
   chunks.append(chunk)
  after=os.fstat(fd);data=b"".join(chunks)
  identity=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_mode,x.st_uid,x.st_nlink)
  if identity(before)!=identity(after):raise ValueError("r55_manual_changed_during_read")
 finally:os.close(fd)
 if _sha(data)!=MANUAL_SHA256:raise ValueError("r55_manual_pin_invalid")
 rows=list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
 if len(rows)!=1559 or len({(x["tab"],x["row"]) for x in rows})!=1559:raise ValueError("r55_manual_census_invalid")
 def amount(x):
  try:return int(float(x["amount"]))
  except (ValueError,TypeError):return 0
 target=[x for x in rows if x["card"]=="국민" and x["tab"]==TRIP_TARGET and
         x["item"]=="트립닷컴_야쿠시마 그린 호텔" and abs(amount(x))==893170]
 if (len(target)!=4 or sorted(amount(x) for x in target)!=[-893170,-893170,893170,893170] or
     sum(x["desc"]=="숙박_1006_1009" for x in target)!=2 or sum(x["desc"]=="취소" for x in target)!=2 or
     any(x["book"] for x in target)):
  raise ValueError("r55_manual_group_invalid")
 # Collision guard: every same card/amount/hotel row must be in the four-row target.
 hidden=[x for x in rows if x["card"]=="국민" and abs(amount(x))==893170]
 if {(x["tab"],x["row"]) for x in hidden}!={(x["tab"],x["row"]) for x in target}:raise ValueError("r55_manual_hidden_collision")
 excluded=[x for x in rows if x["tab"]=="1127_야쿠시마" and x["item"]=="트립닷컴_야쿠시마" and x["desc"]=="숙박_1127_1130"]
 if len(excluded)!=3 or {(x["card"],abs(amount(x))) for x in excluded}!={('하나',1224285),('하나',2385502),('국민',1122624)}:
  raise ValueError("r55_manual_exclusion_invalid")
 # Reopen by pathname after parsing so a selector swap cannot silently pass.
 try:check=os.open(path,flags)
 except OSError as exc:raise ValueError("r55_manual_identity_changed") from exc
 try:
  if identity(os.fstat(check))!=identity(before):raise ValueError("r55_manual_identity_changed")
 finally:os.close(check)
 return target,_sha(_json(sorted(target,key=lambda x:int(x["row"])))),_sha(_json(sorted(excluded,key=lambda x:int(x["row"]))))

def _validate_provider(provenance:dict):
 if provenance.get("relevant_lifecycle_count")!=2 or len(provenance.get("lifecycles",[]))!=2:raise ValueError("r55_provider_lifecycle_invalid")
 ls=provenance["lifecycles"]
 if len({x.get("order_hmac_sha256") for x in ls})!=2 or len({x.get("receipt_sha256") for x in ls})!=2:raise ValueError("r55_provider_swap_or_duplicate")
 for x in ls:
  if (x.get("message_count"),x.get("states"),x.get("amount_jpy"),x.get("stay_start"),x.get("stay_end"),x.get("rooms"),x.get("nights"))!=(2,["confirmation","refund_complete"],92001,"2026-10-06","2026-10-09",1,3):raise ValueError("r55_provider_lifecycle_invalid")
 claims=provenance.get("capture_claims",{})
 if claims.get("authenticated") is not False:raise ValueError("r55_capture_authority_escalation")
 return _sha(_json(sorted((x["order_hmac_sha256"],x["receipt_sha256"]) for x in ls)))

def _validate_current_census(rows,payloads=None):
 rows=list(rows);universe={x["direct_event_key"]:x for x in rows}
 if len(rows)!=len(universe):raise ValueError("r55_current_physical_duplicate")
 kb_amount={k for k,x in universe.items() if x["source_system"] in {"KBO","KBD"} and abs(int(x["signed_amount_krw"]))==893170}
 if (kb_amount!=set(r44.EVENTS) or sum(universe[k]["transaction_type"]=="purchase" for k in kb_amount)!=2 or
     sum(universe[k]["transaction_type"]=="cancellation" for k in kb_amount)!=2):raise ValueError("r55_current_amount_census_invalid")
 if payloads is not None:
  for key,(role,content) in r44.EVENTS.items():
   raw=payloads.get(key)
   if raw is None:raise ValueError("r55_current_payload_missing")
   r44._validate_selected_event(universe[key],raw,role,content)
 return universe

def _live(documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path,ledger_dir:Path):
 verified=r44.auth.verify_provenance(documents_dir,provenance_path,key_path,pypdf_python)
 provider_sha=_validate_provider(verified["provenance"])
 _m,bindings,residual,_remaining=r44._live(ledger_dir)
 r44._validate_atomic_bindings(bindings)
 # Exact raw compound census is enforced by R44._live and additionally bound here.
 if {x["key"] for x in bindings}!=set(r44.EVENTS):raise ValueError("r55_raw_extra_or_subset")
 with tempfile.TemporaryDirectory(prefix="r55-current-") as td:
  ctx=r36._context(ledger_dir,Path(td));db=ctx["db"];payloads={}
  try:
   for event in ctx["events"]:
    if event["direct_event_key"] in r44.EVENTS:
     raw=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(event["current_source_key"],)).fetchall()
     if len(raw)!=1:raise ValueError("r55_current_payload_cardinality")
     payloads[event["direct_event_key"]]=r44._selected_payload(raw[0][0])
   universe=_validate_current_census(ctx["events"],payloads)
  finally:db.close()
 pre=set(residual)-set(r45.EVENTS)-{r49.TARGET_EVENT}
 accepted=set(universe)-pre
 if (len(pre)!=3796 or _setsha(pre)!=PRE_RESIDUAL_SHA256 or len(accepted)!=1532 or
     _setsha(accepted)!=r49.POST_ACCEPTED_SHA256 or not set(r44.EVENTS)<=pre):raise ValueError("r55_pre_state_invalid")
 post=pre-set(r44.EVENTS)
 if len(post)!=3792 or _setsha(post)!=POST_RESIDUAL_SHA256:raise ValueError("r55_post_state_invalid")
 post_accepted=accepted|set(r44.EVENTS)
 if len(post_accepted)!=1536 or _setsha(post_accepted)!=POST_ACCEPTED_SHA256:raise ValueError("r55_post_accepted_state_invalid")
 return bindings,provider_sha

def _build(documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path,ledger_dir:Path=Path(REPOSITORY_ROOT)/"ledger"):
 manual,manual_raw_sha,exclusion_raw_sha=_read_manual();bindings,provider_sha=_live(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir)
 manual_sha=_sha(_json({"domain":"r55-manual-group","provider":provider_sha,"rows":manual_raw_sha}))
 exclusion_sha=_sha(_json({"domain":"r55-manual-exclusion","provider":provider_sha,"rows":exclusion_raw_sha}))
 if sum(int(x["amount"]) for x in bindings)!=0 or sum(int(x["foreign_signed"]) for x in bindings)!=0:raise ValueError("r55_net_zero_invalid")
 axis_authority={"account":"manual_a1_lodging","cost_type":"a0_manual_trip_nature_atomic_reversal","vat":"raw_overseas_signed_supplier","trip":"manual_tab_and_trip_window","posting":"a4_p6_complete_offset","capture":"unverified_not_authority","stay":"support_only_not_event_authority"}
 axis_sha=_sha(_json(axis_authority))
 group_id=_sha(_json({"events":r44.SELECTED_SET,"manual":manual_sha,"provider":provider_sha,"axis":axis_sha}))
 common={"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False}
 group={"group_id":group_id,"member_set_sha256":r44.SELECTED_SET,"member_count":4,"purchase_count":2,"cancellation_count":2,"manual_group_sha256":manual_sha,"manual_exclusion_sha256":exclusion_sha,"provider_lifecycle_set_sha256":provider_sha,"axis_authority_sha256":axis_sha,"cancellation_axis_source":"a2_pair_inversion_from_manual_bound_purchase","trip_target":TRIP_TARGET,"posting_bucket":POSTING_BUCKET,"relation_kind":"unordered_complete_provider_manual_issuer_group","bijection_asserted":False,"individual_relation_count":0,"capture_claim_unverified":True,**common}
 proposals=[]
 for x in sorted(bindings,key=lambda z:z["event_key_sha256"]):
  row={k:v for k,v in x.items() if k not in {"key","amount","foreign_signed","current_source_locator_sha256"}};row.update({"group_id":group_id,"account":ACCOUNT,"cost_type":COST_TYPE,"vat_tag":VAT_TAG,"trip_target":TRIP_TARGET,"posting_bucket":POSTING_BUCKET,"atomic_group_required":True,"atomic_member_count":4,"bijection_asserted":False,"individual_relation_count":0,**common});row["proposal_id"]=_sha(_json({"group":group_id,"event":row["event_key_sha256"]}));proposals.append(row)
 exclusion={"exclusion_set_sha256":exclusion_sha,"reason":"same_name_other_trip_card_amount_mismatch","authority_status":"unattested","posting_status":"blocked","applied":False};exclusion["exclusion_id"]=_sha(_json(exclusion))
 payload={"groups.csv":_csv(GROUP_FIELDS,[group]),"proposals.csv":_csv(PROPOSAL_FIELDS,proposals),"exclusions.csv":_csv(EXCLUSION_FIELDS,[exclusion])}
 base={"artifact_type":ARTIFACT_TYPE,"rule_version":RULE_VERSION,"selected_event_set_sha256":r44.SELECTED_SET,"full_classification_delta":4,"accepted_union":1536,"global_residual":3792,"post_admission_accepted_set_sha256":POST_ACCEPTED_SHA256,"post_admission_residual_set_sha256":POST_RESIDUAL_SHA256,"manual_raw_sha256":MANUAL_SHA256,"atomic_all_four":True,"bijection_asserted":False,"individual_relation_count":0,"capture_claim_unverified":True,"database_applied":False,**common,"contains_sensitive_raw_values":False,"files":{k:{"sha256":_sha(v),"rows":len(v.splitlines())-1} for k,v in payload.items()}}
 base["package_set_sha256"]=_sha(_json(base)+b"".join(payload[k] for k in sorted(payload)));files={"manifest.json":_json(base),**payload};_privacy(files);return base,files

def _privacy(files):
 blob=b"".join(files.values()).decode();forbidden=(r"card:[0-9a-f]{64}#",r"\b8835\b",r"\b92001\b",r"\b893170\b",r"TRIP\.COM",r"야쿠시마",r"\border\b",r"approval",r"source_locator")
 if any(re.search(p,blob,re.I) for p in forbidden):raise ValueError("r55_public_privacy_violation")

def _capture_dirfd(dfd:int):
 dm=os.fstat(dfd)
 if (not stat.S_ISDIR(dm.st_mode) or stat.S_IMODE(dm.st_mode)!=0o700 or dm.st_uid!=os.getuid() or
     set(os.listdir(dfd))!=set(FILES)):raise ValueError("r55_package_shape_invalid")
 result={}
 for name in FILES:
  try:fd=open_at(dfd,name)
  except OSError as exc:raise ValueError("r55_package_file_invalid") from exc
  try:
   before=os.fstat(fd)
   if not stat.S_ISREG(before.st_mode):raise ValueError("r55_package_file_invalid")
   if os.name=="posix" and (before.st_uid!=os.getuid() or before.st_nlink!=1 or
       stat.S_IMODE(before.st_mode)!=0o600):raise ValueError("r55_package_file_invalid")
   chunks=[]
   while True:
    b=os.read(fd,1<<20)
    if not b:break
    chunks.append(b)
   after=os.fstat(fd)
   ident=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_mode,x.st_uid,x.st_nlink)
   if ident(before)!=ident(after):raise ValueError("r55_package_changed_during_read")
   result[name]=b"".join(chunks)
  finally:os.close(fd)
 return result

def _capture(directory:Path):
 try:dfd=open_dir(directory)
 except OSError as exc:raise ValueError("r55_package_directory_invalid") from exc
 try:return _capture_dirfd(dfd)
 finally:os.close(dfd)

class PublicationDurabilityError(OSError):
 def __init__(self,output,package,parent_identity,target_identity):
  super().__init__("r55_published_durability_unknown");self.output=output;self.package_set_sha256=package;self.published=True;self.parent_path=output.parent;self.target_name=output.name;self.parent_identity=parent_identity;self.target_identity=target_identity
class PublicationIntegrityError(OSError):
 def __init__(self,output,package,parent_identity,target_identity):
  super().__init__("r55_published_integrity_invalid");self.output=output;self.package_set_sha256=package;self.published=True;self.parent_path=output.parent;self.target_name=output.name;self.parent_identity=parent_identity;self.target_identity=target_identity

def build_trip_cancel_atomic_admission(documents_dir,provenance_path,key_path,pypdf_python,output=None,ledger_dir=Path(REPOSITORY_ROOT)/"ledger"):
 manifest,files=_build(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir)
 if output is None:return {"manifest":manifest,"files":files}
 if output.parent.is_symlink():raise ValueError("r55_output_parent_symlink")
 out=output.resolve();
 if Path(REPOSITORY_ROOT).resolve() in (out,*out.parents):raise ValueError("r55_output_inside_repository")
 if os.path.lexists(out):raise FileExistsError(out)
 pfd=open_dir(out.parent);parent_id=r45._identity(os.fstat(pfd))
 if r45._identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:os.close(pfd);raise ValueError("r55_parent_identity_changed")
 stage=Path(tempfile.mkdtemp(prefix=".r55-stage-",dir=path_from_fd(pfd)));os.chmod(stage,0o700);published=False
 try:
  for n,d in files.items():
   p=stage/n;fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600)
   try:
    v=memoryview(d)
    while v:
     z=os.write(fd,v)
     if z<=0:raise OSError("r55_short_write_zero")
     v=v[z:]
    os.fsync(fd)
   finally:os.close(fd)
  dfd=open_dir(stage);fsync_dir(dfd);os.close(dfd)
  sfd=open_dir_at(pfd,stage.name)
  try:
   if _capture_dirfd(sfd)!=files:raise ValueError("r55_stage_verify_failed")
  finally:os.close(sfd)
  if r45._identity(os.fstat(pfd))!=parent_id or r45._identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:raise ValueError("r55_parent_identity_changed")
  rename_noreplace_at(pfd,stage.name,out.name);stage=None;published=True
  tfd=open_dir_at(pfd,out.name);target_id=r45._identity(os.fstat(tfd))
  try:
   if _capture_dirfd(tfd)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,target_id)
   try:fsync_dir(pfd)
   except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"],parent_id,target_id) from exc
   check=open_dir_at(pfd,out.name)
   try:
    if (r45._identity(os.fstat(check))!=target_id or r45._identity(os.fstat(tfd))!=target_id or
        r45._identity(os.stat(out.parent,follow_symlinks=False))!=parent_id or _capture_dirfd(tfd)!=files or
        _capture_dirfd(check)!=files):raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,target_id)
   finally:os.close(check)
  finally:os.close(tfd)
 except (PublicationIntegrityError,PublicationDurabilityError):raise
 except (OSError,ValueError) as exc:
  if published:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,locals().get("target_id")) from exc
  raise
 finally:
  if stage is not None and stage.exists():shutil.rmtree(stage)
  os.close(pfd)
 return {"manifest":manifest,"output":str(out)}

def verify_trip_cancel_atomic_admission(directory,*args,**kwargs):
 manifest,expected=_build(*args,**kwargs)
 before=r45._identity(os.stat(directory,follow_symlinks=False));dfd=open_dir(directory)
 try:
  if (r45._identity(os.fstat(dfd))!=before or _capture_dirfd(dfd)!=expected or
      r45._identity(os.stat(directory,follow_symlinks=False))!=before):raise ValueError("r55_package_or_context_mismatch")
 finally:os.close(dfd)
 return manifest

def reconcile_publication(error,*args,**kwargs):
 if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r55_reconcile_state_invalid")
 manifest,expected=_build(*args,**kwargs);pfd=open_dir(error.parent_path)
 try:
  if r45._identity(os.fstat(pfd))!=error.parent_identity or r45._identity(os.stat(error.parent_path,follow_symlinks=False))!=error.parent_identity:raise ValueError("r55_reconcile_parent_identity_mismatch")
  tfd=open_dir_at(pfd,error.target_name)
  try:
   if r45._identity(os.fstat(tfd))!=error.target_identity or _capture_dirfd(tfd)!=expected:raise ValueError("r55_reconcile_target_identity_mismatch")
   fsync_dir(pfd);check=open_dir_at(pfd,error.target_name)
   try:
    if (r45._identity(os.fstat(check))!=error.target_identity or _capture_dirfd(tfd)!=expected or
        _capture_dirfd(check)!=expected or r45._identity(os.stat(error.output,follow_symlinks=False))!=error.target_identity):raise ValueError("r55_reconcile_identity_changed")
   finally:os.close(check)
  finally:os.close(tfd)
 finally:os.close(pfd)
 if manifest["package_set_sha256"]!=error.package_set_sha256:raise ValueError("r55_reconcile_package_mismatch")
 return {"status":"valid","package_set_sha256":manifest["package_set_sha256"],"published":True,"durable":True}
