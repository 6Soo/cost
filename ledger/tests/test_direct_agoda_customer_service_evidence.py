import csv
import copy
import io
import os
import re
import tempfile
import unittest
from ledger.tests._platform import requires_posix_durability
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

from ledger.domain import direct_agoda_customer_service_evidence as r49


PRIVATE = Path("/tmp/cost-r49-agoda-private.DLx7ES")


@requires_posix_durability()
class AgodaCustomerServiceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.provider = {"provider_row_sha256": "1" * 64,
                         "provider_census_sha256": "2" * 64,
                         "signed_header_sha256": "6" * 64,
                         "transport_sha256": "3" * 64}
        self.binding = (json.loads((PRIVATE / "binding.json").read_text()) if PRIVATE.is_dir() else {
            "format_version": 1, "nonce": "a" * 64, "provider_date": "1.2",
            "foreign_amount": "987654321", "booking_reference": "private-ref-fixture",
            "subject_booking_reference": "unrelated-ref-fixture",
            "manual": {"tab": r49.TRIP_TARGET, "row": "1", "date": "entry-date",
                       "item": "private-item-fixture", "desc": "lodging", "card": "issuer",
                       "amount": "123456789.0"},
            "event": {"source_key": "private-source-fixture", "raw_record_id": "private-raw-fixture",
                      "occurred_on": "2026-01-02", "posted_on": "2026-01-03",
                      "source_system": "FIXTURE", "source_kind": "fixture", "event_role": "single",
                      "transaction_type": "purchase", "currency": "ZZZ", "krw": 123456789,
                      "card4": "9876", "merchant": "private-merchant-fixture"},
            "supplier_footer": {"company": "private-company-fixture", "address": "private-address-fixture"},
        })
        self.manual = dict(self.binding["manual"],book=self.binding["booking_reference"])
        self.event = {"current_source_sha256": "4" * 64}
        self.payload = {"redacted": "fixture"}

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self):
        with mock.patch.object(r49, "_read_private", return_value=(b"pinned", self.binding)), \
             mock.patch.object(r49, "_parse_provider_message", return_value=self.provider), \
             mock.patch.object(r49, "_manual_and_trip", return_value=(self.manual, "5" * 64)), \
             mock.patch.object(r49, "_live", return_value=(self.event, self.payload)):
            return r49._build(self.root)

    @unittest.skipUnless(PRIVATE.is_dir(), "restricted R49 evidence unavailable")
    def test_actual_raw_mime_auth_and_semantic_row(self):
        raw,binding = r49._read_private(PRIVATE)
        parsed = r49._parse_provider_message(raw,binding)
        self.assertEqual(len(raw), r49.RAW_MIME_BYTES)
        self.assertEqual(parsed["provider_row_sha256"],
                         "5c74fa046d0649cc4188e6fb557461b24719f1cff9eeff42b318e24264f29917")
        self.assertEqual(parsed["provider_census_sha256"],
                         "1aee568ddd83fee96095d7ed907d5ff93f5889bdf4daa79a1f56550d8ab7127a")

    @unittest.skipUnless(PRIVATE.is_dir(), "restricted R49 evidence unavailable")
    def test_subject_reference_cannot_cross_bind_target_row(self):
        raw,binding = r49._read_private(PRIVATE)
        message = BytesParser(policy=policy.default).parsebytes(raw)
        del message["Subject"]
        message["Subject"] = "Agoda Booking ID " + self.binding["booking_reference"]
        changed = message.as_bytes(policy=policy.SMTP)
        with self.assertRaisesRegex(ValueError, "dkim_(?:body|signature)_invalid"):
            r49._parse_provider_message(changed,binding)

    @unittest.skipUnless(PRIVATE.is_dir(), "restricted R49 evidence unavailable")
    def test_row_column_or_auth_mutation_rejects(self):
        raw,binding = r49._read_private(PRIVATE)
        foreign=self.binding["foreign_amount"].encode()
        changed_foreign=str(int(self.binding["foreign_amount"])+1).encode()
        for changed, reason in ((raw.replace(b">"+foreign+b"</td>", b">"+changed_foreign+b"</td>", 1), "dkim_body_invalid"),
                                (raw.replace(b"dkim=pass", b"dkim=fail", 1), "transport_auth_observation_invalid")):
            with self.assertRaisesRegex(ValueError, reason):
                r49._parse_provider_message(changed,binding)

    def test_singleton_delta_and_manual_date_is_non_authoritative(self):
        manifest, files = self._build()
        mappings = list(csv.DictReader(io.StringIO(files["mappings.csv"].decode())))
        proposals = list(csv.DictReader(io.StringIO(files["proposals.csv"].decode())))
        self.assertEqual((manifest["full_classification_delta"], manifest["accepted_union"],
                          manifest["global_residual"], len(mappings), len(proposals)), (1, 1532, 3796, 1, 1))
        self.assertEqual(mappings[0]["manual_date_role"], "legacy_entry_date_non_authoritative")
        self.assertEqual(manifest["manual_date_authority"], "not_used")
        self.assertEqual((proposals[0]["account"], proposals[0]["cost_type"],
                          proposals[0]["vat_tag"], proposals[0]["trip_target"]),
                         ("숙박비", "여행원가", "불공제_해외", "0620_묘코"))
        self.assertFalse(manifest["database_applied"])
        self.assertEqual(manifest["trip_attribution_basis"],
                         "authenticated_provider_reference_to_authoritative_manual_tab")
        self.assertEqual(manifest["service_period_evidence"], "none_asserted_or_used")

    def test_manual_trip_and_provider_event_date_joins_fail_closed(self):
        wrong_manual=dict(self.binding["manual"]);wrong_manual["tab"]=r49.TRIP_TARGET+"_wrong"
        with self.assertRaisesRegex(ValueError,"manual_trip_join_invalid"):
            r49._validate_manual_trip_join(wrong_manual)
        wrong_date=copy.deepcopy(self.binding)
        month,day=map(int,str(wrong_date["provider_date"]).split("."))
        wrong_date["provider_date"]=f"{month}.{day % 28 + 1}"
        with self.assertRaisesRegex(ValueError,"provider_event_date_join_invalid"):
            r49._validate_provider_event_date(wrong_date)

    def test_public_package_has_no_sensitive_values_or_locators(self):
        _manifest, files = self._build()
        blob = b"".join(files.values()).decode()
        sensitive=[self.binding["booking_reference"],self.binding["foreign_amount"],
                   str(self.binding["event"]["krw"]),self.binding["event"]["card4"],
                   self.binding["event"]["merchant"]]
        for pattern in (r"card:[0-9a-f]{64}#", r"KBO:E:", r"https?://", r"message-id", r"booking",
                        *(re.escape(value) for value in sensitive)):
            self.assertIsNone(re.search(pattern, blob, re.I), pattern)

    @unittest.skipUnless(PRIVATE.is_dir(), "restricted R49 evidence unavailable")
    def test_private_mode_unknown_file_symlink_and_hardlink_reject(self):
        for kind in ("mode", "extra", "symlink", "hardlink"):
            root = self.root / kind
            root.mkdir(mode=0o700)
            target = root / "message.eml"
            target.write_bytes((PRIVATE / "message.eml").read_bytes()); os.chmod(target, 0o600)
            binding_target=root/"binding.json";binding_target.write_bytes((PRIVATE/"binding.json").read_bytes());os.chmod(binding_target,0o600)
            if kind == "mode": os.chmod(target, 0o644)
            elif kind == "extra":
                extra = root / "extra"; extra.write_bytes(b"x"); os.chmod(extra, 0o600)
            elif kind == "symlink":
                target.unlink(); os.symlink(PRIVATE / "message.eml", target)
            elif kind == "hardlink":
                other = root / "other"; os.link(target, other); other.unlink()
                # nlink returns to one after unlink; retain the link under an allowed-name-impossible
                # extra path so the exact-name census and link-count both reject.
                os.link(target, root / "extra")
            with self.assertRaises((ValueError, OSError)):
                r49._read_private(root)

    def test_output_inside_repository_and_existing_target_reject(self):
        with mock.patch.object(r49, "_build", return_value=self._build()):
            with self.assertRaisesRegex(ValueError, "output_inside_repository"):
                r49.build_agoda_customer_service_evidence(self.root,
                    output=Path(__file__).resolve().parent / "forbidden-r49")
            existing = self.root / "existing"; existing.mkdir()
            with self.assertRaises(FileExistsError):
                r49.build_agoda_customer_service_evidence(self.root, output=existing)

    def test_atomic_external_publication_and_tamper_detection(self):
        expected = self._build()
        output = self.root / "published"
        with mock.patch.object(r49, "_build", return_value=expected):
            result = r49.build_agoda_customer_service_evidence(self.root, output=output)
        self.assertEqual(result["manifest"]["full_classification_delta"], 1)
        self.assertEqual(stat_mode(output), 0o700)
        self.assertEqual({stat_mode(item) for item in output.iterdir()}, {0o600})
        (output / "proposals.csv").write_bytes(b"tampered\n")
        with mock.patch.object(r49, "_build", return_value=expected):
            with self.assertRaises(ValueError):
                r49.verify_agoda_customer_service_evidence(output, self.root)

    def test_zero_write_fails_without_publishing(self):
        expected=self._build(); output=self.root/"zero-write"
        with mock.patch.object(r49,"_build",return_value=expected), \
             mock.patch.object(r49.os,"write",return_value=0), \
             self.assertRaisesRegex(OSError,"short_write_zero"):
            r49.build_agoda_customer_service_evidence(self.root,output)
        self.assertFalse(output.exists())

    def test_physical_duplicate_event_rejects_before_dict_collapse(self):
        row={"direct_event_key":"opaque"}
        with self.assertRaisesRegex(ValueError,"current_duplicate_event"):
            r49._unique_event_map([row,dict(row)])

    def test_parent_fsync_failure_is_typed_and_reconcilable(self):
        expected=self._build();output=self.root/"durable";real=os.fsync;calls=0
        def fail(fd):
            nonlocal calls;calls+=1
            if calls==len(r49.FILES)+2: raise OSError("parent fsync")
            return real(fd)
        with mock.patch.object(r49,"_build",return_value=expected),mock.patch.object(r49.os,"fsync",side_effect=fail), \
             self.assertRaises(r49.PublicationDurabilityError) as caught:
            r49.build_agoda_customer_service_evidence(self.root,output)
        self.assertTrue(output.is_dir())
        with mock.patch.object(r49,"_build",return_value=expected):
            self.assertTrue(r49.reconcile_publication(caught.exception,self.root)["durable"])

    def test_parent_path_swap_is_integrity_error(self):
        expected=self._build();parent=self.root/"parent";parent.mkdir();output=parent/"pkg"
        moved=self.root/"moved";real=os.fsync;calls=0
        def swap(fd):
            nonlocal calls;calls+=1
            if calls==len(r49.FILES)+2:
                parent.rename(moved);parent.mkdir();(parent/"pkg").mkdir();(parent/"pkg"/"sentinel").write_text("x")
            return real(fd)
        with mock.patch.object(r49,"_build",return_value=expected),mock.patch.object(r49.os,"fsync",side_effect=swap), \
             self.assertRaises(r49.PublicationIntegrityError):
            r49.build_agoda_customer_service_evidence(self.root,output)
        self.assertTrue((output/"sentinel").is_file())

    def test_target_name_swap_during_parent_fsync_is_integrity_error(self):
        expected=self._build();output=self.root/"selector";moved=self.root/"genuine";real=os.fsync;calls=0
        def swap(fd):
            nonlocal calls;calls+=1
            if calls==len(r49.FILES)+2:
                output.rename(moved);output.mkdir();(output/"sentinel").write_text("x")
            return real(fd)
        with mock.patch.object(r49,"_build",return_value=expected),mock.patch.object(r49.os,"fsync",side_effect=swap), \
             self.assertRaises(r49.PublicationIntegrityError):
            r49.build_agoda_customer_service_evidence(self.root,output)
        self.assertTrue((output/"sentinel").is_file())

    def test_reconcile_rejects_target_name_swap_during_fsync(self):
        expected=self._build();output=self.root/"reconcile-selector"
        with mock.patch.object(r49,"_build",return_value=expected):
            r49.build_agoda_customer_service_evidence(self.root,output)
        parent_identity=r49.r45._identity(os.stat(self.root,follow_symlinks=False))
        target_identity=r49.r45._identity(os.stat(output,follow_symlinks=False))
        error=r49.PublicationDurabilityError(output,expected[0]["package_set_sha256"],parent_identity,target_identity)
        moved=self.root/"reconcile-genuine";real=os.fsync
        def swap(fd):
            output.rename(moved);output.mkdir();(output/"sentinel").write_text("x")
            return real(fd)
        with mock.patch.object(r49,"_build",return_value=expected),mock.patch.object(r49.os,"fsync",side_effect=swap), \
             self.assertRaisesRegex(ValueError,"reconcile_identity_changed"):
            r49.reconcile_publication(error,self.root)


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
