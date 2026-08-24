"""R59 admission of two complete unordered Mytrip/Gotogate airfare groups."""
from __future__ import annotations
import csv,hashlib,io,json,os,re,shutil,stat,tempfile
from pathlib import Path
from ledger.domain import direct_receipt_airfare_evidence as r43
from ledger.domain import direct_trip_airfare_atomic_admission as r57
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_kb_confirmation_evidence as r45
from ledger.domain import direct_agoda_customer_service_evidence as r49
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE="r59-mytrip-airfare-atomic2x2-full-v1";RULE_VERSION="r59-a0-domestic-llc-unordered-two-complete-groups-v1"
FILES=("manifest.json","groups.csv","proposals.csv")
MANUAL=r57.MANUAL;MANUAL_SHA256=r57.MANUAL_SHA256;A0_POLICY_SHA256=r43.A0_POLICY_SHA256
PRE_ACCEPTED_SHA256=r57.POST_ACCEPTED_SHA256;PRE_RESIDUAL_SHA256=r57.POST_RESIDUAL_SHA256
POST_ACCEPTED_SHA256="7a49e7e604a39b2023b7a07d98cf5869266ffcbbca92b06ad7ed47c5528032e9";POST_RESIDUAL_SHA256="df0bafd88645a7605f4629e22db0d1254705aa86346b3748ca9f28a3e3e6d629"
SELECTED_SET_SHA256="93515d41765505ccd1ab79d42b1846cdf5ea0d4901a7cffea53eede7695ea0e8"
GROUPS={
 "1a5034f2897878b0b396a544d9337886eac85815729504400066152bb6905fc6":("dbba027693b8aacd945551d61d301d7895a90147a76bc0168b52622e9c20d887","71203be6e6ed5f4da76c1cf76006888eddc1d6712e521e03ee366c8611b7c30f","0712_몽골","26.03.14",793669,"마이트립"),
 "fe0992319dd7cd96d6c1aa4134d4ec4ff04496d72351583d3c5aa1d24cc2cc29":("1778c638956cedc316683879ec1072da135d4df4fc199d4aa89750610b63c1e6","b4795497612f41afc82d028d4e0fa64e60a7952faa9884b176b547c753f0655b","0924_야마구치","26.02.26",361924,"마이트립_후쿠오카")}
