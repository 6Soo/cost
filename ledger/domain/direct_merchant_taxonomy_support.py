"""R34 non-authoritative merchant taxonomy support (external artifact only)."""
from __future__ import annotations

import argparse, csv, hashlib, io, json, os, re, shutil, stat, tempfile, unicodedata
from collections import defaultdict
from pathlib import Path

from ledger.domain.direct_external_manual_evidence import _build_package as _build_r25
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _build_temp_db, _install_noreplace, build_annex
from ledger.domain.direct_verified_booking_evidence import EXPECTED_RELATIONS as R26_RELATIONS
from ledger.domain.direct_repository_booking_evidence import EXPECTED_BOOKING_NEW, EXPECTED_OTA_NEW

ARTIFACT_TYPE = "r34-merchant-taxonomy-support-v1"
RULE_VERSION = "r34-r23-high-complete-purchase-exact-taxonomy-min3-v1"
SOL_REVIEW_SHA256 = "c04369c57561cdfa14ace40287047cee2bcef45afc0f8afe7965adce96f097c9"
FABLE_CROSS_V2_SHA256 = "532d94e4ffbe6957635ffc7653bfd4ec5ffa4060437b8b253b973c0c94546cbe"
EXPECTED_EVENT_SET_SHA256 = "4fd5c0aa99539cf5913ed0584ee979462a692f5dc958230dc3d87c86a96584c9"
EXPECTED_CURRENT_EVENT_SET_SHA256 = "0f5ca97c971125327e2bdc5aaa0f6505872c5a03c50cf4886d29753b4c1a8c7e"
EXPECTED_DECISION_SCOPE_SHA256 = "22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"
EXPECTED_COMPONENT_SET_SHA256 = {
    "r23":"30bac59b84108f39bcc819a9b4034b62435bba66005c55ac9ce2ff6696a48a5f",
    "r25":"257d29234170071837408cacff1757e935675078d4aa05126c6763442e53e738",
    "r26":"ab105d44d26a098c211bc2f97807cc0dde079455c254ec2d5d2670d687b14fdc",
    "r27":"ecc733de2c01c7fb53c2d84beda746e1e86ba53ff298b01d43633e7f7c51db37",
    "prior":"426b4ec226f804dcfb2f87c8b6f1f8915352169ef401e241945f8c52ee75fc8c",
}
EXPECTED_SEMANTIC_SET_SHA256 = "f7dee10c5154ab77f423ff622b291c334beee234e93c04bea238c3d88a7dce1b"
EXPECTED_MANUAL_SHA256 = "2c6d7486458a0921186311780cb2fab26950c13b369d8cf876a5ad04cac10489"
DEFAULT_MANUAL_CSV = Path("/tmp/cost-r25-manual-v4.csv")
EXPECTED_COUNTS = {"current":5328,"prior_union":1508,"remaining":3820,"rules":48,"events":259,"account":259,"cost_type":259,"vat_tag":258,"vat_unresolved":1,"bucket":0,"full":0,"confirmed":0,"gate5_credit":0}
FILES = ("manifest.json", "proposals.csv")
COLUMNS = ("proposal_id","direct_event_key","current_event_sha256","current_source_kind","current_source_key","current_source_sha256","taxonomy_key_sha256","seed_source_count","seed_event_set_sha256","account","cost_type","vat_tag","vat_unresolved_reason","bucket","disposition","authority_status","posting_status","confirmed_count","gate5_credit")
DISPOSITION="merchant_taxonomy_review_proposal"
AUTHORITY=("unattested","blocked",0,0)
ADVERSE_TOKENS=("확인","미정","검토","추정")
NORMALIZATION_CONTRACT="unicode-nfkc-uppercase-strip-nonalnum-v1"

def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes: return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def _csv(rows):
    s=io.StringIO(); w=csv.DictWriter(s,fieldnames=COLUMNS,lineterminator="\n"); w.writeheader()
    for row in rows: w.writerow({k:row.get(k,"") for k in COLUMNS})
    return s.getvalue().encode()
def _norm(value: object) -> str:
    text=unicodedata.normalize("NFKC",str(value or "")).upper().strip()
    return re.sub(r"[^0-9A-Z가-힣]+","",text)
def _event_set_sha(values) -> str: return _sha("".join(x+"\n" for x in sorted(values)).encode())
def _adverse(value: str) -> bool: return any(x in value for x in ADVERSE_TOKENS)

