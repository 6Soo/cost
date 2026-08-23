from __future__ import annotations

import json
import hashlib
import sqlite3
import unittest

from ledger.domain.agoda_card_reconciliation import (
    build_agoda_card_candidate_report,
)


def _schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_projection_runs(
          run_id TEXT PRIMARY KEY, status TEXT, input_manifest_sha256 TEXT
        );
        CREATE TABLE bookings(
          id INTEGER PRIMARY KEY, provider TEXT, booking_number TEXT,
          status TEXT NOT NULL DEFAULT 'completed'
        );
        CREATE TABLE direct_source_records(
          id INTEGER PRIMARY KEY, source_kind TEXT, source_key TEXT,
          source_sha256 TEXT, payload_json TEXT
        );
        CREATE TABLE booking_source_evidence(
          booking_id INTEGER, direct_source_record_id INTEGER,
          evidence_kind TEXT, evidence_status TEXT NOT NULL DEFAULT 'observed',
          conflict_count INTEGER NOT NULL DEFAULT 0,
          evidence_role TEXT NOT NULL DEFAULT 'portal_payment_claim'
        );
        CREATE TABLE direct_normalized_payments(
          id INTEGER PRIMARY KEY, source_record_id INTEGER,
          amount_krw INTEGER, transaction_type TEXT
        );
        CREATE TABLE direct_card_events(
          source_record_id INTEGER PRIMARY KEY, identity_status TEXT,
          source_system TEXT, amount_krw INTEGER, card_event_id TEXT
        );
        CREATE TABLE payment_transactions(
          id INTEGER PRIMARY KEY, external_key TEXT, source_system TEXT,
          transaction_type TEXT, currency TEXT, foreign_amount TEXT,
          amount_krw INTEGER
        );
        CREATE TABLE direct_payment_projection_links(
          run_id TEXT, direct_payment_id INTEGER, payment_id INTEGER
        );
        """
    )
    db.execute("INSERT INTO direct_projection_runs VALUES ('run-1','passed','manifest')")


def _portal(
    db: sqlite3.Connection,
    booking_id: int,
    booking_number: str,
    source_id: int,
    source_key: str,
    *,
    amount: int = 86411,
    currency: str = "JPY",
    card4: str | None = "8835",
    collection_model: str = "agoda_collect",
    claims: list[dict[str, object]] | None = None,
    components: list[dict[str, object]] | None = None,
    booking_status: str = "completed",
    evidence_status: str = "observed",
    conflict_count: int = 0,
    evidence_role: str = "portal_payment_claim",
    payload_overrides: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "provider": "agoda",
        "booking_number": booking_number,
        "collection_model": collection_model,
        "card_last4": card4,
    }
    if claims is not None:
        payload["portal_event_claims"] = claims
    else:
        payload["price_components"] = components or [{
            "kind": "paid_today", "currency": currency,
            "decimal_text": str(amount), "minor_units": amount, "scale": 0,
        }]
    payload.update(payload_overrides or {})
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_sha256 = hashlib.sha256(wire.encode("utf-8")).hexdigest()
    db.execute(
        "INSERT INTO bookings VALUES (?,?,?,?)",
        (booking_id, "agoda", booking_number, booking_status),
    )
    db.execute(
        "INSERT INTO direct_source_records VALUES (?,?,?,?,?)",
        (source_id, "agoda_portal_detail", source_key, source_sha256, wire),
    )
    db.execute(
        "INSERT INTO booking_source_evidence VALUES (?,?,?,?,?,?)",
        (booking_id, source_id, "agoda_portal_detail", evidence_status, conflict_count, evidence_role),
    )


def _card(
    db: sqlite3.Connection,
    payment_id: int,
    source_id: int,
    *,
    amount_krw: int = 0,
    currency: str = "JPY",
    foreign: str = "86411",
    card4: str | None = "8835",
    transaction_type: str = "purchase",
    identity_status: str = "unique",
    merchant: str = "AGODA.COM",
) -> None:
    payload = {
        "currency": currency,
        "foreign": foreign,
        "card4": card4,
        "merchant": merchant,
    }
    source_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    db.execute(
        "INSERT INTO direct_source_records VALUES (?,?,?,?,?)",
        (source_id, "card_raw", f"card-{source_id}", source_sha256, json.dumps(payload)),
    )
    db.execute(
        "INSERT INTO direct_normalized_payments VALUES (?,?,?,?)",
        (source_id, source_id, amount_krw, transaction_type),
    )
    db.execute(
        "INSERT INTO direct_card_events VALUES (?,?,?,?,?)",
        (source_id, identity_status, "KBO", amount_krw, f"event-{source_id}"),
    )
    db.execute(
        "INSERT INTO payment_transactions VALUES (?,?,?,?,?,?,?)",
        (payment_id, f"payment-{payment_id}", "KBO", transaction_type, currency, foreign, amount_krw),
    )
    db.execute("INSERT INTO direct_payment_projection_links VALUES ('run-1',?,?)", (source_id, payment_id))


def _attestation(db: sqlite3.Connection) -> dict[str, object]:
    hashes = sorted(
        str(row[0])
        for row in db.execute(
            """
            SELECT source_sha256
            FROM direct_source_records
            WHERE source_kind='agoda_portal_detail'
            ORDER BY id
            """
        )
    )
    digest = hashlib.sha256(
        json.dumps(hashes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "source_kind": "agoda_portal_detail",
        "record_count": len(hashes),
        "source_hashes": hashes,
        "source_hashes_sha256": digest,
    }


def _replace_card_payload(db: sqlite3.Connection, source_id: int, **updates: object) -> None:
    row = db.execute(
        "SELECT payload_json FROM direct_source_records WHERE id=?",
        (source_id,),
    ).fetchone()
    payload = json.loads(row[0])
    payload.update(updates)
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(wire.encode("utf-8")).hexdigest()
    db.execute(
        "UPDATE direct_source_records SET payload_json=?, source_sha256=? WHERE id=?",
        (wire, digest, source_id),
    )


class AgodaCardReconciliationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        _schema(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_unique_foreign_card4_is_only_proposed_candidate_and_db_is_unchanged(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        before = tuple(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "bookings", "direct_source_records", "payment_transactions", "direct_payment_projection_links"
        ))
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        after = tuple(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "bookings", "direct_source_records", "payment_transactions", "direct_payment_projection_links"
        ))
        self.assertEqual(before, after)
        self.assertEqual(len(report["proposed_individuals"]), 1)
        self.assertEqual(report["proposed_individuals"][0]["status"], "proposed")
        self.assertFalse(report["authority"]["creates_payment_booking_links"])

    def test_same_amount_many_to_many_remains_review_group(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1", card4=None)
        _portal(self.db, 2, "A-2", 12, "portal-2", card4=None)
        _card(self.db, 101, 21, card4=None)
        _card(self.db, 102, 22, card4=None)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(len(report["proposed_individuals"]), 0)
        self.assertEqual(len(report["review_groups"]), 1)
        self.assertFalse(report["review_groups"][0]["individual_pair_asserted"])

    def test_card4_mismatch_and_currency_mismatch_are_not_candidates(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1", card4="1111")
        _card(self.db, 101, 21, card4="2222")
        _portal(self.db, 2, "A-2", 12, "portal-2", currency="JPY", card4="3333")
        _card(self.db, 102, 22, currency="USD", foreign="86411", card4="3333")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertEqual(report["review_groups"], [])
        reasons = {item.get("reason") for item in report["held"]}
        self.assertTrue(
            reasons & {
                "card4_or_graph_conflict",
                "unbalanced_amount_candidate_cluster",
            }
        )

    def test_property_collect_and_refund_are_held_not_promoted(self) -> None:
        _portal(
            self.db, 1, "A-1", 11, "portal-1", collection_model="property_collect",
            components=[{"kind": "gross_total", "currency": "JPY", "decimal_text": "86411", "minor_units": 86411, "scale": 0}],
        )
        _portal(
            self.db, 2, "A-2", 12, "portal-2", claims=[{
                "event_kind": "refund", "currency": "JPY", "decimal_text": "86411",
                "minor_units": 86411, "scale": 0,
            }],
        )
        _card(self.db, 101, 21, transaction_type="refund")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(item.get("reason") == "no_actual_charge_claim" for item in report["held"]))
        self.assertTrue(any(item.get("reason") == "issuer_lifecycle_event_requires_review" for item in report["held"]))

    def test_missing_collection_model_is_review_candidate_not_proposed(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1", collection_model="")
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertEqual(len(report["amount_candidates"]), 1)
        self.assertTrue(any(
            item.get("reason") == "nonpromotable_competitor_in_closed_cluster"
            for item in report["held"]
        ))

    def test_unsealed_universe_never_proposes(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(self.db, run_id="run-1", universe_sealed=False)
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(item.get("reason") == "unsealed_universe" for item in report["held"]))

    def test_failed_card_projection_run_never_proposes(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        self.db.execute("UPDATE direct_projection_runs SET status='failed'")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(item.get("reason") == "card_projection_run_not_passed" for item in report["held"]))

    def test_lifecycle_and_evidence_guards_never_propose(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1", booking_status="cancelled")
        _portal(self.db, 2, "A-2", 12, "portal-2", evidence_status="rejected")
        _portal(self.db, 3, "A-3", 13, "portal-3", conflict_count=1)
        _card(self.db, 101, 21)
        _card(self.db, 102, 22)
        _card(self.db, 103, 23)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        reasons = {item.get("reason") for item in report["held"]}
        self.assertIn("booking_cancelled_requires_lifecycle_review", reasons)
        self.assertIn("portal_evidence_not_active", reasons)
        self.assertIn("portal_evidence_conflict", reasons)

    def test_missing_card_identity_event_never_proposes(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        self.db.execute("DELETE FROM direct_card_events")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(item.get("reason") == "card_identity_missing" for item in report["held"]))

    def test_missing_universe_attestation_never_proposes(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(self.db, run_id="run-1", universe_sealed=True)
        self.assertEqual(report["proposed_individuals"], [])
        self.assertFalse(report["universe_attestation_verified"])
        self.assertTrue(any(
            item.get("reason") == "universe_attestation_missing_or_invalid"
            for item in report["held"]
        ))

    def test_unlinked_portal_census_record_invalidates_sealed_universe(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        payload = {"provider": "agoda", "booking_number": "unlinked"}
        wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.db.execute(
            "INSERT INTO direct_source_records VALUES (?,?,?,?,?)",
            (99, "agoda_portal_detail", "unlinked", hashlib.sha256(wire.encode()).hexdigest(), wire),
        )
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertFalse(report["universe_sealed"])
        self.assertFalse(report["portal_census_linkage_verified"])
        self.assertIn(
            "portal_census_unlinked_record",
            {item.get("reason") for item in report["held"]},
        )

    def test_negative_portal_charge_never_matches_positive_card(self) -> None:
        _portal(
            self.db, 1, "A-1", 11, "portal-1",
            components=[{
                "kind": "paid_today", "currency": "JPY",
                "decimal_text": "-86411", "minor_units": -86411, "scale": 0,
            }],
        )
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(
            item.get("reason") == "portal_claim_amount_nonpositive"
            for item in report["held"]
        ))

    def test_negative_card_charge_never_matches_positive_portal(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21, foreign="-86411")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(
            item.get("reason") == "issuer_charge_amount_nonpositive"
            for item in report["held"]
        ))

    def test_non_payment_evidence_role_never_becomes_claim(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1", evidence_role="identity")
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertEqual(report["amount_candidates"], [])

    def test_payload_refund_lifecycle_never_proposes(self) -> None:
        _portal(
            self.db, 1, "A-1", 11, "portal-1",
            payload_overrides={
                "payment_status": "refunded",
                "refund_status": "full_or_unspecified",
            },
        )
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(
            item.get("reason") == "portal_lifecycle_requires_review"
            for item in report["held"]
        ))

    def test_unlisted_portal_lifecycle_status_never_proposes(self) -> None:
        _portal(
            self.db, 1, "A-1", 11, "portal-1",
            payload_overrides={"reservation_status": "refunded"},
        )
        _card(self.db, 101, 21)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "portal_lifecycle_requires_review",
            {item.get("reason") for item in report["held"]},
        )

    def test_portal_payload_digest_mismatch_never_proposes(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        row = self.db.execute(
            "SELECT payload_json FROM direct_source_records WHERE id=11",
        ).fetchone()
        payload = json.loads(row[0])
        payload["payment_status"] = "refunded"
        self.db.execute(
            "UPDATE direct_source_records SET payload_json=? WHERE id=11",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),),
        )
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "portal_source_payload_digest_invalid",
            {item.get("reason") for item in report["held"]},
        )

    def test_raw_and_canonical_card_amount_conflict_is_held(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21, amount_krw=100)
        self.db.execute("UPDATE payment_transactions SET amount_krw=200")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(
            item.get("reason") == "card_amount_canonical_conflict"
            for item in report["held"]
        ))

    def test_raw_and_canonical_card_currency_conflict_is_held(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        self.db.execute("UPDATE payment_transactions SET currency='USD', foreign_amount='1'")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True, universe_attestation=_attestation(self.db)
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertTrue(any(
            item.get("reason") == "card_currency_canonical_conflict"
            for item in report["held"]
        ))

    def test_raw_source_and_transaction_contract_conflicts_are_held(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21, amount_krw=800000)
        _replace_card_payload(self.db, 21, src="KBD", krw=800000, cancel=True)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "card_source_system_raw_conflict",
            {item.get("reason") for item in report["held"]},
        )

    def test_raw_cancel_flag_cannot_disagree_with_purchase_type(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21, amount_krw=800000)
        _replace_card_payload(self.db, 21, src="KBO", krw=800000, cancel=True)
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "card_raw_transaction_type_conflict",
            {item.get("reason") for item in report["held"]},
        )

    def test_invalid_raw_currency_cannot_shadow_canonical_currency(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1", currency="KRW", amount=800000)
        _card(self.db, 101, 21, amount_krw=800000, currency="JPY", foreign="86411")
        _replace_card_payload(self.db, 21, src="KBO", krw=800000, cancel=False, currency="BAD!")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "card_currency_raw_invalid",
            {item.get("reason") for item in report["held"]},
        )

    def test_non_agoda_merchant_never_proposes(self) -> None:
        for merchant in (
            "KURASHIKI IVYSQUARE",
            "NOTAGODA",
            "XAGODAY",
            "NOT AGODA",
            "PAYPAL AGODA",
            "AGODA가짜",
            "AGODAé",
        ):
            with self.subTest(merchant=merchant):
                db = sqlite3.connect(":memory:")
                try:
                    _schema(db)
                    _portal(db, 1, "A-1", 11, "portal-1")
                    _card(db, 101, 21, merchant=merchant)
                    report = build_agoda_card_candidate_report(
                        db, run_id="run-1", universe_sealed=True,
                        universe_attestation=_attestation(db),
                    )
                    self.assertEqual(report["proposed_individuals"], [])
                    self.assertIn(
                        "card_merchant_not_agoda",
                        {item.get("reason") for item in report["held"]},
                    )
                finally:
                    db.close()

    def test_observed_agoda_merchant_forms_remain_eligible(self) -> None:
        for merchant in (
            "AGODA.COM",
            "AGODA_NICE-Agoda",
            "아고다_나이스",
            "아고다페이먼츠코리아",
        ):
            with self.subTest(merchant=merchant):
                db = sqlite3.connect(":memory:")
                try:
                    _schema(db)
                    _portal(db, 1, "A-1", 11, "portal-1")
                    _card(db, 101, 21, merchant=merchant)
                    report = build_agoda_card_candidate_report(
                        db, run_id="run-1", universe_sealed=True,
                        universe_attestation=_attestation(db),
                    )
                    self.assertEqual(len(report["proposed_individuals"]), 1)
                finally:
                    db.close()

    def test_non_string_agoda_merchant_never_proposes(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        _replace_card_payload(self.db, 21, merchant=["AGODA"])
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "card_merchant_not_agoda",
            {item.get("reason") for item in report["held"]},
        )

    def test_empty_source_hashes_never_propose(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        self.db.execute("UPDATE direct_source_records SET source_sha256='' WHERE id=21")
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "card_source_payload_digest_invalid",
            {item.get("reason") for item in report["held"]},
        )

        self.db.execute(
            "UPDATE direct_source_records SET source_sha256='' WHERE id=11"
        )
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "portal_source_payload_digest_invalid",
            {item.get("reason") for item in report["held"]},
        )

    def test_malformed_and_mismatched_card_hashes_never_propose(self) -> None:
        for source_hash in ("abc", "g" * 64, 123):
            with self.subTest(source_hash=source_hash):
                db = sqlite3.connect(":memory:")
                try:
                    _schema(db)
                    _portal(db, 1, "A-1", 11, "portal-1")
                    _card(db, 101, 21)
                    db.execute(
                        "UPDATE direct_source_records SET source_sha256=? WHERE id=21",
                        (source_hash,),
                    )
                    report = build_agoda_card_candidate_report(
                        db, run_id="run-1", universe_sealed=True,
                        universe_attestation=_attestation(db),
                    )
                    self.assertEqual(report["proposed_individuals"], [])
                    self.assertIn(
                        "card_source_payload_digest_invalid",
                        {item.get("reason") for item in report["held"]},
                    )
                finally:
                    db.close()

        db = sqlite3.connect(":memory:")
        try:
            _schema(db)
            _portal(db, 1, "A-1", 11, "portal-1")
            _card(db, 101, 21)
            digest = db.execute(
                "SELECT source_sha256 FROM direct_source_records WHERE id=21"
            ).fetchone()[0]
            db.execute(
                "UPDATE direct_source_records SET source_sha256=? WHERE id=21",
                (f" {digest} ",),
            )
            report = build_agoda_card_candidate_report(
                db, run_id="run-1", universe_sealed=True,
                universe_attestation=_attestation(db),
            )
            self.assertEqual(report["proposed_individuals"], [])
            self.assertIn(
                "card_source_payload_digest_invalid",
                {item.get("reason") for item in report["held"]},
            )
        finally:
            db.close()

        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        row = self.db.execute(
            "SELECT payload_json FROM direct_source_records WHERE id=21"
        ).fetchone()
        payload = json.loads(row[0])
        payload["merchant"] = "AGODA.COM TAMPERED"
        self.db.execute(
            "UPDATE direct_source_records SET payload_json=? WHERE id=21",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")),),
        )
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(report["proposed_individuals"], [])
        self.assertIn(
            "card_source_payload_digest_invalid",
            {item.get("reason") for item in report["held"]},
        )

    def test_uppercase_valid_hashes_are_accepted(self) -> None:
        _portal(self.db, 1, "A-1", 11, "portal-1")
        _card(self.db, 101, 21)
        self.db.execute(
            "UPDATE direct_source_records SET source_sha256=upper(source_sha256)"
        )
        report = build_agoda_card_candidate_report(
            self.db, run_id="run-1", universe_sealed=True,
            universe_attestation=_attestation(self.db),
        )
        self.assertEqual(len(report["proposed_individuals"]), 1)


if __name__ == "__main__":
    unittest.main()
