from __future__ import annotations

import copy
import csv
import io
import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from ledger.domain import direct_narrow_service_classification as r37


class _Result:
    def __init__(self,row): self.row=row
    def fetchone(self): return self.row


class _DB:
    def __init__(self,payloads): self.payloads=payloads
    def execute(self,_sql,args): return _Result((self.payloads[args[0]],) if args[0] in self.payloads else None)
    def close(self): pass


class NarrowServiceClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        captured={};orig36,orig25,origmanual,origcontext=(r37.r36._build,r37.r36._build_r25,r37.r36._manual,r37.r36._context)
        def cap36(*a,**k):
            value=orig36(*a,**k);captured["r36"]=copy.deepcopy(value);return value
        def cap25(*a,**k):
            value=orig25(*a,**k);captured["r25"]=copy.deepcopy(value);return value
        def capmanual(*a,**k):
            value=origmanual(*a,**k);captured["manual"]=copy.deepcopy(value);return value
        def capcontext(*a,**k):
            value=origcontext(*a,**k);payloads={}
            for event in value["events"]:
                if event["direct_event_key"] in r37.EXPECTED_EVENTS:
                    payloads[event["current_source_key"]]=value["db"].execute(
                        "SELECT payload_json FROM direct_source_records WHERE source_key=?",(event["current_source_key"],)).fetchone()[0]
            captured["context"]={key:copy.deepcopy(item) for key,item in value.items() if key!="db"};captured["payloads"]=payloads
            return value
        with patch.object(r37.r36,"_build",side_effect=cap36),patch.object(r37.r36,"_build_r25",side_effect=cap25), \
             patch.object(r37.r36,"_manual",side_effect=capmanual),patch.object(r37.r36,"_context",side_effect=capcontext):
            cls.manifest,cls.files=r37._build(Path("ledger"))
        cls.cached=captured

    @staticmethod
    def _rows(raw): return list(csv.DictReader(io.StringIO(raw.decode())))

    def _cached_build(self, *, r36_value=None,r25=None,manual=None,context=None,payloads=None):
        r36_value=copy.deepcopy(self.cached["r36"] if r36_value is None else r36_value)
        r25=copy.deepcopy(self.cached["r25"] if r25 is None else r25)
        manual=copy.deepcopy(self.cached["manual"] if manual is None else manual)
        context=copy.deepcopy(self.cached["context"] if context is None else context)
        payloads=copy.deepcopy(self.cached["payloads"] if payloads is None else payloads);context["db"]=_DB(payloads)
        with patch.object(r37.r36,"_build",return_value=r36_value),patch.object(r37.r36,"_build_r25",return_value=r25), \
             patch.object(r37.r36,"_manual",return_value=manual),patch.object(r37.r36,"_context",return_value=context):
            return r37._build(Path("ledger"))

    def _write(self,root,files=None):
        target=root/"artifact";target.mkdir(mode=0o700)
        for name,data in (files or self.files).items():
            path=target/name;path.write_bytes(data);path.chmod(0o600)
        return target

    def test_live_exact_contract_privacy_and_round_trip(self):
        self.assertEqual(self.manifest["counts"]["proposals"],2);self.assertEqual(self.manifest["counts"]["deferred"],26)
        self.assertEqual(self.manifest["strict_event_set_sha256"],r37.STRICT_SET_SHA256)
        self.assertEqual(self.manifest["strict_semantic_set_sha256"],r37.STRICT_SEMANTIC_SHA256)
        self.assertEqual(self.manifest["deferred_event_set_sha256"],r37.DEFERRED_SET_SHA256)
        self.assertEqual(self.manifest["exclusion_semantic_set_sha256"],r37.EXCLUSION_SEMANTIC_SHA256)
        proposals=self._rows(self.files["proposals.csv"]);exclusions=self._rows(self.files["exclusions.csv"])
        self.assertEqual((len(proposals),len(exclusions),len({x["group_id"] for x in proposals})),(2,26,1))
        self.assertTrue(all((x["account"],x["cost_type"],x["vat_tag"])==("통행료","여행원가","불공제_해외") for x in proposals))
        for columns in (r37.GROUP_COLUMNS,r37.PROPOSAL_COLUMNS,r37.EXCLUSION_COLUMNS):
            self.assertFalse(any(token in name for name in columns for token in r37.SENSITIVE
                                 if token not in {"manual_locator","source_key"}))
            self.assertNotIn("manual_locator",columns);self.assertNotIn("source_key",columns)
        with tempfile.TemporaryDirectory() as dirname:
            result=r37.verify_narrow_service_classification(self._write(Path(dirname)))
            self.assertEqual((result["proposals"],result["deferred"],result["confirmed_count"]),(2,26,0))

    def test_manual_item_description_and_group_mutations_fail_closed(self):
        manual=list(copy.deepcopy(self.cached["manual"]));_,r25_files=self.cached["r25"]
        groups=self._rows(r25_files["groups.csv"]);group=next(x for x in groups if x["group_id"]==r37.STRICT_GROUP_ID)
        locators=json.loads(group["manual_locators_json"])
        cases=(("item","교통"),("desc",""),("desc","숙박"),("amount_krw",-1))
        for field,value in cases:
            changed=copy.deepcopy(manual);row=next(x for x in changed[1] if x["locator"]==locators[0]);row[field]=value
            with self.subTest(field=field,value=value),self.assertRaisesRegex(ValueError,"r37_(manual_class|manual_semantic|manual_rows|manual_group_identity)"):
                self._cached_build(manual=tuple(changed))
        r25_manifest,r25_files=copy.deepcopy(self.cached["r25"]);rows=self._rows(r25_files["groups.csv"])
        row=next(x for x in rows if x["group_id"]==r37.STRICT_GROUP_ID);row["manual_cardinality"]="1"
        files=copy.deepcopy(r25_files);files["groups.csv"]=r37._csv(tuple(rows[0]),rows)
        with self.assertRaisesRegex(ValueError,"complete_group_invalid"):
            self._cached_build(r25=(r25_manifest,files))

    def test_current_merchant_currency_role_source_and_biz_mutations_fail_closed(self):
        context=copy.deepcopy(self.cached["context"]);event=next(x for x in context["events"] if x["direct_event_key"] in r37.EXPECTED_EVENTS)
        cases=(("merchant","HIGHWAY"),("merchant","TOLL"),("merchant","GENERIC PG"),("transaction_type","cancellation"),
               ("event_role","refund"),("source_system","KBD"),("current_source_sha256","0"*64))
        for field,value in cases:
            changed=copy.deepcopy(context);next(x for x in changed["events"] if x["direct_event_key"]==event["direct_event_key"])[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,"r37_(current_source_drift|current_role_invalid|merchant_class_invalid)"):
                self._cached_build(context=changed)
        for field,value in (("currency","KRW"),("currency",""),("currency","USD"),("biz","숙박")):
            payloads=copy.deepcopy(self.cached["payloads"]);key=event["current_source_key"]
            payload=json.loads(payloads[key]);payload[field]=value;payloads[key]=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
            with self.subTest(payload_field=field),self.assertRaisesRegex(ValueError,"r37_(current_source_drift|foreign_fact_invalid|biz_source_drift)"):
                self._cached_build(payloads=payloads)

    def test_same_count_bucket_group_and_output_forgery_fail_closed(self):
        manifest,files=copy.deepcopy(self.cached["r36"]);bucket=self._rows(files["bucket_support.csv"])
        strict=next(x for x in bucket if x["direct_event_key"] in r37.EXPECTED_EVENTS);other=next(x for x in bucket if x["group_id"]!=r37.STRICT_GROUP_ID)
        strict["direct_event_key"]=other["direct_event_key"]
        files["bucket_support.csv"]=r37._csv(tuple(bucket[0]),bucket)
        with self.assertRaisesRegex(ValueError,"bucket_only_invalid"):
            self._cached_build(r36_value=(manifest,files))
        with tempfile.TemporaryDirectory() as dirname:
            target=self._write(Path(dirname));rows=self._rows((target/"proposals.csv").read_bytes());rows[0]["vat_tag"]="확인"
            forged=r37._csv(r37.PROPOSAL_COLUMNS,rows);(target/"proposals.csv").write_bytes(forged)
            manifest=json.loads((target/"manifest.json").read_bytes());manifest["files"]["proposals.csv"]["sha256"]=r37.r36._sha(forged)
            (target/"manifest.json").write_bytes(r37.r36._json(manifest))
            with self.assertRaisesRegex(ValueError,"live_context_or_package_mismatch"):
                r37.verify_narrow_service_classification(target)

    def test_authority_shape_modes_symlink_and_extra_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=self._write(root);manifest=json.loads((target/"manifest.json").read_bytes());manifest["applied"]=True
            (target/"manifest.json").write_bytes(r37.r36._json(manifest));(target/"manifest.json").chmod(0o600)
            with self.assertRaisesRegex(ValueError,"authority_boundary"):
                r37.verify_narrow_service_classification(target)
            (target/"manifest.json").write_bytes(self.files["manifest.json"]);(target/"manifest.json").chmod(0o644)
            with self.assertRaisesRegex(ValueError,"package_file"):
                r37.verify_narrow_service_classification(target)
            (target/"manifest.json").chmod(0o600);(target/"extra").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"package_shape"):
                r37.verify_narrow_service_classification(target)

    def test_atomic_failures_parent_state_stale_stage_and_reconcile_swap(self):
        from contextlib import ExitStack
        injectors=(
            ("write",lambda s:s.enter_context(patch.object(r37,"_write_file",side_effect=OSError("write")))),
            ("stage",lambda s:s.enter_context(patch.object(r37,"_fsync_dir",side_effect=OSError("stage")))),
            ("verify",lambda s:s.enter_context(patch.object(r37,"verify_narrow_service_classification",side_effect=ValueError("verify")))),
            ("rename",lambda s:s.enter_context(patch.object(r37,"_install_noreplace",side_effect=OSError("rename")))),
        )
        for label,inject in injectors:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as dirname:
                root=Path(dirname);target=root/"out"
                with ExitStack() as stack:
                    stack.enter_context(patch.object(r37,"_build",return_value=(self.manifest,self.files)))
                    if label!="verify":stack.enter_context(patch.object(r37,"verify_narrow_service_classification",return_value={"status":"valid"}))
                    inject(stack)
                    with self.assertRaises((OSError,ValueError)):r37.build_narrow_service_classification(output=target)
                self.assertFalse(target.exists());self.assertFalse(any(root.iterdir()))
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out";stage=root/".out-fixed";calls=0
            def make(**_):stage.mkdir();return str(stage)
            def fsync(_):
                nonlocal calls;calls+=1
                if calls==2:stage.mkdir();(stage/"sentinel").write_text("owned", encoding="utf-8");raise OSError("parent")
            with patch.object(r37,"_build",return_value=(self.manifest,self.files)),patch.object(r37,"verify_narrow_service_classification",return_value={"status":"valid"}), \
                 patch.object(r37.tempfile,"mkdtemp",side_effect=make),patch.object(r37,"_fsync_dir",side_effect=fsync), \
                 self.assertRaises(r37.PublicationDurabilityError) as caught:
                r37.build_narrow_service_classification(output=target)
            self.assertEqual((stage/"sentinel").read_text(encoding="utf-8"),"owned");self.assertTrue(target.is_dir())
            competitor=root/"competitor";competitor.mkdir();(competitor/"x").write_text("competitor", encoding="utf-8");moved=root/"moved"
            def swap(_):target.rename(moved);competitor.rename(target)
            with patch.object(r37,"verify_narrow_service_classification",return_value={"status":"valid"}),patch.object(r37,"_fsync_dir",side_effect=swap), \
                 self.assertRaises((ValueError,OSError)):
                r37.reconcile_publication_durability(caught.exception)
            self.assertEqual((target/"x").read_text(encoding="utf-8"),"competitor")

    def test_concurrent_no_replace_one_winner(self):
        with tempfile.TemporaryDirectory() as dirname:
            target=Path(dirname)/"out"
            with patch.object(r37,"_build",return_value=(self.manifest,self.files)),patch.object(r37,"verify_narrow_service_classification",return_value={"status":"valid"}):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(r37.build_narrow_service_classification,output=target) for _ in range(2)]
                    outcomes=[]
                    for future in futures:
                        try:future.result();outcomes.append("ok")
                        except FileExistsError:outcomes.append("exists")
            self.assertEqual(sorted(outcomes),["exists","ok"]);self.assertEqual({x.name for x in target.iterdir()},set(r37.FILES))


if __name__=="__main__": unittest.main()
