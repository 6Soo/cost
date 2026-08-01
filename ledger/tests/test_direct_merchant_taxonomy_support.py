from __future__ import annotations
import csv, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from ledger.domain.direct_merchant_taxonomy_support import (
    EXPECTED_EVENT_SET_SHA256, EXPECTED_SEMANTIC_SET_SHA256, RULE_SHA256,
    _adverse, _candidate_rule, _compile_rules, _semantic_set_sha,
    build_merchant_taxonomy_support, verify_merchant_taxonomy_support,
)

class MerchantTaxonomySupportTest(unittest.TestCase):
    def test_pure_rule_gates_distinct_source_purchase_partition_conflict_adverse(self):
        key=("HAN","MERCHANT","BIZ","KRW","purchase"); triple=("식비","여행원가","불공제_해외")
        split=[{"event":f"e{i}","key":key,"source_key":"HAN:G:7","triple":triple} for i in range(3)]
        self.assertEqual(_compile_rules(split),{})
        seeds=[{"event":f"e{i}","key":key,"source_key":f"HAN:G:{i}","triple":triple} for i in range(3)]
        rules=_compile_rules(seeds); self.assertIn(key,rules)
        self.assertIsNone(_candidate_rule({"type":"refund","key":key},rules))
        self.assertIsNone(_candidate_rule({"type":"purchase","key":(*key[:3],"JPY","purchase")},rules))
        conflict=seeds+[{"event":"e4","key":key,"source_key":"HAN:G:4","triple":("숙박비","여행원가","불공제_해외")}]
        self.assertEqual(_compile_rules(conflict),{})
        self.assertTrue(_adverse("확인")); self.assertFalse(_adverse("불공제_해외"))

    def test_semantic_projection_detects_same_id_label_forgery(self):
        row={"direct_event_key":"e","taxonomy_key_sha256":"k","seed_source_count":3,"seed_event_set_sha256":"s","account":"식비","cost_type":"여행원가","vat_tag":"불공제_해외","vat_unresolved_reason":"","current_source_kind":"card_raw","current_source_key":"HAN:G:1","current_source_sha256":"x","current_event_sha256":"y"}
        original=_semantic_set_sha([row]); forged=dict(row,account="숙박비")
        self.assertNotEqual(original,_semantic_set_sha([forged])); self.assertNotEqual(_semantic_set_sha([forged]),EXPECTED_SEMANTIC_SET_SHA256)

    def test_live_fixed_census_and_authority_boundary(self):
        result=build_merchant_taxonomy_support(); m=result["manifest"]
        self.assertEqual(m["counts"],{"current":5328,"prior_union":1508,"remaining":3820,"rules":48,"events":259,"account":259,"cost_type":259,"vat_tag":258,"vat_unresolved":1,"bucket":0,"full":0,"confirmed":0,"gate5_credit":0})
        self.assertEqual(m["selected_event_set_sha256"],EXPECTED_EVENT_SET_SHA256)
        self.assertEqual(m["semantic_set_sha256"],EXPECTED_SEMANTIC_SET_SHA256)
        self.assertEqual(m["prior_union_set_sha256"],"426b4ec226f804dcfb2f87c8b6f1f8915352169ef401e241945f8c52ee75fc8c")
        self.assertEqual(m["current_event_set_sha256"],"de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93")
        self.assertEqual(m["rule_contract_sha256"],RULE_SHA256)
        self.assertEqual((m["authority_status"],m["posting_status"],m["confirmed_count"],m["gate5_credit"]),("unattested","blocked",0,0))

    def test_external_package_round_trip_and_fields(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out)
            v=verify_merchant_taxonomy_support(out); self.assertEqual((v["events"],v["vat_tag"],v["bucket"]),(259,258,0))
            with (out/"proposals.csv").open(encoding="utf8") as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),259); self.assertTrue(all(r["account"] and r["cost_type"] and not r["bucket"] for r in rows))
            unresolved=[r for r in rows if r["vat_unresolved_reason"]]
            self.assertEqual(len(unresolved),1); self.assertEqual(unresolved[0]["vat_tag"],"")
            self.assertTrue(all(int(r["seed_source_count"])>=3 for r in rows))
            self.assertTrue(all((r["authority_status"],r["posting_status"],r["confirmed_count"],r["gate5_credit"])==("unattested","blocked","0","0") for r in rows))

    def test_tamper_extra_file_and_existing_target_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out)
            (out/"proposals.csv").write_bytes((out/"proposals.csv").read_bytes()+b"tamper\n")
            with self.assertRaisesRegex(ValueError,"semantics_mismatch"): verify_merchant_taxonomy_support(out)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; out.mkdir()
            with self.assertRaises(FileExistsError): build_merchant_taxonomy_support(output=out)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out); (out/"extra").write_text("x")
            with self.assertRaisesRegex(ValueError,"shape_invalid"): verify_merchant_taxonomy_support(out)

    def test_self_consistent_file_manifest_forgery_rejected(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out)
            with (out/"proposals.csv").open(encoding="utf8") as stream: rows=list(csv.DictReader(stream))
            rows[0]["account"]="FORGED"
            with (out/"proposals.csv").open("w",encoding="utf8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=rows[0].keys(),lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
            proposal=(out/"proposals.csv").read_bytes(); manifest=json.loads((out/"manifest.json").read_text())
            manifest["files"]["proposals.csv"]["sha256"]=hashlib.sha256(proposal).hexdigest()
            manifest["semantic_set_sha256"]="0"*64; manifest["package_set_sha256"]="1"*64; manifest["analysis_run_id"]="2"*64
            (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n")
            with self.assertRaisesRegex(ValueError,"semantics_mismatch"): verify_merchant_taxonomy_support(out)

    def test_authority_forgery_symlink_and_hardlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out)
            manifest=json.loads((out/"manifest.json").read_text()); manifest["confirmed_count"]=259
            (out/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,"authority_boundary_invalid"): verify_merchant_taxonomy_support(out)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out)
            original=(out/"proposals.csv"); replacement=Path(td)/"replacement"; replacement.write_bytes(original.read_bytes())
            original.unlink(); original.symlink_to(replacement)
            with self.assertRaisesRegex(ValueError,"package_file_invalid"): verify_merchant_taxonomy_support(out)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"; build_merchant_taxonomy_support(output=out)
            os.link(out/"proposals.csv",Path(td)/"second-link")
            with self.assertRaisesRegex(ValueError,"package_file_invalid"): verify_merchant_taxonomy_support(out)

    def test_atomic_install_failure_leaves_no_target(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"
            with patch("ledger.domain.direct_merchant_taxonomy_support._install_noreplace",side_effect=OSError("injected")):
                with self.assertRaisesRegex(OSError,"injected"): build_merchant_taxonomy_support(output=out)
            self.assertFalse(out.exists()); self.assertEqual(list(Path(td).iterdir()),[])

    def test_staging_fsync_and_verify_failures_leave_no_target(self):
        for target,side_effect in (("_fsync",OSError("fsync-injected")),("verify_merchant_taxonomy_support",ValueError("verify-injected"))):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as td:
                out=Path(td)/"pkg"
                with patch(f"ledger.domain.direct_merchant_taxonomy_support.{target}",side_effect=side_effect):
                    with self.assertRaises(type(side_effect)): build_merchant_taxonomy_support(output=out)
                self.assertFalse(out.exists()); self.assertEqual(list(Path(td).iterdir()),[])

    def test_output_inside_repository_rejected(self):
        with self.assertRaisesRegex(ValueError,"output_inside_repository"):
            build_merchant_taxonomy_support(output=Path("ledger")/"forbidden-r34")

if __name__=="__main__": unittest.main()
