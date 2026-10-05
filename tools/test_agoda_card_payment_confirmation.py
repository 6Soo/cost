import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import prepare_review_template as publication


BASE_DB = Path("/tmp/classification-mvp-20260815/candidate.db")
STAGING_DB = Path("/tmp/agoda-2026-page-staging-20260815-final-r3.sqlite")
OUTPUT_DB = Path("/tmp/agoda-card-confirmation-20260815-v4/candidate.db")
REPORT = Path("/tmp/agoda-card-confirmation-20260815-v4/report.json")


class AgodaCardPaymentConfirmationTests(unittest.TestCase):
    def test_private_artifact_revalidates_against_base(self):
        if not all(path.exists() for path in (BASE_DB, STAGING_DB, OUTPUT_DB, REPORT)):
            self.skipTest("private Agoda candidate artifact is not present")
        # Historical private-artifact verification is not a startup dependency
        # of the current synthetic publication tests.
        from tools import agoda_card_payment_confirmation as confirmation
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
        from tools import agoda_card_payment_confirmation as confirmation
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
            # Keep the no-overwrite contract against a current repository CLI,
            # rather than restoring the removed private candidate builder.
            with self.assertRaises(publication._CliError) as caught:
                publication._publish(str(final), stage.read_bytes(), [])
            self.assertEqual(caught.exception.code, publication.CODE_OUTPUT_EXISTS)
            self.assertEqual(final.read_bytes(), b"old")
            self.assertEqual(stage.read_bytes(), b"new")

    def test_noreplace_cleans_only_its_own_link_after_failure(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            failure = publication._CliError(publication.CODE_INPUT_CHANGED_DURING_READ)
            # The input changes after the hard link was published. Only that
            # link may be removed during rollback.
            with mock.patch.object(publication, "_reverify", side_effect=[None, failure]):
                with self.assertRaises(publication._CliError) as caught:
                    publication._publish(str(final), stage.read_bytes(), [object()])
            self.assertEqual(caught.exception.code, failure.code)
            self.assertFalse(final.exists())
            self.assertEqual(list(root.iterdir()), [stage])

    def test_noreplace_does_not_delete_replaced_inode(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            checks = 0

            def reverify_with_competitor(_input):
                nonlocal checks
                checks += 1
                if checks == 2:
                    final.unlink()
                    final.write_bytes(b"other process")
                    raise publication._CliError(publication.CODE_INPUT_CHANGED_DURING_READ)

            with mock.patch.object(publication, "_reverify", side_effect=reverify_with_competitor):
                with self.assertRaises(publication._CliError) as caught:
                    publication._publish(str(final), stage.read_bytes(), [object()])
            self.assertEqual(caught.exception.code, publication.CODE_INPUT_CHANGED_DURING_READ)
            self.assertEqual(final.read_bytes(), b"other process")
            self.assertEqual(stage.read_bytes(), b"new")
            self.assertEqual(set(root.iterdir()), {stage, final})


if __name__ == "__main__":
    unittest.main()
