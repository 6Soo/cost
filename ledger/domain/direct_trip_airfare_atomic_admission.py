"""R57 atomic admission for the two indistinguishable Trip.com airfare events.

R43 stays immutable and support-only.  This contract admits exactly one unordered
two-event group; it deliberately makes no receipt-to-event or card-last-four claim.
"""
from __future__ import annotations

import csv, hashlib, io, json, os, re, shutil, stat, tempfile
from ledger.domain.staged_inputs import staged
_r55_package = staged('cost-r44-trip-cancel-restricted.S2RPTC')
r55_documents_dir = _r55_package
r55_provenance = staged('cost-r44-trip-cancel-restricted.S2RPTC', 'provenance.v2.3.json')
r55_key = staged('cost-r44-trip-cancel-restricted.S2RPTC', 'seal.key')
from pathlib import Path

from ledger.domain import direct_receipt_airfare_evidence as r43
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_trip_cancel_atomic_admission as r55
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.posix_publication import open_dir, open_dir_at, open_nofollow, open_at, path_from_fd, verify_regular_single_link, fsync_dir, rename_noreplace_at, identity as posix_identity

ARTIFACT_TYPE="r57-trip-airfare-atomic2-full-v1"
RULE_VERSION="r57-receipt-manual-current-unordered-complete-group-v1"
FILES=("manifest.json","groups.csv","proposals.csv")
MANUAL=r55.MANUAL
MANUAL_SHA256=r55.MANUAL_SHA256
GID="4792823347ceedb9e764952351c187ede6be26c03592e9d85d9551e729ba23a5"
MEMBER_SET_SHA256="618073eac93beedb695f5681ace201b25ed384fcbd9a2700d7a2f20ebba4f68e"
DOCUMENT_SET_SHA256="3a298f3ff93cd406ba5df6508f4e1b5c650c3e8b34b81436fc57a24304913b3b"
PRE_ACCEPTED_SHA256=r55.POST_ACCEPTED_SHA256
PRE_RESIDUAL_SHA256=r55.POST_RESIDUAL_SHA256
POST_ACCEPTED_SHA256="05dded46b7e63edb7be5e4df98f1b8e3f6f3acf01e96787b88ffb4849bf0be5d"
POST_RESIDUAL_SHA256="b21ca6741f3acaeb568cc1b7692ba7f59fb96bc71bf42af7ffe1fba558e2f04f"
ACCOUNT,COST_TYPE,VAT_TAG,TRIP_TARGET="항공료","여행원가","불공제_해외","5월_유럽"
GROUP_FIELDS=("group_id","member_set_sha256","document_set_sha256","member_count","document_count","manual_set_sha256","axis_authority_sha256","relation_kind","bijection_asserted","individual_relation_count","receipt_permutation_count","capture_authority_caveat","korean_vat_document_count","card4_asserted","authority_status","posting_status","confirmed_count","gate5_credit","applied")
PROPOSAL_FIELDS=("proposal_id","event_key_sha256","current_event_sha256","current_source_sha256","current_payload_sha256","group_id","account","cost_type","vat_tag","trip_target","atomic_group_required","atomic_member_count","bijection_asserted","individual_relation_count","card4_asserted","authority_status","posting_status","confirmed_count","gate5_credit","applied")

def _sha(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def _json(x)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(xs)->str:return r36._event_set_sha(set(xs))
def _csv(fields,rows):
 s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
 for row in rows:w.writerow({k:(str(row.get(k,"")).lower() if isinstance(row.get(k),bool) else row.get(k,"")) for k in fields})
 return s.getvalue().encode()

def _secure_read(path:Path,pin:str):
 try:fd=open_nofollow(path)
 except OSError as exc:raise ValueError("r57_manual_file_invalid") from exc
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode):raise ValueError("r57_manual_file_invalid")
  if os.name=="posix" and (before.st_uid!=os.getuid() or before.st_nlink!=1 or stat.S_IMODE(before.st_mode) not in {0o600,0o644}):raise ValueError("r57_manual_file_invalid")
  data=b""
  while True:
   b=os.read(fd,1<<20)
   if not b:break
   data+=b
  after=os.fstat(fd);ident=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_mode,x.st_uid,x.st_nlink)
  if ident(before)!=ident(after):raise ValueError("r57_manual_changed_during_read")
 finally:os.close(fd)
 if _sha(data)!=pin:raise ValueError("r57_manual_pin_invalid")
 try:check=open_nofollow(path)
 except OSError as exc:raise ValueError("r57_manual_identity_changed") from exc
 try:
  if posix_identity(os.fstat(check))!=posix_identity(before):raise ValueError("r57_manual_identity_changed")
 finally:os.close(check)
 return data

