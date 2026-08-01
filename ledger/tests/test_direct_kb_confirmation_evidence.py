import csv
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ledger.domain import direct_kb_confirmation_evidence as r45


PIN = Path("/tmp/cost-r45-kb-pinned-v4.2SR9yH")
ENVELOPES = Path("/tmp/cost-r45-kb-usage.5V8jJg")


class KBConfirmationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.bindings = []
        for index, (key, content) in enumerate(r45.EVENTS.items()):
            self.bindings.append({"key": key, "event_key_sha256": r45._sha(key.encode()),
                                  "current_event_sha256": content,
                                  "current_source_sha256": f"{index + 1:064x}",
                                  "current_payload_sha256": f"{index + 21:064x}"})
        self.remaining = [{"direct_event_key": f"safe-{i}", "current_event_sha256": f"{i + 40:064x}",
                           "group_id": f"{i + 80:064x}", "group_member_set_sha256": f"{i + 120:064x}",
                           "reason_code": "still_deferred"} for i in range(21)]

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self):
        residual = set(r45.EVENTS) | {f"residual-{i}" for i in range(3797)}
        with mock.patch.object(r45, "verify_private_pin", return_value={
                "private_pin_set_sha256": "a" * 64, "member_count": 3, "delivery_count": 23,
                "unique_envelope_count": 19, "duplicate_pairs": 4,
                "decrypted_fact_attestation": "session-asserted-artifact-pinned"}), \
             mock.patch.object(r45, "_live", return_value=(self.bindings, self.remaining, residual)), \
             mock.patch.object(r45, "_trip_contract", return_value="b" * 64):
            return r45._build(self.root, self.root)

    def _copy_private(self, source, destination):
        destination.mkdir(mode=0o700)
        for item in source.iterdir():
            target = destination / item.name
            target.write_bytes(item.read_bytes())
            os.chmod(target, 0o600)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_actual_private_pin_and_envelopes_verify(self):
        result = r45.verify_private_pin(PIN, ENVELOPES)
        self.assertEqual((result["member_count"], result["delivery_count"],
                          result["unique_envelope_count"], result["duplicate_pairs"]), (3, 23, 19, 4))

    def test_exact_atomic_three_delta_and_no_edges(self):
        manifest, files = self._build()
        proposals = list(csv.DictReader(io.StringIO(files["proposals.csv"].decode())))
        self.assertEqual((len(proposals), manifest["accepted_union"], manifest["global_residual"],
                          manifest["frontier_authoritative"], manifest["full_classification_delta"]),
                         (3, 1531, 3797, 21, 3))
        self.assertEqual(manifest["post_admission_accepted_set_sha256"], r45.POST_ACCEPTED_SET)
        self.assertEqual(manifest["post_admission_residual_set_sha256"], r45.POST_RESIDUAL_SET)
        self.assertEqual(manifest["remaining_frontier_set_sha256"],
                         r45._setsha(row["direct_event_key"] for row in self.remaining))
        self.assertEqual(manifest["remaining_frontier_group_count"], 10)
        self.assertEqual({(row["bijection_asserted"], row["individual_relation_count"],
                           row["atomic_member_count"]) for row in proposals}, {("false", "0", "3")})
        self.assertEqual({(row["account"], row["cost_type"], row["vat_tag"], row["trip_target"])
                          for row in proposals}, {("여행원가", "숙박비", "불공제_해외", "0613_북해도")})
        self.assertFalse(manifest["database_applied"])
        self.assertTrue(manifest["adjacent_group_unchanged"])

    def test_partial_group_fails_atomic(self):
        self.bindings.pop()
        with self.assertRaisesRegex(ValueError, "permutation_invariance_invalid"):
            self._build()

    def test_public_output_has_no_private_values(self):
        _manifest, files = self._build()
        blob = b"".join(files.values()).decode()
        for pattern in (r"(?<![0-9a-f])8835(?![0-9a-f])",
                        r"(?<![0-9A-Fa-f])\d{6}(?![0-9A-Fa-f])",
                        r"(?<![0-9a-f])410621(?![0-9a-f])", r"(?<![0-9a-f])43200(?![0-9a-f])",
                        r"(?<![0-9a-f])205309(?![0-9a-f])", r"(?<![0-9a-f])21600(?![0-9a-f])",
                        r"AGODA", r"NEW AKAN", r"KBO:E:", r"주식회사"):
            self.assertIsNone(re.search(pattern, blob, re.I))

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_private_target_fact_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            pin = Path(td)
            os.chmod(pin, 0o700)
            for source in PIN.iterdir():
                target = pin / source.name
                target.write_bytes(source.read_bytes())
                os.chmod(target, 0o600)
            record = pin / "15.json"
            record.write_bytes(record.read_bytes().replace(b"410,621", b"410,622"))
            os.chmod(record, 0o600)
            with self.assertRaisesRegex(ValueError, "hash_invalid"):
                r45.verify_private_pin(pin, ENVELOPES)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_envelope_duplicate_group_swap_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            envelopes = root / "envelopes"
            envelopes.mkdir(mode=0o700)
            for source in ENVELOPES.iterdir():
                target = envelopes / source.name
                target.write_bytes(source.read_bytes())
                os.chmod(target, 0o600)
            three = (envelopes / "03.html").read_bytes()
            eleven = (envelopes / "11.html").read_bytes()
            (envelopes / "03.html").write_bytes(eleven)
            (envelopes / "11.html").write_bytes(three)
            with self.assertRaisesRegex(ValueError, "duplicate_census_invalid"):
                r45.verify_private_pin(PIN, envelopes)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_private_unknown_file_and_hardlink_reject(self):
        pin = self.root / "pin"
        self._copy_private(PIN, pin)
        extra = pin / "99.json"
        extra.write_bytes(b"{}")
        os.chmod(extra, 0o600)
        with self.assertRaisesRegex(ValueError, "pin_census_invalid"):
            r45.verify_private_pin(pin, ENVELOPES)
        extra.unlink()
        (pin / "15.json").unlink()
        os.link(pin / "17.json", pin / "15.json")
        with self.assertRaisesRegex(ValueError, "private_file_invalid"):
            r45.verify_private_pin(pin, ENVELOPES)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_private_symlink_reject(self):
        pin = self.root / "pin"
        self._copy_private(PIN, pin)
        (pin / "15.json").unlink()
        os.symlink(pin / "17.json", pin / "15.json")
        with self.assertRaises(OSError):
            r45.verify_private_pin(pin, ENVELOPES)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_private_duplicate_json_key_and_nonfinite_reject(self):
        for injected in (b'{"format_version":1,"format_version":1,"members":[]}',
                         b'{"format_version":NaN,"members":[]}'):
            pin = self.root / ("pin-" + r45._sha(injected)[:8])
            self._copy_private(PIN, pin)
            manifest = pin / "manifest.json"
            manifest.write_bytes(injected)
            os.chmod(manifest, 0o600)
            with self.assertRaises(ValueError):
                r45.verify_private_pin(pin, ENVELOPES)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_forged_dom_and_manifest_rehash_still_rejects(self):
        pin = self.root / "forged-pin"
        self._copy_private(PIN, pin)
        record_path = pin / "15.json"
        record = json.loads(record_path.read_text())
        record["decrypted_dom_html"] += "<!-- forged -->"
        record["decrypted_dom_sha256"] = r45._sha(record["decrypted_dom_html"].encode())
        record_bytes = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        record_path.write_bytes(record_bytes)
        os.chmod(record_path, 0o600)
        manifest_path = pin / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        member = next(row for row in manifest["members"] if row["private_record_filename"] == "15.json")
        member["decrypted_dom_sha256"] = record["decrypted_dom_sha256"]
        member["private_record_sha256"] = r45._sha(record_bytes)
        manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False,
                                              separators=(",", ":")) + "\n").encode())
        os.chmod(manifest_path, 0o600)
        with self.assertRaisesRegex(ValueError, "pin_manifest_hash_invalid"):
            r45.verify_private_pin(pin, ENVELOPES)

    @unittest.skipUnless(PIN.is_dir() and ENVELOPES.is_dir(), "restricted R45 evidence unavailable")
    def test_unknown_private_record_field_rejects(self):
        pin = self.root / "unknown-field-pin"
        self._copy_private(PIN, pin)
        record_path = pin / "15.json"
        record = json.loads(record_path.read_text())
        record["capture_complete"] = True
        record_path.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.chmod(record_path, 0o600)
        with self.assertRaises(ValueError):
            r45.verify_private_pin(pin, ENVELOPES)

    def test_public_schema_has_no_low_entropy_locator_digest(self):
        manifest, files = self._build()
        names = set(manifest)
        for data in files.values():
            if data.startswith(b"{"):
                names.update(json.loads(data))
            elif data:
                names.update(next(csv.reader(io.StringIO(data.decode()))))
        self.assertNotIn("current_source_locator_sha256", names)

    def test_raw_signature_census_rejects_same_signature_added_or_cancelled(self):
        base = {"src": "KBO", "card4": "8835", "currency": "JPY", "foreign": 43200,
                "merchant": "AGODA.COM NEW AKAN H", "krw": 410621,
                "cancel": False, "cancel_amount": 0}
        rows = [(key, dict(base)) for key in ("KBO:E:1477", "KBO:E:1478", "KBO:E:1480")]
        r45._validate_raw_target_census(rows)
        with self.assertRaisesRegex(ValueError, "raw_target_census_invalid"):
            r45._validate_raw_target_census(rows + [("KBO:E:9999", dict(base))])
        cancelled = dict(base, cancel=True, cancel_amount=410621)
        with self.assertRaisesRegex(ValueError, "raw_target_census_invalid"):
            r45._validate_raw_target_census(rows + [("KBO:E:9999", cancelled)])

    def test_publication_is_external_only_and_no_replace(self):
        target = self.root / "package"
        with mock.patch.object(r45, "_build", return_value=({"package_set_sha256": "c" * 64},
                                                             {name: name.encode() for name in r45.FILES})):
            result = r45.build_kb_confirmation_evidence(self.root, self.root, target)
            self.assertEqual(result["output"], str(target))
            with self.assertRaises(FileExistsError):
                r45.build_kb_confirmation_evidence(self.root, self.root, target)

    def test_post_install_mutation_is_integrity_error_and_reconcile_fails(self):
        target = self.root / "mutated-package"
        files = {name: name.encode() for name in r45.FILES}
        built = ({"package_set_sha256": "c" * 64}, files)
        original = r45._capture_dirfd
        calls = 0

        def mutate_on_target(dirfd):
            nonlocal calls
            calls += 1
            if calls == 2:
                fd = os.open("groups.csv", os.O_WRONLY | os.O_TRUNC, dir_fd=dirfd)
                os.write(fd, b"mutated")
                os.close(fd)
            return original(dirfd)

        with mock.patch.object(r45, "_build", return_value=built), \
             mock.patch.object(r45, "_capture_dirfd", side_effect=mutate_on_target):
            with self.assertRaises(r45.PublicationIntegrityError) as raised:
                r45.build_kb_confirmation_evidence(self.root, self.root, target)
        with mock.patch.object(r45, "_build", return_value=built):
            with self.assertRaisesRegex(ValueError, "reconcile_target_identity_mismatch"):
                r45.reconcile_publication(raised.exception, self.root, self.root)

    def test_parent_fsync_failure_is_reconcilable_durability_error(self):
        target = self.root / "durability-package"
        files = {name: name.encode() for name in r45.FILES}
        built = ({"package_set_sha256": "d" * 64}, files)
        real_fsync = os.fsync
        calls = 0

        def fail_parent_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == len(r45.FILES) + 2:
                raise OSError("injected parent fsync failure")
            return real_fsync(fd)

        with mock.patch.object(r45, "_build", return_value=built), \
             mock.patch.object(r45.os, "fsync", side_effect=fail_parent_fsync):
            with self.assertRaises(r45.PublicationDurabilityError) as raised:
                r45.build_kb_confirmation_evidence(self.root, self.root, target)
        with mock.patch.object(r45, "_build", return_value=built):
            result = r45.reconcile_publication(raised.exception, self.root, self.root)
        self.assertEqual((result["published"], result["durable"]), (True, True))

    def test_verifier_rejects_package_tamper(self):
        manifest, files = self._build()
        package = self.root / "verify"
        package.mkdir(mode=0o700)
        for name, data in files.items():
            path = package / name
            path.write_bytes(data)
            os.chmod(path, 0o600)
        (package / "groups.csv").write_bytes(b"tamper")
        with mock.patch.object(r45, "_build", return_value=(manifest, files)):
            with self.assertRaisesRegex(ValueError, "package_or_context_mismatch"):
                r45.verify_kb_confirmation_evidence(package, self.root, self.root)


if __name__ == "__main__":
    unittest.main()
