from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from ledger.tests._platform import allow_pin_drift
from datetime import date, timedelta
from pathlib import Path

from ledger.domain.direct_projection import (
    _apply_schema,
    project_confirmed_full_axis_allocations,
)
from ledger.domain.direct_sources import (
    _insert_source,
    import_geographic_trip_context,
    import_lodging_facts,
    import_trip_schedule,
)
from ledger.domain.direct_verified_ota_lodging import (
    _canonical,
    _sha,
    _2025_mail_service_period_allowed,
    finalize_lodging_manifest,
    prepare_external_lodging_facts,
    project_verified_lodging_decisions,
    validate_lodging_authorities,
    validate_lodging_fact_document,
    validate_lodging_fact_record,
    validate_lodging_manifest,
)
from ledger.domain.ledger_db import initialize


FACT_PATH = Path("ledger/data/ota_lodging_facts_v2.json")
TRIP_PATH = Path("ledger/data/trips.json")
GEOGRAPHIC_CONTEXT_PATH = Path("ledger/data/current_geographic_trip_context.json")


class VerifiedOtaLodgingTest(unittest.TestCase):
    def test_2025_payment_requires_explicit_2026_trip_mail_service_period(self) -> None:
        self.assertTrue(
            _2025_mail_service_period_allowed("2025-12-20", "2026-01-09")
        )
        self.assertFalse(
            _2025_mail_service_period_allowed("2025-12-20", "2025-12-29")
        )
        self.assertTrue(
            _2025_mail_service_period_allowed("2026-01-02", "2026-01-09")
        )

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        initialize(db)
        _apply_schema(db)
        db.execute(
            """INSERT INTO direct_projection_runs(
                 run_id,status,schema_version,input_manifest_sha256,
                 code_commit,code_bundle_sha256)
               VALUES ('run','building','p07-direct-v3',?,'commit',?)""",
            ("a" * 64, "b" * 64),
        )
        for kind in ("trip_schedule", "ota_lodging_fact"):
            db.execute(
                """INSERT INTO direct_projection_inputs(
                     run_id,source_kind,relative_path,raw_sha256,lf_sha256,
                     byte_count,key_set_sha256,record_count,parser_version)
                   VALUES ('run',?,?,?,NULL,1,?,1,'test-v1')""",
                (kind, f"{kind}.json", "c" * 64, "d" * 64),
            )
        # This fixture deliberately supplies an explicit authority document.
        # Production must never derive authority from the legacy window file;
        # the separate schedule-authority tests cover that fail-closed path.
        legacy_rows = json.loads(TRIP_PATH.read_text(encoding="utf-8"))
        explicit_rows = []
        for row in legacy_rows:
            start = date(2026, int(row["mm"]), int(row["dd"]))
            end = start + timedelta(days=int(row["window"]) - 1)
            explicit_rows.append({
                "tab": row["tab"],
                "event_year": 2026,
                "starts_on": start.isoformat(),
                "ends_on": end.isoformat(),
                "region": row["region"],
                "authority_kind": "user_confirmed_schedule",
                "authority_status": "authoritative",
                "end_semantics": "inclusive_last_service_date",
            })
        with tempfile.TemporaryDirectory() as temporary:
            schedule_path = Path(temporary) / "explicit-trip-schedule.json"
            schedule_path.write_text(
                json.dumps(explicit_rows, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            import_trip_schedule(db, schedule_path)
        import_lodging_facts(db, FACT_PATH)
        return db

    def _prepare(self) -> sqlite3.Connection:
        db = self._db()
        result = prepare_external_lodging_facts(db, "run")
        self.assertEqual(result, {
            "source_records": 50,
            "source_withheld": 1,
            "lifecycle_blocked_confirmations": 8,
            "target_blocked_confirmations": 8,
            "active_facts": 23,
        })
        return db

    def _insert_cards(
        self, db: sqlite3.Connection, *, skip_fact_ids: set[str] | None = None,
    ) -> None:
        skip = skip_fact_ids or set()
        facts = db.execute(
            """SELECT fact_id,seoul_sent_on,paid_total_krw
               FROM direct_verified_lodging_facts
               WHERE run_id='run' ORDER BY fact_id"""
        ).fetchall()
        for index, fact in enumerate(facts):
            if str(fact["fact_id"]) in skip:
                continue
            self._insert_card_for_fact(db, fact, index)

    def _insert_card_for_fact(
        self, db: sqlite3.Connection, fact: sqlite3.Row, index: int,
        *, identity_status: str = "unique",
    ) -> None:
        source_key = f"KBD:T:{index}"
        payload = {
            "src": "KBD", "raw_record_id": f"T:{index}", "card4": "1234",
            "currency": "KRW", "foreign": "",
        }
        source_id, _ = _insert_source(db, "card_raw", source_key, payload)
        event_id = "card:" + hashlib.sha256(
            f"event:{index}".encode("utf-8")
        ).hexdigest()
        db.execute(
            """INSERT INTO direct_card_events(
                 source_record_id,card_event_id,generator_version,identity_status,
                 source_system,amount_krw,approval_number,occurred_on,merchant)
               VALUES (?,?,'test-v1',?,'KBD',?,NULL,?,'트립닷컴(구)_NICE')""",
            (
                source_id, event_id, identity_status,
                fact["paid_total_krw"], fact["seoul_sent_on"],
            ),
        )
        direct_id = int(db.execute(
            """INSERT INTO direct_normalized_payments(
                 source_record_id,event_role,card_event_id,amount_krw,
                 transaction_type,normalization_version)
               VALUES (?,'single',?,?,'purchase','test-v1')""",
            (source_id, event_id, fact["paid_total_krw"]),
        ).lastrowid)
        external_key = f"external:{index}"
        payment_id = int(db.execute(
            """INSERT INTO payment_transactions(
                 external_key,source_event_id,identity_fingerprint,source_system,
                 occurred_on,merchant,amount_krw,transaction_type)
               VALUES (?,?,?,'KBD',?,'트립닷컴(구)_NICE',?,'purchase')""",
            (
                external_key, event_id,
                hashlib.sha256(f"fingerprint:{index}".encode()).hexdigest(),
                fact["seoul_sent_on"], fact["paid_total_krw"],
            ),
        ).lastrowid)
        db.execute(
            """INSERT INTO direct_payment_projection_links(
                 run_id,direct_payment_id,payment_id) VALUES ('run',?,?)""",
            (direct_id, payment_id),
        )
        fact_hash = hashlib.sha256(f"current:{index}".encode()).hexdigest()
        source_hash = db.execute(
            "SELECT source_sha256 FROM direct_source_records WHERE id=?", (source_id,),
        ).fetchone()[0]
        db.execute(
            """INSERT INTO direct_promotion_evidence(
                 evidence_id,run_id,evidence_kind,authority_status,direct_event_key,
                 source_kind,source_key,source_sha256,fact_sha256)
               VALUES (?,'run','current_card','current_raw',?,'card_raw',?,?,?)""",
            (
                "current-card:" + fact_hash, event_id + "#single",
                source_key, source_hash, fact_hash,
            ),
        )

    def test_safe_fact_document_is_content_addressed_and_fail_closed(self) -> None:
        raw = json.loads(FACT_PATH.read_text(encoding="utf-8"))
        validated = validate_lodging_fact_document(raw)
        self.assertEqual((validated["record_count"], validated["eligible_count"]), (50, 49))

        amount_tamper = copy.deepcopy(raw)
        amount_tamper["records"][1]["paid_total_krw"] += 1
        with self.assertRaisesRegex(ValueError, "lodging_fact_hash_mismatch"):
            validate_lodging_fact_document(amount_tamper)

        auth_tamper = copy.deepcopy(next(
            row for row in raw["records"] if row["eligibility_status"] == "eligible"
        ))
        auth_tamper["auth_evidence_sha256"] = ""
        unhashed = dict(auth_tamper)
        unhashed.pop("fact_sha256")
        auth_tamper["fact_sha256"] = _sha(unhashed)
        with self.assertRaisesRegex(ValueError, "authenticated_eligibility_invalid"):
            validate_lodging_fact_record(auth_tamper)

        privacy_tamper = copy.deepcopy(raw["records"][1])
        privacy_tamper["body"] = "not allowed"
        with self.assertRaisesRegex(ValueError, "record_schema_invalid"):
            validate_lodging_fact_record(privacy_tamper)

    @allow_pin_drift()
    def test_booking_reference_lifecycle_beats_accidental_group_sum(self) -> None:
        db = self._prepare()
        try:
            active = [tuple(row) for row in db.execute(
                """SELECT booking_ref,paid_total_krw FROM direct_verified_lodging_facts
                   WHERE property_name='호텔 파티오 도고'"""
            ).fetchall()]
            self.assertEqual(active, [("1400822641924013", 318622)])
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_verified_lodging_facts
                   WHERE paid_total_krw=159311"""
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_withheld
                   WHERE reason_code='booking_ref_cancelled'"""
            ).fetchone()[0], 8)
        finally:
            db.close()

    @allow_pin_drift()
    def test_taiwan_context_targets_service_period_and_never_becomes_evidence(self) -> None:
        db = self._db()
        try:
            import_geographic_trip_context(db, GEOGRAPHIC_CONTEXT_PATH)
            prepared = prepare_external_lodging_facts(db, "run")
            self.assertEqual(prepared, {
                "source_records": 50,
                "source_withheld": 1,
                "lifecycle_blocked_confirmations": 8,
                "target_blocked_confirmations": 7,
                "active_facts": 24,
            })
            taiwan_fact = db.execute(
                """SELECT fact_id,seoul_sent_on,paid_total_krw
                   FROM direct_verified_lodging_facts
                   WHERE target_code='0107_대만'"""
            ).fetchone()
            self.assertIsNotNone(taiwan_fact)
            self.assertEqual(taiwan_fact["paid_total_krw"], 613326)
            self.assertEqual(taiwan_fact["seoul_sent_on"], "2025-12-26")
            self._insert_cards(db)
            projected = project_verified_lodging_decisions(db, "run")
            self.assertEqual(projected["payments"], 20)
            target_authorities = db.execute(
                """SELECT COUNT(*) FROM direct_lodging_authorities
                   WHERE allocation_target='0107_대만'"""
            ).fetchone()[0]
            self.assertEqual(target_authorities, 1)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_promotion_evidence
                   WHERE run_id='run' AND source_kind='geographic_trip_context'"""
            ).fetchone()[0], 0)
            self.assertTrue(validate_lodging_authorities(db, "run")["passed"])
        finally:
            db.close()

    @allow_pin_drift()
    def test_withheld_cancellation_blocks_same_booking_as_uncertainty(self) -> None:
        db = self._db()
        try:
            document = json.loads(FACT_PATH.read_text(encoding="utf-8"))
            cancellation = copy.deepcopy(next(
                row for row in document["records"]
                if row["message_class"] == "cancel"
            ))
            cancellation.update(
                message_id=hashlib.sha256(b"withheld-cancel").hexdigest()[:16],
                booking_ref="1400822641924013",
                eligibility_status="withheld",
                aligned_dkim_domain="",
                auth_evidence_sha256="",
                withheld_reasons=["aligned_dkim_missing"],
            )
            unhashed = dict(cancellation)
            unhashed.pop("fact_sha256")
            cancellation["fact_sha256"] = _sha(unhashed)
            validate_lodging_fact_record(cancellation)
            _insert_source(
                db, "ota_lodging_fact", str(cancellation["message_id"]),
                cancellation,
                "no_subject_body_name_pin_recipient_or_address_text",
            )
            result = prepare_external_lodging_facts(db, "run")
            self.assertEqual(result["active_facts"], 22)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_verified_lodging_facts
                   WHERE booking_ref='1400822641924013'"""
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_withheld
                   WHERE reason_code='unverified_cancellation_conflict'"""
            ).fetchone()[0], 1)
        finally:
            db.close()

    @allow_pin_drift()
    def test_equal_amount_mn_is_withheld_without_pairwise_links(self) -> None:
        db = self._prepare()
        try:
            self._insert_cards(db)
            projected = project_verified_lodging_decisions(db, "run")
            self.assertEqual(projected, {
                "authorities": 19, "set_authorities": 0, "payments": 19,
                "decisions": 57, "matching_withheld_items": 10,
            })
            set_rows = db.execute(
                """SELECT event_count,fact_count,payload_json
                   FROM direct_lodging_authorities
                   WHERE authority_kind='axis_invariant_set'
                   ORDER BY authority_id"""
            ).fetchall()
            self.assertEqual(set_rows, [])
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_withheld
                   WHERE reason_code='many_to_many_component_withheld'"""
            ).fetchone()[0], 10)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM payment_booking_links"
            ).fetchone()[0], 0)
            self.assertEqual(project_confirmed_full_axis_allocations(db, "run")["payments"], 19)
            self.assertTrue(validate_lodging_authorities(
                db, "run", require_allocations=True
            )["passed"])
            finalize_lodging_manifest(db, "run")
            self.assertTrue(validate_lodging_manifest(db, "run")["passed"])
        finally:
            db.close()

    @allow_pin_drift()
    def test_open_cardinality_component_is_withheld_not_force_paired(self) -> None:
        db = self._prepare()
        try:
            duplicate_facts = db.execute(
                """SELECT fact_id FROM direct_verified_lodging_facts
                   WHERE paid_total_krw=280544 ORDER BY fact_id"""
            ).fetchall()
            self.assertEqual(len(duplicate_facts), 2)
            self._insert_cards(db, skip_fact_ids={str(duplicate_facts[0][0])})
            projected = project_verified_lodging_decisions(db, "run")
            self.assertEqual(projected["payments"], 19)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_withheld
                   WHERE reason_code='component_cardinality_mismatch'"""
            ).fetchone()[0], 4)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_authorities
                   WHERE json_extract(payload_json,'$.match_key.amount_krw')=280544"""
            ).fetchone()[0], 0)
        finally:
            db.close()

    @allow_pin_drift()
    def test_extra_collision_card_cannot_be_silently_filtered_from_component(self) -> None:
        db = self._prepare()
        try:
            self._insert_cards(db)
            fact = db.execute(
                """SELECT fact_id,seoul_sent_on,paid_total_krw
                   FROM direct_verified_lodging_facts WHERE paid_total_krw=318622"""
            ).fetchone()
            self._insert_card_for_fact(db, fact, 999, identity_status="collision")
            projected = project_verified_lodging_decisions(db, "run")
            self.assertEqual(projected["payments"], 18)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_authorities
                   WHERE json_extract(payload_json,'$.match_key.amount_krw')=318622"""
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM direct_lodging_withheld
                   WHERE reason_code='component_cardinality_mismatch'"""
            ).fetchone()[0], 4)
        finally:
            db.close()

    @allow_pin_drift()
    def test_schedule_hash_is_part_of_fact_and_authority_content_address(self) -> None:
        db = self._prepare()
        try:
            self._insert_cards(db)
            project_verified_lodging_decisions(db, "run")
            project_confirmed_full_axis_allocations(db, "run")
            finalize_lodging_manifest(db, "run")
            fact = db.execute(
                """SELECT fact_id,payload_json FROM direct_verified_lodging_facts
                   ORDER BY fact_id LIMIT 1"""
            ).fetchone()
            payload = json.loads(fact["payload_json"])
            payload["trip_schedule_source_sha256"] = "f" * 64
            db.execute(
                """UPDATE direct_verified_lodging_facts SET payload_json=?
                   WHERE fact_id=?""",
                (_canonical(payload).decode("utf-8"), fact["fact_id"]),
            )
            authority = validate_lodging_authorities(
                db, "run", require_allocations=True
            )
            self.assertFalse(authority["passed"])
            self.assertTrue(any(
                "active_fact_payload_source_mismatch" in issue
                for issue in authority["issues"]
            ))
            self.assertFalse(validate_lodging_manifest(db, "run")["passed"])
        finally:
            db.close()

    @allow_pin_drift()
    def test_authority_and_manifest_tampering_is_detected(self) -> None:
        db = self._prepare()
        try:
            self._insert_cards(db)
            project_verified_lodging_decisions(db, "run")
            project_confirmed_full_axis_allocations(db, "run")
            finalize_lodging_manifest(db, "run")
            db.execute(
                """UPDATE direct_lodging_authorities SET payload_json='{}'
                   WHERE authority_id=(SELECT MIN(authority_id)
                                       FROM direct_lodging_authorities)"""
            )
            self.assertFalse(validate_lodging_authorities(
                db, "run", require_allocations=True
            )["passed"])
            self.assertFalse(validate_lodging_manifest(db, "run")["passed"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