def _compile_rules(seeds):
    groups=defaultdict(list)
    for seed in seeds: groups[tuple(seed["key"])].append(seed)
    rules={}
    for key,values in groups.items():
        sources={str(x["source_key"]) for x in values}; triples={tuple(x["triple"]) for x in values}
        if len(sources)>=3 and len(triples)==1:
            rules[key]={"triple":next(iter(triples)),"sources":sources,"events":{str(x["event"]) for x in values}}
    return rules

def _candidate_rule(candidate, rules):
    return rules.get(tuple(candidate["key"])) if candidate.get("type")=="purchase" else None

SEMANTIC_FIELDS=("direct_event_key","taxonomy_key_sha256","seed_source_count","seed_event_set_sha256","account","cost_type","vat_tag","vat_unresolved_reason","current_source_kind","current_source_key","current_source_sha256","current_event_sha256")
def _semantic_set_sha(rows) -> str:
    values=[{field:row.get(field,"") for field in SEMANTIC_FIELDS} for row in rows]
    values.sort(key=lambda x:x["direct_event_key"])
    return _sha(_json(values))

RULE_SHA256 = _sha(_json({"artifact_type":ARTIFACT_TYPE,"rule_version":RULE_VERSION,"key":["source_system","normalized_merchant","exact_biz_category","currency","purchase"],"normalization_contract":NORMALIZATION_CONTRACT,"minimum_distinct_source_keys":3,"seed":"R23 high/high complete purchase","full_triple_unanimous":True,"adverse_tokens":ADVERSE_TOKENS,"adverse_vat_unresolved":True,"bucket":None,"columns":COLUMNS,"semantic_fields":SEMANTIC_FIELDS,"disposition":DISPOSITION,"authority":AUTHORITY,"expected_counts":EXPECTED_COUNTS,"expected_event_set_sha256":EXPECTED_EVENT_SET_SHA256,"expected_current_event_set_sha256":EXPECTED_CURRENT_EVENT_SET_SHA256,"expected_decision_scope_sha256":EXPECTED_DECISION_SCOPE_SHA256,"expected_component_set_sha256":EXPECTED_COMPONENT_SET_SHA256,"expected_semantic_set_sha256":EXPECTED_SEMANTIC_SET_SHA256,"sol_review_sha256":SOL_REVIEW_SHA256,"fable_cross_v2_sha256":FABLE_CROSS_V2_SHA256}))