def _read_manual(path:Path=MANUAL):
 if path.resolve()!=MANUAL.resolve():raise ValueError("r57_manual_pin_invalid")
 rows=list(csv.DictReader(io.StringIO(_secure_read(path,MANUAL_SHA256).decode("utf-8-sig"))))
 if len(rows)!=1559 or len({(x["tab"],x["row"]) for x in rows})!=1559:raise ValueError("r57_manual_census_invalid")
 def amount(x):
  try:return abs(int(float(x.get("amount") or 0)))
  except (TypeError,ValueError):return -1
 target=[x for x in rows if x.get("card")=="국민" and amount(x)==208400]
 if (len(target)!=2 or len({(x["tab"],x["row"]) for x in target})!=2 or
     {(x["tab"],x["item"],x["desc"],x["card"],x["date"],amount(x)) for x in target}!={(TRIP_TARGET,"트립닷컴_0515","항공","국민","26.03.24",208400)} or
     any(x.get("book") for x in target)):
  raise ValueError("r57_manual_global_collision_invalid")
 return target,_sha(_json(sorted(target,key=lambda x:(x["tab"],int(x["row"])))))

def _validate_receipts(documents_dir:Path):
 cfg=r43.GROUPS[GID];facts=[];refs=[]
 for alias in cfg["aliases"]:
  text=r43._read_private(documents_dir,alias+".txt").decode()
  ref,provider,date,total=r43._parse(alias,text,cfg)
  if text.count("Trip.com Travel Singapore Pte. Ltd.")<2 or text.count("Kookmin Card")!=1:raise ValueError("r57_receipt_supplier_or_token_invalid")
  if re.search(r"(?i)korean\s+vat|부가가치세|tax invoice|세금계산서",text):raise ValueError("r57_korean_vat_claim_invalid")
  refs.append(ref);facts.append((provider,date,total))
 if len(set(refs))!=2 or set(facts)!={("tripcom","2026-03-24",208400)}:raise ValueError("r57_receipt_fact_invalid")
 return _setsha(_sha(x.encode()) for x in refs)

def _validate_current(rows,payloads,selected):
 rows=list(rows);universe={x["direct_event_key"]:x for x in rows}
 if len(rows)!=len(universe):raise ValueError("r57_current_physical_duplicate")
 if not selected<=set(universe):raise ValueError("r57_current_member_exchange")
 def sig(e):return (e["source_system"],e["occurred_on"],int(e["signed_amount_krw"]),e["currency"],e["transaction_type"],e["event_role"],e["merchant"])
 expected={sig(universe[k]) for k in selected};matches={k for k,e in universe.items() if sig(e) in expected and e["source_system"] in {"KBO","KBD"}}
 amount={k for k,e in universe.items() if e["source_system"] in {"KBO","KBD"} and abs(int(e["signed_amount_krw"]))==208400}
 if len(expected)!=1 or matches!=selected or amount!=selected:raise ValueError("r57_current_global_collision_invalid")
 for k in selected:
  e=universe[k];p=payloads.get(k)
  if p is None:raise ValueError("r57_current_payload_missing")
  if (e["source_system"]!="KBD" or e["occurred_on"]!="2026-03-24" or int(e["signed_amount_krw"])!=208400 or e["currency"]!="KRW" or e["transaction_type"]!="purchase" or e["event_role"]!="single" or r43._provider_from_live(e,p)!="tripcom"):
   raise ValueError("r57_current_fact_invalid")
 return universe

