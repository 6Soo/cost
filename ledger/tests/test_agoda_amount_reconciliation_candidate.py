from __future__ import annotations

import hashlib
import sqlite3
import json
import os
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from tools.agoda_amount_candidate_graph import PaymentAmount, ReservationAmount
from tools.agoda_amount_reconciliation_candidate import (
    PaymentEvidence,
    ReconciliationError,
    ReservationEvidence,
    _create_tables,
    _apply_card_coverage,
    _foreign_minor_units,
    build,
    _insert_results,
)


def reservation(key: str, booking_id: str) -> ReservationEvidence:
    return ReservationEvidence(
        node=ReservationAmount(
            key=key,
            currency="JPY",
            amount_minor_units=86411,
            card4="3820",
        ),
        booking_id=booking_id,
        booking_id_sha256=(booking_id * 64)[:64],
        booking_pseudonym_hmac=("h" + booking_id * 64)[:64],
        service_start_on="2026-04-01",
        service_end_on="2026-04-02",
        source_scope_status="target_2026_overlap",
        detail_scope_status="target_2026_overlap",
        evidence_kind="paid_today",
        semantic_detail_sha256=("s" + booking_id * 64)[:64],
    )


def payment(key: str, payment_id: int) -> PaymentEvidence:
    return PaymentEvidence(
        node=PaymentAmount(
            key=key,
            currency="JPY",
            amount_minor_units=86411,
            card4="3820",
        ),
        payment_id=payment_id,
        occurred_on="2026-03-01",
        direct_event_key_sha256=("d" * 63) + str(payment_id),
        source_sha256=("e" * 63) + str(payment_id),
    )


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE payment_transactions(id INTEGER PRIMARY KEY);
        CREATE TABLE bookings(
          id INTEGER PRIMARY KEY, provider TEXT, booking_number TEXT,
          product_type TEXT, label TEXT, service_start_on TEXT,
          service_end_on TEXT, status TEXT, UNIQUE(provider,booking_number)
        );
        CREATE TABLE booking_identifiers(
          id INTEGER PRIMARY KEY, booking_id INTEGER, provider TEXT,
          identifier TEXT, identifier_type TEXT, identifier_status TEXT,
          rule_id TEXT, first_seen_document_id INTEGER,
          last_seen_document_id INTEGER, superseded_by_document_id INTEGER,
          UNIQUE(booking_id,provider,identifier,identifier_type)
        );
        CREATE TABLE source_documents(
          id INTEGER PRIMARY KEY, source_kind TEXT, path TEXT, sha256 TEXT,
          UNIQUE(source_kind,path,sha256)
        );
        CREATE TABLE payment_booking_links(
          payment_id INTEGER, booking_id INTEGER, relation_type TEXT,
          confidence REAL, link_status TEXT, first_seen_document_id INTEGER,
          last_seen_document_id INTEGER, superseded_by_document_id INTEGER,
          PRIMARY KEY(payment_id,booking_id,relation_type)
        );
        """
    )
    connection.executemany(
        "INSERT INTO payment_transactions(id) VALUES (?)", [(1,), (2,)]
    )
    _create_tables(connection)
    return connection


def integration_base(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE direct_projection_runs(run_id TEXT,status TEXT,created_at TEXT);
        CREATE TABLE payment_transactions(
          id INTEGER PRIMARY KEY, occurred_on TEXT, transaction_type TEXT,
          amount_krw INTEGER, merchant TEXT, currency TEXT, foreign_amount TEXT
        );
        CREATE TABLE direct_promotion_evidence(
          direct_event_key TEXT,source_sha256 TEXT,run_id TEXT,evidence_kind TEXT,
          authority_status TEXT,source_kind TEXT,source_key TEXT
        );
        CREATE TABLE direct_normalized_payments(
          id INTEGER PRIMARY KEY,source_record_id INTEGER,event_role TEXT,card_event_id TEXT
        );
        CREATE TABLE direct_payment_projection_links(
          run_id TEXT,direct_payment_id INTEGER,payment_id INTEGER
        );
        CREATE TABLE direct_source_records(
          id INTEGER PRIMARY KEY,source_kind TEXT,source_key TEXT,
          source_sha256 TEXT,payload_json TEXT
        );
        CREATE TABLE bookings(
          id INTEGER PRIMARY KEY,provider TEXT,booking_number TEXT,product_type TEXT,
          label TEXT,service_start_on TEXT,service_end_on TEXT,status TEXT,
          UNIQUE(provider,booking_number)
        );
        CREATE TABLE booking_identifiers(
          id INTEGER PRIMARY KEY,booking_id INTEGER,provider TEXT,identifier TEXT,
          identifier_type TEXT,identifier_status TEXT,rule_id TEXT,
          first_seen_document_id INTEGER,last_seen_document_id INTEGER,
          superseded_by_document_id INTEGER,
          UNIQUE(booking_id,provider,identifier,identifier_type)
        );
        CREATE TABLE source_documents(
          id INTEGER PRIMARY KEY,source_kind TEXT,path TEXT,sha256 TEXT,
          UNIQUE(source_kind,path,sha256)
        );
        CREATE TABLE payment_booking_links(
          payment_id INTEGER,booking_id INTEGER,relation_type TEXT,confidence REAL,
          link_status TEXT,first_seen_document_id INTEGER,last_seen_document_id INTEGER,
          superseded_by_document_id INTEGER,
          PRIMARY KEY(payment_id,booking_id,relation_type)
        );
        INSERT INTO direct_projection_runs VALUES ('base','failed','2026-08-15');
        INSERT INTO payment_transactions VALUES
          (1,'2026-07-20','purchase',900000,'AGODA','JPY','86411');
        INSERT INTO direct_source_records VALUES
          (1,'card_raw','source','source-sha',
           '{"card4":"3820","currency":"JPY","foreign_amount":"86411"}');
        INSERT INTO direct_normalized_payments VALUES (1,1,'purchase','event');
        INSERT INTO direct_payment_projection_links VALUES ('base',1,1);
        INSERT INTO direct_promotion_evidence VALUES
          ('event#purchase','source-sha','base','current_card','current_raw','card_raw','source');
        """
    )
    connection.commit()
    connection.close()


