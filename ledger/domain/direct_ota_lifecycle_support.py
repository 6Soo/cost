"""R41 privacy-safe, support-only OTA lifecycle compiler."""
from __future__ import annotations
import csv,hashlib,io,json,os,re,shutil,stat,tempfile
from email.utils import parsedate_to_datetime
from datetime import date,datetime,timezone
from collections import Counter,defaultdict
from pathlib import Path
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT,_install_noreplace
from ledger.domain import direct_verified_booking_evidence as r26
from ledger.domain import direct_repository_booking_evidence as r27
from ledger.domain import direct_original_approval_relation as r40
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_narrow_service_classification as r37
from ledger.domain import direct_structured_lodging_evidence as r38
from ledger.domain.direct_lineage_annex import build_annex
from ledger.domain.direct_external_manual_evidence import _build_package as build25

ARTIFACT_TYPE="r41-ota-lifecycle-support-v1"
FILES=("manifest.json","components.csv","rejections.csv","existing_links.csv","new_proposals.csv")
MAIL_SHA="db258948ff2240b682d579422c4de3edbc5079e6425a8fd7c0a224f57c40cb11"
EXPECTED_EXISTING_EVENT_SET="7b897c564e987807291ca0a86dc4c314f8e75c0e76e8aac398dac9350497e610"
LEGACY_UTC_ROWS={
 ("19b37ccdfe62b244","e5e6512ca88dfa4c2ad08b1f9f2496ab717cf71e33efca41cf5a030a523b4d7d","2025-12-19T10:08:52.871317255","booking"),
 ("19b37c2c5d3a2e44","2e69153170fd1f8138150dd2e5a3ada14525f8b83bba6af5b694408e1f60c296","2025-12-19T09:57:50.081107162","booking"),
 ("19b18a9100f0c52d","39320b97e2973cc1047a40486bf59495613986a7001dfd8dcdfa2f0259d095f8","2025-12-13T09:01:32.13741219","booking"),
}
LEGACY_UTC_SET_SHA256="56494e89fca2b4e41338f33c6da8f83566ee15a443ee2406ccc738a42c61cf2d"
EXPECTED_UNRESOLVED_FACT_SET_SHA256="e36ca746b62270c08df27174ec61d887a262da972e575e54178648cfc0879d06"
QUARANTINED_ORPHAN_FACT_ROWS={
 ("TRIP-0100","19aee32b547c5e1a","4953e36b57a4b0a71a8f1d8a5375755634729e80c2c8b9c2969c32891780491b"),
 ("TRIP-0112","19cd62daa3871d9f","e9e7da8b0c3aa98f71cc325b6fbbb5f0a708497c1ee4b292e4272df2dd445e4d"),
}
QUARANTINED_ORPHAN_FACT_SET_SHA256="f6158b7165d2e9b226817c1eaddf5740b11b48b6ba0eba9968877b75f1579cd6"
INPUT_SHA={"booking_info.json":"1e456ecd17fc5d078141d9645d7179d24d912b0b857e710a5e1019d7d4047549","booking_periods_verified.json":"2c56525285c31f613708b76b7831fff1510ccb15ade8f97eb3d27adb3397955e","ota_event_links_verified.json":"2a3bc075b0d7596d5d99bef9dd7b9fda61a88428cf833e48042f55fbe6801b27","ota_mail_index.json":MAIL_SHA}
MAIL_FIELDS={"messageId","subject","sentAt","provider","bookingRefs","pnrs","travelDates","amounts","messageHash","redactionVersion"}
COMP_FIELDS=("component_id","message_set_sha256","message_count","provider_count","identity_node_count","lifecycle_tokens","conflict_status","edge_status","unresolved_reasons","authority_status","posting_status","confirmed_count","gate5_credit","applied")
REJ_FIELDS=("rejection_id","message_content_sha256","source_fact_set_sha256","reason","amount_only_singleton_messages","amount_singleton_message_set_sha256","candidate_cardinality","authority_status","posting_status")
LINK_FIELDS=("link_id","component_id","identity_node_id","message_set_sha256","source_fact_set_sha256","component_event_set_sha256","component_event_count","target_event_key_sha256","target_content_sha256","target_source_kind","target_source_key_sha256","target_source_sha256","target_payload_sha256","prior_union_status","disposition","authority_status","posting_status","confirmed_count","gate5_credit","applied")
NEW_FIELDS=("proposal_id","target_event_key_sha256","disposition")
EXPECTED={"mail_messages":1720,"identity_messages":416,"identity_nodes_all":454,"rich_messages":215,"rich_identity_nodes":263,"lifecycle_components":199,"duplicate_delivery_topology":16,"repository_fact_components":38,"current_linked_components":37,"repository_fact_current_unresolved":1,"no_repository_fact_components":161,"no_current_edge_components":162,"existing_relation_pairs":61,"linked_identity_nodes":54,"existing_bridge_events":40,"amount_only_singletons_rejected":61,"net_new_events":0}
def _sha(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def _json(x)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _setsha(xs)->str:return _sha("".join(f"{x}\n" for x in sorted(xs)).encode())
def _csv(fields,rows):
 s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(rows);return s.getvalue().encode()
def _strict(path):
 raw=path.read_bytes()
 def pairs(xs):
  out={}
  for k,v in xs:
   if k in out:raise ValueError("r41_json_duplicate_key")
   out[k]=v
  return out
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError("r41_json_nonfinite"))),raw
def _lifecycle(subject):
 text=str(subject).lower();found=[]
 if any(x in text for x in ("취소","cancel","환불","refund")):found.append("cancel")
 if any(x in text for x in ("변경","change","modify","수정")):found.append("change")
 if any(x in text for x in ("확정","confirm","예약 완료")):found.append("confirm")
 if any(x in text for x in ("결제","payment","paid")):found.append("payment")
 return tuple(found or ("unknown",))