def _live(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir):
 # Freshly verifies all six R43 documents and immutable R43 evidence contract.
 _m43,f43=r43._build(documents_dir,provenance_path,key_path,pypdf_python)
 groups=[x for x in csv.DictReader(io.StringIO(f43["groups.csv"].decode())) if x["group_id"]==GID]
 if (len(groups)!=1 or groups[0]["member_set_sha256"]!=MEMBER_SET_SHA256 or
     groups[0]["document_set_sha256"]!=DOCUMENT_SET_SHA256 or
     (groups[0]["member_count"],groups[0]["document_count"])!=("2","2")):
  raise ValueError("r57_member_or_document_set_mismatch")
 props=[x for x in csv.DictReader(io.StringIO(f43["proposals.csv"].decode())) if x["group_id"]==GID]
 if len(props)!=2 or {x["current_event_sha256"] for x in props}.__len__()!=2:raise ValueError("r57_r43_selected_invalid")
 r55._live(documents_dir=documents_dir,provenance_path=r55_provenance,key_path=r55_key,pypdf_python=pypdf_python,ledger_dir=ledger_dir)
 with tempfile.TemporaryDirectory(prefix="r57-current-") as td:
  c=r36._context(ledger_dir,Path(td));db=c["db"]
  try:
   selected={e["direct_event_key"] for e in c["events"] if e["current_event_sha256"] in {x["current_event_sha256"] for x in props}}
   payloads={}
   for e in c["events"]:
    if e["direct_event_key"] in selected:
     got=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(e["current_source_key"],)).fetchall()
     if len(got)!=1:raise ValueError("r57_current_payload_cardinality")
     payloads[e["direct_event_key"]]=json.loads(got[0][0])
   universe=_validate_current(c["events"],payloads,selected)
  finally:db.close()
 accepted,_=r44._accepted_union(ledger_dir);pre=set(universe)-accepted-set(r44.EVENTS)-set(__import__('ledger.domain.direct_kb_confirmation_evidence',fromlist=['EVENTS']).EVENTS)-{__import__('ledger.domain.direct_agoda_customer_service_evidence',fromlist=['TARGET_EVENT']).TARGET_EVENT}
 preaccepted=set(universe)-pre
 if len(preaccepted)!=1536 or _setsha(preaccepted)!=PRE_ACCEPTED_SHA256 or len(pre)!=3792 or _setsha(pre)!=PRE_RESIDUAL_SHA256 or not selected<=pre:raise ValueError("r57_pre_state_invalid")
 post=pre-selected;postaccepted=preaccepted|selected
 if len(post)!=3790 or _setsha(post)!=POST_RESIDUAL_SHA256 or len(postaccepted)!=1538 or _setsha(postaccepted)!=POST_ACCEPTED_SHA256:raise ValueError("r57_post_state_invalid")
 return props,selected

