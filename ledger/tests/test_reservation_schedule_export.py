import json
import hashlib
import sqlite3
import unittest

from ledger.domain.direct_verified_ota_lodging import load_authoritative_trip_schedule
from ledger.domain.ledger_db import initialize
from ledger.domain.direct_projection import _apply_schema
from ledger.domain.reservation_schedule_export import (
    EXPORT_SCHEMA_VERSION,
    EXPORT_SCHEMA_VERSION_V3,
    import_reservation_schedule_export,
    schedule_export_sha256_v3,
    validate_schedule_export,
)


def export_document(*records):
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "parser_contract": "reservation:cafeParse:R1-1",
        "exported_at": "2026-08-24T00:00:00.000Z",
        "records": list(records),
    }


def export_document_v3(*records, exported_at="2026-08-24T00:00:00.000Z"):
    return {
        "schema_version": EXPORT_SCHEMA_VERSION_V3,
        "parser_contract": "reservation:cafeParse:R1-1",
        "exported_at": exported_at,
        "records": list(records),
    }


def activity_sha(value):
    payload = {
        "cafe_fldid": value["cafe_fldid"],
        "cafe_datanum": value["cafe_datanum"],
        "source_post_sha256": value["source_post_sha256"],
        "comment_count": value["comment_count"],
        "listed_comment_count": value["listed_comment_count"],
        "fetched_unique_comment_count": value["fetched_unique_comment_count"],
        "comment_threshold": value["comment_threshold"],
        "comment_census_complete": value["comment_census_complete"],
        "activity_status": value["activity_status"],
        "activity_source_status": value["activity_source_status"],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record(**overrides):
    value = {
        "trip_code": "reservation:ehime-2025",
        "cafe_fldid": "ehime-2025",
        "cafe_datanum": "101",
        "event_year": 2025,
        "starts_on": "2025-04-08",
        "ends_on": "2025-04-10",
        "region": "에히메",
        "date_source": "parsed",
        "authority_kind": "explicit_trip_registry",
        "authority_status": "authoritative",
        "source_locator": "https://cafe.daum.net/sixsungwon/ehime-2025/101",
        "source_post_sha256": "a" * 64,
        "end_semantics": "inclusive_last_service_date",
        "hold_reason": None,
        "comment_count": 10,
        "listed_comment_count": 10,
        "fetched_unique_comment_count": 10,
        "comment_threshold": 10,
        "comment_census_complete": True,
        "comment_observed_at": "2025-04-20T00:00:00.000Z",
        "activity_status": "activity_confirmed",
        "activity_source_status": "archived_snapshot_available",
        "activity_snapshot_sha256": None,
    }
    value.update(overrides)
    if "activity_snapshot_sha256" not in overrides:
        value["activity_snapshot_sha256"] = (
            activity_sha(value)
            if value["activity_source_status"] == "archived_snapshot_available"
            else None
        )
    return value


class ReservationScheduleExportTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize(self.db)
        _apply_schema(self.db)

    def tearDown(self):
        self.db.close()

    def test_imports_explicit_stored_year_and_authority(self):
        result = import_reservation_schedule_export(self.db, export_document(record()))
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["authoritative"], 1)
        authority = load_authoritative_trip_schedule(self.db)
        self.assertEqual(authority["reservation:ehime-2025"]["event_year"], 2025)
        self.assertEqual(authority["reservation:ehime-2025"]["starts_on"], "2025-04-08")
        self.assertEqual(authority["reservation:ehime-2025"]["ends_on"], "2025-04-10")
        self.assertEqual(authority["reservation:ehime-2025"]["authority_kind"], "explicit_trip_registry")

    def test_incomplete_record_is_retained_as_candidate_not_authority(self):
        candidate = record(
            trip_code="reservation:open",
            cafe_fldid="open",
            cafe_datanum=None,
            event_year=2026,
            starts_on="2026-10-30",
            ends_on=None,
            authority_kind="legacy_window_candidate",
            authority_status="candidate_only",
            end_semantics=None,
            hold_reason="stored_period_incomplete",
            comment_count=None,
            listed_comment_count=None,
            fetched_unique_comment_count=None,
            comment_census_complete=False,
            comment_observed_at=None,
            activity_status="not_observable_yet",
            activity_source_status="no_archived_snapshot",
            activity_snapshot_sha256=None,
        )
        result = import_reservation_schedule_export(self.db, export_document(candidate))
        self.assertEqual(result["authoritative"], 0)
        self.assertEqual(result["candidate_only"], 1)
        self.assertEqual(result["candidate_reasons"][0]["reason"], "stored_period_incomplete")
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='reservation_schedule_record'"
            ).fetchone()[0],
            1,
        )
        with self.assertRaisesRegex(ValueError, "trip_schedule_source_missing"):
            load_authoritative_trip_schedule(self.db)

    def test_same_export_is_idempotent(self):
        document = export_document(record())
        first = import_reservation_schedule_export(self.db, document)
        self.db.commit()
        before = self.db.total_changes
        second = import_reservation_schedule_export(self.db, json.dumps(document, ensure_ascii=False))
        self.assertEqual(first["export_sha256"], second["export_sha256"])
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(self.db.total_changes, before)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0],
            5,
        )

    def test_changed_export_timestamp_is_still_idempotent(self):
        first = export_document(record())
        second = export_document(record())
        second["exported_at"] = "2026-08-25T00:00:00.000Z"
        first_result = import_reservation_schedule_export(self.db, first)
        self.db.commit()
        before = self.db.total_changes
        second_result = import_reservation_schedule_export(self.db, second)
        self.assertEqual(first_result["export_sha256"], second_result["export_sha256"])
        self.assertEqual(second_result["inserted"], 0)
        self.assertEqual(self.db.total_changes, before)

    def test_changed_observation_time_keeps_content_identity_and_adds_observation(self):
        first_document = export_document(record(comment_observed_at="2025-04-20T00:00:00.000Z"))
        second_document = export_document(record(comment_observed_at="2025-04-21T00:00:00.000Z"))
        first = import_reservation_schedule_export(self.db, first_document)
        self.db.commit()
        second = import_reservation_schedule_export(self.db, second_document)
        self.assertEqual(first["export_sha256"], second["export_sha256"])
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='reservation_schedule_activity'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='reservation_schedule_activity_observation'"
            ).fetchone()[0],
            2,
        )

    def test_export_root_and_row_are_strictly_validated(self):
        bad = export_document(record())
        bad["parser_contract"] = "wrong"
        with self.assertRaisesRegex(ValueError, "parser_contract"):
            validate_schedule_export(bad)
        bad = export_document(record(event_year=2026))
        with self.assertRaisesRegex(ValueError, "event_year_mismatch"):
            validate_schedule_export(bad)
        bad = export_document(record(activity_snapshot_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "activity_snapshot_digest_invalid"):
            validate_schedule_export(bad)

    def test_changed_schedule_for_same_trip_fails_closed_and_rolls_back(self):
        document = export_document(record())
        import_reservation_schedule_export(self.db, document)
        changed = export_document(record(starts_on="2025-04-09", ends_on="2025-04-11"))
        with self.assertRaisesRegex(ValueError, "source_key_content_conflict:trip_schedule"):
            import_reservation_schedule_export(self.db, changed)
        self.assertEqual(
            json.loads(self.db.execute(
                "SELECT payload_json FROM direct_source_records WHERE source_kind='trip_schedule'"
            ).fetchone()[0])["starts_on"],
            "2025-04-08",
        )

    def test_nine_comments_is_insufficient_but_keeps_schedule_authority(self):
        nine = record(
            comment_count=9,
            listed_comment_count=9,
            fetched_unique_comment_count=9,
            activity_status="activity_insufficient",
        )
        result = import_reservation_schedule_export(self.db, export_document(nine))
        self.assertEqual(result["activity_counts"], {"activity_insufficient": 1})
        self.assertEqual(result["authoritative"], 1)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='reservation_schedule_activity'"
            ).fetchone()[0],
            1,
        )

    def test_incomplete_comment_census_never_confirms_activity(self):
        incomplete = record(
            fetched_unique_comment_count=8,
            comment_census_complete=False,
            activity_status="activity_incomplete",
        )
        result = import_reservation_schedule_export(self.db, export_document(incomplete))
        self.assertEqual(result["activity_counts"], {"activity_incomplete": 1})

    def test_later_missing_archive_does_not_delete_confirmed_evidence(self):
        confirmed = export_document(record())
        first = import_reservation_schedule_export(self.db, confirmed)
        self.db.commit()
        unavailable = record(
            comment_count=None,
            listed_comment_count=None,
            fetched_unique_comment_count=None,
            comment_census_complete=False,
            comment_observed_at=None,
            activity_status="activity_unavailable",
            activity_source_status="no_archived_snapshot",
            activity_snapshot_sha256=None,
        )
        later = export_document(unavailable)
        later["exported_at"] = "2026-08-25T00:00:00.000Z"
        second = import_reservation_schedule_export(self.db, later)
        self.assertGreater(second["inserted"], 0)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='reservation_schedule_activity'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='trip_schedule'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(first["authoritative"], 1)
        self.assertEqual(second["authoritative"], 1)

    def test_v3_reversed_multilingual_rows_are_one_content_identity(self):
        first_record = record(
            trip_code="reservation:豈",
            cafe_fldid="fld-豈",
            cafe_datanum="701",
            region="東京",
            source_locator="https://cafe.daum.net/sixsungwon/fld-豈/701",
            source_post_sha256="b" * 64,
            activity_status="activity_unavailable",
            activity_source_status="no_archived_snapshot",
            comment_count=None,
            listed_comment_count=None,
            fetched_unique_comment_count=None,
            comment_census_complete=False,
            comment_observed_at=None,
            activity_snapshot_sha256=None,
        )
        second_record = record(
            trip_code="reservation:𐀀",
            cafe_fldid="fld-𐀀",
            cafe_datanum="702",
            region="서울",
            source_locator="https://cafe.daum.net/sixsungwon/fld-𐀀/702",
            source_post_sha256="c" * 64,
            activity_status="activity_unavailable",
            activity_source_status="no_archived_snapshot",
            comment_count=None,
            listed_comment_count=None,
            fetched_unique_comment_count=None,
            comment_census_complete=False,
            comment_observed_at=None,
            activity_snapshot_sha256=None,
        )
        first_document = export_document_v3(first_record, second_record)
        reversed_document = export_document_v3(
            second_record,
            first_record,
            exported_at="2026-08-25T00:00:00.000Z",
        )
        first = import_reservation_schedule_export(self.db, first_document)
        self.db.commit()
        before = self.db.total_changes
        second = import_reservation_schedule_export(self.db, reversed_document)
        self.assertEqual(first["export_sha256"], second["export_sha256"])
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(self.db.total_changes, before)
        self.assertEqual(
            first["export_sha256"],
            schedule_export_sha256_v3(first_document),
        )
        self.assertEqual(
            first["export_sha256"],
            "f52edbf12c116dc1a8f81dd92049dc8a614289fc1a9f7c125e8bfdc079b18e96",
        )
        observed_later = export_document_v3(
            dict(first_record, comment_observed_at="2026-08-25T00:00:00.000Z"),
            second_record,
            exported_at="2026-08-25T00:00:00.000Z",
        )
        self.assertEqual(
            first["export_sha256"],
            schedule_export_sha256_v3(observed_later),
        )

    def test_v3_hash_matches_shared_fixture_and_business_changes(self):
        fixture = record(
            trip_code="reservation:豈",
            cafe_fldid="fld-豈",
            cafe_datanum="701",
            region="東京",
            source_locator="https://cafe.daum.net/sixsungwon/fld-豈/701",
            source_post_sha256="b" * 64,
            activity_status="activity_unavailable",
            activity_source_status="no_archived_snapshot",
            comment_count=None,
            listed_comment_count=None,
            fetched_unique_comment_count=None,
            comment_census_complete=False,
            comment_observed_at=None,
            activity_snapshot_sha256=None,
        )
        document = export_document_v3(fixture)
        self.assertEqual(
            schedule_export_sha256_v3(document),
            "4cce2ce8d8cb79b76f524fa8a8172f59200a59b7aa9fc2818b7f394eb5c5c655",
        )
        changed = export_document_v3(
            record(
                trip_code="reservation:豈",
                cafe_fldid="fld-豈",
                cafe_datanum="701",
                region="大阪",
                source_locator="https://cafe.daum.net/sixsungwon/fld-豈/701",
                source_post_sha256="d" * 64,
                activity_status="activity_unavailable",
                activity_source_status="no_archived_snapshot",
                comment_count=None,
                listed_comment_count=None,
                fetched_unique_comment_count=None,
                comment_census_complete=False,
                comment_observed_at=None,
                activity_snapshot_sha256=None,
            )
        )
        self.assertNotEqual(schedule_export_sha256_v3(document), schedule_export_sha256_v3(changed))

    def test_v3_duplicate_trip_code_fails_closed(self):
        duplicate = record(
            trip_code="reservation:豈",
            cafe_fldid="fld-other",
            cafe_datanum="703",
            region="제주",
            source_locator="https://cafe.daum.net/sixsungwon/fld-other/703",
            activity_status="activity_unavailable",
            activity_source_status="no_archived_snapshot",
            comment_count=None,
            listed_comment_count=None,
            fetched_unique_comment_count=None,
            comment_census_complete=False,
            comment_observed_at=None,
            activity_snapshot_sha256=None,
        )
        with self.assertRaisesRegex(ValueError, "duplicate_trip_code"):
            validate_schedule_export(export_document_v3(record(trip_code="reservation:豈"), duplicate))

    def test_v3_adds_audit_version_without_replacing_v2_source(self):
        v2_document = export_document(record())
        v3_document = export_document_v3(record())
        import_reservation_schedule_export(self.db, v2_document)
        self.db.commit()
        before_v2 = self.db.execute(
            "SELECT source_sha256, payload_json FROM direct_source_records "
            "WHERE source_kind='reservation_schedule_export'"
        ).fetchone()
        result = import_reservation_schedule_export(self.db, v3_document)
        self.assertGreater(result["inserted"], 0)
        roots = self.db.execute(
            "SELECT redaction_version, source_sha256, payload_json FROM direct_source_records "
            "WHERE source_kind='reservation_schedule_export' ORDER BY id"
        ).fetchall()
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0][0], "reservation-trip-schedule-export-v2")
        self.assertEqual(roots[0][1], before_v2[0])
        self.assertEqual(roots[0][2], before_v2[1])
        self.assertEqual(roots[1][0], EXPORT_SCHEMA_VERSION_V3)


if __name__ == "__main__":
    unittest.main()
