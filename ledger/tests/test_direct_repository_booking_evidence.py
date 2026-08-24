import csv
import hashlib
import json
import os
import tempfile
import unittest
from ledger.tests._platform import requires_posix_durability
from unittest.mock import patch
from pathlib import Path
import io

import ledger.domain.direct_repository_booking_evidence as r27

from ledger.domain.direct_repository_booking_evidence import (
    EXPECTED_BOOKING_AMBIGUITIES,
    EXPECTED_BOOKING_NEW,
    EXPECTED_COUNTS,
    EXPECTED_OTA_AMBIGUITIES,
    EXPECTED_OTA_NEW,
    DISPOSITION,
    SENSITIVE_DENYLIST,
    _booking_tokens,
    _digits,
    _resolve_approval,
    _resolve_uid_first,
    _strict_json,
    _validate_bound_file,
    _validate_r26_upstream,
    R26_BOOKING_PERIODS_SHA256,
    build_repository_booking_evidence,
    verify_repository_booking_evidence,
)

ROOT = Path(__file__).resolve().parents[2]


def stat_mode(path):
    return path.stat().st_mode & 0o777


@requires_posix_durability()
class RepositoryBookingEvidenceTests(unittest.TestCase):
    def paths(self):
        manual = Path("/tmp/cost-r25-manual-v4.csv")
        if not manual.is_file():
            raise RuntimeError("real R27 integration precondition missing: /tmp/cost-r25-manual-v4.csv")
        return ROOT / "ledger/data/booking_info.json", ROOT / "ledger/data/ota_event_links_verified.json", manual

    def test_live_binding_package_and_authority(self):
        booking, ota, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "r27"
            protected = [booking, ota, ROOT / "ledger/data/classified_v14.csv", ROOT / "STATUS.md"]
            before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
            result = build_repository_booking_evidence(
                booking_info=booking, ota_links=ota, manual_csv=manual, output=out)
            self.assertEqual(before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected})
            self.assertEqual(result["manifest"]["counts"], EXPECTED_COUNTS)
            self.assertEqual(sorted(x.name for x in out.iterdir()),
                             ["ambiguities.csv", "coverage.csv", "manifest.json", "relations.csv"])
            with (out / "relations.csv").open(encoding="utf-8", newline="") as stream:
                relations = list(csv.DictReader(stream))
            self.assertEqual(len(relations), 6)
            booking_actual = {(r["booking_reference"], r["historical_uid"], r["approval_normalized"], r["direct_event_key"])
                              for r in relations if r["source_tier"] == "booking_info"}
            ota_actual = {(r["source_uid"], r["booking_reference"], r["approval_normalized"], r["direct_event_key"])
                          for r in relations if r["source_tier"] == "ota_event_links"}
            self.assertEqual(booking_actual, EXPECTED_BOOKING_NEW)
            self.assertEqual(ota_actual, EXPECTED_OTA_NEW)
            self.assertTrue(all(r["prior_union_member"] == "false" for r in relations))
            self.assertEqual({(r["authority_status"], r["posting_status"], r["confirmed_count"], r["gate5_credit"])
                              for r in relations}, {("unattested", "blocked", "0", "0")})
            self.assertEqual({r["disposition"] for r in relations}, {DISPOSITION})
            self.assertFalse(SENSITIVE_DENYLIST & set(relations[0]))
            with (out / "coverage.csv").open(encoding="utf-8", newline="") as stream:
                coverage = list(csv.DictReader(stream))
            self.assertEqual((len(coverage), sum(r["source_tier"] == "booking_info" for r in coverage),
                              sum(r["source_tier"] == "ota_event_links" for r in coverage)), (116, 53, 63))
            with (out / "ambiguities.csv").open(encoding="utf-8", newline="") as stream:
                ambiguities = list(csv.DictReader(stream))
            self.assertEqual(len(ambiguities), 12)
            self.assertTrue(all(len(r["source_row_sha256"]) == 64 for r in ambiguities))
            self.assertEqual({(r["historical_uid"], r["booking_reference"]) for r in ambiguities
                              if r["source_tier"] == "booking_info"}, EXPECTED_BOOKING_AMBIGUITIES)
            self.assertEqual({r["source_uid"] for r in ambiguities if r["source_tier"] == "ota_event_links"},
                             EXPECTED_OTA_AMBIGUITIES)
            self.assertEqual(verify_repository_booking_evidence(
                out, booking_info=booking, ota_links=ota, manual_csv=manual)["remaining_after"], 3820)
            self.assertEqual(result["manifest"]["ota_field_shape_count"], 21)
            self.assertEqual(stat_mode(out), 0o700)
            self.assertTrue(all(stat_mode(out / name) == 0o600 for name in ("manifest.json", "relations.csv", "coverage.csv", "ambiguities.csv")))
            out2 = Path(td) / "r27-second"
            second = build_repository_booking_evidence(booking_info=booking, ota_links=ota, manual_csv=manual, output=out2)
            self.assertEqual(result["manifest_sha256"], second["manifest_sha256"])
            self.assertEqual({p.name:p.read_bytes() for p in out.iterdir()}, {p.name:p.read_bytes() for p in out2.iterdir()})

    def test_no_replace_authority_tamper_and_symlink_fail_closed(self):
        booking, ota, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "r27"
            build_repository_booking_evidence(booking_info=booking, ota_links=ota, manual_csv=manual, output=out)
            with self.assertRaises(FileExistsError):
                build_repository_booking_evidence(booking_info=booking, ota_links=ota, manual_csv=manual, output=out)
            pristine = {name:(out / name).read_bytes() for name in ("manifest.json", "relations.csv", "coverage.csv", "ambiguities.csv")}
            rows = list(csv.DictReader(io.StringIO(pristine["relations.csv"].decode())))
            rows[0]["direct_event_key"] = rows[1]["direct_event_key"]
            stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
            forged_relations = stream.getvalue().encode(); (out / "relations.csv").write_bytes(forged_relations)
            forged_manifest = json.loads(pristine["manifest.json"]); forged_manifest["files"]["relations.csv"]["sha256"] = hashlib.sha256(forged_relations).hexdigest()
            forged_manifest["package_set_sha256"] = "0" * 64; (out / "manifest.json").write_text(json.dumps(forged_manifest))
            with self.assertRaisesRegex(ValueError, "semantics_mismatch"):
                verify_repository_booking_evidence(out, booking_info=booking, ota_links=ota, manual_csv=manual)
            for name, data in pristine.items(): (out / name).write_bytes(data)

            expected_manifest = json.loads(pristine["manifest.json"])
            for filename, old, new in (("relations.csv", b"hashidate", b"forged-group"),
                                       ("ambiguities.csv", b"TRIP-0170", b"TRIP-9999")):
                forged = pristine[filename].replace(old, new, 1); self.assertNotEqual(forged, pristine[filename])
                (out / filename).write_bytes(forged)
                with patch.object(r27, "_build", return_value=(expected_manifest, pristine)):
                    with self.assertRaisesRegex(ValueError, "semantics_mismatch"):
                        verify_repository_booking_evidence(out, booking_info=booking, ota_links=ota, manual_csv=manual)
                (out / filename).write_bytes(pristine[filename])
            for field, value in (("authority_status","attested"),("posting_status","ready"),("confirmed_count","1"),("gate5_credit","1")):
                rows = list(csv.DictReader(io.StringIO(pristine["relations.csv"].decode()))); rows[0][field] = value
                stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
                (out / "relations.csv").write_bytes(stream.getvalue().encode())
                with patch.object(r27, "_build", return_value=(expected_manifest, pristine)):
                    with self.assertRaisesRegex(ValueError, "semantics_mismatch"):
                        verify_repository_booking_evidence(out, booking_info=booking, ota_links=ota, manual_csv=manual)
                (out / "relations.csv").write_bytes(pristine["relations.csv"])
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8")); manifest["gate5_credit"] = 1
            (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "authority_boundary"):
                verify_repository_booking_evidence(out, booking_info=booking, ota_links=ota, manual_csv=manual)
            (out / "manifest.json").unlink(); (out / "manifest.json").symlink_to(out / "coverage.csv")
            with self.assertRaisesRegex(ValueError, "package_file"):
                verify_repository_booking_evidence(out, booking_info=booking, ota_links=ota, manual_csv=manual)

    def test_atomic_failure_boundaries(self):
        manifest = {"authority_status":"unattested", "posting_status":"blocked", "confirmed_count":0, "gate5_credit":0,
                    "analysis_run_id":"test"}
        files = {"manifest.json":json.dumps(manifest).encode(), "relations.csv":b"x\n", "coverage.csv":b"x\n", "ambiguities.csv":b"x\n"}
        dummy = Path("unused")
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            for failure in ("write", "file_fsync", "stage_fsync", "verify", "rename"):
                out = parent / failure
                with patch.object(r27, "_build", return_value=(manifest, files)):
                    if failure == "write": context = patch.object(Path, "open", side_effect=OSError("injected-write"))
                    elif failure == "file_fsync": context = patch.object(r27.os, "fsync", side_effect=OSError("injected-file-fsync"))
                    elif failure == "stage_fsync": context = patch.object(r27, "_fsync_directory", side_effect=OSError("injected-stage-fsync"))
                    elif failure == "verify": context = patch.object(r27, "verify_repository_booking_evidence", side_effect=ValueError("injected-verify"))
                    else: context = patch.object(r27, "_install_noreplace", side_effect=OSError("injected-rename"))
                    with context, self.assertRaises((OSError, ValueError)):
                        build_repository_booking_evidence(booking_info=dummy, ota_links=dummy, manual_csv=dummy, output=out)
                self.assertFalse(out.exists())
            out = parent / "parent-fsync"
            with patch.object(r27, "_build", return_value=(manifest, files)), \
                 patch.object(r27, "verify_repository_booking_evidence", return_value={"status":"valid"}), \
                 patch.object(r27, "_fsync_directory", side_effect=[None, OSError("injected-parent-fsync")]):
                with self.assertRaises(OSError):
                    build_repository_booking_evidence(booking_info=dummy, ota_links=dummy, manual_csv=dummy, output=out)
            self.assertTrue(out.is_dir())

    def test_token_approval_and_cardinality_contract(self):
        self.assertEqual(_booking_tokens("예약1400823535413714 plain 1400823535395178"), {"1400823535413714"})
        self.assertEqual((_digits("00123"), _digits("12-3"), _digits("000")), ("00123", "", ""))
        key = ("KB", "00123"); event = {"event":"e"}
        self.assertEqual(_resolve_approval({key:[{}]}, {key:[event]}, *key), (event,1,1))
        self.assertEqual(_resolve_approval({key:[{},{}]}, {key:[event]}, *key), (None,2,1))
        self.assertEqual(_resolve_approval({key:[{}]}, {key:[event,event]}, *key), (None,1,2))
        r23_event = {"event":"r23"}; approval_event = {"event":"approval"}
        resolved = _resolve_uid_first("UID", {"UID":"r23"}, {"r23":r23_event}, {key:[{}]}, {key:[approval_event]}, *key)
        self.assertEqual(resolved[:2], (r23_event, "r23_uid_existing"))
        self.assertEqual(_resolve_uid_first("OTHER", {"UID":"r23"}, {"r23":r23_event}, {key:[{}]}, {key:[approval_event]}, *key)[:2],
                         (approval_event, "approval_family_1x1"))
        self.assertEqual(_digits("１２３"), "")

    def test_duplicate_nonfinite_and_noncanonical_copy_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"; bad.write_text('{"x":1,"x":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate_key"): _strict_json(bad)
            bad.write_text('{"x":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nonfinite"): _strict_json(bad)
            booking, ota, manual = self.paths(); copied = Path(td) / "booking.json"; copied.write_bytes(booking.read_bytes())
            with self.assertRaisesRegex(ValueError, "noncanonical_booking_info"):
                build_repository_booking_evidence(booking_info=copied, ota_links=ota, manual_csv=manual)

    def test_hardlink_input_rejected(self):
        booking, ota, manual = self.paths()
        with tempfile.TemporaryDirectory() as td:
            linked = Path(td) / "manual.csv"; os.link(manual, linked)
            with self.assertRaisesRegex(ValueError, "manual_file_invalid"):
                build_repository_booking_evidence(booking_info=booking, ota_links=ota, manual_csv=linked)
            symlink = Path(td) / "booking.json"; symlink.symlink_to(booking)
            with self.assertRaisesRegex(ValueError, "booking_file_invalid"):
                build_repository_booking_evidence(booking_info=symlink, ota_links=ota, manual_csv=manual)

    def test_lightweight_r26_upstream_binding(self):
        canonical = ROOT / "ledger/data/booking_periods_verified.json"
        contract = _validate_r26_upstream(ROOT / "ledger")
        self.assertEqual(contract["booking_periods_sha256"], R26_BOOKING_PERIODS_SHA256)
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / canonical.name; copied.write_bytes(canonical.read_bytes())
            with self.assertRaisesRegex(ValueError, "noncanonical"):
                _validate_bound_file(copied, canonical, R26_BOOKING_PERIODS_SHA256, "test")
            copied.write_bytes(copied.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                _validate_bound_file(copied, copied, R26_BOOKING_PERIODS_SHA256, "test")
        with patch.object(r27.r26_contract, "RULE_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "code_contract_drift"):
                _validate_r26_upstream(ROOT / "ledger")


if __name__ == "__main__":
    unittest.main()