def _build(ledger_dir: Path, manual_csv: Path):
    if ledger_dir.resolve() != (REPOSITORY_ROOT/"ledger").resolve(): raise ValueError("r34_noncanonical_ledger")
    if _sha(manual_csv.read_bytes()) != EXPECTED_MANUAL_SHA256: raise ValueError("r34_manual_snapshot_invalid")
    r23=build_annex(ledger_dir=ledger_dir)
    envelopes=r23["package"]["envelopes"]
    r23_set={str(x["direct_event_key"]) for x in envelopes if x.get("historical_uid")}
    r25_manifest,r25_files=_build_r25(manual_csv,ledger_dir)
    p=list(csv.DictReader(io.StringIO(r25_files["proposals.csv"].decode())))
    e=list(csv.DictReader(io.StringIO(r25_files["evidence_sets.csv"].decode())))
    r25_set={x["direct_event_key"] for x in p}|{x["direct_event_key"] for x in e if x["evidence_tier"] in {"clean_110","typed_v14_65","portal_1"}}
    r26_set={x[2] for x in R26_RELATIONS}
    r27_set={x[3] for x in EXPECTED_BOOKING_NEW}|{x[3] for x in EXPECTED_OTA_NEW}
    prior=r23_set|r25_set|r26_set|r27_set
    prior_counts=(len(r23_set),len(r25_set),len(r26_set),len(r27_set),len(prior))
    if prior_counts != (1227,272,7,6,1508): raise ValueError(f"r34_prior_union_invalid:{prior_counts}")
    actual_components={"r23":_event_set_sha(r23_set),"r25":_event_set_sha(r25_set),"r26":_event_set_sha(r26_set),"r27":_event_set_sha(r27_set),"prior":_event_set_sha(prior)}
    if actual_components != EXPECTED_COMPONENT_SET_SHA256: raise ValueError("r34_prior_component_set_invalid")
    with tempfile.TemporaryDirectory(prefix="r34-current-") as td:
        db,run,_inventory,event_set_sha,scope_sha,current_hashes=_build_temp_db(ledger_dir,Path(td))
        qr=db.execute("""SELECT d.card_event_id||'#'||d.event_role,p.source_system,p.transaction_type,
          s.payload_json,s.source_kind,s.source_key,s.source_sha256 FROM direct_payment_projection_links l
          JOIN payment_transactions p ON p.id=l.payment_id JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
          JOIN direct_source_records s ON s.id=d.source_record_id WHERE l.run_id=? ORDER BY 1""",(run,)).fetchall(); db.close()
    events={x[0]:{"id":x[0],"source":x[1],"type":x[2],"payload":json.loads(x[3]),"source_kind":x[4],"source_key":x[5],"source_sha":x[6],"event_sha":current_hashes[x[0]]} for x in qr}
    if len(events)!=5328 or not prior<=set(events): raise ValueError("r34_current_census_invalid")
    if event_set_sha!=EXPECTED_CURRENT_EVENT_SET_SHA256 or scope_sha!=EXPECTED_DECISION_SCOPE_SHA256: raise ValueError("r34_current_universe_invalid")
    def key(ev):
        q=ev["payload"]
        return (ev["source"],_norm(q.get("merchant")),_norm(q.get("biz")),_norm(q.get("currency")),"purchase")
    seeds=[]
    for env in envelopes:
        eid=str(env["direct_event_key"]); proposal=env.get("proposal"); ev=events.get(eid)
        if not proposal or not ev or ev["type"]!="purchase": continue
        if proposal.get("confidence")!="상" or proposal.get("tax_conf")!="상" or any(not str(proposal.get(f) or "").strip() for f in ("bucket","account","cost_type","vat_tag")): continue
        seeds.append({"event":eid,"key":key(ev),"source_key":ev["source_key"],"triple":tuple(str(proposal[d]) for d in ("account","cost_type","vat_tag"))})
    rules=_compile_rules(seeds)
    rows=[]
    for eid in sorted(set(events)-prior):
        ev=events[eid]
        rule=_candidate_rule({"type":ev["type"],"key":key(ev)},rules)
        if rule is None: continue
        account,cost_type,vat=rule["triple"]
        vat_reason="adverse_seed_value" if _adverse(vat) else ""
        key_sha=_sha(_json(key(ev))); seed_sha=_event_set_sha(rule["events"])
        row={"direct_event_key":eid,"current_event_sha256":ev["event_sha"],"current_source_kind":ev["source_kind"],"current_source_key":ev["source_key"],"current_source_sha256":ev["source_sha"],"taxonomy_key_sha256":key_sha,"seed_source_count":len(rule["sources"]),"seed_event_set_sha256":seed_sha,"account":account,"cost_type":cost_type,"vat_tag":"" if vat_reason else vat,"vat_unresolved_reason":vat_reason,"bucket":"","disposition":DISPOSITION,"authority_status":AUTHORITY[0],"posting_status":AUTHORITY[1],"confirmed_count":AUTHORITY[2],"gate5_credit":AUTHORITY[3]}
        row["proposal_id"]=_sha(_json({"rule":RULE_SHA256,"event":eid,"event_sha":ev["event_sha"],"key":key_sha,"seeds":seed_sha}))
        rows.append(row)
    selected={r["direct_event_key"] for r in rows}; selected_sha=_event_set_sha(selected)
    semantic_sha=_semantic_set_sha(rows)
    counts={"current":len(events),"prior_union":len(prior),"remaining":len(events)-len(prior),"rules":len(rules),"events":len(rows),"account":sum(bool(r["account"]) for r in rows),"cost_type":sum(bool(r["cost_type"]) for r in rows),"vat_tag":sum(bool(r["vat_tag"]) for r in rows),"vat_unresolved":sum(bool(r["vat_unresolved_reason"]) for r in rows),"bucket":sum(bool(r["bucket"]) for r in rows),"full":sum(all(r[x] for x in ("account","cost_type","vat_tag","bucket")) for r in rows),"confirmed":0,"gate5_credit":0}
    if counts!=EXPECTED_COUNTS or selected_sha!=EXPECTED_EVENT_SET_SHA256: raise ValueError("r34_expected_set_or_counts_invalid")
    if semantic_sha!=EXPECTED_SEMANTIC_SET_SHA256: raise ValueError(f"r34_semantic_set_invalid:{semantic_sha}")
    proposal_bytes=_csv(rows)
    base={"format_version":1,"artifact_type":ARTIFACT_TYPE,"rule_contract_version":RULE_VERSION,"rule_contract_sha256":RULE_SHA256,"sol_review_sha256":SOL_REVIEW_SHA256,"fable_cross_v2_sha256":FABLE_CROSS_V2_SHA256,"authority_status":"unattested","posting_status":"blocked","confirmed_count":0,"gate5_credit":0,"bucket_proposals":0,"full_classifications":0,"current_event_set_sha256":event_set_sha,"decision_scope_sha256":scope_sha,"component_set_sha256":actual_components,"prior_union_set_sha256":_event_set_sha(prior),"selected_event_set_sha256":selected_sha,"semantic_set_sha256":semantic_sha,"r23_envelope_set_sha256":r23["manifest"]["envelope_set_sha256"],"r25_package_set_sha256":r25_manifest["package_set_sha256"],"manual_raw_sha256":_sha(manual_csv.read_bytes()),"counts":counts,"files":{"proposals.csv":{"sha256":_sha(proposal_bytes),"rows":len(rows)}}}
    package_sha=_sha(_json(base)+proposal_bytes)
    manifest={**base,"package_set_sha256":package_sha,"analysis_run_id":_sha(_json({"rule":RULE_SHA256,"package":package_sha,"current":event_set_sha,"prior":base["prior_union_set_sha256"]}))}
    return manifest,{"manifest.json":_json(manifest),"proposals.csv":proposal_bytes}

