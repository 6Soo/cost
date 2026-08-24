"""Adversarial and functional test suite for R42 document acquisition census."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from ledger.tests._platform import allow_pin_drift
from pathlib import Path
from unittest.mock import patch

from ledger.domain import direct_document_acquisition_census as r42

from ledger.domain.direct_document_acquisition_census import (
    ACCEPTED_UNION_COUNT,
    BROAD3533_EVENTS_COUNT,
    BULK_SEARCH_UNIVERSE_6741,
    PILOT_SEARCH_UNIVERSE_3820,
    PILOT_SEARCH_UNIVERSE_CORP,
    PORTAL_QUEUE_COMPONENTS_COUNT,
    REMAINING24_EVENTS_COUNT,
    REMAINING24_GROUPS_COUNT,
    REPOSITORY_ROOT,
    RESIDUAL_COUNT,
    TAXONOMY243_EVENTS_COUNT,
    TAXONOMY243_VAT_TAG_MISSING_COUNT,
    TAXONOMY243_VAT_TAG_PRESENT_UNATTESTED_COUNT,
    PublicationDurabilityError,
    PublicationIntegrityError,
    build_document_acquisition_census,
    check_privacy_compliance,
    reconcile_publication,
    validate_document_ingestion_gate,
    verify_document_acquisition_census,
)


@allow_pin_drift()
class TestDirectDocumentAcquisitionCensus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.live_bundle = r42._build()

    def test_build_manifest_structure_and_disposition(self):
        with patch.object(r42, "_build", return_value=self.live_bundle):
            res = build_document_acquisition_census()
        manifest = res["manifest"]
        self.assertEqual(manifest["artifact_type"], "r42-document-acquisition-census-v1")
        self.assertEqual(manifest["disposition"], "ACQUISITION_BLOCKED_NO_DOCUMENTS")
        self.assertEqual(manifest["full_classification_delta"], 0)
        self.assertEqual(manifest["vat_proposals"], 0)
        self.assertEqual(manifest["authority_status"], "unattested")
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertEqual(manifest["confirmed_count"], 0)
        self.assertEqual(manifest["gate5_credit"], 0)
        self.assertFalse(manifest["applied"])
        self.assertFalse(manifest["contains_sensitive_raw_values"])

        self.assertEqual(manifest["accepted_union"], ACCEPTED_UNION_COUNT)
        self.assertEqual(manifest["incomplete_residual"], RESIDUAL_COUNT)

        counts = manifest["frontier_counts"]
        self.assertEqual(counts["remaining24_events"], REMAINING24_EVENTS_COUNT)
        self.assertEqual(counts["remaining24_groups"], REMAINING24_GROUPS_COUNT)
        self.assertEqual(counts["taxonomy243_events"], TAXONOMY243_EVENTS_COUNT)
        self.assertEqual(counts["taxonomy243_vat_tag_present_unattested"], TAXONOMY243_VAT_TAG_PRESENT_UNATTESTED_COUNT)
        self.assertEqual(counts["taxonomy243_vat_tag_missing"], TAXONOMY243_VAT_TAG_MISSING_COUNT)
        self.assertEqual(counts["broad3533_events"], BROAD3533_EVENTS_COUNT)
        self.assertEqual(counts["portal_queue_components"], PORTAL_QUEUE_COMPONENTS_COUNT)
        self.assertEqual(counts["corp_search_universe"], PILOT_SEARCH_UNIVERSE_CORP)
        self.assertEqual(counts["card3820_search_universe"], PILOT_SEARCH_UNIVERSE_3820)
        self.assertEqual(counts["card6741_search_universe"], BULK_SEARCH_UNIVERSE_6741)
        self.assertEqual(counts["production_documents"], 0)
        self.assertEqual(counts["classification_candidates"], 0)

        # File shape
        files = manifest["files"]
        self.assertIn("frontier_groups.csv", files)
        self.assertEqual(files["frontier_groups.csv"]["rows"], REMAINING24_GROUPS_COUNT)
        self.assertEqual(files["documents.csv"]["rows"], 0)
        self.assertEqual(files["payment_edges.csv"]["rows"], 0)
        self.assertEqual(files["classification_candidates.csv"]["rows"], 0)
        self.assertEqual(files["rejections.csv"]["rows"], 0)

    def test_publish_verify_and_reconcile(self):
        with tempfile.TemporaryDirectory(prefix="r42-test-pub-") as td:
            output = Path(td) / "r42_pkg"
            with patch.object(r42, "_build", return_value=self.live_bundle):
                res = build_document_acquisition_census(output=output)
                self.assertEqual(res["output"], str(output))
                self.assertTrue(output.exists())

                # Verification
                ver = verify_document_acquisition_census(output)
                self.assertEqual(ver["status"], "valid")
                self.assertEqual(ver["disposition"], "ACQUISITION_BLOCKED_NO_DOCUMENTS")
                self.assertEqual(ver["package_set_sha256"], res["manifest"]["package_set_sha256"])

                # Durability reconciliation simulation
                err = PublicationDurabilityError(output, res["manifest"]["package_set_sha256"])
                rec = reconcile_publication(err)
                self.assertTrue(rec["published"])
                self.assertTrue(rec["durable"])
                self.assertEqual(rec["package_set_sha256"], res["manifest"]["package_set_sha256"])

    def test_publish_output_inside_repository_forbidden(self):
        inside_output = REPOSITORY_ROOT / "ledger" / "r42_test_pkg"
        with self.assertRaises(ValueError) as ctx:
            build_document_acquisition_census(output=inside_output)
        self.assertEqual(str(ctx.exception), "r42_output_inside_repository")

    def test_publish_output_exists_forbidden(self):
        with tempfile.TemporaryDirectory(prefix="r42-test-exists-") as td:
            existing_output = Path(td) / "existing_dir"
            existing_output.mkdir()
            with self.assertRaises(FileExistsError):
                build_document_acquisition_census(output=existing_output)

    def test_any_configured_document_directory_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="r42-docs-") as td:
            documents = Path(td)
            with self.assertRaisesRegex(ValueError, "r42_document_intake_not_implemented"):
                build_document_acquisition_census(documents_dir=documents)
            (documents / "receipt.bin").write_bytes(b"raw")
            with self.assertRaisesRegex(ValueError, "r42_document_intake_not_implemented"):
                build_document_acquisition_census(documents_dir=documents)

    def test_post_install_integrity_failure_is_explicit(self):
        manifest, files = self.live_bundle
        tampered = dict(files)
        tampered["manifest.json"] += b"x"
        with tempfile.TemporaryDirectory(prefix="r42-integrity-") as td:
            output = Path(td) / "package"
            with patch.object(r42, "_build", return_value=self.live_bundle), patch.object(
                r42, "_capture_package", side_effect=[files, tampered]
            ):
                with self.assertRaises(PublicationIntegrityError):
                    build_document_acquisition_census(output=output)
            self.assertTrue(output.exists())

    def test_parent_fsync_failure_is_explicit(self):
        real_fsync = os.fsync
        calls = 0

        def fail_parent(fd):
            nonlocal calls
            calls += 1
            if calls == len(r42.FILES) + 2:
                raise OSError("simulated parent fsync failure")
            return real_fsync(fd)

        with tempfile.TemporaryDirectory(prefix="r42-durability-") as td:
            output = Path(td) / "package"
            with patch.object(r42, "_build", return_value=self.live_bundle), patch.object(
                r42.os, "fsync", side_effect=fail_parent
            ):
                with self.assertRaises(PublicationDurabilityError):
                    build_document_acquisition_census(output=output)
            self.assertTrue(output.exists())

    def test_privacy_compliance_denylist(self):
        # Clean text
        check_privacy_compliance(json.dumps({"document_id": "doc_12345", "status": "ok"}))

        # Raw credit card number leak
        with self.assertRaises(ValueError) as ctx:
            check_privacy_compliance("Card number: 1234-5678-9012-3456")
        self.assertEqual(str(ctx.exception), "r42_privacy_denylist_violation")

        # URL / access token leak
        with self.assertRaises(ValueError) as ctx:
            check_privacy_compliance("Access link: https://portal.agoda.com/auth?token=secret123")
        self.assertEqual(str(ctx.exception), "r42_privacy_denylist_violation")

        # Email address leak
        with self.assertRaises(ValueError) as ctx:
            check_privacy_compliance("Guest contact: user@example.com")
        self.assertEqual(str(ctx.exception), "r42_privacy_denylist_violation")

    def test_adversarial_ingestion_gate_attacks(self):
        attacks = (
            (b"Approval 12345678 card4 3820 guest Kim token SECRET", {}, set(), set()),
            (b"raw", {"identity_binding_sha256": "a" * 64}, {"fabricated"}, {"fabricated"}),
            (b"raw", {"currency": "USD"}, {"evt1"}, {"evt1", "evt2"}),
        )
        for raw, metadata, covered, group in attacks:
            ok, reason = validate_document_ingestion_gate(
                raw, metadata, covered, group,
                has_jurisdiction_tax_evidence=True,
                has_exact_one_bucket=True,
                has_card_conflict=False,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "document_intake_parser_not_implemented")


if __name__ == "__main__":
    unittest.main()
