import csv, io, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from ledger.domain import direct_kbo_signature_cardinality as r46
from ledger.domain import direct_manual_group_taxonomy_evidence as r36


class KboSignatureCardinalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.files = r46._build()

    def test_live_cardinality_conflict_is_partial_and_inert(self):
        m=self.manifest
        self.assertEqual((m["raw_count"],m["legacy_count"],m["master_count"],m["legacy_excess"]),(2,4,2,2))
        self.assertEqual((m["support_count"],m["conflict_count"],m["full_classification_delta"]),(2,4,0))
        self.assertEqual((m["accepted_union"],m["incomplete_residual"],m["residual_set_sha256"]),(1528,3800,r46.EXPECTED_RESIDUAL))
        self.assertEqual((m["authority_status"],m["posting_status"],m["confirmed_count"],m["gate5_credit"],m["applied"]),("unattested","blocked",0,0,False))

    def test_exact_sets_and_r45_are_disjoint(self):
        m=self.manifest
        self.assertEqual(m["selected_event_set_sha256"],r46.EXPECTED_SELECTED)
        self.assertEqual(m["r45_target3_set_sha256"],r46.EXPECTED_R45_TARGET3)
        self.assertEqual(m["r45_intersection_count"],0)

    def test_group_support_never_asserts_uid_bijection(self):
        groups=list(csv.DictReader(io.StringIO(self.files["groups.csv"].decode())))
        support=list(csv.DictReader(io.StringIO(self.files["support.csv"].decode())))
        conflicts=list(csv.DictReader(io.StringIO(self.files["conflicts.csv"].decode())))
        self.assertEqual((len(groups),len(support),len(conflicts)),(1,2,4))
        self.assertEqual(groups[0]["missing_dimensions"],"cost_type")
        self.assertEqual(groups[0]["bijection_asserted"],"false")
        self.assertEqual(groups[0]["individual_relation_count"],"0")
        for row in support:
            self.assertEqual((row["bucket_present"],row["account_present"],row["cost_type_present"],row["vat_tag_present"]),("true","true","false","true"))
            self.assertEqual((row["bijection_asserted"],row["disposition"],row["applied"]),("false","partial_support_not_classification","false"))
        self.assertEqual({x["reason"] for x in conflicts},{"legacy_cardinality_exceeds_raw_no_uid_bijection"})

    def test_public_package_contains_no_raw_sensitive_values(self):
        r46._privacy(self.files)
        blob=b"".join(self.files.values()).decode()
        for value in ("KBO:E:","8835","21600","209498","AGODA.COM","KBO-0349"):
            self.assertNotIn(value,blob)
        self.assertNotIn("card:",blob)

    def test_same_count_member_exchange_and_input_drift_are_bound(self):
        m=self.manifest
        self.assertEqual(m["current_event_set_sha256"],r46.EXPECTED_CURRENT)
        self.assertEqual(m["decision_scope_sha256"],r46.EXPECTED_SCOPE)
        self.assertEqual(m["files"]["support.csv"]["sha256"],r46._sha(self.files["support.csv"]))
        altered=self.files["support.csv"].replace(b"partial_support_not_classification",b"partial_support_not_classificatioN",1)
        self.assertNotEqual(r46._sha(altered),m["files"]["support.csv"]["sha256"])
        selected={"member-a","member-b"};r45={"other-a","other-b","other-c"}
        with mock.patch.object(r46,"EXPECTED_SELECTED",r46._setsha(selected)),mock.patch.object(r46,"EXPECTED_R45_TARGET3",r46._setsha(r45)):
            r46._validate_member_sets(selected,r45)
            with self.assertRaisesRegex(ValueError,"selected_or_r45_set_invalid"):
                r46._validate_member_sets({"member-a","member-c"},r45)

    def test_real_live_context_selector_exchange_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ctx=r36._context(Path("ledger").resolve(),Path(td));ctx["db"].close();by={e["current_source_key"]:e for e in ctx["events"]}
        r46._select_live_events(by)
        with mock.patch.object(r46,"SELECTED_SOURCE_KEYS",{"KBO:E:1017","KBO:E:1477"}):
            with self.assertRaisesRegex(ValueError,"selected_or_r45_set_invalid"):r46._select_live_events(by)

    def test_external_only_noreplace_and_modes(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"
            with mock.patch.object(r46,"_build",return_value=(self.manifest,self.files)):
                r46.build_kbo_signature_cardinality(out)
            self.assertEqual(stat_mode(out),0o700)
            self.assertEqual(set(x.name for x in out.iterdir()),set(r46.FILES))
            self.assertTrue(all(stat_mode(x)==0o600 for x in out.iterdir()))
            with mock.patch.object(r46,"_build",return_value=(self.manifest,self.files)):
                with self.assertRaises(FileExistsError):r46.build_kbo_signature_cardinality(out)

    def test_public_verifier_rebuilds_and_publication_failure_is_reconcilable(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg"
            with mock.patch.object(r46,"_build",return_value=(self.manifest,self.files)):
                r46.build_kbo_signature_cardinality(out)
                self.assertEqual(r46.verify_kbo_signature_cardinality_package(out),self.manifest)
                self.assertEqual(r46.reconcile_kbo_signature_cardinality(out),self.manifest)
            tampered=dict(self.files);tampered["support.csv"]+=b"x"
            with mock.patch.object(r46,"_build",return_value=(self.manifest,tampered)):
                with self.assertRaisesRegex(ValueError,"live_rebuild_mismatch"):r46.verify_kbo_signature_cardinality_package(out)

    def test_parent_fsync_failure_reports_published_state(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"pkg";real=os.fsync;calls=0
            def seam(fd):
                nonlocal calls;calls+=1
                if calls==6:raise OSError("parent seam")
                return real(fd)
            with mock.patch.object(r46,"_build",return_value=(self.manifest,self.files)),mock.patch.object(r46.os,"fsync",side_effect=seam):
                with self.assertRaises(r46.PublicationDurabilityError) as got:r46.build_kbo_signature_cardinality(out)
            self.assertTrue(got.exception.published);self.assertTrue(out.is_dir())
            with mock.patch.object(r46,"_build",return_value=(self.manifest,self.files)):
                self.assertEqual(r46.reconcile_kbo_signature_cardinality(out),self.manifest)

    def test_parent_path_swap_is_detected_after_dirfd_publish(self):
        with tempfile.TemporaryDirectory() as root:
            parent=Path(root)/"parent";parent.mkdir();out=parent/"pkg";old=Path(root)/"old";real=r46._rename_noreplace_at
            def seam(pfd,source,target):
                parent.rename(old);parent.mkdir();return real(pfd,source,target)
            with mock.patch.object(r46,"_build",return_value=(self.manifest,self.files)),mock.patch.object(r46,"_rename_noreplace_at",side_effect=seam):
                with self.assertRaises(r46.PublicationIntegrityError) as got:r46.build_kbo_signature_cardinality(out)
            self.assertTrue(got.exception.published);self.assertTrue((old/"pkg").is_dir());self.assertFalse(out.exists())

    def test_privacy_mutation_fails_closed(self):
        bad=dict(self.files);bad["support.csv"]=bad["support.csv"]+b"KBO:E:1017\n"
        with self.assertRaisesRegex(ValueError,"privacy_violation"):r46._privacy(bad)


def stat_mode(path:Path)->int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":unittest.main()
