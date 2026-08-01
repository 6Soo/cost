import csv
import io
import json
import os
import tempfile
import unittest
import subprocess
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain import direct_trip_cancel_provenance as auth


class TripCancelLifecycleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);os.chmod(self.root,0o700)
        self.provenance={"relevant_lifecycle_count":2,"lifecycles":[{"x":1},{"x":2}],"receipt_set_sha256":"a"*64,
            "capture_claims":{"closed_query_union_count":9,"closed_query_pages_exhausted":True,"authenticated":False,"basis":"operator_gmail_session_2026-08-01"}}
        self.bindings=[]
        for index,(key,(role,content)) in enumerate(r44.EVENTS.items()):
            self.bindings.append({"key":key,"event_key_sha256":r44._sha(key.encode()),"current_event_sha256":content,
                "current_source_sha256":f"{index+1:064x}","current_source_locator_sha256":f"{index+11:064x}",
                "current_payload_sha256":f"{index+21:064x}","transaction_type":role,
                "amount":893170 if role=="purchase" else -893170,"foreign_signed":92001 if role=="purchase" else -92001})
        self.remaining=[]
        for i in range(22):
            self.remaining.append({"direct_event_key":f"safe-event-{i}","current_event_sha256":f"{i+40:064x}",
                "group_id":f"{i+80:064x}","group_member_set_sha256":f"{i+120:064x}","reason_code":"still_deferred"})
        self.live=({"package_set_sha256":r44.EXPECTED_R42_PACKAGE},self.bindings,set(r44.EVENTS)|{"other"},self.remaining)

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self):
        with mock.patch.object(r44.auth,"verify_provenance",return_value={"provenance":self.provenance,"provenance_sha256":"b"*64}),\
             mock.patch.object(r44,"_live",return_value=self.live),mock.patch.object(r44,"_trip_contract",return_value="c"*64):
            return r44._build(self.root,self.root/"p",self.root/"k",self.root/"python")

    def test_exact_atomic_four_are_inert_and_net_zero_bucket(self):
        manifest,files=self._build();proposals=list(csv.DictReader(io.StringIO(files["proposals.csv"].decode())))
        self.assertEqual((len(proposals),manifest["accepted_union"],manifest["global_residual"],manifest["frontier_authoritative"],manifest["full_classification_delta"]),(4,1528,3800,24,0))
        self.assertEqual(manifest["supported_frontier"],2)
        self.assertEqual({x["posting_bucket"] for x in proposals},{"취소환불(net0)"})
        self.assertEqual({x["trip_target"] for x in proposals},{"10월_도고"})
        self.assertEqual({x["applied"] for x in proposals},{"false"})
        self.assertEqual({x["individual_relation_count"] for x in proposals},{"0"})
        self.assertEqual({(x["atomic_group_required"],x["atomic_member_count"]) for x in proposals},{("true","4")})
        self.assertFalse(manifest["capture_claims"]["authenticated"])
        self.assertIn("r42_package_set_sha256_pinned",manifest)

    def test_fable_correction_prevents_trip_target_as_posting_bucket(self):
        _manifest,files=self._build()
        self.assertNotIn(b"10\xec\x9b\x94_\xeb\x8f\x84\xea\xb3\xa0,complete_group",files["proposals.csv"])
        self.assertIn("취소환불(net0)".encode(),files["proposals.csv"])

    def test_partial_selected_group_fails_atomic(self):
        self.bindings.pop()
        with self.assertRaisesRegex(ValueError,"atomic_member_set_invalid"):self._build()

    def test_permutation_is_invariant_and_role_change_is_not_net_zero(self):
        first=r44._permutation_sha(self.bindings);second=r44._permutation_sha(list(reversed(self.bindings)))
        self.assertEqual(first,second)
        changed=[dict(x) for x in self.bindings];changed[0]["current_event_sha256"]="f"*64
        self.assertNotEqual(first,r44._permutation_sha(changed))
        self.bindings[0]["amount"]=-893170
        with self.assertRaisesRegex(ValueError,"atomic_role_or_total_invalid"):self._build()

    def test_frontier_exclusions_are_privacy_hashed(self):
        _manifest,files=self._build();text=files["exclusions.csv"].decode()
        self.assertNotIn("safe-event-",text);self.assertEqual(len(text.splitlines())-1,22)

    def test_public_privacy_rejects_raw_event_and_order(self):
        with self.assertRaisesRegex(ValueError,"privacy_violation"):r44._privacy_scan({"x":b"card:"+b"a"*64+b"#single"})
        with self.assertRaisesRegex(ValueError,"privacy_violation"):r44._privacy_scan({"x":b"order_ref"})

    def test_publication_never_replaces_target(self):
        target=self.root/"exists";target.write_bytes(b"keep")
        with mock.patch.object(r44,"_build",return_value=({},{})):
            with self.assertRaises(FileExistsError):r44.build_trip_cancel_lifecycle_evidence(self.root,self.root/"p",self.root/"k",self.root/"py",target)
        self.assertEqual(target.read_bytes(),b"keep")

    def test_publication_rejects_symlink_parent_before_resolve(self):
        real=self.root/"real";real.mkdir();link=self.root/"link";link.symlink_to(real,target_is_directory=True)
        with mock.patch.object(r44,"_build",return_value=({},{})):
            with self.assertRaisesRegex(ValueError,"output_parent_symlink"):
                r44.build_trip_cancel_lifecycle_evidence(self.root,self.root/"p",self.root/"k",self.root/"py",link/"out")

    def test_fd_pinned_publication_roundtrip(self):
        target=self.root/"published";expected={name:(name+"-expected").encode() for name in r44.FILES}
        with mock.patch.object(r44,"_build",return_value=({"package_set_sha256":"d"*64},expected)):
            result=r44.build_trip_cancel_lifecycle_evidence(self.root,self.root/"p",self.root/"k",self.root/"py",target)
        self.assertEqual(result["output"],str(target));self.assertEqual(r44._capture(target),expected)

    def test_verifier_rejects_tamper(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        expected={name:(name+"-expected").encode() for name in r44.FILES}
        for name,data in expected.items():p=package/name;p.write_bytes(data);os.chmod(p,0o600)
        (package/"groups.csv").write_bytes(b"tampered")
        with mock.patch.object(r44,"_build",return_value=({"package_set_sha256":"f"*64},expected)):
            with self.assertRaisesRegex(ValueError,"package_or_context_mismatch"):
                r44.verify_trip_cancel_lifecycle_evidence(package,self.root,self.root/"p",self.root/"k",self.root/"py")

    def test_provenance_seal_is_domain_separated_and_deterministic(self):
        unsigned={"artifact_type":auth.ARTIFACT_TYPE,"documents":[]};key=b"k"*32
        self.assertEqual(auth._sealed(unsigned,key),auth._sealed(unsigned,key))
        parsed=json.loads(auth._sealed(unsigned,key));self.assertRegex(parsed["provenance_hmac_sha256"],r"^[0-9a-f]{64}$")

    def test_provenance_rejects_extra_raw_mime(self):
        p=self.root/"doc-10.eml";p.write_bytes(b"x");os.chmod(p,0o600)
        with self.assertRaisesRegex(ValueError,"raw_mime_census_invalid"):
            auth._fresh_unsigned(self.root,b"k"*32,self.root/"python")

    def test_same_cardinality_residual_exchange_fails_hash(self):
        universe=set(r44.EVENTS)|{f"event-{i}" for i in range(5324)}
        accepted=set(sorted(universe-set(r44.EVENTS))[:1528]);residual=universe-accepted
        with mock.patch.object(r44,"EXPECTED_RESIDUAL",r44._setsha(residual)):
            self.assertEqual(len(r44._validate_residual(accepted,universe)),3800)
            out=next(iter(residual-set(r44.EVENTS)));inside=next(iter(accepted));mutated=(accepted-{inside})|{out}
            with self.assertRaisesRegex(ValueError,"selected_not_exact_global_residual"):
                r44._validate_residual(mutated,universe)

    def _valid_event_payload(self,role="purchase"):
        event={"current_event_sha256":"a"*64,"source_system":"KBO","current_source_kind":"card_raw","event_role":"single",
            "transaction_type":role,"card4":"8835","currency":"JPY","foreign_amount":"92001","signed_amount_krw":893170 if role=="purchase" else -893170,
            "merchant":"TRIP.COM","occurred_on":"2026-03-20" if role=="purchase" else "2026-04-07",
            "posted_on":"2026-03-23" if role=="purchase" else "2026-04-07"}
        payload={"biz":"해외","merchant":"TRIP.COM","cancel":role=="cancellation","orig_appr":None,"appr":None}
        return event,payload

    def test_vat_payload_mutations_fail_closed(self):
        for field,value in (("biz","국내"),("merchant","OTHER"),("cancel",True)):
            event,payload=self._valid_event_payload();payload[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,"selected_event_contract_invalid"):
                r44._validate_selected_event(event,payload,"purchase","a"*64)

    def test_strict_payload_rejects_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError,"duplicate_key"):
            r44._selected_payload('{"biz":"해외","biz":"국내"}'.encode())

    def _message(self,auth_header="mx.google.com; dkim=pass header.i=@trip.com header.d=trip.com header.s=x header.b=y",signature="v=1; d=trip.com; s=x; b=y"):
        raw=(f"From: Sender <sender@trip.com>\nAuthentication-Results: {auth_header}\nDKIM-Signature: {signature}\n\nbody").encode()
        return BytesParser(policy=policy.default).parsebytes(raw)

    def test_dkim_requires_trusted_google_authserv(self):
        auth._trusted_dkim(self._message())
        with self.assertRaisesRegex(ValueError,"trusted_authentication_results_invalid"):
            auth._trusted_dkim(self._message("evil.example; dkim=pass header.i=@trip.com"))

    def test_dkim_rejects_wrong_signing_domain_and_conflicting_trusted_results(self):
        with self.assertRaisesRegex(ValueError,"selector_association"):
            auth._trusted_dkim(self._message(signature="v=1; d=evil.example; s=x; b=y"))
        message=self._message();message["Authentication-Results"]="mx.google.com; dkim=fail header.i=@trip.com"
        with self.assertRaisesRegex(ValueError,"trusted_authentication_results_invalid"):
            auth._trusted_dkim(message)

    def test_dkim_accepts_missing_header_d_only_with_selector_and_signature_binding(self):
        auth._trusted_dkim(self._message("mx.google.com; dkim=pass header.i=@trip.com header.s=x header.b=y"))
        auth._trusted_dkim(self._message('mx.google.com; dkim=pass header.i=@trip.com header.s=x header.b="y"'))
        with self.assertRaisesRegex(ValueError,"dkim_invalid"):
            auth._trusted_dkim(self._message("mx.google.com; dkim=pass header.i=@trip.com header.d=evil.example header.s=x header.b=y"))
        with self.assertRaisesRegex(ValueError,"selector_invalid"):
            auth._trusted_dkim(self._message("mx.google.com; dkim=pass header.i=@trip.com header.s=x"))

    def test_dkim_rejects_selector_mismatch_and_cross_clause_association(self):
        with self.assertRaisesRegex(ValueError,"selector_association"):
            auth._trusted_dkim(self._message(signature="v=1; d=trip.com; s=other; b=y"))
        with self.assertRaisesRegex(ValueError,"selector_association"):
            auth._trusted_dkim(self._message(signature="v=1; d=trip.com; s=x; b=other"))
        conflicting=("mx.google.com; dkim=pass header.i=@trip.com header.d=trip.com header.s=x; "
                     "dkim=pass header.i=@trip.com header.d=evil.example header.s=x header.b=y")
        with self.assertRaisesRegex(ValueError,"dkim_invalid"):
            auth._trusted_dkim(self._message(conflicting))

    def test_dkim_allows_unrelated_signature_but_rejects_competing_association(self):
        message=self._message()
        message["DKIM-Signature"]="v=1; d=amazonses.com; s=ses; b=unrelated"
        auth._trusted_dkim(message)
        message=self._message()
        message["DKIM-Signature"]="v=1; d=evil.example; s=x; b=y"
        with self.assertRaisesRegex(ValueError,"selector_association"):
            auth._trusted_dkim(message)
        message=self._message()
        message["DKIM-Signature"]="v=1; d=trip.com; s=other; b=other"
        with self.assertRaisesRegex(ValueError,"selector_association"):
            auth._trusted_dkim(message)

    def test_pdf_extractor_rejects_fake_executable_and_oversize(self):
        fake=self.root/"fake-python";fake.write_text("#!/bin/sh\nprintf x");os.chmod(fake,0o700)
        with self.assertRaisesRegex(ValueError,"runtime_invalid"):auth._extract_pdf(b"%PDF-1.4\n%%EOF",fake)
        with self.assertRaisesRegex(ValueError,"size_invalid"):auth._extract_pdf(b"%PDF-"+b"x"*(2*1024*1024)+b"%%EOF",Path(auth.PINNED_RUNTIME["requested_path"]))

    def test_pdf_runtime_rejects_package_tree_commitment_mutation(self):
        good=Path(auth.PINNED_RUNTIME["requested_path"])
        with mock.patch.dict(auth.PINNED_RUNTIME,{"pypdf_tree_sha256":"0"*64}):
            with self.assertRaisesRegex(ValueError,"runtime_invalid"):
                auth._validate_runtime(good)

    def test_pdf_extractor_rejects_active_empty_and_stderr(self):
        good=Path(auth.PINNED_RUNTIME["requested_path"]);pdf=b"%PDF-1.4\n%%EOF"
        cases=[
            subprocess.CompletedProcess([],0,b'{"active":true,"pages":1,"text":"x","version":"5.9.0"}\n',b""),
            subprocess.CompletedProcess([],0,b'{"active":false,"pages":1,"text":"","version":"5.9.0"}\n',b""),
            subprocess.CompletedProcess([],0,b'{"active":false,"pages":1,"text":"x","version":"5.9.0"}\n',b"noise"),
        ]
        for result in cases:
            with self.subTest(result=result),mock.patch.object(auth,"_validate_runtime",return_value=good),mock.patch.object(auth.subprocess,"run",return_value=result):
                with self.assertRaisesRegex(ValueError,"extractor_(?:contract|output)_invalid"):auth._extract_pdf(pdf,good)

    def test_pdf_extractor_timeout_fails_closed(self):
        good=Path(auth.PINNED_RUNTIME["requested_path"])
        with mock.patch.object(auth,"_validate_runtime",return_value=good),mock.patch.object(auth.subprocess,"run",side_effect=subprocess.TimeoutExpired("python",30)):
            with self.assertRaisesRegex(ValueError,"extraction_failed"):auth._extract_pdf(b"%PDF-1.4\n%%EOF",good)

    def test_package_capture_rejects_extra_file(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        for name in r44.FILES:
            p=package/name;p.write_bytes(b"x");os.chmod(p,0o600)
        p=package/"extra";p.write_bytes(b"x");os.chmod(p,0o600)
        with self.assertRaisesRegex(ValueError,"package_shape_invalid"):r44._capture(package)

    def test_reconcile_requires_identical_double_verification(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        expected={name:(name+"-expected").encode() for name in r44.FILES}
        for name,data in expected.items():p=package/name;p.write_bytes(data);os.chmod(p,0o600)
        parent_id=r44._fs_identity(self.root.stat());target_id=r44._fs_identity(package.stat())
        err=r44.PublicationDurabilityError(package,"d"*64,parent_id,target_id)
        with mock.patch.object(r44,"_build",return_value=({"package_set_sha256":"d"*64},expected)):
            result=r44.reconcile_publication(err,self.root,self.root/"p",self.root/"k",self.root/"py")
        self.assertTrue(result["durable"])

    def test_reconcile_rejects_wrong_package_identity(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        expected={name:(name+"-expected").encode() for name in r44.FILES}
        for name,data in expected.items():p=package/name;p.write_bytes(data);os.chmod(p,0o600)
        wrong_target=(package.stat().st_dev,package.stat().st_ino+1)
        err=r44.PublicationIntegrityError(package,"d"*64,r44._fs_identity(self.root.stat()),wrong_target)
        with mock.patch.object(r44,"_build",return_value=({"package_set_sha256":"d"*64},expected)):
            with self.assertRaisesRegex(ValueError,"target_identity_mismatch"):
                r44.reconcile_publication(err,self.root,self.root/"p",self.root/"k",self.root/"py")

    def test_reconcile_rejects_real_target_swap(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        expected={name:(name+"-expected").encode() for name in r44.FILES}
        for name,data in expected.items():p=package/name;p.write_bytes(data);os.chmod(p,0o600)
        err=r44.PublicationDurabilityError(package,"d"*64,r44._fs_identity(self.root.stat()),r44._fs_identity(package.stat()))
        package.rename(self.root/"old");package.mkdir();os.chmod(package,0o700)
        for name,data in expected.items():p=package/name;p.write_bytes(data);os.chmod(p,0o600)
        with mock.patch.object(r44,"_build",return_value=({"package_set_sha256":"d"*64},expected)):
            with self.assertRaisesRegex(ValueError,"target_identity_mismatch"):
                r44.reconcile_publication(err,self.root,self.root/"p",self.root/"k",self.root/"py")

    def test_actual_raw9_pdf_fresh_provenance_integration(self):
        root=Path("/tmp/cost-r44-trip-cancel-restricted.S2RPTC");python=Path("/tmp/cost-r43-pdf-venv/bin/python")
        if not root.exists() or not python.exists():self.skipTest("restricted R44 inputs unavailable")
        if (root/"provenance.v2.3.json").exists():
            result=auth.verify_provenance(root,root/"provenance.v2.3.json",root/"seal.key",python)
            self.assertEqual((result["status"],result["messages"],result["lifecycles"]),("valid",9,2))
        else:
            result=auth._fresh_unsigned(root,(root/"seal.key").read_bytes(),python)
            self.assertEqual((len(result["documents"]),result["relevant_lifecycle_count"]),(9,2))


if __name__=="__main__":unittest.main()