def _validate_message(m):
 if not isinstance(m,dict) or set(m)!=MAIL_FIELDS:raise ValueError("r41_mail_schema_invalid")
 if not isinstance(m["messageId"],str) or not re.fullmatch(r"[0-9a-f]{16}",m["messageId"]):raise ValueError("r41_message_id_invalid")
 if not isinstance(m["messageHash"],str) or not re.fullmatch(r"[0-9a-f]{64}",m["messageHash"]):raise ValueError("r41_message_hash_invalid")
 if m["redactionVersion"]!="ota-allowlist-v1" or not isinstance(m["provider"],str) or not m["provider"]:raise ValueError("r41_mail_contract_invalid")
 if m["provider"] not in {"trip","booking","agoda","mytrip","travelrover"} or not isinstance(m["subject"],str) or not m["subject"] or not isinstance(m["sentAt"],str):raise ValueError("r41_mail_contract_invalid")
 try:
  iso=re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?",m["sentAt"],re.ASCII)
  if iso:
   dt=datetime.fromisoformat(m["sentAt"].replace("Z","+00:00"))
   # Exactly three pinned legacy rows are UTC under ota-allowlist-v1.
   if dt.tzinfo is None:
    if (m["messageId"],m["messageHash"],m["sentAt"],m["provider"]) not in LEGACY_UTC_ROWS:raise ValueError("timezone")
    dt=dt.replace(tzinfo=timezone.utc)
  else:dt=parsedate_to_datetime(m["sentAt"])
  if dt.tzinfo is None or dt.utcoffset() is None:raise ValueError("timezone")
 except (TypeError,ValueError,OverflowError) as exc:raise ValueError("r41_sent_at_invalid") from exc
 for field in ("bookingRefs","pnrs","travelDates","amounts"):
  if not isinstance(m[field],list):raise ValueError("r41_mail_field_type_invalid")
 if any(not isinstance(x,str) or not x or x.strip()!=x for x in m["bookingRefs"]+m["pnrs"]):raise ValueError("r41_identity_invalid")
 if any(isinstance(x,bool) or not isinstance(x,int) for x in m["amounts"]):raise ValueError("r41_amount_type_invalid")
 if any(abs(x)>10**15 for x in m["amounts"]):raise ValueError("r41_amount_range_invalid")
 for token in m["travelDates"]:
  if not isinstance(token,str) or not re.fullmatch(r"[0-9]{4}",token,re.ASCII):raise ValueError("r41_travel_date_invalid")
  try:date(2000,int(token[:2]),int(token[2:]))
  except ValueError as exc:raise ValueError("r41_travel_date_invalid") from exc
 if len(m["bookingRefs"])!=len(set(m["bookingRefs"])) or len(m["pnrs"])!=len(set(m["pnrs"])):raise ValueError("r41_identity_duplicate")
 ref_patterns={"trip":r"[0-9]{16}","booking":r"[0-9]{10}","agoda":r"(?:[0-9]{10}|[0-9]{24})","mytrip":r"[0-9]{4}-[0-9]{3}-[0-9]{3}","travelrover":r"(?!)"}
 if any(re.fullmatch(ref_patterns[m["provider"]],x,re.ASCII) is None for x in m["bookingRefs"]):raise ValueError("r41_booking_ref_invalid")
 if any(re.fullmatch(r"[A-Z0-9]{6,8}",x,re.ASCII) is None for x in m["pnrs"]):raise ValueError("r41_pnr_invalid")

def _resolve_fact_node(value,kind,provider,nodes_by_kind_value):
 candidates=nodes_by_kind_value.get((kind,value),set())
 if provider is not None:candidates={node for node in candidates if node[0]==provider}
 return next(iter(candidates)) if len(candidates)==1 else None