GROUP_FIELDS=("group_id","member_set_sha256","document_set_sha256","receipt_reference_set_sha256","member_count","document_count","manual_set_sha256","axis_authority_sha256","relation_kind","bijection_asserted","individual_relation_count","receipt_permutation_count","capture_authority_caveat","korean_tax_invoice_count","card4_asserted","authority_status","posting_status","confirmed_count","gate5_credit","applied")
PROPOSAL_FIELDS=("proposal_id","event_key_sha256","current_event_sha256","current_source_sha256","current_payload_sha256","group_id","account","cost_type","vat_tag","trip_target","atomic_group_required","atomic_member_count","bijection_asserted","individual_relation_count","card4_asserted","authority_status","posting_status","confirmed_count","gate5_credit","applied")
def _sha(x):return hashlib.sha256(x).hexdigest()
def _json(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(xs):return r36._event_set_sha(set(xs))
def _csv(fields,rows):
 s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader()
 for x in rows:w.writerow({k:(str(x.get(k,"")).lower() if isinstance(x.get(k),bool) else x.get(k,"")) for k in fields})
 return s.getvalue().encode()

def _read_manual(path=None):
 if path is None:path=MANUAL
 data=r57._secure_read(path,MANUAL_SHA256);rows=list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
 if len(rows)!=1559 or len({(x["tab"],x["row"]) for x in rows})!=1559:raise ValueError("r59_manual_census_invalid")
 def amt(x):
  try:return abs(int(float(x.get("amount") or 0)))
  except (TypeError,ValueError):return -1
 result={}
 for gid,(_ms,_ds,tab,day,amount,item) in GROUPS.items():
  target=[x for x in rows if x.get("card")=="국민" and amt(x)==amount]
  if len(target)!=2 or len({(x["tab"],x["row"]) for x in target})!=2 or any((x["tab"],x["date"],x["item"])!=(tab,day,item) for x in target):raise ValueError("r59_manual_global_collision_invalid")
  result[gid]=_sha(_json(sorted(target,key=lambda x:int(x["row"]))))
 return result

def _receipts(directory):
 out={}
 prohibited=re.compile(r"(?i)(tax invoice|세금계산서|부가가치세\s*[:：]?\s*[0-9]|vat\s+(?:amount|rate|included))")
 for gid in GROUPS:
  cfg=r43.GROUPS[gid];refs=[];facts=[]
  for alias in cfg["aliases"]:
   text=r43._read_private(directory,alias+".txt").decode();ref,provider,day,total=r43._parse(alias,text,cfg)
   required=("Gotogate Korea LLC","고투게이트코리아 유한책임회사","Seocho-gu, Seoul","184-86-02130","항공편")
   if not all(x in text for x in required) or prohibited.search(text):raise ValueError("r59_receipt_supplier_or_tax_invoice_invalid")
   refs.append(ref);facts.append((provider,day,total))
  expected=GROUPS[gid]
  expected_iso="20"+expected[3].replace(".","-")
  if len(set(refs))!=2 or len(set(facts))!=1 or next(iter(set(facts)))!=("mytrip_gotogate",expected_iso,expected[4]):raise ValueError("r59_receipt_fact_invalid")
  out[gid]=_setsha(_sha(x.encode()) for x in refs)
 return out

def _validate_current_census(universe,selected,payload,bycontent):
 if len(universe)!=len(set(universe)):raise ValueError("r59_current_physical_duplicate")
 if len(selected)!=4 or not selected<=set(universe):raise ValueError("r59_current_member_exchange")
 def sig(e):return (e["source_system"],e["occurred_on"],abs(int(e["signed_amount_krw"])),e["currency"],e["transaction_type"],e["event_role"],r43._provider_from_live(e,payload[e["direct_event_key"]]) if e["direct_event_key"] in payload else "")
 expected={sig(universe[k]) for k in selected};matches={k for k,e in universe.items() if e["source_system"] in {"KBD","KBO"} and abs(int(e["signed_amount_krw"])) in {793669,361924} and k in payload and sig(e) in expected}
 amount_matches={k for k,e in universe.items() if e["source_system"] in {"KBD","KBO"} and abs(int(e["signed_amount_krw"])) in {793669,361924}}
 if matches!=selected or amount_matches!=selected or _setsha(selected)!=SELECTED_SET_SHA256:raise ValueError("r59_current_global_collision_invalid")
 for k in selected:
  e=universe[k];p=payload.get(k);x=bycontent.get(e["current_event_sha256"])
  if p is None or x is None:raise ValueError("r59_current_payload_or_content_missing")
  amount=GROUPS[x["group_id"]][4];expected_iso="20"+GROUPS[x["group_id"]][3].replace(".","-")
  if e["source_system"]!="KBD" or e["occurred_on"]!=expected_iso or e["transaction_type"]!="purchase" or e["event_role"]!="single" or e["currency"]!="KRW" or int(e["signed_amount_krw"])!=amount or r43._provider_from_live(e,p)!="mytrip_gotogate":raise ValueError("r59_current_fact_invalid")

def _live(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir):
 auth=r43.r43auth.verify_authenticated_inputs(documents_dir,provenance_path,key_path,r43.DOCS,pypdf_python)
 entries={x.get("alias"):x for x in auth["provenance"].get("documents",[])}
 transport={(a,entries.get(a,{}).get("transport_auth")) for gid in GROUPS for a in r43.GROUPS[gid]["aliases"]}
 expected_transport={(a,"forwarded_outer_auth_observed_unverified") for gid in GROUPS for a in r43.GROUPS[gid]["aliases"]}
 if transport!=expected_transport:raise ValueError("r59_transport_authority_escalation")
 transport_sha=_sha(_json(sorted(transport)))
 m43,f43=r43._build(documents_dir,provenance_path,key_path,pypdf_python)
 if m43.get("a0_policy_sha256")!=A0_POLICY_SHA256:raise ValueError("r59_a0_authority_invalid")
 gs={x["group_id"]:x for x in csv.DictReader(io.StringIO(f43["groups.csv"].decode())) if x["group_id"] in GROUPS}
 for gid,(member,doc,*_) in GROUPS.items():
  if gid not in gs or (gs[gid]["member_set_sha256"],gs[gid]["document_set_sha256"],gs[gid]["member_count"],gs[gid]["document_count"])!=(member,doc,"2","2"):raise ValueError("r59_r43_group_commitment_invalid")
 allprops=list(csv.DictReader(io.StringIO(f43["proposals.csv"].decode())));props=[x for x in allprops if x["group_id"] in GROUPS]
 if len(props)!=4 or {gid:sum(x["group_id"]==gid for x in props) for gid in GROUPS}!={gid:2 for gid in GROUPS}:raise ValueError("r59_r43_selected_invalid")
 contents={x["current_event_sha256"] for x in props}
 with tempfile.TemporaryDirectory(prefix="r59-current-") as td:
  c=r36._context(ledger_dir,Path(td));db=c["db"]
  try:
   universe={x["direct_event_key"]:x for x in c["events"]};selected={k for k,e in universe.items() if e["current_event_sha256"] in contents};payload={}
   if len(c["events"])!=len(universe):raise ValueError("r59_current_physical_duplicate")
   for k in selected:
    got=db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",(universe[k]["current_source_key"],)).fetchall()
    if len(got)!=1:raise ValueError("r59_current_payload_cardinality")
    payload[k]=json.loads(got[0][0])
  finally:db.close()
 bycontent={x["current_event_sha256"]:x for x in props}
 _validate_current_census(universe,selected,payload,bycontent)
 accepted0,_=r44._accepted_union(ledger_dir);base=set(universe)-accepted0-set(r45.EVENTS)-{r49.TARGET_EVENT}-set(r44.EVENTS)
 trip_contents={x["current_event_sha256"] for x in allprops if x["group_id"]==r57.GID}
 r57set={k for k,e in universe.items() if e["current_event_sha256"] in trip_contents};pre=base-r57set;pa=set(universe)-pre
 if len(pa)!=1538 or _setsha(pa)!=PRE_ACCEPTED_SHA256 or len(pre)!=3790 or _setsha(pre)!=PRE_RESIDUAL_SHA256 or not selected<=pre:raise ValueError("r59_pre_state_invalid")
 post=pre-selected;aa=pa|selected
 if len(aa)!=1542 or _setsha(aa)!=POST_ACCEPTED_SHA256 or len(post)!=3786 or _setsha(post)!=POST_RESIDUAL_SHA256:raise ValueError("r59_post_state_invalid")
 return props,selected,transport_sha

def _build(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir=Path(REPOSITORY_ROOT)/"ledger"):
 manual=_read_manual();refs=_receipts(documents_dir);props,selected,transport_sha=_live(documents_dir,provenance_path,key_path,pypdf_python,ledger_dir)
 policy=Path(REPOSITORY_ROOT)/"docs/비용분류_지시사항_원장.md"
 if _sha(policy.read_bytes())!=A0_POLICY_SHA256:raise ValueError("r59_a0_authority_invalid")
 common={"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False};groups=[]
 axis=_sha(_json({"account":"authenticated_airfare_receipt","cost":"manual_trip_nature","vat":"a0_customer_travel_expense_noncredit_domestic_supplier","bucket":"manual_tab","tax_invoice":"absent_not_positive_authority"}))
 for gid,(member,doc,tab,*_) in sorted(GROUPS.items()):groups.append({"group_id":gid,"member_set_sha256":member,"document_set_sha256":doc,"receipt_reference_set_sha256":refs[gid],"member_count":2,"document_count":2,"manual_set_sha256":manual[gid],"axis_authority_sha256":axis,"relation_kind":"unordered_complete_receipt_manual_issuer_group","bijection_asserted":False,"individual_relation_count":0,"receipt_permutation_count":2,"capture_authority_caveat":True,"korean_tax_invoice_count":0,"card4_asserted":False,**common})
 out=[]
 for x in sorted(props,key=lambda z:z["event_key_sha256"]):
  row={k:x[k] for k in ("event_key_sha256","current_event_sha256","current_source_sha256","current_payload_sha256")};row.update({"group_id":x["group_id"],"account":"항공료","cost_type":"여행원가","vat_tag":"불공제_국내","trip_target":GROUPS[x["group_id"]][2],"atomic_group_required":True,"atomic_member_count":2,"bijection_asserted":False,"individual_relation_count":0,"card4_asserted":False,**common});row["proposal_id"]=_sha(_json({"group":x["group_id"],"event":row["event_key_sha256"]}));out.append(row)
 payload={"groups.csv":_csv(GROUP_FIELDS,groups),"proposals.csv":_csv(PROPOSAL_FIELDS,out)}
 base={"artifact_type":ARTIFACT_TYPE,"rule_version":RULE_VERSION,"selected_event_set_sha256":_setsha(selected),"full_classification_delta":4,"accepted_union":1542,"global_residual":3786,"post_admission_accepted_set_sha256":POST_ACCEPTED_SHA256,"post_admission_residual_set_sha256":POST_RESIDUAL_SHA256,"a0_policy_sha256":A0_POLICY_SHA256,"manual_raw_sha256":MANUAL_SHA256,"atomic_group_count":2,"bijection_asserted":False,"individual_relation_count":0,"korean_tax_invoice_count":0,"vat_basis":"a0_noncredit_customer_travel_expense","receipt_transport_auth":"forwarded_outer_auth_observed_unverified","receipt_transport_set_sha256":transport_sha,"capture_authority_caveat":True,"database_applied":False,**common,"contains_sensitive_raw_values":False,"files":{k:{"sha256":_sha(v),"rows":len(v.splitlines())-1} for k,v in payload.items()}}
 base["receipt_reference_commitment_sha256"]=_sha(_json(refs));base["package_set_sha256"]=_sha(_json(base)+b"".join(payload[k] for k in sorted(payload)));files={"manifest.json":_json(base),**payload};_privacy(files);return base,files
def _privacy(files):
 blob=b"".join(files.values()).decode();patterns=(r"\b793669\b",r"\b361924\b",r"184-86-02130",r"Gotogate",r"Booking No",r"source_locator",r"\b[0-9]{3}-[0-9]{3}-[0-9]{3}\b")
 if any(re.search(p,blob,re.I) for p in patterns):raise ValueError("r59_public_privacy_violation")

# Local publication contract uses R57's immutable dirfd primitives, never global patching.
PublicationDurabilityError=r57.PublicationDurabilityError;PublicationIntegrityError=r57.PublicationIntegrityError
def build_mytrip_airfare_atomic_admission(*args,output=None,**kwargs):
 manifest,files=_build(*args,**kwargs)
 if output is None:return {"manifest":manifest,"files":files}
 return _publish(manifest,files,output)
def _publish(manifest,files,output):
 out=output.resolve();
 if output.parent.is_symlink() or Path(REPOSITORY_ROOT).resolve() in (out,*out.parents):raise ValueError("r59_output_invalid")
 if os.path.lexists(out):raise FileExistsError(out)
 pfd=os.open(out.parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0));pid=r45._identity(os.fstat(pfd));stage=None;published=False
 try:
  if r45._identity(os.stat(out.parent,follow_symlinks=False))!=pid:raise ValueError("r59_parent_identity_changed")
  stage=Path(tempfile.mkdtemp(prefix=".r59-stage-",dir=f"/proc/self/fd/{pfd}"));os.chmod(stage,0o700)
  for n,d in files.items():
   fd=os.open(stage/n,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600)
   try:
    view=memoryview(d)
    while view:
     z=os.write(fd,view)
     if z<=0:raise OSError("r59_short_write_zero")
     view=view[z:]
    os.fsync(fd)
   finally:os.close(fd)
  dfd=os.open(stage,os.O_RDONLY|os.O_DIRECTORY);os.fsync(dfd);os.close(dfd);sfd=os.open(stage.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=pfd)
  try:
   if r57._capture_dirfd(sfd)!=files:raise ValueError("r59_stage_invalid")
  finally:os.close(sfd)
  if r45._identity(os.fstat(pfd))!=pid or r45._identity(os.stat(out.parent,follow_symlinks=False))!=pid:raise ValueError("r59_parent_identity_changed")
  r45._rename_noreplace_at(pfd,stage.name,out.name);stage=None;published=True;tfd=os.open(out.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=pfd);tid=r45._identity(os.fstat(tfd))
  try:
   if r57._capture_dirfd(tfd)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],pid,tid)
   try:os.fsync(pfd)
   except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"],pid,tid) from exc
   check=os.open(out.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=pfd)
   try:
    if r45._identity(os.fstat(check))!=tid or r45._identity(os.fstat(tfd))!=tid or r45._identity(os.stat(out.parent,follow_symlinks=False))!=pid or r57._capture_dirfd(tfd)!=files or r57._capture_dirfd(check)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],pid,tid)
   finally:os.close(check)
  finally:os.close(tfd)
 except (PublicationIntegrityError,PublicationDurabilityError):raise
 except (OSError,ValueError) as exc:
  if published:raise PublicationIntegrityError(out,manifest["package_set_sha256"],pid,locals().get("tid")) from exc
  raise
 finally:
  if stage is not None and stage.exists():shutil.rmtree(stage)
  os.close(pfd)
 return {"manifest":manifest,"output":str(out)}
