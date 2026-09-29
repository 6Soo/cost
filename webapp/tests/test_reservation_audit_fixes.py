"""2026-09-29 Reservation Audit fixes: behavior tests, synthetic data only.

Each audit requirement gets a real behavior check against the store or the
importer subprocess -- never a string search. All person ids, nicknames and
trip codes below are invented for the tests.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ledger.domain.reservation_access_snapshot import (
    parse_reservation_access_snapshot,
)
from webapp import access_control

ROOT = Path(__file__).resolve().parents[2]
IMPORTER = ROOT / "tools" / "import_reservation_access.py"
BASE = 1_800_000_000_000


def raw_snapshot(revision_ms: int, persons: list) -> bytes:
    exported_at = datetime.fromtimestamp(
        revision_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")
    return json.dumps({
        "schema_version": "reservation-access-snapshot-v1",
        "exported_at": exported_at,
        "snapshot_revision": revision_ms,
        "persons": persons,
    }, ensure_ascii=False).encode("utf-8")


def person(person_id="rp-1", nickname="guide-one", *, active=True,
           assignments=None, display_name="Guide One"):
    return {
        "reservation_person_id": person_id,
        "display_name": display_name,
        "nickname": nickname,
        "is_active": active,
        "assignments": list(assignments or []),
    }


def snapshot_doc(revision_ms: int, persons: list) -> dict:
    return parse_reservation_access_snapshot(raw_snapshot(revision_ms, persons))


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE trip_tabs(tab_id TEXT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0,"
            " archived INTEGER NOT NULL DEFAULT 0, starts_on TEXT NOT NULL DEFAULT '')")
        for tab in ("trip-a", "trip-b", "trip-c"):
            self.conn.execute("INSERT INTO trip_tabs(tab_id) VALUES (?)", (tab,))
        self.store = access_control.AccessStore(self.conn)


class LargeDropGuardTests(_StoreCase):
    def test_empty_snapshot_requires_explicit_override(self):
        snap = snapshot_doc(BASE, [])
        with self.assertRaises(access_control.AccessError) as caught:
            self.store.sync_reservation_access_snapshot(snapshot=snap)
        self.assertEqual(
            caught.exception.code,
            access_control.SNAPSHOT_EMPTY_REQUIRES_OVERRIDE)
        self.assertEqual(caught.exception.status, 409)
        self.assertIsNone(self.store.reservation_directory_head())
        attempts = self.store.list_sync_attempts()
        self.assertEqual(attempts[0]["outcome"], "empty_requires_override")

        applied = self.store.sync_reservation_access_snapshot(
            snapshot=snap, allow_empty=True)
        self.assertFalse(applied["ignored_stale_or_equal"])
        self.assertEqual(applied["persons_seen"], 0)
        self.assertEqual(
            self.store.reservation_directory_head()["persons_seen"], 0)

    def test_shrunk_directory_requires_override_then_applies_with_flag(self):
        seed = [person(f"rp-{i}", f"nick-{i}") for i in range(4)]
        self.store.sync_reservation_access_snapshot(
            snapshot=snapshot_doc(BASE, seed))
        shrunk = snapshot_doc(BASE + 1000, seed[:1])
        with self.assertRaises(access_control.AccessError) as caught:
            self.store.sync_reservation_access_snapshot(snapshot=shrunk)
        self.assertEqual(
            caught.exception.code,
            access_control.SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE)
        # The refused snapshot changed nothing: the old head still stands.
        self.assertEqual(
            self.store.reservation_directory_head()["snapshot_revision"], BASE)
        applied = self.store.sync_reservation_access_snapshot(
            snapshot=shrunk, allow_large_drop=True)
        self.assertFalse(applied["ignored_stale_or_equal"])
        self.assertEqual(applied["persons_seen"], 1)

    def test_exactly_half_is_allowed_but_below_half_is_not(self):
        seed = [person(f"rp-{i}", f"nick-{i}") for i in range(4)]
        self.store.sync_reservation_access_snapshot(
            snapshot=snapshot_doc(BASE, seed))
        # The ratio is measured against the last head: 4 -> 2 -> 1 each keep
        # at least half, so each passes without a flag.
        half = self.store.sync_reservation_access_snapshot(
            snapshot=snapshot_doc(BASE + 1000, seed[:2]))
        self.assertFalse(half["ignored_stale_or_equal"])
        quarter = self.store.sync_reservation_access_snapshot(
            snapshot=snapshot_doc(BASE + 2000, seed[:1]))
        self.assertFalse(quarter["ignored_stale_or_equal"])
        # A direct 4 -> 1 jump on a fresh store drops below half: blocked.
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE trip_tabs(tab_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO trip_tabs(tab_id) VALUES ('trip-a')")
        conn.commit()
        fresh = access_control.AccessStore(conn)
        fresh.sync_reservation_access_snapshot(
            snapshot=snapshot_doc(BASE, seed))
        with self.assertRaises(access_control.AccessError):
            fresh.sync_reservation_access_snapshot(
                snapshot=snapshot_doc(BASE + 1000, seed[:1]))


class DigestConflictTests(_StoreCase):
    def test_same_revision_different_digest_is_conflict(self):
        first = snapshot_doc(BASE, [person("rp-1", "nick-a")])
        second = snapshot_doc(BASE, [person("rp-1", "nick-b")])
        self.assertNotEqual(first["digest"], second["digest"])
        self.store.sync_reservation_access_snapshot(snapshot=first)
        with self.assertRaises(access_control.AccessError) as caught:
            self.store.sync_reservation_access_snapshot(snapshot=second)
        self.assertEqual(caught.exception.code,
                         access_control.SNAPSHOT_CONFLICT)
        self.assertEqual(caught.exception.status, 409)
        head = self.store.reservation_directory_head()
        self.assertEqual(head["digest"], first["digest"])
        outcomes = [a["outcome"] for a in self.store.list_sync_attempts()]
        self.assertIn("conflict", outcomes)

    def test_same_revision_same_digest_is_idempotent(self):
        snap = snapshot_doc(BASE, [person()])
        self.store.sync_reservation_access_snapshot(snapshot=snap)
        again = self.store.sync_reservation_access_snapshot(snapshot=snap)
        self.assertTrue(again["ignored_stale_or_equal"])


class TripValidationTests(_StoreCase):
    def test_unknown_trip_code_is_refused_atomically(self):
        snap = snapshot_doc(
            BASE, [person(assignments=["trip-a", "trip-zzz"])])
        with self.assertRaises(access_control.AccessError) as caught:
            self.store.sync_reservation_access_snapshot(snapshot=snap)
        self.assertEqual(caught.exception.code, access_control.UNKNOWN_TRIP)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("trip-zzz", str(caught.exception))
        self.assertIsNone(self.store.reservation_directory_head())

    def test_missing_trip_table_refuses_assignments_but_not_empty_ones(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        store = access_control.AccessStore(conn)
        with_assign = snapshot_doc(BASE, [person(assignments=["trip-a"])])
        with self.assertRaises(access_control.AccessError) as caught:
            store.sync_reservation_access_snapshot(snapshot=with_assign)
        self.assertEqual(caught.exception.code, access_control.UNKNOWN_TRIP)
        without_assign = snapshot_doc(BASE + 1000, [person()])
        result = store.sync_reservation_access_snapshot(snapshot=without_assign)
        self.assertFalse(result["ignored_stale_or_equal"])


class DisplayPolicyTests(unittest.TestCase):
    def test_display_name_length_cap(self):
        ok_person = person(display_name="x" * 100)
        parsed = snapshot_doc(BASE, [ok_person])
        self.assertEqual(parsed["persons"][0]["display_name"], "x" * 100)
        with self.assertRaises(ValueError):
            snapshot_doc(BASE, [person(display_name="x" * 101)])

    def test_control_characters_rejected(self):
        # Unicode category Cc only: format characters (Cf, e.g. ZWSP) stay
        # allowed so scripts that need them keep working.
        for bad in ("bad\x00name", "bad\x07name", "bad\tname",
                    "bad\x7fname", "bad\x9fname", "bad\nname", "bad\rname"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                snapshot_doc(BASE, [person(display_name=bad)])
        parsed = snapshot_doc(BASE, [person(display_name="홍길동 가이드")])
        self.assertEqual(parsed["persons"][0]["display_name"], "홍길동 가이드")

    def test_register_disambiguator_empty_does_not_overwrite(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        store = access_control.AccessStore(conn)
        store.register_reservation_person(
            reservation_person_id="rp-1", display_name="홍길동",
            nickname="길동", disambiguator="B 여행")
        kept = store.register_reservation_person(
            reservation_person_id="rp-1", display_name="홍길동",
            nickname="길동", disambiguator="")
        self.assertEqual(kept["disambiguator"], "B 여행")
        changed = store.register_reservation_person(
            reservation_person_id="rp-1", display_name="홍길동",
            nickname="길동", disambiguator="C 여행")
        self.assertEqual(changed["disambiguator"], "C 여행")

    def test_register_rejects_bad_labels(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        store = access_control.AccessStore(conn)
        with self.assertRaises(access_control.AccessError) as caught:
            store.register_reservation_person(
                reservation_person_id="rp-9", display_name="x" * 101,
                nickname="nick")
        self.assertEqual(caught.exception.code, "INVALID_VALUE")
        with self.assertRaises(access_control.AccessError):
            store.register_reservation_person(
                reservation_person_id="rp-9", display_name="bad\x00name",
                nickname="nick")


class SyncAttemptLogTests(_StoreCase):
    def test_attempts_record_applied_and_refused(self):
        applied_snap = snapshot_doc(BASE, [person()])
        self.store.sync_reservation_access_snapshot(snapshot=applied_snap)
        try:
            self.store.sync_reservation_access_snapshot(
                snapshot=snapshot_doc(BASE + 1000, []))
        except access_control.AccessError:
            pass
        attempts = self.store.list_sync_attempts()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["outcome"], "empty_requires_override")
        self.assertEqual(attempts[0]["error_code"],
                         access_control.SNAPSHOT_EMPTY_REQUIRES_OVERRIDE)
        self.assertEqual(attempts[1]["outcome"], "applied")
        self.assertEqual(attempts[1]["persons_seen"], 1)


class BusyPolicyTests(unittest.TestCase):
    def test_busy_timeout_is_set_on_store_connections(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        access_control.AccessStore(conn)
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(value, access_control.BUSY_TIMEOUT_MS)

    def test_locked_database_answers_503_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "locked.sqlite")
            main_conn = sqlite3.connect(db_path)
            try:
                store = access_control.AccessStore(main_conn)
                holder = sqlite3.connect(db_path)
                try:
                    holder.execute("BEGIN IMMEDIATE")
                    holder.execute("CREATE TABLE IF NOT EXISTS hold(x)")
                    main_conn.execute("PRAGMA busy_timeout=0")
                    snap = snapshot_doc(BASE, [person()])
                    with self.assertRaises(access_control.AccessError) as caught:
                        store.sync_reservation_access_snapshot(snapshot=snap)
                    self.assertEqual(caught.exception.code,
                                     access_control.TEMPORARILY_UNAVAILABLE)
                    self.assertEqual(caught.exception.status, 503)
                    holder.execute("ROLLBACK")
                finally:
                    holder.close()
            finally:
                main_conn.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ImporterCliTests(unittest.TestCase):
    def _write_snapshot(self, tmp: Path, name: str, revision: int,
                        persons: list) -> Path:
        path = tmp / name
        path.write_bytes(raw_snapshot(revision, persons))
        return path

    def _make_db(self, tmp: Path, name: str = "access.sqlite",
                 trips=("trip-a",)) -> Path:
        db_path = tmp / name
        conn = sqlite3.connect(str(db_path))
        try:
            access_control.AccessStore(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS trip_tabs(tab_id TEXT PRIMARY KEY)")
            for trip in trips:
                conn.execute("INSERT OR IGNORE INTO trip_tabs(tab_id) VALUES (?)",
                             (trip,))
            conn.commit()
        finally:
            conn.close()
        return db_path

    def _run(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(IMPORTER), *argv],
            cwd=ROOT, text=True, capture_output=True, check=False)

    def test_apply_backs_up_and_reports_counts_without_identity_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = self._make_db(tmp_path)
            input_path = self._write_snapshot(
                tmp_path, "snap.json", BASE,
                [person("secret-person-id", "secret-nick",
                        assignments=["trip-a"])])
            proc = self._run("--input", str(input_path), "--db", str(db_path))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = json.loads(proc.stdout)
            self.assertTrue(body["ok"])
            self.assertTrue(body["idempotent"])
            self.assertEqual(body["persons_seen"], 1)
            self.assertIn("backup", body)
            self.assertTrue(Path(body["backup"]).is_file())
            self.assertNotIn("secret-person-id", proc.stdout)
            self.assertNotIn("secret-nick", proc.stdout)
            self.assertNotIn("Traceback", proc.stderr)

    def test_missing_db_is_refused_with_structured_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = self._write_snapshot(tmp_path, "snap.json", BASE,
                                              [person()])
            proc = self._run("--input", str(input_path),
                             "--db", str(tmp_path / "no-such.sqlite"))
            self.assertEqual(proc.returncode, 4, proc.stderr)
            body = json.loads(proc.stdout)
            self.assertFalse(body["ok"])
            self.assertEqual(body["code"], "RESERVATION_TARGET_MISSING")
            self.assertNotIn("Traceback", proc.stderr)

    def test_missing_and_invalid_input_are_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = self._make_db(tmp_path)
            missing = self._run("--input", str(tmp_path / "nope.json"),
                                "--db", str(db_path))
            self.assertEqual(missing.returncode, 3)
            self.assertEqual(json.loads(missing.stdout)["code"],
                             "SNAPSHOT_INPUT_MISSING")
            bad = tmp_path / "bad.json"
            bad.write_bytes(b"{not json")
            invalid = self._run("--input", str(bad), "--db", str(db_path))
            self.assertEqual(invalid.returncode, 3)
            self.assertEqual(json.loads(invalid.stdout)["code"],
                             "SNAPSHOT_INVALID")
            for proc in (missing, invalid):
                self.assertNotIn("Traceback", proc.stderr)
                self.assertNotIn("Traceback", proc.stdout)

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = self._make_db(tmp_path)
            before = _sha256(db_path)
            input_path = self._write_snapshot(
                tmp_path, "snap.json", BASE, [person(assignments=["trip-a"])])
            proc = self._run("--input", str(input_path), "--db", str(db_path),
                             "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = json.loads(proc.stdout)
            self.assertTrue(body["dry_run"])
            self.assertFalse(body["applied_to_real_database"])
            self.assertTrue(body["source_unchanged"])
            self.assertEqual(_sha256(db_path), before)
            conn = sqlite3.connect(str(db_path))
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM access_reservation_directory_head"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 0)

    def test_empty_and_large_drop_need_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = self._make_db(tmp_path)
            seed = [person(f"rp-{i}", f"nick-{i}") for i in range(4)]
            seed_path = self._write_snapshot(tmp_path, "seed.json", BASE, seed)
            self.assertEqual(
                self._run("--input", str(seed_path),
                          "--db", str(db_path)).returncode, 0)
            empty_path = self._write_snapshot(tmp_path, "empty.json",
                                              BASE + 1000, [])
            refused = self._run("--input", str(empty_path),
                                "--db", str(db_path))
            self.assertEqual(refused.returncode, 5)
            self.assertEqual(json.loads(refused.stdout)["code"],
                             "SNAPSHOT_EMPTY_REQUIRES_OVERRIDE")
            allowed = self._run("--input", str(empty_path),
                                "--db", str(db_path), "--allow-empty")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

            db2 = self._make_db(tmp_path, name="second.sqlite")
            self.assertEqual(
                self._run("--input", str(seed_path),
                          "--db", str(db2)).returncode, 0)
            shrunk_path = self._write_snapshot(tmp_path, "shrunk.json",
                                               BASE + 1000, seed[:1])
            drop = self._run("--input", str(shrunk_path), "--db", str(db2))
            self.assertEqual(drop.returncode, 5)
            self.assertEqual(json.loads(drop.stdout)["code"],
                             "SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE")
            drop_ok = self._run("--input", str(shrunk_path), "--db", str(db2),
                                "--allow-large-drop")
            self.assertEqual(drop_ok.returncode, 0, drop_ok.stderr)

    def test_unknown_trip_and_conflict_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = self._make_db(tmp_path)
            strange = self._write_snapshot(
                tmp_path, "strange.json", BASE,
                [person(assignments=["trip-zzz"])])
            proc = self._run("--input", str(strange), "--db", str(db_path))
            self.assertEqual(proc.returncode, 5)
            body = json.loads(proc.stdout)
            self.assertEqual(body["code"], "UNKNOWN_TRIP")
            self.assertIn("trip-zzz", body["message"])

            first = self._write_snapshot(tmp_path, "first.json", BASE,
                                         [person("rp-1", "nick-a")])
            second = self._write_snapshot(tmp_path, "second.json", BASE,
                                          [person("rp-1", "nick-b")])
            self.assertEqual(
                self._run("--input", str(first),
                          "--db", str(db_path)).returncode, 0)
            conflict = self._run("--input", str(second), "--db", str(db_path))
            self.assertEqual(conflict.returncode, 5)
            self.assertEqual(json.loads(conflict.stdout)["code"],
                             "SNAPSHOT_CONFLICT")
            # Replaying the exact same snapshot stays a success (idempotent).
            replay = self._run("--input", str(first), "--db", str(db_path))
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertTrue(json.loads(replay.stdout)["idempotent"])


if __name__ == "__main__":
    unittest.main()