def _build(documents_dir:Path,provenance_path:Path,key_path:Path,pypdf_python:Path,ledger_dir:Path=Path(REPOSITORY_ROOT)/"ledger"):
 manual,manual_sha=_read_manual();receipt_sha=_validate_receipts(documents_dir);props,selected=_live(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir)
 axis={"account":"manual_airfare","cost_type":"manual_trip_nature","vat":"overseas_supplier_only_not_korean_vat","trip":"manual_tab","relation":"unordered_atomic_no_payment_locator","capture":"provider_dkim_attachment_provenance_not_card_capture"};axis_sha=_sha(_json(axis))
 common={"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False}
 group={"group_id":GID,"member_set_sha256":MEMBER_SET_SHA256,"document_set_sha256":DOCUMENT_SET_SHA256,"member_count":2,"document_count":2,"manual_set_sha256":manual_sha,"axis_authority_sha256":axis_sha,"relation_kind":"unordered_complete_receipt_manual_issuer_group","bijection_asserted":False,"individual_relation_count":0,"receipt_permutation_count":2,"capture_authority_caveat":True,"korean_vat_document_count":0,"card4_asserted":False,**common}
 out=[]
 for x in sorted(props,key=lambda z:z["event_key_sha256"]):
  row={k:x[k] for k in ("event_key_sha256","current_event_sha256","current_source_sha256","current_payload_sha256")};row.update({"group_id":GID,"account":ACCOUNT,"cost_type":COST_TYPE,"vat_tag":VAT_TAG,"trip_target":TRIP_TARGET,"atomic_group_required":True,"atomic_member_count":2,"bijection_asserted":False,"individual_relation_count":0,"card4_asserted":False,**common});row["proposal_id"]=_sha(_json({"group":GID,"event":row["event_key_sha256"]}));out.append(row)
 payload={"groups.csv":_csv(GROUP_FIELDS,[group]),"proposals.csv":_csv(PROPOSAL_FIELDS,out)}
 base={"artifact_type":ARTIFACT_TYPE,"rule_version":RULE_VERSION,"selected_event_set_sha256":_setsha(selected),"receipt_reference_set_sha256":receipt_sha,"full_classification_delta":2,"accepted_union":1538,"global_residual":3790,"post_admission_accepted_set_sha256":POST_ACCEPTED_SHA256,"post_admission_residual_set_sha256":POST_RESIDUAL_SHA256,"manual_raw_sha256":MANUAL_SHA256,"atomic_all_two":True,"bijection_asserted":False,"individual_relation_count":0,"receipt_permutation_count":2,"capture_authority_caveat":True,"korean_vat_document_count":0,"vat_basis":"overseas_supplier_only","card4_asserted":False,"database_applied":False,**common,"contains_sensitive_raw_values":False,"files":{k:{"sha256":_sha(v),"rows":len(v.splitlines())-1} for k,v in payload.items()}}
 base["package_set_sha256"]=_sha(_json(base)+b"".join(payload[k] for k in sorted(payload)));files={"manifest.json":_json(base),**payload};_privacy(files);return base,files

def _privacy(files):
 blob=b"".join(files.values()).decode();forbidden=(r"\b208400\b",r"558526",r"\b[0-9]{16}\b",r"Booking No",r"source_locator")
 if any(re.search(p,blob,re.I) for p in forbidden):raise ValueError("r57_public_privacy_violation")

def _capture_dirfd(dfd:int):
 dm=os.fstat(dfd)
 if not stat.S_ISDIR(dm.st_mode) or stat.S_IMODE(dm.st_mode)!=0o700 or dm.st_uid!=os.getuid() or set(os.listdir(dfd))!=set(FILES):raise ValueError("r57_package_shape_invalid")
 result={}
 for name in FILES:
  try:fd=open_at(dfd, name)
  except OSError as exc:raise ValueError("r57_package_file_invalid") from exc
  try:
   before=os.fstat(fd)
   if not stat.S_ISREG(before.st_mode):raise ValueError("r57_package_file_invalid")
   if os.name=="posix" and (before.st_uid!=os.getuid() or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600):raise ValueError("r57_package_file_invalid")
   chunks=[]
   while True:
    b=os.read(fd,1<<20)
    if not b:break
    chunks.append(b)
   if identity(before)!=identity(os.fstat(fd)):raise ValueError("r57_package_changed_during_read")
   result[name]=b"".join(chunks)
  finally:os.close(fd)
 return result

def _capture(directory:Path):
 try:dfd=open_dir(directory)
 except OSError as exc:raise ValueError("r57_package_directory_invalid") from exc
 try:return _capture_dirfd(dfd)
 finally:os.close(dfd)

class PublicationDurabilityError(OSError):
 def __init__(self,output,package,parent_identity,target_identity):
  super().__init__("r57_published_durability_unknown");self.output=output;self.package_set_sha256=package;self.published=True;self.parent_path=output.parent;self.target_name=output.name;self.parent_identity=parent_identity;self.target_identity=target_identity
class PublicationIntegrityError(OSError):
 def __init__(self,output,package,parent_identity,target_identity):
  super().__init__("r57_published_integrity_invalid");self.output=output;self.package_set_sha256=package;self.published=True;self.parent_path=output.parent;self.target_name=output.name;self.parent_identity=parent_identity;self.target_identity=target_identity

def build_trip_airfare_atomic_admission(*args,output=None,**kwargs):
 manifest,files=_build(*args,**kwargs)
 if output is None:return {"manifest":manifest,"files":files}
 if output.parent.is_symlink():raise ValueError("r57_output_parent_symlink")
 out=output.resolve()
 if Path(REPOSITORY_ROOT).resolve() in (out,*out.parents):raise ValueError("r57_output_inside_repository")
 if os.path.lexists(out):raise FileExistsError(out)
 pfd=open_dir(out.parent);parent_id=posix_identity(os.fstat(pfd))
 if posix_identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:os.close(pfd);raise ValueError("r57_parent_identity_changed")
 stage=Path(tempfile.mkdtemp(prefix=".r57-stage-",dir=path_from_fd(pfd)));os.chmod(stage,0o700);published=False
 try:
  for n,d in files.items():
   fd=os.open(stage/n,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600)
   try:
    view=memoryview(d)
    while view:
     z=os.write(fd,view)
     if z<=0:raise OSError("r57_short_write_zero")
     view=view[z:]
    os.fsync(fd)
   finally:os.close(fd)
  dfd=open_dir(stage);fsync_dir(dfd);os.close(dfd)
  sfd=open_dir_at(pfd,stage.name)
  try:
   if _capture_dirfd(sfd)!=files:raise ValueError("r57_stage_verify_failed")
  finally:os.close(sfd)
  if posix_identity(os.fstat(pfd))!=parent_id or posix_identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:raise ValueError("r57_parent_identity_changed")
  rename_noreplace_at(pfd,stage.name,out.name);stage=None;published=True
  tfd=open_dir_at(pfd,out.name);target_id=posix_identity(os.fstat(tfd))
  try:
   if _capture_dirfd(tfd)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,target_id)
   try:fsync_dir(pfd)
   except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"],parent_id,target_id) from exc
   check=open_dir_at(pfd,out.name)
   try:
    if posix_identity(os.fstat(check))!=target_id or posix_identity(os.fstat(tfd))!=target_id or posix_identity(os.stat(out.parent,follow_symlinks=False))!=parent_id or _capture_dirfd(tfd)!=files or _capture_dirfd(check)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,target_id)
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

