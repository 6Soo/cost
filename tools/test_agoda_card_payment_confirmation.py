import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import agoda_card_payment_confirmation as confirmation


BASE_DB = Path("/tmp/classification-mvp-20260815/candidate.db")
STAGING_DB = Path("/tmp/agoda-2026-page-staging-20260815-final-r3.sqlite")
OUTPUT_DB = Path("/tmp/agoda-card-confirmation-20260815-v4/candidate.db")
REPORT = Path("/tmp/agoda-card-confirmation-20260815-v4/report.json")


class AgodaCardPaymentConfirmationTests(unittest.TestCase):
    def test_private_artifact_revalidates_against_base(self):
        if not all(path.exists() for path in (BASE_DB, STAGING_DB, OUTPUT_DB, REPORT)):
            self.skipTest("private Agoda candidate artifact is not present")
        result = confirmation.verify(
            base_db=BASE_DB,
            output_db=OUTPUT_DB,
            staging_db=STAGING_DB,
            report_path=REPORT,
        )
        self.assertEqual(result["confirmed_relation_count"], 5)
        self.assertEqual(result["held_relation_count"], 306)
        self.assertEqual(result["publication_status"], "private_candidate_only")

    def test_verify_rejects_tampered_report(self):
        if not all(path.exists() for path in (BASE_DB, STAGING_DB, OUTPUT_DB, REPORT)):
            self.skipTest("private Agoda candidate artifact is not present")
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "candidate.db"
            report = tmp_path / "report.json"
            shutil.copyfile(OUTPUT_DB, output)
            os.chmod(output, 0o600)
            payload = json.loads(REPORT.read_text(encoding="utf-8"))
            payload["held_booking_relations"] = 305
            report.write_bytes(confirmation._canonical(payload))
            os.chmod(report, 0o600)
            with self.assertRaisesRegex(ValueError, "confirmation_manifest_mismatch"):
                confirmation.verify(
                    base_db=BASE_DB,
                    output_db=output,
                    staging_db=STAGING_DB,
                    report_path=report,
                )

    def test_noreplace_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            final.write_bytes(b"old")
            with self.assertRaises(FileExistsError):
                confirmation._publish_noreplace(stage, final)
            self.assertEqual(final.read_bytes(), b"old")

    def test_noreplace_cleans_only_its_own_link_after_failure(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            with mock.patch.object(confirmation.os, "fsync", side_effect=OSError("test")):
                with self.assertRaises(OSError):
                    confirmation._publish_noreplace(stage, final)
            self.assertFalse(final.exists())

    def test_noreplace_does_not_delete_replaced_inode(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            real_lstat = confirmation.os.lstat
            final_lookup_count = 0

            def lstat_with_competitor(path):
                nonlocal final_lookup_count
                info = real_lstat(path)
                if Path(path) == final:
                    final_lookup_count += 1
                    if final_lookup_count <= 2:
                        return os.stat_result(
                            (
                                info.st_mode,
                                info.st_ino,
                                info.st_dev + 1,
                                info.st_nlink,
                                info.st_uid,
                                info.st_gid,
                                info.st_size,
                                info.st_atime,
                                info.st_mtime,
                                info.st_ctime,
                            )
                        )
                return info

            with mock.patch.object(confirmation.os, "lstat", side_effect=lstat_with_competitor):
                with self.assertRaisesRegex(RuntimeError, "published_inode_changed"):
                    confirmation._publish_noreplace(stage, final)
            self.assertEqual(final.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