def integration_detail(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sealed_manifest(
          run_id TEXT,booking_count INTEGER,target_2026_count INTEGER,
          competitor_count INTEGER,membership_set_sha256 TEXT,policy_sha256 TEXT
        );
        CREATE TABLE capture_run_manifest(
          run_id TEXT,epoch_status TEXT,final_revalidation_sha256 TEXT,
          target_count INTEGER,target_2026_count INTEGER,competitor_count INTEGER,
          source_capture_set_sha256 TEXT
        );
        CREATE TABLE booking_detail_snapshots(
          snapshot_id INTEGER PRIMARY KEY,run_id TEXT,booking_id TEXT,
          booking_id_sha256 TEXT,booking_pseudonym_hmac TEXT,
          source_scope_status TEXT,detail_scope_status TEXT,
          reservation_status TEXT,refund_status TEXT,collection_model TEXT,
          card4 TEXT,detail_service_start_on TEXT,detail_service_end_on TEXT,
          semantic_detail_sha256 TEXT
        );
        CREATE TABLE price_components(
          snapshot_id INTEGER,ordinal INTEGER,component_kind TEXT,currency TEXT,
          amount_minor_units INTEGER
        );
        CREATE TABLE payment_events(
          event_id INTEGER PRIMARY KEY,snapshot_id INTEGER,event_kind TEXT,
          currency TEXT,amount_minor_units INTEGER
        );
        INSERT INTO sealed_manifest VALUES
          ('detail',1,1,0,'membership','policy');
        INSERT INTO capture_run_manifest VALUES
          ('detail','complete','revalidated',1,1,0,
           'pppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp');
        INSERT INTO booking_detail_snapshots VALUES
          (1,'detail','booking-1',
           '1111111111111111111111111111111111111111111111111111111111111111',
           'hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh',
           'target_2026_overlap','target_2026_overlap','confirmed',
           'none_displayed','agoda_collect','3820','2026-04-01','2026-04-02',
           'ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss');
        INSERT INTO price_components VALUES (1,1,'paid_today','JPY',86411);
        INSERT INTO price_components VALUES (1,2,'gross_total','JPY',86411);
        """
    )
    connection.commit()
    connection.close()
    os.chmod(path, 0o600)


def integration_detail_with_terminal_no_price(path: Path) -> None:
    integration_detail(path)
    connection = sqlite3.connect(path)
    pseudonym = "q" * 64
    membership_hash = hashlib.sha256(
        json.dumps([pseudonym], separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    connection.executescript(
        f"""
        ALTER TABLE sealed_manifest ADD COLUMN price_snapshot_count INTEGER;
        ALTER TABLE sealed_manifest ADD COLUMN terminal_no_price_count INTEGER;
        ALTER TABLE sealed_manifest ADD COLUMN amount_universe_sealed INTEGER;
        UPDATE sealed_manifest
        SET booking_count=2, target_2026_count=2, price_snapshot_count=1,
            terminal_no_price_count=1, amount_universe_sealed=0;
        UPDATE capture_run_manifest
        SET target_count=2, target_2026_count=2;
        CREATE TABLE page_attestations(
          attestation_id INTEGER,run_id TEXT,tab_name TEXT,page_no INTEGER,
          phase TEXT,expected_selected_page INTEGER,observed_selected_page INTEGER,
          ordered_membership_sha256 TEXT,set_membership_sha256 TEXT,
          source_page_set_sha256 TEXT
        );
        INSERT INTO page_attestations VALUES(
          1,'detail','Cancelled',1,'before_click',1,1,
          '{membership_hash}',
          '{membership_hash}',
          'pppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp'
        );
        CREATE TABLE page_attestation_members(
          attestation_id INTEGER,ordinal INTEGER,
          booking_pseudonym_hmac TEXT,list_card_sha256 TEXT
        );
        INSERT INTO page_attestation_members VALUES(
          1,1,'{pseudonym}',
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'
        );
        CREATE TABLE booking_detail_observations(
          booking_id_sha256 TEXT,booking_pseudonym_hmac TEXT,
          run_id TEXT,tab_name TEXT,page_no INTEGER,
          list_card_sha256 TEXT,list_attestation_id INTEGER,
          attested_ordered_membership_sha256 TEXT,
          attested_set_membership_sha256 TEXT,
          attested_source_page_set_sha256 TEXT,
          source_service_start_on TEXT,source_service_end_on TEXT,
          source_reservation_status TEXT,detail_service_start_on TEXT,
          detail_service_end_on TEXT,reservation_status TEXT,
          detail_reservation_status TEXT,observation_kind TEXT,
          payment_information_present INTEGER,gross_total_present INTEGER,
          visible_money_value_count INTEGER,amount_matching_eligible INTEGER,
          unresolved_competitor INTEGER,semantic_detail_sha256 TEXT
        );
        INSERT INTO booking_detail_observations VALUES(
          '2222222222222222222222222222222222222222222222222222222222222222',
          '{pseudonym}',
          'detail','Cancelled',1,
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
          1,
          '{membership_hash}',
          '{membership_hash}',
          'pppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp',
          '2026-05-01','2026-05-02','Cancelled',
          '2026-05-01','2026-05-02','cancelled','unknown',
          'price_evidence_not_displayed',1,0,0,0,1,
          'tttttttttttttttttttttttttttttttttttttttttttttttttttttttttttt'
        );
        """
    )
    connection.commit()
    connection.close()
    os.chmod(path, 0o600)


class AgodaAmountReconciliationCandidateTests(unittest.TestCase):
    def base_kwargs(self) -> dict[str, object]:
        return {
            "reconciliation_run_id": "run",
            "detail": {
                "path": Path("/tmp/detail.sqlite"),
                "sha256": "a" * 64,
                "run_id": "detail",
                "booking_count": 2,
                "price_snapshot_count": 2,
                "terminal_no_price_count": 0,
                "amount_universe_sealed": True,
                "target_2026_count": 2,
                "competitor_count": 0,
                "evidence_kind_counts": {"paid_today": 2},
            },
            "cards": {
                "sha256": "b" * 64,
                "run_id": "base",
                "coverage_end": "2026-07-20",
                "current_card_count": 2,
                "agoda_payment_count": 2,
                "coverage_card_count": 1,
            },
            "policy_sha256": "c" * 64,
            "report_sha256": "d" * 64,
        }

    def test_foreign_card_amount_uses_currency_minor_units_without_float(self) -> None:
        self.assertEqual(_foreign_minor_units("88,564", "JPY"), 88564)
        self.assertEqual(_foreign_minor_units("44.75", "USD"), 4475)
        self.assertEqual(_foreign_minor_units("1,234.56", "EUR"), 123456)
        self.assertIsNone(_foreign_minor_units("12.345", "USD"))

    def test_individual_authority_creates_only_proposed_generic_link(self) -> None:
        connection = database()
        left = reservation("r1", "1")
        right = payment("p1", 1)
        graph = {
            "amount_candidates": (
                {
                    "reservation_key": "r1",
                    "payment_key": "p1",
                    "signature": ("charge", "JPY", 86411),
                    "match_method": "foreign_amount_card4",
                },
            ),
            "confirmed_individuals": (
                {
                    "reservation_key": "r1",
                    "payment_key": "p1",
                    "signature": ("charge", "JPY", 86411),
                    "tier": "foreign_amount_card4_forced",
                },
            ),
            "confirmed_groups": (),
            "held": (),
        }
        counts = _insert_results(
            connection,
            reservation_evidence=(left,),
            payment_evidence=(right,),
            graph=graph,
            **self.base_kwargs(),
        )
        self.assertEqual(counts["individual"], 1)
        self.assertEqual(
            connection.execute(
                "SELECT link_status FROM payment_booking_links"
            ).fetchone()[0],
            "proposed",
        )
        self.assertEqual(
            connection.execute(
                "SELECT relation_status FROM direct_agoda_amount_individual_authorities"
            ).fetchone()[0],
            "confirmed",
        )
        connection.close()

    def test_service_after_current_card_event_coverage_is_held(self) -> None:
        item = replace(reservation("r1", "1"), service_end_on="2026-07-25")
        held = _apply_card_coverage((item,), "2026-07-20")[0]
        self.assertFalse(held.node.promotion_eligible)
        self.assertEqual(
            held.node.hold_reason,
            "card_source_coverage_ends_before_service_end",
        )

    def test_unordered_group_creates_no_generic_pair_links(self) -> None:
        connection = database()
        left = (reservation("r1", "1"), reservation("r2", "2"))
        right = (payment("p1", 1), payment("p2", 2))
        graph = {
            "amount_candidates": (),
            "confirmed_individuals": (),
            "confirmed_groups": (
                {
                    "group_id": "g" * 64,
                    "signature": ("charge", "JPY", 86411),
                    "reservation_keys": ("r1", "r2"),
                    "payment_keys": ("p1", "p2"),
                    "member_count_each_side": 2,
                    "individual_pair_asserted": False,
                },
            ),
            "held": (),
        }
        counts = _insert_results(
            connection,
            reservation_evidence=left,
            payment_evidence=right,
            graph=graph,
            **self.base_kwargs(),
        )
        self.assertEqual(counts["group_member"], 4)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM payment_booking_links").fetchone()[0],
            0,
        )
        self.assertEqual(
            connection.execute(
                "SELECT individual_pair_asserted FROM direct_agoda_amount_group_authorities"
            ).fetchone()[0],
            0,
        )
        connection.close()

    def test_build_publishes_private_candidate_without_accounting_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sqlite"
            detail = root / "detail.sqlite"
            output = root / "candidate.sqlite"
            report = root / "report.json"
            integration_base(base)
            integration_detail(detail)
            result = build(
                base_db=base,
                detail_db=detail,
                output_db=output,
                report_path=report,
            )
            self.assertEqual(result["confirmed_individual_count"], 1)
            self.assertEqual(result["confirmed_group_count"], 0)
            if os.name != "nt":
                self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
                self.assertEqual(os.stat(report).st_mode & 0o777, 0o600)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(payload["external_posting"])
            with closing(sqlite3.connect(output)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM direct_agoda_amount_individual_authorities"
                    ).fetchone()[0],
                    1,
                )

    def test_terminal_no_price_keeps_edges_but_blocks_all_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sqlite"
            detail = root / "detail.sqlite"
            output = root / "candidate.sqlite"
            report = root / "report.json"
            integration_base(base)
            integration_detail_with_terminal_no_price(detail)
            result = build(
                base_db=base,
                detail_db=detail,
                output_db=output,
                report_path=report,
            )
            self.assertEqual(result["amount_candidate_edge_count"], 1)
            self.assertEqual(result["confirmed_individual_count"], 0)
            self.assertEqual(result["confirmed_group_count"], 0)
            self.assertFalse(result["amount_universe_sealed"])
            self.assertEqual(result["detail_terminal_no_price_count"], 1)
            with closing(sqlite3.connect(output)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) "
                        "FROM direct_agoda_amount_individual_authorities"
                    ).fetchone()[0],
                    0,
                )

    def test_cancelled_list_detail_status_conflict_is_terminal_not_matchable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sqlite"
            detail = root / "detail.sqlite"
            output = root / "candidate.sqlite"
            report = root / "report.json"
            integration_base(base)
            integration_detail_with_terminal_no_price(detail)
            with closing(sqlite3.connect(detail)) as connection:
                connection.execute(
                    "UPDATE booking_detail_observations "
                    "SET observation_kind=?,detail_reservation_status='confirmed'",
                    ("cancelled_list_detail_status_conflict_no_price",),
                )
                connection.commit()
            result = build(
                base_db=base,
                detail_db=detail,
                output_db=output,
                report_path=report,
            )
            self.assertFalse(result["amount_universe_sealed"])
            self.assertEqual(result["confirmed_individual_count"], 0)
            self.assertEqual(result["confirmed_group_count"], 0)

    def test_terminal_observation_requires_bound_live_list_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sqlite"
            detail = root / "detail.sqlite"
            integration_base(base)
            integration_detail_with_terminal_no_price(detail)
            with closing(sqlite3.connect(detail)) as connection:
                connection.execute("DELETE FROM page_attestations")
                connection.commit()
            with self.assertRaisesRegex(
                ReconciliationError,
                "terminal_observation_attestation_invalid",
            ):
                build(
                    base_db=base,
                    detail_db=detail,
                    output_db=root / "candidate.sqlite",
                    report_path=root / "report.json",
                )

    def test_terminal_observation_requires_exact_attested_membership_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sqlite"
            detail = root / "detail.sqlite"
            integration_base(base)
            integration_detail_with_terminal_no_price(detail)
            with closing(sqlite3.connect(detail)) as connection:
                connection.execute(
                    "UPDATE page_attestations SET ordered_membership_sha256=?",
                    ("x" * 64,),
                )
                connection.execute(
                    "UPDATE booking_detail_observations "
                    "SET attested_ordered_membership_sha256=?",
                    ("x" * 64,),
                )
                connection.commit()
            with self.assertRaisesRegex(
                ReconciliationError,
                "terminal_observation_list_membership_invalid",
            ):
                build(
                    base_db=base,
                    detail_db=detail,
                    output_db=root / "candidate.sqlite",
                    report_path=root / "report.json",
                )

    def test_terminal_observation_rejects_joint_source_hash_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sqlite"
            detail = root / "detail.sqlite"
            integration_base(base)
            integration_detail_with_terminal_no_price(detail)
            with closing(sqlite3.connect(detail)) as connection:
                connection.execute(
                    "UPDATE page_attestations SET source_page_set_sha256=?",
                    ("x" * 64,),
                )
                connection.execute(
                    "UPDATE booking_detail_observations "
                    "SET attested_source_page_set_sha256=?",
                    ("x" * 64,),
                )
                connection.commit()
            with self.assertRaisesRegex(
                ReconciliationError,
                "terminal_observation_contract_invalid",
            ):
                build(
                    base_db=base,
                    detail_db=detail,
                    output_db=root / "candidate.sqlite",
                    report_path=root / "report.json",
                )


if __name__ == "__main__":
    unittest.main()
