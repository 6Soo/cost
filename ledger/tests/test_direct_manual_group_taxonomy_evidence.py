from __future__ import annotations

import csv
import copy
import io
import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import ledger.domain.direct_manual_group_taxonomy_evidence as r36
import ledger.domain.direct_lineage_annex as lineage


class ManualGroupTaxonomyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        captured = {}
        orig25,orig34,origmanual,origcontext,origannex=(r36._build_r25,r36._build_r34,r36._manual,r36._context,lineage.build_annex)
        def cap25(*args,**kwargs):
            value=orig25(*args,**kwargs);captured["r25"]=copy.deepcopy(value);return value
        def cap34(*args,**kwargs):
            value=orig34(*args,**kwargs);captured["r34"]=copy.deepcopy(value);return value
        def capmanual(*args,**kwargs):
            value=origmanual(*args,**kwargs);captured["manual"]=copy.deepcopy(value);return value
        def capcontext(*args,**kwargs):
            value=origcontext(*args,**kwargs);captured["context"]={k:copy.deepcopy(v) for k,v in value.items() if k!="db"};return value
        def capannex(*args,**kwargs):
            value=origannex(*args,**kwargs);captured["annex"]=copy.deepcopy(value);return value
        with patch.object(r36,"_build_r25",side_effect=cap25),patch.object(r36,"_build_r34",side_effect=cap34), \
             patch.object(r36,"_manual",side_effect=capmanual),patch.object(r36,"_context",side_effect=capcontext), \
             patch.object(lineage,"build_annex",side_effect=capannex):
            cls.manifest, cls.files = r36._build(Path("ledger"), r36.DEFAULT_MANUAL_CSV)
        cls.cached=captured

    def _cached_build(self, *, r25=None, r34=None, manual=None, context=None, annex=None):
        r25=copy.deepcopy(self.cached["r25"] if r25 is None else r25)
        r34=copy.deepcopy(self.cached["r34"] if r34 is None else r34)
        manual=copy.deepcopy(self.cached["manual"] if manual is None else manual)
        context=copy.deepcopy(self.cached["context"] if context is None else context);context["db"]=Mock()
        annex=copy.deepcopy(self.cached["annex"] if annex is None else annex)
        with patch.object(r36,"_build_r25",return_value=r25),patch.object(r36,"_build_r34",return_value=r34), \
             patch.object(r36,"_manual",return_value=manual),patch.object(r36,"_context",return_value=context), \
             patch.object(lineage,"build_annex",return_value=annex):
            return r36._build(Path("ledger"),r36.DEFAULT_MANUAL_CSV)

    @staticmethod
    def _csv_rows(raw: bytes):
        return list(csv.DictReader(io.StringIO(raw.decode())))

    def _write(self, root: Path, files=None) -> Path:
        target = root / "artifact"; target.mkdir()
        for name, data in (files or self.files).items():
            (target / name).write_bytes(data)
        return target

    def test_live_contract_exact_sets_semantics_and_safe_schema(self) -> None:
        manifest = self.manifest
        self.assertEqual(manifest["counts"], {
            "current":5328,"prior_union":1508,"residual":3820,"eligible_groups":18,
            "bucket_support":44,"full_groups":5,"full_classification":16,"bucket_only":28,
            "excluded_mismatch_groups":2,"excluded_mismatch_events":4,"confirmed":0,"gate5_credit":0})
        self.assertEqual(manifest["bucket_event_set_sha256"], r36.BUCKET_SET_SHA256)
        self.assertEqual(manifest["bucket_semantic_set_sha256"],r36.BUCKET_SEMANTIC_SHA256)
        self.assertEqual(manifest["full_event_set_sha256"], r36.FULL_SET_SHA256)
        self.assertEqual(manifest["full_semantic_set_sha256"], r36.FULL_SEMANTIC_SHA256)
        self.assertEqual(manifest["group_partition_sha256"], r36.GROUP_PARTITION_SHA256)
        self.assertEqual(manifest["excluded_mismatch_event_set_sha256"], r36.EXCLUDED_MISMATCH_SET_SHA256)
        self.assertEqual((manifest["authority_status"],manifest["posting_status"],manifest["confirmed_count"],
                          manifest["gate5_credit"],manifest["applied"],manifest["bijection_asserted"]),
                         ("unattested","blocked",0,0,False,False))
        groups=list(csv.DictReader(io.StringIO(self.files["groups.csv"].decode())))
        bucket=list(csv.DictReader(io.StringIO(self.files["bucket_support.csv"].decode())))
        rows=list(csv.DictReader(io.StringIO(self.files["classifications.csv"].decode())))
        self.assertEqual((len(groups),len(rows),len({x["group_id"] for x in rows})),(18,16,5))
        self.assertEqual((len(bucket),len({x["direct_event_key"] for x in bucket}),len({x["group_id"] for x in bucket})),(44,44,18))
        self.assertEqual(len({x["direct_event_key"] for x in bucket}-{x["direct_event_key"] for x in rows}),28)
        self.assertTrue(all(x["bijection_asserted"]=="false" for x in groups))
        self.assertTrue(all(x["transaction_type"]=="purchase" and x["applied"]=="false" for x in rows))
        denied=("amount","merchant","booking_reference","guest","passenger","pnr","pin","card4",
                "source_key","email","token")
        for columns in (r36.GROUP_COLUMNS,r36.BUCKET_COLUMNS,r36.CLASSIFICATION_COLUMNS):
            self.assertFalse(any(token in name for name in columns for token in denied))
            self.assertNotIn("manual_locator",columns)
        self.assertNotIn("full_signed_amount_krw",manifest)

    def test_public_verifier_round_trip_and_self_consistent_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname); target=self._write(root)
            result=r36.verify_manual_group_taxonomy_evidence(target)
            self.assertEqual((result["groups"],result["bucket_support"],result["full_classification"]),(18,44,16))
            original={name:(target/name).read_bytes() for name in r36.FILES}
            rows=list(csv.DictReader(io.StringIO(original["classifications.csv"].decode())))
            rows[0]["bucket"],rows[1]["bucket"]=rows[1]["bucket"],rows[0]["bucket"]
            forged=r36._csv_bytes(r36.CLASSIFICATION_COLUMNS,rows);(target/"classifications.csv").write_bytes(forged)
            manifest=json.loads(original["manifest.json"]);manifest["files"]["classifications.csv"]["sha256"]=r36._sha(forged)
            (target/"manifest.json").write_bytes(r36._json(manifest))
            with self.assertRaisesRegex(ValueError,"live_context_or_package_mismatch"):
                r36.verify_manual_group_taxonomy_evidence(target)

    def test_authority_shape_symlink_hardlink_and_extra_fail_before_trust(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname); target=self._write(root)
            manifest=json.loads((target/"manifest.json").read_bytes());manifest["gate5_credit"]=1
            (target/"manifest.json").write_bytes(r36._json(manifest))
            with self.assertRaisesRegex(ValueError,"authority_boundary"):
                r36.verify_manual_group_taxonomy_evidence(target)
            (target/"manifest.json").write_bytes(self.files["manifest.json"]);(target/"extra").write_text("x")
            with self.assertRaisesRegex(ValueError,"package_shape"):
                r36.verify_manual_group_taxonomy_evidence(target)
            (target/"extra").unlink();(target/"groups.csv").unlink();(target/"groups.csv").symlink_to(target/"classifications.csv")
            with self.assertRaisesRegex(ValueError,"package_file"):
                r36.verify_manual_group_taxonomy_evidence(target)
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=self._write(root);other=root/"hard";os.link(target/"groups.csv",other)
            with self.assertRaisesRegex(ValueError,"package_file"):
                r36.verify_manual_group_taxonomy_evidence(target)

    def test_duplicate_json_nonfinite_and_noncanonical_manual_fail(self) -> None:
        with self.assertRaisesRegex(ValueError,"duplicate_key"):
            r36._strict_json(b'{"a":1,"a":2}',"x")
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            r36._strict_json(b'{"a":NaN}',"x")
        with tempfile.TemporaryDirectory() as dirname:
            copy=Path(dirname)/"manual.csv";copy.write_bytes(r36.DEFAULT_MANUAL_CSV.read_bytes())
            with self.assertRaisesRegex(ValueError,"noncanonical_manual"):
                r36._validate_inputs(Path("ledger"),copy)

    def test_atomic_no_replace_permissions_and_install_failure_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out"
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}):
                result=r36.build_manual_group_taxonomy_evidence(output=target)
            self.assertEqual(result["output"],str(target));self.assertTrue(target.is_dir())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
            self.assertTrue(all(stat.S_IMODE((target/x).stat().st_mode)==0o600 for x in r36.FILES))
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)):
                with self.assertRaises(FileExistsError):r36.build_manual_group_taxonomy_evidence(output=target)
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out"
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36,"_install_noreplace",side_effect=OSError("injected")):
                with self.assertRaises(OSError):r36.build_manual_group_taxonomy_evidence(output=target)
            self.assertFalse(target.exists());self.assertFalse(any(root.iterdir()))

    def test_inside_repository_output_and_manual_symlink_rejected(self) -> None:
        with patch.object(r36,"_build",return_value=(self.manifest,self.files)):
            with self.assertRaisesRegex(ValueError,"inside_repository"):
                r36.build_manual_group_taxonomy_evidence(output=Path("ledger/r36-forbidden"))
        with tempfile.TemporaryDirectory() as dirname:
            link=Path(dirname)/"manual.csv";link.symlink_to(r36.DEFAULT_MANUAL_CSV)
            with patch.object(r36,"DEFAULT_MANUAL_CSV",link):
                with self.assertRaisesRegex(ValueError,"manual_file_invalid"):
                    r36._validate_inputs(Path("ledger"),link)

    def test_cached_builder_rejects_group_manual_and_counterexample_mutations(self) -> None:
        r25_manifest,r25_files=copy.deepcopy(self.cached["r25"])
        rows=self._csv_rows(r25_files["groups.csv"])
        accepted={x["group_id"] for x in self._csv_rows(self.files["groups.csv"])}
        base=next(x for x in rows if x["group_id"] in accepted)
        rejected=next(x for x in rows if x["group_type"]=="current_duplicate" and
                      x["current_cardinality"]=="2" and x["manual_cardinality"]=="1")
        cases=[]
        changed=copy.deepcopy(rows); row=next(x for x in changed if x["group_id"]==base["group_id"])
        members=json.loads(row["current_event_keys_json"]);members.pop();row["current_event_keys_json"]=json.dumps(members)
        cases.append(("member_remove",changed))
        changed=copy.deepcopy(rows);row=next(x for x in changed if x["group_id"]==base["group_id"])
        locators=json.loads(row["manual_locators_json"]);locators[-1]=locators[0];row["manual_locators_json"]=json.dumps(locators)
        cases.append(("locator_duplicate",changed))
        changed=copy.deepcopy(rows);row=next(x for x in changed if x["group_id"]==base["group_id"])
        compound=json.loads(row["compound_key_json"]);compound[2]=-int(compound[2]);row["compound_key_json"]=json.dumps(compound)
        cases.append(("sign_or_abs_join",changed))
        changed=copy.deepcopy(rows);row=next(x for x in changed if x["group_id"]==rejected["group_id"])
        row["group_type"]="both_duplicate";row["manual_cardinality"]="2"
        row["manual_locators_json"]=json.dumps(json.loads(row["manual_locators_json"])*2)
        cases.append(("current2_manual1_leak",changed))
        for label,mutated in cases:
            with self.subTest(label=label):
                files=copy.deepcopy(r25_files);files["groups.csv"]=r36._csv_bytes(tuple(mutated[0]),mutated)
                with self.assertRaisesRegex(ValueError,"r36_(excluded_counterexample_set_invalid|group_live_rebuild_mismatch|bucket_group_set_invalid|group_cardinality_mismatch)"):
                    self._cached_build(r25=(r25_manifest,files))

        manual=list(copy.deepcopy(self.cached["manual"])); manual_rows=manual[1]
        locator=json.loads(base["manual_locators_json"])[0]; item=next(x for x in manual_rows if x["locator"]==locator)
        for field,value in (("tab","__wrong_tab__"),("amount_krw",-int(item["amount_krw"]))):
            changed=copy.deepcopy(manual);target=next(x for x in changed[1] if x["locator"]==locator);target[field]=value
            with self.subTest(manual_field=field),self.assertRaisesRegex(ValueError,"r36_(group_live_rebuild_mismatch|bucket_group_set_invalid)"):
                self._cached_build(manual=tuple(changed))

    def test_cached_builder_rejects_same_count_r34_prior_and_current_drift(self) -> None:
        bucket_ids={x["direct_event_key"] for x in self._csv_rows(self.files["bucket_support.csv"])}
        full_ids={x["direct_event_key"] for x in self._csv_rows(self.files["classifications.csv"])}
        context=copy.deepcopy(self.cached["context"]);all_ids={x["direct_event_key"] for x in context["events"]}
        r34_manifest,r34_files=copy.deepcopy(self.cached["r34"]); rows=self._csv_rows(r34_files["proposals.csv"])
        outside=next(x for x in all_ids if x not in {r["direct_event_key"] for r in rows})
        swapped=copy.deepcopy(rows);next(x for x in swapped if x["direct_event_key"] in full_ids)["direct_event_key"]=outside
        files=copy.deepcopy(r34_files);files["proposals.csv"]=r36._csv_bytes(tuple(swapped[0]),swapped)
        with self.assertRaisesRegex(ValueError,"r36_r34_set_invalid"):
            self._cached_build(r34=(r34_manifest,files))

        semantic=copy.deepcopy(rows); candidates=[x for x in semantic if x["direct_event_key"] in full_ids]
        pair=next((a,b) for a in candidates for b in candidates if a["account"]!=b["account"])
        pair[0]["account"],pair[1]["account"]=pair[1]["account"],pair[0]["account"]
        files=copy.deepcopy(r34_files);files["proposals.csv"]=r36._csv_bytes(tuple(semantic[0]),semantic)
        with self.assertRaisesRegex(ValueError,"r36_full_set_or_semantic_invalid"):
            self._cached_build(r34=(r34_manifest,files))

        annex=copy.deepcopy(self.cached["annex"]); envelope=next(x for x in annex["package"]["envelopes"] if x.get("historical_uid"))
        envelope["direct_event_key"]=next(x for x in all_ids if x not in bucket_ids and x!=envelope["direct_event_key"])
        with self.assertRaisesRegex(ValueError,"r36_prior_or_residual_invalid"):
            self._cached_build(annex=annex)

        accepted=next(x for x in context["events"] if x["direct_event_key"] in bucket_ids)
        mutations=(("source_system","__other__"),("occurred_on","2099-01-01"),
                   ("signed_amount_krw",-int(accepted["signed_amount_krw"])))
        for field,value in mutations:
            changed=copy.deepcopy(context);next(x for x in changed["events"] if x["direct_event_key"]==accepted["direct_event_key"])[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,"r36_(group_live_rebuild_mismatch|bucket_group_set_invalid)"):
                self._cached_build(context=changed)

        full=next(x for x in context["events"] if x["direct_event_key"] in full_ids)
        changed=copy.deepcopy(context);next(x for x in changed["events"] if x["direct_event_key"]==full["direct_event_key"])["transaction_type"]="cancellation"
        with self.assertRaisesRegex(ValueError,"r36_nonpurchase_full_event"):
            self._cached_build(context=changed)

    def test_bucket_semantic_and_row_authority_forgery_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target=self._write(Path(dirname)); original={x:(target/x).read_bytes() for x in r36.FILES}
            rows=self._csv_rows(original["bucket_support.csv"]); a,b=next((a,b) for a in rows for b in rows if a["bucket"]!=b["bucket"])
            a["bucket"],b["bucket"]=b["bucket"],a["bucket"]
            forged=r36._csv_bytes(r36.BUCKET_COLUMNS,rows);(target/"bucket_support.csv").write_bytes(forged)
            manifest=json.loads(original["manifest.json"]);manifest["files"]["bucket_support.csv"]["sha256"]=r36._sha(forged)
            manifest["bucket_semantic_set_sha256"]="0"*64;(target/"manifest.json").write_bytes(r36._json(manifest))
            with self.assertRaisesRegex(ValueError,"live_context_or_package_mismatch"):
                r36.verify_manual_group_taxonomy_evidence(target)
        for filename,field,value in (("groups.csv","applied","true"),("bucket_support.csv","gate5_credit","1"),
                                     ("classifications.csv","authority_status","confirmed")):
            with self.subTest(filename=filename),tempfile.TemporaryDirectory() as dirname:
                target=self._write(Path(dirname));rows=self._csv_rows((target/filename).read_bytes());rows[0][field]=value
                columns={"groups.csv":r36.GROUP_COLUMNS,"bucket_support.csv":r36.BUCKET_COLUMNS,
                         "classifications.csv":r36.CLASSIFICATION_COLUMNS}[filename]
                (target/filename).write_bytes(r36._csv_bytes(columns,rows))
                with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                     self.assertRaisesRegex(ValueError,"live_context_or_package_mismatch"):
                    r36.verify_manual_group_taxonomy_evidence(target)

    def test_atomic_failure_matrix_rolls_back_without_partial_target(self) -> None:
        cases=(
            ("write",lambda stack: stack.enter_context(patch.object(r36,"_write_file_fsync",side_effect=OSError("write")))),
            ("file_fsync",lambda stack: stack.enter_context(patch.object(os,"fsync",side_effect=OSError("file fsync")))),
            ("stage_fsync",lambda stack: stack.enter_context(patch.object(r36,"_fsync_dir",side_effect=OSError("stage fsync")))),
            ("verify",lambda stack: stack.enter_context(patch.object(r36,"verify_manual_group_taxonomy_evidence",side_effect=ValueError("verify")))),
            ("rename",lambda stack: stack.enter_context(patch.object(r36,"_install_noreplace",side_effect=OSError("rename")))),
        )
        from contextlib import ExitStack
        for label,inject in cases:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as dirname:
                root=Path(dirname);target=root/"out"
                with ExitStack() as stack:
                    stack.enter_context(patch.object(r36,"_build",return_value=(self.manifest,self.files)))
                    if label not in {"verify"}: stack.enter_context(patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}))
                    inject(stack)
                    with self.assertRaises((OSError,ValueError)):r36.build_manual_group_taxonomy_evidence(output=target)
                self.assertFalse(target.exists());self.assertFalse(any(root.iterdir()))

        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out";calls=0
            def directory_fsync(_path):
                nonlocal calls;calls+=1
                if calls==2: raise OSError("parent fsync")
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36,"_fsync_dir",side_effect=directory_fsync), \
                 self.assertRaises(r36.PublicationDurabilityError) as caught:
                r36.build_manual_group_taxonomy_evidence(output=target)
            error=caught.exception
            self.assertEqual((error.output,error.expected_package_sha256,error.published,error.parent_fsync),
                             (target,self.manifest["package_set_sha256"],True,False))
            self.assertTrue(target.is_dir());self.assertEqual(calls,2)
            with patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36,"_fsync_dir") as retry:
                result=r36.reconcile_publication_durability(error)
            self.assertEqual((result["published"],result["parent_fsync"]),(True,True));retry.assert_called_once()

    def test_parent_fsync_swap_race_preserves_competing_target_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out";moved=root/"published";competitor=root/"competitor"
            competitor.mkdir();sentinel=b"competitor-owned\n";(competitor/"sentinel").write_bytes(sentinel);calls=0
            def swap_then_fail(_path):
                nonlocal calls;calls+=1
                if calls==2:
                    target.rename(moved);competitor.rename(target)
                    raise OSError("parent fsync after target swap")
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36,"_fsync_dir",side_effect=swap_then_fail), \
                 self.assertRaises(r36.PublicationDurabilityError) as caught:
                r36.build_manual_group_taxonomy_evidence(output=target)
            self.assertEqual((target/"sentinel").read_bytes(),sentinel)
            self.assertEqual({x.name for x in moved.iterdir()},set(r36.FILES))
            with patch.object(os,"rename",side_effect=AssertionError("post-publish rollback forbidden")), \
                 patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 self.assertRaises(FileExistsError):
                r36.build_manual_group_taxonomy_evidence(output=target)
            with self.assertRaisesRegex(ValueError,"package_shape"):
                r36.reconcile_publication_durability(caught.exception)

        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out";calls=0
            def fail_parent(_path):
                nonlocal calls;calls+=1
                if calls==2: raise OSError("parent fsync")
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36,"_fsync_dir",side_effect=fail_parent), \
                 patch.object(os,"rename",side_effect=AssertionError("rollback rename must not run")), \
                 self.assertRaises(r36.PublicationDurabilityError):
                r36.build_manual_group_taxonomy_evidence(output=target)
            self.assertTrue(target.is_dir())

    def test_post_publish_stale_stage_path_reuse_is_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=root/"out";stage=root/".out-fixed";sentinel=b"new-stage-owner\n";calls=0
            def fixed_stage(**_kwargs):
                stage.mkdir(mode=0o700);return str(stage)
            def reuse_stage_then_fail(_path):
                nonlocal calls;calls+=1
                if calls==2:
                    stage.mkdir();(stage/"sentinel").write_bytes(sentinel)
                    raise OSError("parent fsync after stale stage reuse")
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36.tempfile,"mkdtemp",side_effect=fixed_stage), \
                 patch.object(r36,"_fsync_dir",side_effect=reuse_stage_then_fail), \
                 self.assertRaises(r36.PublicationDurabilityError):
                r36.build_manual_group_taxonomy_evidence(output=target)
            self.assertEqual((stage/"sentinel").read_bytes(),sentinel)
            self.assertEqual({x.name for x in target.iterdir()},set(r36.FILES))

    def test_reconcile_swap_during_parent_fsync_never_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);target=self._write(root);moved=root/"published";competitor=root/"competitor"
            competitor.mkdir();forged=copy.deepcopy(self.files)
            manifest=json.loads(forged["manifest.json"]);manifest["package_set_sha256"]="f"*64
            forged["manifest.json"]=r36._json(manifest)
            for name,data in forged.items():(competitor/name).write_bytes(data)
            error=r36.PublicationDurabilityError(target,self.manifest["package_set_sha256"])
            def swap(_parent):
                target.rename(moved);competitor.rename(target)
            with patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}), \
                 patch.object(r36,"_fsync_dir",side_effect=swap), \
                 self.assertRaisesRegex(ValueError,"publication_package_mismatch"):
                r36.reconcile_publication_durability(error)
            self.assertEqual(json.loads((target/"manifest.json").read_bytes())["package_set_sha256"],"f"*64)
            self.assertEqual({x.name for x in moved.iterdir()},set(r36.FILES))

    def test_concurrent_no_replace_has_one_complete_winner(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target=Path(dirname)/"out"
            def run(): return r36.build_manual_group_taxonomy_evidence(output=target)
            with patch.object(r36,"_build",return_value=(self.manifest,self.files)), \
                 patch.object(r36,"verify_manual_group_taxonomy_evidence",return_value={"status":"valid"}):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(run) for _ in range(2)]
                    results=[]
                    for future in futures:
                        try: results.append(("ok",future.result()))
                        except FileExistsError as exc: results.append(("exists",exc))
            self.assertEqual(sorted(x[0] for x in results),["exists","ok"])
            self.assertEqual({x.name for x in target.iterdir()},set(r36.FILES))


if __name__ == "__main__":
    unittest.main()