def _regular(path: Path):
    try: st=path.lstat()
    except OSError as exc: raise ValueError("r34_package_file_invalid") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1: raise ValueError("r34_package_file_invalid")
def _fsync(path: Path):
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try: os.fsync(fd)
    finally: os.close(fd)

def verify_merchant_taxonomy_support(directory: Path, *, ledger_dir: Path=REPOSITORY_ROOT/"ledger", manual_csv: Path=DEFAULT_MANUAL_CSV, current: bool=True):
    if directory.is_symlink() or not directory.is_dir() or sorted(x.name for x in directory.iterdir())!=sorted(FILES): raise ValueError("r34_package_shape_invalid")
    for name in FILES: _regular(directory/name)
    actual={name:(directory/name).read_bytes() for name in FILES}
    try: parsed=json.loads(actual["manifest.json"])
    except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValueError("r34_manifest_invalid") from exc
    if not isinstance(parsed,dict) or (parsed.get("authority_status"),parsed.get("posting_status"),parsed.get("confirmed_count"),parsed.get("gate5_credit"),parsed.get("bucket_proposals"),parsed.get("full_classifications")) != (*AUTHORITY,0,0): raise ValueError("r34_authority_boundary_invalid")
    manifest,expected=_build(ledger_dir,manual_csv)
    if actual!=expected: raise ValueError("r34_live_context_or_semantics_mismatch" if current else "r34_staging_semantics_mismatch")
    return {"status":"valid","analysis_run_id":manifest["analysis_run_id"],"events":259,"vat_tag":258,"bucket":0,"remaining":3820}

def build_merchant_taxonomy_support(*, output: Path|None=None, ledger_dir: Path=REPOSITORY_ROOT/"ledger", manual_csv: Path=DEFAULT_MANUAL_CSV):
    manifest,files=_build(ledger_dir,manual_csv)
    if output is not None:
        parent=output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r34_output_inside_repository")
        if os.path.lexists(output): raise FileExistsError("r34_output_exists")
        stage=Path(tempfile.mkdtemp(prefix=f".{output.name}-",dir=str(parent)))
        try:
            os.chmod(stage,0o700)
            for name,data in files.items():
                with (stage/name).open("wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.chmod(stage/name,0o600)
            _fsync(stage); verify_merchant_taxonomy_support(stage,ledger_dir=ledger_dir,manual_csv=manual_csv,current=False)
            _install_noreplace(stage,output); _fsync(parent)
        except Exception: shutil.rmtree(stage,ignore_errors=True); raise
    return {"manifest":manifest,"manifest_sha256":_sha(files["manifest.json"]),"output":None if output is None else str(output)}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--output",type=Path); p.add_argument("--verify",type=Path); p.add_argument("--manual-csv",type=Path,default=DEFAULT_MANUAL_CSV); a=p.parse_args()
    try: result=verify_merchant_taxonomy_support(a.verify,manual_csv=a.manual_csv) if a.verify else build_merchant_taxonomy_support(output=a.output,manual_csv=a.manual_csv); print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc: print(json.dumps({"status":"invalid","error":str(exc)},ensure_ascii=False,sort_keys=True)); return 2
if __name__=="__main__": raise SystemExit(main())