def verify_mytrip_airfare_atomic_admission(directory,*args,**kwargs):
 m,e=_build(*args,**kwargs);before=r45._identity(os.stat(directory,follow_symlinks=False));dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  if r45._identity(os.fstat(dfd))!=before or r57._capture_dirfd(dfd)!=e or r45._identity(os.stat(directory,follow_symlinks=False))!=before:raise ValueError("r59_package_or_context_mismatch")
 finally:os.close(dfd)
 return m
def reconcile_publication(error,*args,**kwargs):
 if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r59_reconcile_state_invalid")
 m,e=_build(*args,**kwargs)
 pfd=os.open(error.parent_path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  if r45._identity(os.fstat(pfd))!=error.parent_identity or r45._identity(os.stat(error.parent_path,follow_symlinks=False))!=error.parent_identity:raise ValueError("r59_reconcile_parent_mismatch")
  tfd=os.open(error.target_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=pfd)
  try:
   if r45._identity(os.fstat(tfd))!=error.target_identity or r57._capture_dirfd(tfd)!=e:raise ValueError("r59_reconcile_target_mismatch")
   os.fsync(pfd);check=os.open(error.target_name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=pfd)
   try:
    if r45._identity(os.fstat(check))!=error.target_identity or r57._capture_dirfd(tfd)!=e or r57._capture_dirfd(check)!=e or r45._identity(os.stat(error.output,follow_symlinks=False))!=error.target_identity:raise ValueError("r59_reconcile_identity_changed")
   finally:os.close(check)
  finally:os.close(tfd)
 finally:os.close(pfd)
 if m["package_set_sha256"]!=error.package_set_sha256:raise ValueError("r59_reconcile_package_mismatch")
 return {"status":"valid","package_set_sha256":m["package_set_sha256"],"published":True,"durable":True}
