import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ledger.domain.direct_trip_schedule_authority import (
    END_SEMANTICS,
    SCHEMA_VERSION,
    ScheduleRecord,
    legacy_window_candidates,
    match_service_period,
    normalize_service_period,
    validate_document,
)
from ledger.domain.direct_sources import import_trip_schedule
from ledger.domain.ledger_db import infer_trip, load_trips
from ledger.domain.direct_verified_ota_lodging import (
    load_authoritative_trip_schedule,
    load_trip_schedule,
)


def record(**overrides):
    value = {
        "trip_code": "0408_교토",
        "event_year": 2026,
        "starts_on": "2026-04-08",
        "ends_on": "2026-04-14",
        "region": "교토",
        "authority_kind": "official_event_schedule",
        "source_locator": "evidence://trip/0408",
        "source_sha256": "a" * 64,
        "authority_status": "authoritative",
        "end_semantics": END_SEMANTICS,
    }
    value.update(overrides)
    return value


class DirectTripScheduleAuthorityTests(unittest.TestCase):
    def test_explicit_dates_bind_using_checkout_exclusive_end(self):
        records = validate_document({"schema_version": SCHEMA_VERSION, "records": [record()]})
        matched = match_service_period("2026-04-08", "2026-04-11", records)
        self.assertEqual([item.trip_code for item in matched], ["0408_교토"])
        self.assertEqual(matched[0].ends_on, date(2026, 4, 14))

    def test_legacy_candidate_never_counts_as_authority(self):
        candidate = ScheduleRecord(
            "0408_교토", 2026, date(2026, 4, 8), date(2026, 4, 14), "교토",
            "legacy_window_candidate", "ledger/data/trips.json#/1", "b" * 64,
            "candidate_only",
        )
        self.assertEqual(match_service_period("2026-04-08", "2026-04-11", [candidate]), [])
        self.assertEqual(
            [item.trip_code for item in match_service_period(
                "2026-04-08", "2026-04-11", [candidate], authoritative_only=False
            )],
            ["0408_교토"],
        )

    def test_two_explicit_overlapping_periods_are_ambiguous(self):
        first = record(trip_code="0404_에히메", starts_on="2026-04-04", ends_on="2026-04-10", region="에히메")
        second = record()
        records = validate_document({"schema_version": SCHEMA_VERSION, "records": [first, second]})
        self.assertEqual(
            [item.trip_code for item in match_service_period("2026-04-08", "2026-04-10", records)],
            ["0404_에히메", "0408_교토"],
        )

    def test_missing_ends_on_is_rejected(self):
        value = record()
        del value["ends_on"]
        with self.assertRaisesRegex(ValueError, "record_shape"):
            validate_document({"schema_version": SCHEMA_VERSION, "records": [value]})

    def test_year_is_not_inferred_from_month_day(self):
        records = validate_document({"schema_version": SCHEMA_VERSION, "records": [record()]})
        self.assertEqual(match_service_period("2025-04-08", "2025-04-10", records), [])

    def test_explicit_cross_year_period_requires_explicit_event_year(self):
        value = record(
            trip_code="1231_크로스연도",
            event_year=2025,
            starts_on="2025-12-31",
            ends_on="2026-01-02",
        )
        records = validate_document({"schema_version": SCHEMA_VERSION, "records": [value]})
        self.assertEqual(
            [item.trip_code for item in match_service_period("2025-12-31", "2026-01-02", records)],
            ["1231_크로스연도"],
        )

    def test_legacy_conversion_keeps_source_hash_and_candidate_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trips.json"
            path.write_text(
                json.dumps([{"tab": "0408_교토", "mm": 4, "dd": 8, "region": "교토", "window": 7}], ensure_ascii=False),
                encoding="utf-8",
            )
            rows, source_sha = legacy_window_candidates(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].authority_status, "candidate_only")
        self.assertEqual(rows[0].authority_kind, "legacy_window_candidate")
        self.assertEqual(rows[0].source_sha256, source_sha)

    def test_service_end_is_checkout_exclusive_and_last_day_is_derived(self):
        period = normalize_service_period("2026-04-08", "2026-04-11")
        self.assertEqual(period.service_start_on, date(2026, 4, 8))
        self.assertEqual(period.service_end_on_exclusive, date(2026, 4, 11))
        self.assertEqual(period.last_service_on, date(2026, 4, 10))

    def test_legacy_source_is_preserved_as_candidate_but_cannot_be_authority(self):
        explicit = {
            "tab": "0414_나가노",
            "event_year": 2026,
            "starts_on": "2026-04-14",
            "ends_on": "2026-04-15",
            "region": "나가노",
            "authority_kind": "official_event_schedule",
            "authority_status": "authoritative",
            "end_semantics": END_SEMANTICS,
        }
        service_period_explicit = {
            "tab": "0420_도쿄",
            "event_year": 2026,
            "service_start_on": "2026-04-20",
            "service_end_on": "2026-04-23",
            "region": "도쿄",
            "authority_kind": "explicit_trip_registry",
            "authority_status": "authoritative",
            "end_semantics": "exclusive_service_end",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trip_schedule.json"
            path.write_text(json.dumps([
                {"tab": "0408_교토", "mm": 4, "dd": 8,
                 "region": "교토", "window": 7},
                explicit,
                service_period_explicit,
            ], ensure_ascii=False), encoding="utf-8")
            db = sqlite3.connect(":memory:")
            try:
                db.executescript(Path("ledger/domain/schema.sql").read_text(encoding="utf-8"))
                import_trip_schedule(db, path)
                candidates = load_trip_schedule(db)
                authority = load_authoritative_trip_schedule(db)
            finally:
                db.close()
        self.assertEqual(set(candidates), {"0408_교토"})
        self.assertEqual(set(authority), {"0414_나가노", "0420_도쿄"})
        self.assertEqual(authority["0414_나가노"]["window"], 2)
        self.assertEqual(authority["0414_나가노"]["ends_on"], "2026-04-15")
        self.assertEqual(authority["0420_도쿄"]["ends_on"], "2026-04-22")

    def test_relational_trip_rows_do_not_infer_dates_from_legacy_or_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trips.json"
            path.write_text(json.dumps([
                {"tab": "0408_교토", "mm": 4, "dd": 8,
                 "region": "교토", "window": 7},
            ], ensure_ascii=False), encoding="utf-8")
            db = sqlite3.connect(":memory:")
            try:
                db.executescript(Path("ledger/domain/schema.sql").read_text(encoding="utf-8"))
                load_trips(db, path)
                infer_trip(db, "0410_오사카")
                rows = db.execute(
                    "SELECT code,starts_on,ends_on,status FROM trips ORDER BY code"
                ).fetchall()
            finally:
                db.close()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                ("0408_교토", None, None, "candidate_only"),
                ("0410_오사카", None, None, "candidate_only"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
