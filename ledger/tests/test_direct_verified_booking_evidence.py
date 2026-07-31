import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_verified_booking_evidence import EXPECTED_RELATIONS, TARGET_FACT, _booking_tokens, _digits, _load_json, _resolve_approval, _validate_fact, _validate_target_message, build_verified_booking_evidence, verify_verified_booking_evidence


ROOT = Path(__file__).resolve().parents[2]


class VerifiedBookingEvidenceTests(unittest.TestCase):
    def paths(self):
        manual = Path("/tmp/cost-r25-manual-v4.csv")
        if not manual.is_file(): raise RuntimeError("real R26 integration precondition missing: /tmp/cost-r25-manual-v4.csv")
        return ROOT / "ledger/data/booking_periods_verified.json", ROOT / "ledger/data/ota_mail_index.json", manual

    def test_binding_counts_relations_and_conflicts(self):
        periods, mail, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "annex"
            protected = [ROOT / "ledger/data/booking_periods_verified.json", ROOT / "ledger/data/ota_mail_index.json", ROOT / "ledger/data/classified_v14.csv", ROOT / "STATUS.md"]
            before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
            result = build_verified_booking_evidence(booking_periods=periods, ota_mail=mail, manual_csv=manual, output=out)
            self.assertEqual(before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected})
            counts = result["manifest"]["counts"]
            self.assertEqual(counts, {"facts":13,"linked_unique_events":19,"r23_duplicate":11,"r25_union_overlap":5,"r26_only_events":3,"new_booking_relations":7,"ambiguous":0,"remaining_before":3829,"remaining_after":3826})
            with (out / "relations.csv").open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual((len(rows), sum(r["r25_union_member"] == "true" for r in rows), sum(r["date_conflict"] == "true" for r in rows)), (7, 4, 1))
            self.assertEqual(len({r["approval_normalized"] for r in rows}), 7)
            self.assertEqual({(r["historical_uid"], r["approval_normalized"], r["direct_event_key"]) for r in rows}, EXPECTED_RELATIONS)
            self.assertTrue(all(r["issuer_subtype_mismatch"] == "true" for r in rows))
            self.assertEqual({r["authority_status"] for r in rows}, {"unattested"})
            self.assertEqual(verify_verified_booking_evidence(out, booking_periods=periods, ota_mail=mail, manual_csv=manual)["r26_only_events"], 3)

    def test_tamper_and_no_replace_fail_closed(self):
        periods, mail, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "annex"
            build_verified_booking_evidence(booking_periods=periods, ota_mail=mail, manual_csv=manual, output=out)
            with self.assertRaises(FileExistsError): build_verified_booking_evidence(booking_periods=periods, ota_mail=mail, manual_csv=manual, output=out)
            manifest = json.loads((out / "manifest.json").read_text()); manifest["gate5_credit"] = 1; (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): verify_verified_booking_evidence(out, booking_periods=periods, ota_mail=mail, manual_csv=manual)

    def test_exact_token_and_approval_cardinality_fail_closed(self):
        self.assertEqual(_booking_tokens("예약1400824130566434 / x14008241305664349"), {"1400824130566434"})
        self.assertEqual(_booking_tokens("plain 1400824130566434"), set())
        key = ("KB", "123")
        event = {"direct_event_key": "event"}
        self.assertEqual(_resolve_approval({key:[{}]}, {key:[event]}, *key), event)
        self.assertIsNone(_resolve_approval({key:[{},{}]}, {key:[event]}, *key))
        self.assertIsNone(_resolve_approval({key:[{}]}, {key:[event,event]}, *key))
        self.assertIsNone(_resolve_approval({key:[{}]}, {key:[event]}, "KB", ""))
        self.assertEqual((_digits("00123"), _digits("12-3"), _digits("000")), ("00123", "", ""))

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"; path.write_text('{"x":1,"x":2}')
            with self.assertRaisesRegex(ValueError, "duplicate_key"):
                _load_json(path)
            path.write_text('{"x":NaN}')
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                _load_json(path)

    def test_fact_and_target_mail_semantics_fail_closed(self):
        _validate_fact("1400824130566434", TARGET_FACT)
        for bad in ({"category": [], "period":"0414_0415", "source":"x"}, {"category":"기타", "period":"0414_0415", "source":"x"}, {"category":"숙박", "period":"0230_0301", "source":"x"}, {"category":"숙박", "period":"0415_0414", "source":"x"}):
            with self.assertRaises(ValueError): _validate_fact("1400824130566434", bad)
        _, mail = self.paths()[:2]
        records = json.loads(mail.read_text())["records"]
        target = next(r for r in records if "1400824130566434" in r.get("bookingRefs", []))
        _validate_target_message(target)
        for field, value in (("messageHash","x"),("redactionVersion","wrong"),("travelDates",["0414"]),("bookingRefs",["1400824130566434", "1400824130566434"])):
            bad = dict(target); bad[field] = value
            with self.assertRaises(ValueError): _validate_target_message(bad)

    def test_canonical_evidence_copy_rejected(self):
        periods, mail, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            forged = Path(td) / "booking.json"; forged.write_bytes(periods.read_bytes())
            with self.assertRaisesRegex(ValueError, "noncanonical_booking_periods"):
                build_verified_booking_evidence(booking_periods=forged, ota_mail=mail, manual_csv=manual)

    def test_symlink_and_unknown_manifest_field_rejected(self):
        periods, mail, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "annex"
            build_verified_booking_evidence(booking_periods=periods, ota_mail=mail, manual_csv=manual, output=out)
            manifest = json.loads((out / "manifest.json").read_text()); manifest["unknown"] = True; (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): verify_verified_booking_evidence(out, booking_periods=periods, ota_mail=mail, manual_csv=manual)
            (out / "manifest.json").unlink(); (out / "manifest.json").symlink_to(out / "coverage.csv")
            with self.assertRaises(ValueError): verify_verified_booking_evidence(out, booking_periods=periods, ota_mail=mail, manual_csv=manual)


if __name__ == "__main__": unittest.main()