def verify_trip_airfare_atomic_admission(directory,*args,**kwargs):
 manifest,expected=_build(*args,**kwargs);before=posix_identity(os.stat(directory,follow_symlinks=False));dfd=open_dir(directory)
 try:
  if posix_identity(os.fstat(dfd))!=before or _capture_dirfd(dfd)!=expected or posix_identity(os.stat(directory,follow_symlinks=False))!=before:raise ValueError("r57_package_or_context_mismatch")
 finally:os.close(dfd)
 return manifest

def reconcile_publication(error,*args,**kwargs):
 if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r57_reconcile_state_invalid")
 manifest,expected=_build(*args,**kwargs);pfd=open_dir(error.parent_path)
 try:
  if posix_identity(os.fstat(pfd))!=error.parent_identity or posix_identity(os.stat(error.parent_path,follow_symlinks=False))!=error.parent_identity:raise ValueError("r57_reconcile_parent_identity_mismatch")
  tfd=open_dir_at(pfd,error.target_name)
  try:
   if posix_identity(os.fstat(tfd))!=error.target_identity or _capture_dirfd(tfd)!=expected:raise ValueError("r57_reconcile_target_identity_mismatch")
   fsync_dir(pfd);check=open_dir_at(pfd,error.target_name)
   try:
    if posix_identity(os.fstat(check))!=error.target_identity or _capture_dirfd(tfd)!=expected or _capture_dirfd(check)!=expected or posix_identity(os.stat(error.output,follow_symlinks=False))!=error.target_identity:raise ValueError("r57_reconcile_identity_changed")
   finally:os.close(check)
  finally:os.close(tfd)
 finally:os.close(pfd)
 if manifest["package_set_sha256"]!=error.package_set_sha256:raise ValueError("r57_reconcile_package_mismatch")
 return {"status":"valid","package_set_sha256":manifest["package_set_sha256"],"published":True,"durable":True}
