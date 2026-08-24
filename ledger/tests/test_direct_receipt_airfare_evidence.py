import copy
import hashlib
import json
import os
import tempfile
import unittest
from ledger.tests._platform import requires_posix_durability
from pathlib import Path
from unittest import mock

from ledger.domain import direct_receipt_airfare_evidence as r43


@requires_posix_durability()
class ReceiptAirfareEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);os.chmod(self.root,0o700)
        self.docs={};self.entries=[]
        facts={
            "1a5034f2897878b0b396a544d9337886eac85815729504400066152bb6905fc6":("26. 3. 14.","2026-03-14",793669),
            "fe0992319dd7cd96d6c1aa4134d4ec4ff04496d72351583d3c5aa1d24cc2cc29":("26. 2. 26.","2026-02-26",361924),
            "4792823347ceedb9e764952351c187ede6be26c03592e9d85d9551e729ba23a5":("March 24, 2026","2026-03-24",208400),
        }
        self.bindings={}
        serial=100
        for gid,cfg in r43.GROUPS.items():
            display_date,iso_date,amount=facts[gid]
            self.bindings[gid]=[]
            for alias in cfg["aliases"]:
                pdf=(b"%PDF-1.4\n"+alias.encode()+b"\n%%EOF")
                if cfg["provider"]=="mytrip_gotogate":
                    text=(f"주문 번호: {serial:04d}-123-456\nGotogate Korea LLC\n예약 일자: {display_date}\n영수증\nMASTERCARD Corporate\n"
                          +" ".join(cfg["service_tokens"])+f"\n결제 정보 요약\n설명 가격 세금 및 수수료 합계\n승객 {amount:,} KRW\n성인 성인\n항공편 {cfg['parts'][0]:,} KRW {cfg['parts'][1]:,} KRW {amount:,} KRW\n합계 {amount:,} KRW\n총계 {amount:,} KRW").encode()
                else:
                    text=(f"Trip.com Travel Singapore Pte. Ltd.\nBooking No. {serial:016d}\n예약번호\nDate of Booking: 6∶34 AM, {display_date} (GMT+8)\nReceipt\nKookmin Card\n"
                          +" ".join(cfg["service_tokens"])+f"\nFlights\na\nb\nc\nd\nFare\nTaxes & fees\nTrip.com booking fee\nKRW {cfg['parts'][0]:,}\nKRW {cfg['parts'][1]:,}\nKRW {cfg['parts'][2]:,}\nTotal (Kookmin Card (credit) 558526***35) KRW {amount:,}").encode()
                token=hashlib.sha256((gid+alias).encode()).hexdigest()
                self.bindings[gid].append({"event_key_sha256":token,"current_event_sha256":hashlib.sha256((token+"event").encode()).hexdigest(),
                    "current_source_sha256":hashlib.sha256((token+"source").encode()).hexdigest(),"current_source_locator_sha256":hashlib.sha256((token+"locator").encode()).hexdigest(),
                    "current_payload_sha256":hashlib.sha256((token+"payload").encode()).hexdigest(),"purchase_date":iso_date,"amount":amount,"provider":cfg["provider"]})
                serial+=1
                self.docs[alias]=(pdf,text)
                for suffix,data in (("pdf",pdf),("txt",text)):
                    p=self.root/f"{alias}.{suffix}";p.write_bytes(data);os.chmod(p,0o600)
                ps,ts=map(lambda b:hashlib.sha256(b).hexdigest(),(pdf,text))
                self.entries.append({"alias":alias,"attachment_name_hmac":hashlib.sha256((alias+"-file").encode()).hexdigest(),"document_id_hmac":hashlib.sha256((alias+"-document").encode()).hexdigest(),"pdf_sha256":ps,"text_sha256":ts,"message_id_hmac":hashlib.sha256((alias+"-message").encode()).hexdigest()})
        self.provenance=self.root/"provenance.json";self._write_provenance()
        self.pinned={a:(hashlib.sha256(p).hexdigest(),hashlib.sha256(t).hexdigest(),r43.DOCS[a][2]) for a,(p,t) in self.docs.items()}
        self.live={"package_set_sha256":r43.EXPECTED_R42_PACKAGE,"upstream":{"r36_package":r43.EXPECTED_R36_PACKAGE,"r38_package":r43.EXPECTED_R38_PACKAGE}}

    def tearDown(self):self.tmp.cleanup()
    def _write_provenance(self):
        data={"schema_version":1,"source_kind":"gmail_attachment","account_hmac":"a"*64,"extractor_contract_sha256":r43.EXTRACTOR_CONTRACT_SHA256,"documents":self.entries}
        self.provenance.write_text(json.dumps(data));os.chmod(self.provenance,0o600)
    def _build(self):
        with mock.patch.object(r43,"DOCS",self.pinned),mock.patch.object(r43,"_live_context",return_value=(self.live,self.bindings)),mock.patch.object(r43.r43auth,"verify_authenticated_inputs",return_value={"status":"valid","provenance":{"documents":self.entries}}):
            return r43._build(self.root,self.provenance,self.provenance,self.provenance)

    def test_exact_six_proposals_are_zero_authority(self):
        manifest,files=self._build()
        self.assertEqual((manifest["groups"],manifest["proposals"],manifest["full_classification_delta"],manifest["accepted_union"],manifest["incomplete_residual"]),(3,6,0,1528,3800))
        self.assertIn(b"airfare",files["documents.csv"])
        self.assertNotIn(b"event_id",files["proposals.csv"])
        self.assertIn(b"event_key_sha256",files["proposals.csv"])
        self.assertNotIn(b"@",b"".join(files.values()))

    def test_receipt_must_match_live_purchase_facts(self):
        next(iter(self.bindings.values()))[0]["amount"]+=1
        with self.assertRaisesRegex(ValueError,"receipt_live_fact_mismatch"):self._build()

    def test_partial_census_fails_closed(self):
        (self.root/"mytrip_a.pdf").unlink()
        with self.assertRaisesRegex(ValueError,"private_file_invalid"):self._build()

    def test_duplicate_reference_fails_closed(self):
        original=(self.root/"mytrip_a.txt").read_bytes();(self.root/"mytrip_b.txt").write_bytes(original);os.chmod(self.root/"mytrip_b.txt",0o600)
        self.pinned["mytrip_b"]=(self.pinned["mytrip_b"][0],hashlib.sha256(original).hexdigest(),1)
        next(x for x in self.entries if x["alias"]=="mytrip_b")["text_sha256"]=self.pinned["mytrip_b"][1];self._write_provenance()
        with self.assertRaisesRegex(ValueError,"duplicate_reference"):self._build()

    def test_swapped_document_fails_hash_binding(self):
        a=self.root/"mytrip_a.txt";b=self.root/"mytrip_c.txt";x=a.read_bytes();a.write_bytes(b.read_bytes());b.write_bytes(x)
        with self.assertRaisesRegex(ValueError,"document_bytes_invalid"):self._build()

    def test_public_pii_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"privacy_violation"):r43._privacy_scan({"manifest.json":b'{"email":"person@example.com"}'})

    def test_unordered_token_bag_is_rejected(self):
        gid=next(iter(r43.GROUPS));cfg=r43.GROUPS[gid]
        bag="Gotogate Korea LLC 주문 번호: 1000-123-456 예약 일자: 26. 3. 14. 영수증 MASTERCARD Corporate "+" ".join(cfg["service_tokens"])+" 673,969 119,700 총계 793,669 KRW"
        with self.assertRaisesRegex(ValueError,"provider_template_invalid"):r43._parse("attack",bag,cfg)

    def test_duplicate_provenance_identity_is_rejected(self):
        with mock.patch.object(r43,"DOCS",self.pinned),mock.patch.object(r43.r43auth,"verify_authenticated_inputs",side_effect=ValueError("r43_provenance_identity_invalid")):
            with self.assertRaisesRegex(ValueError,"provenance_identity_invalid"):r43._build(self.root,self.provenance,self.provenance,self.provenance)

    def test_extractor_contract_drift_is_rejected(self):
        with mock.patch.object(r43,"DOCS",self.pinned),mock.patch.object(r43.r43auth,"verify_authenticated_inputs",side_effect=ValueError("r43_extractor_contract_invalid")):
            with self.assertRaisesRegex(ValueError,"extractor_contract_invalid"):r43._build(self.root,self.provenance,self.provenance,self.provenance)

    def test_package_capture_rejects_extra_and_tampered_files(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        for name in r43.FILES:
            p=package/name;p.write_bytes(b"x");os.chmod(p,0o600)
        (package/"extra").write_bytes(b"x");os.chmod(package/"extra",0o600)
        with self.assertRaisesRegex(ValueError,"package_shape_invalid"):r43._capture_package(package)

    def test_publication_inside_repository_is_rejected(self):
        with mock.patch.object(r43,"_build",return_value=({},{})):
            with self.assertRaisesRegex(ValueError,"output_inside_repository"):
                r43.build_receipt_airfare_evidence(self.root,self.provenance,self.provenance,self.provenance,r43.REPOSITORY_ROOT/"forbidden-r43")

    def test_publication_never_replaces_existing_target(self):
        target=self.root/"existing";target.write_bytes(b"keep")
        with mock.patch.object(r43,"_build",return_value=({},{})):
            with self.assertRaises(FileExistsError):r43.build_receipt_airfare_evidence(self.root,self.provenance,self.provenance,self.provenance,target)
        self.assertEqual(target.read_bytes(),b"keep")

    def test_verifier_rejects_post_publication_tamper(self):
        package=self.root/"package";package.mkdir();os.chmod(package,0o700)
        expected={name:(name+"-expected").encode() for name in r43.FILES}
        for name,data in expected.items():
            p=package/name;p.write_bytes(data);os.chmod(p,0o600)
        (package/"groups.csv").write_bytes(b"tampered")
        with mock.patch.object(r43,"_build",return_value=({"package_set_sha256":"f"*64},expected)):
            with self.assertRaisesRegex(ValueError,"package_or_context_mismatch"):
                r43.verify_receipt_airfare_evidence(package,self.root,self.provenance,self.provenance,self.provenance)

    def test_actual_authenticated_mime_and_pdf_extraction_integration(self):
        root=Path("/tmp/cost-r43-evidence.tdApsq");python=Path("/tmp/cost-r43-pdf-venv/bin/python")
        if not (root/"provenance.v2.json").exists() or not python.exists():self.skipTest("restricted R43 integration inputs unavailable")
        result=r43.r43auth.verify_authenticated_inputs(root,root/"provenance.v2.json",root/"provenance.key",r43.DOCS,python)
        self.assertEqual((result["status"],result["documents"]),("valid",6))


if __name__=="__main__":unittest.main()