def _validate_repository_facts(booking,periods,ota,messages=None,source_uids=None,allowed_orphan_fact_rows=frozenset()):
 def valid_period(value,prefixed=False,empty=False):
  if not isinstance(value,str) or (not value and not empty):return False
  if not value:return True
  if prefixed:
   match=re.fullmatch(r"(숙박|렌트)_([0-9]{4}(?:_[0-9]{4})?)",value)
   if match is None:return False
   text=match.group(2)
  else:text=value
  tokens=text.split("_")
  if len(tokens) not in {1,2}:return False
  try:
   for token in tokens:
    if re.fullmatch(r"[0-9]{4}",token,re.ASCII) is None:return False
    date(2000,int(token[:2]),int(token[2:]))
  except ValueError:return False
  return True
 if not isinstance(booking,dict) or not isinstance(periods,dict) or not isinstance(ota,dict):raise ValueError("r41_fact_root_invalid")
 for ref,fact in booking.items():
  if re.fullmatch(r"[0-9]{10,16}",ref,re.ASCII) is None or not isinstance(fact,dict) or set(fact)!={"label","period"} or not isinstance(fact["label"],str) or not fact["label"] or not valid_period(fact["period"],prefixed=True):raise ValueError("r41_booking_fact_invalid")
 for ref,fact in periods.items():
  if re.fullmatch(r"[0-9]{8,24}",ref,re.ASCII) is None or not isinstance(fact,dict) or set(fact)!={"category","period","source"} or fact.get("category") not in {"숙박","렌트"} or not isinstance(fact["source"],str) or not fact["source"] or not valid_period(fact["period"]):raise ValueError("r41_period_fact_invalid")
 allowed={"booking_id","category","period","hotel","guest","card4","foreign_amount","currency","verification_source","reference_code","paid_amount","amount_verification","linked_uid","link_type","route","passenger","passenger_count","gross_amount","payment_discount","rooms","nights","hotel_pay_amount","hotel_pay_currency","external_source_id","destination","pnr","e_ticket_numbers","source_message_id","order_id","match_score","match_reasons"}
 ints={"foreign_amount","paid_amount","passenger_count","gross_amount","payment_discount","rooms","nights","hotel_pay_amount","match_score"};lists={"e_ticket_numbers","match_reasons"}
 for uid,fact in ota.items():
  if not isinstance(uid,str) or not re.fullmatch(r"[A-Z]+-[0-9]{4}",uid,re.ASCII) or not isinstance(fact,dict) or not {"category","period"}<=set(fact) or not set(fact)<=allowed or fact["category"] not in {"숙박","항공"}:raise ValueError("r41_ota_fact_invalid")
  for k,v in fact.items():
   if k in ints:
    if isinstance(v,bool) or not isinstance(v,int):raise ValueError("r41_ota_fact_type_invalid")
   elif k in lists:
    if not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v):raise ValueError("r41_ota_fact_type_invalid")
   elif not isinstance(v,str) or (not v and k!="period"):raise ValueError("r41_ota_fact_type_invalid")
  if "card4" in fact and re.fullmatch(r"[0-9]{4}",fact["card4"],re.ASCII) is None:raise ValueError("r41_ota_card4_invalid")
  if "currency" in fact and re.fullmatch(r"[A-Z]{3}",fact["currency"],re.ASCII) is None:raise ValueError("r41_ota_currency_invalid")
  if "source_message_id" in fact and re.fullmatch(r"[0-9a-f]{16}",fact["source_message_id"],re.ASCII) is None:raise ValueError("r41_ota_message_id_invalid")
  if "source_message_id" in fact and (messages is None or fact["source_message_id"] not in messages):
   orphan=(uid,fact["source_message_id"],_sha(_json({"uid":uid,**fact})))
   if orphan not in allowed_orphan_fact_rows:raise ValueError("r41_ota_message_reference_missing")
  if not valid_period(fact["period"],empty=True):raise ValueError("r41_ota_period_invalid")
  provider=None
  if messages and fact.get("source_message_id") in messages:provider=messages[fact["source_message_id"]]["provider"]
  source=str(fact.get("verification_source") or "").lower()
  if provider is None:
   for candidate,token in (("agoda","agoda"),("booking","booking.com"),("mytrip","mytrip"),("trip","trip.com"),("travelrover","travelrover")):
    if token in source:provider=candidate;break
  if "booking_id" in fact:
   patterns={"trip":r"[0-9]{16}","booking":r"[0-9]{10}","agoda":r"[0-9]{10}",None:r"(?:[0-9]{10}|[0-9]{16})"}
   if re.fullmatch(patterns.get(provider,r"(?:[0-9]{10}|[0-9]{16})"),fact["booking_id"],re.ASCII) is None:raise ValueError("r41_ota_booking_id_invalid")
  if "order_id" in fact and (provider not in {None,"mytrip"} or re.fullmatch(r"[0-9]{4}-[0-9]{3}-[0-9]{3}",fact["order_id"],re.ASCII) is None):raise ValueError("r41_ota_order_id_invalid")
  if "pnr" in fact and re.fullmatch(r"[A-Z0-9]{6}",fact["pnr"],re.ASCII) is None:raise ValueError("r41_ota_pnr_invalid")
  if "reference_code" in fact and re.fullmatch(r"(?:[a-z0-9]{8}|[A-Z0-9]{16}|[0-9]{19})",fact["reference_code"],re.ASCII) is None:raise ValueError("r41_ota_reference_code_invalid")
  if "linked_uid" in fact:
   if re.fullmatch(r"[A-Z]+-[0-9]{4}",fact["linked_uid"],re.ASCII) is None:raise ValueError("r41_ota_linked_uid_invalid")
   if source_uids is None or fact["linked_uid"] not in source_uids:raise ValueError("r41_ota_linked_uid_missing")
  if "external_source_id" in fact and re.fullmatch(r"[a-z_]+:[0-9]{4}:[0-9]+",fact["external_source_id"],re.ASCII) is None:raise ValueError("r41_ota_external_source_invalid")
  if set(fact)&{"vat","vat_tag","tax_type"}:raise ValueError("r41_vat_fact_unauthorized")

