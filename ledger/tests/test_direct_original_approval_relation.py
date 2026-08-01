from __future__ import annotations
import hashlib,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ledger.domain import direct_original_approval_relation as r40

class OriginalApprovalRelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.manifest,cls.files=r40._build(Path("ledger"))
    def test_exact_privacy_safe_census_and_authority_boundary(self):
        m=self.manifest;self.assertEqual(m["counts"],{"relations":210,"HAN":82,"KBD":128,"target_accepted":23,"target_residual":187,"target_independent_full":0,"missing_target":29,"no_usable_original":147,"ambiguous":0,"collision":0})
        self.assertEqual((m["accepted_union"],m["incomplete_residual"],m["full_classification_delta"]),(1528,3800,0));self.assertEqual(m["relation_event_set_sha256"],r40.EXPECTED_RELATIONS)
        raw=b"".join(self.files.values()).decode();self.assertNotIn("raw_orig_appr_sha256",raw)
        for guess in ("123456","000123","123.0"):self.assertNotIn(hashlib.sha256(guess.encode()).hexdigest(),raw)
    def test_normalization_rejects_unsafe_and_preserves_contract(self):
        self.assertEqual(r40.normalize_approval(" 000123 ","HAN")[1],"000123")
        for value in ("", "000", "1e5", "12-3", "1.2", "123.0", 1.5, True):
            with self.assertRaises(ValueError):r40.normalize_approval(value,"HAN")
        with self.assertRaises(ValueError):r40.normalize_approval("123","OTHER")
    def test_external_no_replace(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"pkg"
            with patch.object(r40,"_build",return_value=(self.manifest,self.files)):
                r40.build_original_approval_relation(out)
                self.assertEqual(set(x.name for x in out.iterdir()),set(r40.FILES))
                self.assertEqual(r40.verify_original_approval_relation(out)["relations"],210)
                with self.assertRaises(FileExistsError):r40.build_original_approval_relation(out)
                out.chmod(0o777)
                with self.assertRaisesRegex(ValueError,"shape_invalid"):r40.verify_original_approval_relation(out)
    def test_repository_output_and_parent_fsync_failure_fail_closed(self):
        with patch.object(r40,"_build",return_value=(self.manifest,self.files)):
            with self.assertRaisesRegex(ValueError,"inside_repository"):r40.build_original_approval_relation(Path("ledger/r40-forbidden"))
            with tempfile.TemporaryDirectory() as d:
                out=Path(d)/"pkg";real=os.fsync;calls=0
                def fail(fd):
                    nonlocal calls;calls+=1
                    if calls==5:raise OSError("parent")
                    return real(fd)
                with patch.object(r40.os,"fsync",side_effect=fail),self.assertRaises(r40.PublicationDurabilityError):r40.build_original_approval_relation(out)
                self.assertTrue(out.exists())
    def test_authority_is_live_bound_and_purchase_census_present(self):
        self.assertIn("normalization_authority_sha256",self.manifest)
        self.assertIsInstance(self.manifest["purchase_exclusion_reasons"],dict)
        inventory=[{"relative_path":path,"raw_sha256":digest,"parser_version":contract["parser_version"]} for contract in r40.NORMALIZATION_CONTRACTS.values() for path,digest in contract["inputs"].items()]
        inventory[0]["raw_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"normalization_authority_invalid"):r40._validate_normalization_authority(Path("ledger"),inventory)
    def test_post_install_tamper_is_integrity_error_and_preserved(self):
        with tempfile.TemporaryDirectory() as d,patch.object(r40,"_build",return_value=(self.manifest,self.files)):
            out=Path(d)/"pkg";install=r40._install_noreplace
            def tamper(stage,target):
                install(stage,target);(target/"relations.csv").write_bytes(b"TAMPERED\n");os.chmod(target/"relations.csv",0o600)
            with patch.object(r40,"_install_noreplace",side_effect=tamper),self.assertRaises(r40.PublicationIntegrityError) as caught:r40.build_original_approval_relation(out)
            self.assertTrue(caught.exception.published);self.assertTrue(out.exists());self.assertEqual((out/"relations.csv").read_bytes(),b"TAMPERED\n")
            with self.assertRaises(ValueError):r40.reconcile_publication(caught.exception)
    def test_capture_normalizes_symlink_errors(self):
        with tempfile.TemporaryDirectory() as d:
            pkg=Path(d)/"pkg";pkg.mkdir(mode=0o700)
            for name,data in self.files.items():(pkg/name).write_bytes(data);os.chmod(pkg/name,0o600)
            (pkg/"relations.csv").unlink();(pkg/"relations.csv").symlink_to(pkg/"exclusions.csv")
            with self.assertRaisesRegex(ValueError,"package_file_invalid"):r40._capture_package(pkg)

if __name__=="__main__":unittest.main()