class PublicationDurabilityError(OSError):
 def __init__(self,output,package):super().__init__("r41_published_durability_unknown");self.output=output;self.package_set_sha256=package;self.published=True
class PublicationIntegrityError(OSError):
 def __init__(self,output,package):super().__init__("r41_published_integrity_invalid");self.output=output;self.package_set_sha256=package;self.published=True
def _opaque_groups(groups,messages):
 buckets=defaultdict(list)
 for key,mids in groups.items():buckets[(key[0],key[1],tuple(sorted(messages[x]["messageHash"] for x in mids)))].append(key)
 ids={}
 for signature,keys in sorted(buckets.items()):
  for n,key in enumerate(sorted(keys)):ids[key]=_sha(_json({"namespace":signature[:2],"message_hashes":signature[2],"ordinal":n}))
 return ids

def _build(ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 if ledger_dir.resolve()!=(REPOSITORY_ROOT/"ledger").resolve():raise ValueError("r41_noncanonical_ledger")
 values={};raws={};stats={}
 for name,digest in INPUT_SHA.items():
  path=ledger_dir/"data"/name
  if path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1:raise ValueError("r41_input_file_invalid")
  stats[name]=path.stat();values[name],raws[name]=_strict(path)
  if _sha(raws[name])!=digest:raise ValueError(f"r41_input_hash_invalid:{name}")
 mail=values["ota_mail_index.json"]
 if not isinstance(mail,dict) or set(mail)!={"generatedAt","records"} or not isinstance(mail["records"],list):raise ValueError("r41_mail_root_invalid")
 messages={};hash_owner={}
 for m in mail["records"]:
  _validate_message(m);mid=m["messageId"]
  if mid in messages:raise ValueError("r41_duplicate_message_id")
  if m["messageHash"] in hash_owner and hash_owner[m["messageHash"]]!=mid:raise ValueError("r41_message_hash_collision")
  messages[mid]=m;hash_owner[m["messageHash"]]=mid
 legacy_live={(m["messageId"],m["messageHash"],m["sentAt"],m["provider"]) for m in messages.values() if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?",m["sentAt"],re.ASCII)}
 if legacy_live!=LEGACY_UTC_ROWS or _sha(_json(sorted(legacy_live)))!=LEGACY_UTC_SET_SHA256:raise ValueError("r41_legacy_utc_contract_invalid")
 groups=defaultdict(set);rich_messages=set()
 for mid,m in messages.items():
  identities=[("ref",x) for x in m["bookingRefs"]]+[("pnr",x) for x in m["pnrs"]]
  for kind,value in identities:groups[(m["provider"],kind,value)].add(mid)
  if identities and m["amounts"] and m["travelDates"]:rich_messages.add(mid)
 rich_groups={k for k,v in groups.items() if v&rich_messages};opaque=_opaque_groups(groups,messages)
 # Rich-message connected components; identity equality is exact and provider/type scoped.
 parent={m:m for m in rich_messages}
 def find(x):
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 def union(a,b):
  a,b=find(a),find(b)
  if a!=b:parent[b]=a
 for k,mids in groups.items():
  xs=sorted(set(mids)&rich_messages)
  for x in xs[1:]:union(xs[0],x)
 comps=defaultdict(set)
 for mid in rich_messages:comps[find(mid)].add(mid)
 component_rows=[]
 for mids in sorted(comps.values(),key=lambda x:sorted(x)):
  states=sorted({s for mid in mids for s in _lifecycle(messages[mid]["subject"])});conflict=bool({"cancel","change"}&set(states))
  reasons=["currency_missing","amount_roles_untyped","card_identity_missing","date_roles_untyped_or_year_missing","product_untyped","lifecycle_state_unattested"]
  if len(mids)>1:reasons.append("multiple_messages_same_identity")
  if conflict:reasons.append("lifecycle_conflict")
  mhashes=[messages[x]["messageHash"] for x in mids];nodes=sum(bool(set(v)&mids) for v in groups.values())
  component_rows.append({"component_id":_sha(_json({"messages":sorted(mhashes)})),"message_set_sha256":_setsha(mhashes),"message_count":len(mids),"provider_count":len({messages[x]["provider"] for x in mids}),"identity_node_count":nodes,"lifecycle_tokens":json.dumps(states,separators=(",",":")),"conflict_status":"deferred" if conflict else "unattested","edge_status":"support_only","unresolved_reasons":json.dumps(sorted(reasons),separators=(",",":")),"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False})
 # Rebuild the pinned R26/R27 chains and join only their exact fact identities to graph nodes.
 m26,f26=r26._build(booking_periods=ledger_dir/"data/booking_periods_verified.json",ota_mail=ledger_dir/"data/ota_mail_index.json",manual_csv=r40.MANUAL,ledger_dir=ledger_dir)
 m27,f27=r27._build(booking_info=ledger_dir/"data/booking_info.json",ota_links=ledger_dir/"data/ota_event_links_verified.json",manual_csv=r40.MANUAL,ledger_dir=ledger_dir)
 c26=list(csv.DictReader(io.StringIO(f26["coverage.csv"].decode())));c27=list(csv.DictReader(io.StringIO(f27["coverage.csv"].decode())))
 rel26=list(csv.DictReader(io.StringIO(f26["relations.csv"].decode())));rel27=list(csv.DictReader(io.StringIO(f27["relations.csv"].decode())))
 with tempfile.TemporaryDirectory(prefix="r41-current-") as td:
  current=r36._context(ledger_dir,Path(td));db=current["db"]
  payload_by_source={row[0]:json.loads(row[1]) for row in db.execute("SELECT source_key,payload_json FROM direct_source_records")};db.close()
 content={x["direct_event_key"]:x for x in current["events"]}
 if (current["current_event_set_sha256"],current["decision_scope_sha256"])!=(r40.EXPECTED_CURRENT,r40.EXPECTED_SCOPE):raise ValueError("r41_current_context_invalid")
 ota=values["ota_event_links_verified.json"];booking=values["booking_info.json"];periods=values["booking_periods_verified.json"]
 source_uids={row["uid"] for row in csv.DictReader(io.StringIO((ledger_dir/"data/classified_v14.csv").read_text(encoding="utf-8-sig")))}
 _validate_repository_facts(booking,periods,ota,messages,source_uids,QUARANTINED_ORPHAN_FACT_ROWS)
 orphan_live={(uid,fact["source_message_id"],_sha(_json({"uid":uid,**fact}))) for uid,fact in ota.items() if "source_message_id" in fact and fact["source_message_id"] not in messages}
 if orphan_live!=QUARANTINED_ORPHAN_FACT_ROWS or _sha(_json(sorted(orphan_live)))!=QUARANTINED_ORPHAN_FACT_SET_SHA256:raise ValueError("r41_orphan_message_reference_drift")
 nodes_by_kind_value=defaultdict(set)
 for node in rich_groups:nodes_by_kind_value[(node[1],node[2])].add(node)
 def fact_provider(fact,field):
  mid=fact.get("source_message_id") if isinstance(fact,dict) else None
  if mid in messages:return messages[mid]["provider"]
  source=str(fact.get("verification_source") or "").lower() if isinstance(fact,dict) else ""
  for provider,token in (("agoda","agoda"),("booking","booking.com"),("mytrip","mytrip"),("trip","trip.com"),("travelrover","travelrover")):
   if token in source:return provider
  return "mytrip" if field=="order_id" else None
 identity_events=defaultdict(set);identity_facts=defaultdict(set);fact_nodes=set();namespace_ambiguous=set()
 for row in c27:
  if row["source_tier"]=="booking_info":fields=[("ref",row["booking_reference"],"trip" if len(row["booking_reference"])==16 else None)]
  else:
   fact=ota[row["source_uid"]];fields=[("pnr" if k in {"pnr","reference_code"} else "ref",fact[k],fact_provider(fact,k)) for k in ("booking_id","order_id","pnr","reference_code") if isinstance(fact.get(k),str) and fact[k]]
  for kind,identity,provider in fields:
   node=_resolve_fact_node(identity,kind,provider,nodes_by_kind_value)
   if node is None:
    if len(nodes_by_kind_value.get((kind,identity),set()))>1:namespace_ambiguous.add((kind,identity))
    continue
   fact_nodes.add(node);identity_events[node].add(row["direct_event_key"]);identity_facts[node].add(row["source_row_sha256"])
 for fact in ota.values():
  if isinstance(fact,dict):
   for k in ("booking_id","order_id","pnr","reference_code"):
    identity=fact.get(k)
    if not isinstance(identity,str) or not identity:continue
    kind="pnr" if k in {"pnr","reference_code"} else "ref";node=_resolve_fact_node(identity,kind,fact_provider(fact,k),nodes_by_kind_value)
    if node is not None:fact_nodes.add(node)
    elif len(nodes_by_kind_value.get((kind,identity),set()))>1:namespace_ambiguous.add((kind,identity))
 for row in csv.DictReader(io.StringIO(f27["ambiguities.csv"].decode())):
  if row["source_tier"]=="ota_event_links" and row["source_uid"] in ota:
   fact=ota[row["source_uid"]]
   for k in ("booking_id","order_id","pnr","reference_code"):
    identity=fact.get(k)
    if not isinstance(identity,str) or not identity:continue
    kind="pnr" if k in {"pnr","reference_code"} else "ref";resolved_node=_resolve_fact_node(identity,kind,fact_provider(fact,k),nodes_by_kind_value)
    if resolved_node is not None:identity_facts[resolved_node].add(row["source_row_sha256"])
 target_ref=r26.TARGET_REF
 for row in c26:
  if row["booking_reference"]==target_ref:
   node=_resolve_fact_node(target_ref,"ref","trip",nodes_by_kind_value)
   if node is None:raise ValueError("r41_r26_fact_namespace_ambiguous")
   fact_nodes.add(node);identity_events[node].add(row["direct_event_key"])
 for row in rel26:
  identity_facts[node].add(row["booking_fact_row_sha256"])
 for identity in set(booking)|set(periods):
  resolved_node=_resolve_fact_node(identity,"ref","trip" if identity in booking and len(identity)==16 else None,nodes_by_kind_value)
  if resolved_node is not None:fact_nodes.add(resolved_node)
  elif len(nodes_by_kind_value.get(("ref",identity),set()))>1:namespace_ambiguous.add(("ref",identity))
 root_nodes=defaultdict(set)
 for node,mids in groups.items():
  rich_mids=set(mids)&rich_messages
  if rich_mids:root_nodes[find(next(iter(rich_mids)))].add(node)
 root_events={root:set().union(*(identity_events.get(node,set()) for node in nodes)) for root,nodes in root_nodes.items()}
 linked_roots={root for root,events_ in root_events.items() if events_};fact_roots={root for root,nodes in root_nodes.items() if any(node in fact_nodes for node in nodes)}
 unresolved_fact_roots=fact_roots-linked_roots;no_fact_roots=set(comps)-fact_roots
 existing=[]
 for root in sorted(linked_roots):
  mids=comps[root];mset=_setsha(messages[mid]["messageHash"] for mid in mids);events_=root_events[root];event_set=_setsha(events_);component_id=_sha(_json({"messages":sorted(messages[x]["messageHash"] for x in mids)}))
  for node in sorted(root_nodes[root]):
   for event in sorted(identity_events.get(node,set())):
    if event not in content:raise ValueError("r41_live_event_content_missing")
    facts=_setsha(identity_facts[node]);target=content[event];payload=payload_by_source[target["current_source_key"]]
    base_link={"component_id":component_id,"identity_node_id":opaque[node],"message_set_sha256":mset,"source_fact_set_sha256":facts,"component_event_set_sha256":event_set,"component_event_count":len(events_),"target_event_key_sha256":_sha(event.encode()),"target_content_sha256":target["current_event_sha256"],"target_source_kind":target["current_source_kind"],"target_source_key_sha256":_sha(target["current_source_key"].encode()),"target_source_sha256":target["current_source_sha256"],"target_payload_sha256":_sha(_json(payload)),"prior_union_status":"accepted_r26_r27","disposition":"existing_support_no_new_edge","authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False}
    existing.append({"link_id":_sha(_json(base_link)),**base_link})
 all_linked_events=set().union(*(root_events[root] for root in linked_roots));exact_event_set=_setsha(all_linked_events)
 if exact_event_set!=EXPECTED_EXISTING_EVENT_SET:raise ValueError("r41_existing_event_set_drift")
 bridge_partition=(len(linked_roots),len(unresolved_fact_roots),len(no_fact_roots),len(existing),len(all_linked_events))
 if bridge_partition!=(37,1,161,61,40):raise ValueError(f"r41_bridge_partition_invalid:{bridge_partition}")
 # Amount candidates are diagnostics only: they never enter identity_events.
 source_message_ids={str(v.get("source_message_id")) for v in ota.values() if isinstance(v,dict) and v.get("source_message_id")}
 curated={mid for mid in rich_messages if mid in source_message_ids or set(messages[mid]["bookingRefs"])&set(booking) or set(messages[mid]["bookingRefs"])&set(periods)}
 if len(curated)!=38:raise ValueError("r41_curated_message_census_invalid")
 amount_index=defaultdict(set)
 for event,target in content.items():amount_index[abs(int(target["signed_amount_krw"]))].add(event)
 singleton_messages=set()
 for mid in rich_messages-curated:
  candidates=set().union(*(amount_index.get(abs(value),set()) for value in messages[mid]["amounts"]))
  if len(candidates)==1:singleton_messages.add(mid)
 if len(singleton_messages)!=61:raise ValueError("r41_amount_singleton_census_invalid")
 amount_singleton_set=_setsha(messages[mid]["messageHash"] for mid in singleton_messages)
 # Independently derive typed support from the exact source facts.
 service_events=set();period_events=set()
 for row in c27:
  fact=booking[row["booking_reference"]] if row["source_tier"]=="booking_info" else ota[row["source_uid"]]
  if str(fact.get("label") or fact.get("category") or "").strip():service_events.add(row["direct_event_key"])
  if str(fact.get("period") or "").strip():period_events.add(row["direct_event_key"])
 for row in c26:
  if row["booking_reference"]==target_ref:
   service_events.add(row["direct_event_key"]);period_events.add(row["direct_event_key"])
 tax_fields={k for fact in list(booking.values())+list(periods.values())+list(ota.values()) for k in fact if k in {"vat","vat_tag","tax_type","tax_authority"}}
 if tax_fields:raise ValueError("r41_vat_fact_unauthorized")
 vat_events=set()
 if (len(service_events&all_linked_events),len(period_events&all_linked_events),len(vat_events&all_linked_events))!=(40,37,0):raise ValueError("r41_typed_support_census_invalid")
 # Rebuild the full accepted union exactly as R40 does, then subtract rather than assert an empty literal.
 r23_live=build_annex(ledger_dir=ledger_dir);m25,f25=build25(r40.MANUAL,ledger_dir);m36,f36=r36._build(ledger_dir,r36.DEFAULT_MANUAL_CSV);m38,f38=r38._build(ledger_dir)
 p25=list(csv.DictReader(io.StringIO(f25["proposals.csv"].decode())));e25=list(csv.DictReader(io.StringIO(f25["evidence_sets.csv"].decode())))
 prior={str(x["direct_event_key"]) for x in r23_live["package"]["envelopes"] if x.get("historical_uid")}|{x["direct_event_key"] for x in p25}|{x["direct_event_key"] for x in e25 if x["evidence_tier"] in {"clean_110","typed_v14_65","portal_1"}}|{x[2] for x in r26.EXPECTED_RELATIONS}|{x[3] for x in r27.EXPECTED_BOOKING_NEW}|{x[3] for x in r27.EXPECTED_OTA_NEW}
 full36={x["direct_event_key"] for x in csv.DictReader(io.StringIO(f36["classifications.csv"].decode()))};accepted=prior|full36|set(r37.EXPECTED_EVENTS)|set(r38.EXPECTED_EVENTS);residual=set(content)-accepted;new_events=all_linked_events-accepted
 if (len(accepted),len(residual),_setsha(residual),new_events)!=(1528,3800,r40.EXPECTED_RESIDUAL,set()):raise ValueError("r41_accepted_union_invalid")
 m40,_=r40._build(ledger_dir)
 rejections=[]
 for root in sorted(unresolved_fact_roots|no_fact_roots):
  mids=comps[root]
  mhashes=[messages[x]["messageHash"] for x in mids];content_set=_setsha(mhashes)
  reason="repository_fact_current_identity_unresolved" if root in unresolved_fact_roots else "card_identity_observation_missing"
  single=sorted(set(mids)&singleton_messages);single_set=_setsha(messages[x]["messageHash"] for x in single)
  fact_set=_setsha({f for node in root_nodes[root] for f in identity_facts.get(node,set())})
  if root in unresolved_fact_roots and fact_set!=EXPECTED_UNRESOLVED_FACT_SET_SHA256:raise ValueError("r41_unresolved_fact_set_drift")
  rejections.append({"rejection_id":_sha(_json({"message_set":content_set,"fact_set":fact_set,"reason":reason})),"message_content_sha256":content_set,"source_fact_set_sha256":fact_set,"reason":reason,"amount_only_singleton_messages":len(single),"amount_singleton_message_set_sha256":single_set,"candidate_cardinality":"untrusted_untyped_amount","authority_status":"unattested","posting_status":"blocked"})
 identity_messages=sum(bool(m["bookingRefs"] or m["pnrs"]) for m in messages.values())
 actual={"mail_messages":len(messages),"identity_messages":identity_messages,"identity_nodes_all":len(groups),"rich_messages":len(rich_messages),"rich_identity_nodes":len(rich_groups),"lifecycle_components":len(comps),"duplicate_delivery_topology":len(rich_messages)-len(comps),"repository_fact_components":len(fact_roots),"current_linked_components":len(linked_roots),"repository_fact_current_unresolved":len(unresolved_fact_roots),"no_repository_fact_components":len(no_fact_roots),"no_current_edge_components":len(comps)-len(linked_roots),"existing_relation_pairs":len(existing),"linked_identity_nodes":sum(bool(identity_events.get(node)) for nodes in root_nodes.values() for node in nodes),"existing_bridge_events":len(all_linked_events),"amount_only_singletons_rejected":len(singleton_messages),"net_new_events":len(new_events)}
 if actual!=EXPECTED:raise ValueError(f"r41_live_census_invalid:{actual}")
 component_bytes=_csv(COMP_FIELDS,component_rows);reject_bytes=_csv(REJ_FIELDS,rejections);link_bytes=_csv(LINK_FIELDS,existing);new_bytes=_csv(NEW_FIELDS,[])
 rule=_sha(_json({"artifact":ARTIFACT_TYPE,"mail_fields":sorted(MAIL_FIELDS),"legacy_utc_set_sha256":LEGACY_UTC_SET_SHA256,"quarantined_orphan_fact_set_sha256":QUARANTINED_ORPHAN_FACT_SET_SHA256,"exact_namespace":["provider","identity_type","exact_value"],"amount_edge_forbidden":True,"privacy":"no-raw-or-unsalted-identity-digest","expected":EXPECTED,"files":FILES}))
 base={"format_version":1,"artifact_type":ARTIFACT_TYPE,"rule_contract_sha256":rule,"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"applied":False,"contains_sensitive_raw_values":False,"full_classification_delta":len(new_events),"vat_proposals":len(vat_events&all_linked_events),"full_classifications":0,"service_support_existing":len(service_events&all_linked_events),"period_support_existing":len(period_events&all_linked_events),"vat_support_existing":len(vat_events&all_linked_events),"accepted_union":len(accepted),"accepted_union_set_sha256":_setsha(accepted),"incomplete_residual":len(residual),"residual_set_sha256":_setsha(residual),"existing_event_set_sha256":exact_event_set,"new_event_set_sha256":_setsha(new_events),"amount_singleton_message_set_sha256":amount_singleton_set,"current_event_set_sha256":r40.EXPECTED_CURRENT,"decision_scope_sha256":r40.EXPECTED_SCOPE,"counts":actual,"reason_census":{"identity_missing":len(messages)-identity_messages,"identity_present_but_not_rich":identity_messages-len(rich_messages),"rich_currency_missing":len(rich_messages),"rich_typed_amount_missing":len(rich_messages),"rich_card_identity_missing":len(rich_messages),"no_repository_fact":len(no_fact_roots),"repository_fact_current_identity_unresolved":len(unresolved_fact_roots),"fact_identity_namespace_ambiguous":len(namespace_ambiguous),"amount_only_singleton_forbidden":len(singleton_messages)},"input_files_sha256":dict(sorted(INPUT_SHA.items())),"upstream":{"range":"R23-R40","r23_rule":r23_live["manifest"]["rule_contract_sha256"],"r23_package":r23_live["manifest"]["envelope_set_sha256"],"r25_rule":m25["rule_contract_sha256"],"r25_package":m25["package_set_sha256"],"r26_rule":m26["rule_contract_sha256"],"r26_package":m26["package_set_sha256"],"r27_rule":m27["rule_contract_sha256"],"r27_package":m27["package_set_sha256"],"r36_rule":m36["rule_contract_sha256"],"r36_package":m36["package_set_sha256"],"r37_rule":m38["r37_rule_contract_sha256"],"r37_package":m38["r37_package_set_sha256"],"r38_rule":m38["rule_contract_sha256"],"r38_package":m38["package_set_sha256"],"r40_relation_set":r40.EXPECTED_RELATIONS,"r40_residual_set":r40.EXPECTED_RESIDUAL},"files":{"components.csv":{"sha256":_sha(component_bytes),"rows":len(component_rows)},"rejections.csv":{"sha256":_sha(reject_bytes),"rows":len(rejections)},"existing_links.csv":{"sha256":_sha(link_bytes),"rows":len(existing)},"new_proposals.csv":{"sha256":_sha(new_bytes),"rows":0}}}
 base["legacy_utc_set_sha256"]=LEGACY_UTC_SET_SHA256
 base["quarantined_orphan_fact_count"]=len(orphan_live)
 base["quarantined_orphan_fact_set_sha256"]=QUARANTINED_ORPHAN_FACT_SET_SHA256
 base["upstream"].update({"r40_rule":m40["rule_contract_sha256"],"r40_package":m40["package_set_sha256"]})
 package=_sha(_json(base)+component_bytes+reject_bytes+link_bytes+new_bytes);manifest={**base,"package_set_sha256":package};files={"manifest.json":_json(manifest),"components.csv":component_bytes,"rejections.csv":reject_bytes,"existing_links.csv":link_bytes,"new_proposals.csv":new_bytes}
 for name in INPUT_SHA:
  after=(ledger_dir/"data"/name).stat()
  before=stats[name]
  if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or (ledger_dir/"data"/name).read_bytes()!=raws[name]:raise ValueError("r41_input_changed_during_build")
 return manifest,files

def build_ota_lifecycle_support(output:Path|None=None,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 manifest,files=_build(ledger_dir)
 if output is not None:
  if output.parent.is_symlink():raise ValueError("r41_output_parent_symlink")
  parent=output.parent.resolve(strict=True)
  try:parent.relative_to(REPOSITORY_ROOT.resolve());raise ValueError("r41_output_inside_repository")
  except ValueError as exc:
   if str(exc)=="r41_output_inside_repository":raise
  if os.path.lexists(output):raise FileExistsError("r41_output_exists")
  stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=parent));os.chmod(stage,0o700);published=False
  try:
   for name,data in files.items():
    fd=os.open(stage/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL | getattr(os, "O_BINARY", 0),0o600)
    try:
     view=memoryview(data)
     while view:view=view[os.write(fd,view):]
     os.fsync(fd)
    finally:os.close(fd)
   fd=os.open(stage,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
   try:os.fsync(fd)
   finally:os.close(fd)
   if r40._capture_package(stage,FILES)!=files:raise ValueError("r41_stage_invalid")
   _install_noreplace(stage,output);published=True
   try:
    if r40._capture_package(output,FILES)!=files:raise ValueError("r41_post_install_mismatch")
   except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"]) from exc
   try:fd=os.open(parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
   except OSError as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
   try:
    try:os.fsync(fd)
    except OSError as exc:raise PublicationDurabilityError(output,manifest["package_set_sha256"]) from exc
   finally:os.close(fd)
   try:
    if r40._capture_package(output,FILES)!=files:raise ValueError("r41_post_fsync_mismatch")
   except Exception as exc:raise PublicationIntegrityError(output,manifest["package_set_sha256"]) from exc
  except Exception:
   if not published and stage.exists():shutil.rmtree(stage)
   raise
 return {"manifest":manifest,"output":None if output is None else str(output)}
def verify_ota_lifecycle_support(directory:Path,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 actual=r40._capture_package(directory,FILES);manifest,expected=_build(ledger_dir)
 if actual!=expected:raise ValueError("r41_package_semantics_mismatch")
 return {"status":"valid","package_set_sha256":manifest["package_set_sha256"],"net_new_events":0}
def reconcile_ota_lifecycle_publication(error,ledger_dir:Path=REPOSITORY_ROOT/"ledger"):
 if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):raise ValueError("r41_reconcile_state_invalid")
 first=verify_ota_lifecycle_support(error.output,ledger_dir)
 try:fd=os.open(error.output.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
 except OSError as exc:raise PublicationDurabilityError(error.output,error.package_set_sha256) from exc
 try:
  try:os.fsync(fd)
  except OSError as exc:raise PublicationDurabilityError(error.output,error.package_set_sha256) from exc
 finally:os.close(fd)
 second=verify_ota_lifecycle_support(error.output,ledger_dir)
 if first!=second or first["package_set_sha256"]!=error.package_set_sha256:raise ValueError("r41_reconcile_package_mismatch")
 return {**second,"published":True,"durable":True}
