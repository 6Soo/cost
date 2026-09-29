import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledger.domain.reservation_access_snapshot import parse_reservation_access_snapshot
from webapp import access_control


ROOT = Path(__file__).resolve().parents[2]


def raw_snapshot(revision_ms: int, persons: list[dict]) -> bytes:
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


class ReservationAccessParserTests(unittest.TestCase):
    BASE = 1_800_000_000_000

    def parse(self, persons=None, revision=None):
        return parse_reservation_access_snapshot(raw_snapshot(
            revision or self.BASE, persons if persons is not None else [person()]))

    def test_parser_normalizes_and_digest_ignores_transport_revision(self):
        one = self.parse([person(assignments=["trip-b", "trip-a"])], self.BASE)
        two = self.parse([person(assignments=["trip-a", "trip-b"])], self.BASE + 1000)
        self.assertEqual(one["digest"], two["digest"])
        self.assertEqual(one["persons"][0]["assignments"], ["trip-b", "trip-a"])

    def test_parser_rejects_wrong_shape_schema_and_duplicates(self):
        base = json.loads(raw_snapshot(self.BASE, [person()]))
        for mutate in (
            lambda d: d.update(extra=True),
            lambda d: d.__setitem__("schema_version", "wrong"),
            lambda d: d.__setitem__("persons", [person(), person()]),
            lambda d: d.__setitem__("persons", [person("rp-1", "same"), person("rp-2", "same")]),
            lambda d: d.__setitem__("persons", [person(assignments=["trip-a", "trip-a"])]),
            lambda d: d.__setitem__("persons", [person(nickname="")]),
        ):
            doc = json.loads(json.dumps(base))
            mutate(doc)
            with self.assertRaises(ValueError):
                parse_reservation_access_snapshot(doc)

    def test_parser_rejects_bad_revision_time_and_inactive_assignments(self):
        base = json.loads(raw_snapshot(self.BASE, [person()]))
        bad_docs = []
        for value in (-1, 9_007_199_254_740_992, True):
            doc = json.loads(json.dumps(base))
            doc["snapshot_revision"] = value
            bad_docs.append(doc)
        doc = json.loads(json.dumps(base)); doc["snapshot_revision"] += 1; bad_docs.append(doc)
        doc = json.loads(json.dumps(base)); doc["exported_at"] = "2026-09-29"; bad_docs.append(doc)
        doc = json.loads(json.dumps(base)); doc["persons"] = [person(active=False, assignments=["trip-a"])]; bad_docs.append(doc)
        for doc in bad_docs:
            with self.assertRaises(ValueError):
                parse_reservation_access_snapshot(doc)


class ReservationAccessSyncTests(unittest.TestCase):
    BASE = 1_800_000_000_000

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE trip_tabs(tab_id TEXT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0,"
            " archived INTEGER NOT NULL DEFAULT 0, starts_on TEXT NOT NULL DEFAULT '')")
        for tab in ("trip-a", "trip-b", "trip-c"):
            self.conn.execute("INSERT INTO trip_tabs(tab_id) VALUES (?)", (tab,))
        self.store = access_control.AccessStore(self.conn)
        self.store.create_account(user_id="viewer-1", role=access_control.ROLE_VIEWER)

    def tearDown(self):
        self.conn.close()

    def snapshot(self, revision, persons):
        return parse_reservation_access_snapshot(raw_snapshot(revision, persons))

    def link_direct(self, person_id="rp-1", user_id="viewer-1"):
        now = access_control.iso(access_control.utc_now())
        self.conn.execute(
            "INSERT INTO access_connections(connection_id,user_id,reservation_person_id,"
            "reservation_person_label,status,revision,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("conn-" + user_id, user_id, person_id, "label", access_control.CONNECTION_ACTIVE, 1, now, now))
        self.conn.commit()

    def test_first_import_second_idempotent_and_exact_trip_mapping(self):
        snap = self.snapshot(self.BASE, [person(assignments=["trip-a", "trip-b"])])
        self.store.sync_reservation_access_snapshot(snapshot=snap)
        self.link_direct()
        newer = self.snapshot(self.BASE + 1000, [person(assignments=["trip-a", "trip-b"])])
        first = self.store.sync_reservation_access_snapshot(snapshot=newer)
        second = self.store.sync_reservation_access_snapshot(snapshot=newer)
        self.assertEqual(self.store.visible_tabs("viewer-1"), {"trip-a", "trip-b"})
        self.assertEqual(first["assignments_applied"], 2)
        self.assertTrue(second["ignored_stale_or_equal"])

    def test_reassignment_revokes_omission_and_stale_snapshot_cannot_restore(self):
        self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE, [person(assignments=["trip-a"])]))
        self.link_direct()
        self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 1000, [person(assignments=["trip-a"])]))
        self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 2000, [person(assignments=["trip-b"])]))
        self.assertEqual(self.store.assignment_head("viewer-1", "trip-a")["state"], access_control.ASSIGN_REVOKED)
        self.assertEqual(self.store.visible_tabs("viewer-1"), {"trip-b"})
        stale = self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 1000, [person(assignments=["trip-a"])]))
        self.assertTrue(stale["ignored_stale_or_equal"])
        self.assertEqual(self.store.visible_tabs("viewer-1"), {"trip-b"})

    def test_newer_per_trip_head_is_not_overwritten_by_directory_snapshot(self):
        self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE, [person(assignments=[])]))
        self.link_direct()
        self.store.apply_assignment_snapshot(
            user_id="viewer-1",
            items=[{"tab_id": "trip-c", "state": access_control.ASSIGN_ACTIVE,
                    "snapshot_revision": self.BASE + 5000}],
            source_version="future", complete=False)
        result = self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 1000, [person(assignments=["trip-a"])]))
        self.assertEqual(self.store.assignment_head("viewer-1", "trip-c")["snapshot_revision"], self.BASE + 5000)
        self.assertEqual(self.store.assignment_head("viewer-1", "trip-c")["state"], access_control.ASSIGN_ACTIVE)
        self.assertGreaterEqual(result["assignments_ignored_older"], 1)

    def test_inactive_and_omitted_person_revoke_connection_and_bump_session(self):
        self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE, [person(assignments=[])]))
        self.link_direct()
        before = self.store.session_generation("viewer-1")
        inactive = self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 1000, [person(active=False)]))
        self.assertEqual(inactive["connections_revoked"], 1)
        self.assertEqual(self.store.session_generation("viewer-1"), before + 1)
        self.assertIsNone(self.store.active_connection("viewer-1"))

        self.store.create_account(user_id="viewer-2", role=access_control.ROLE_VIEWER)
        self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 2000, [person("rp-2", "guide-two")]))
        self.link_direct("rp-2", "viewer-2")
        before2 = self.store.session_generation("viewer-2")
        # An empty directory revokes everyone, so it needs the explicit
        # override (fail-closed): the old expectation of a silent apply is
        # replaced by the Sol-approved guard.
        with self.assertRaises(access_control.AccessError) as refused:
            self.store.sync_reservation_access_snapshot(
                snapshot=self.snapshot(self.BASE + 3000, []))
        self.assertEqual(refused.exception.code,
                         access_control.SNAPSHOT_EMPTY_REQUIRES_OVERRIDE)
        omitted = self.store.sync_reservation_access_snapshot(
            snapshot=self.snapshot(self.BASE + 3000, []), allow_empty=True)
        self.assertEqual(omitted["connections_revoked"], 1)
        self.assertEqual(self.store.session_generation("viewer-2"), before2 + 1)

    def test_nickname_rename_preserves_stable_identity_and_unconnected_has_no_permissions(self):
        first = self.snapshot(self.BASE, [person(nickname="old", assignments=["trip-a"])])
        self.store.sync_reservation_access_snapshot(snapshot=first)
        renamed = self.snapshot(self.BASE + 1000, [person(nickname="new", assignments=["trip-b"])])
        result = self.store.sync_reservation_access_snapshot(snapshot=renamed)
        row = self.store.reservation_person("rp-1")
        self.assertEqual(row["nickname"], "new")
        self.assertEqual(result["connected_persons_synced"], 0)
        self.assertEqual(self.store.visible_tabs("viewer-1"), set())


class ReservationAccessImporterTests(unittest.TestCase):
    def test_importer_requires_explicit_paths_and_reports_idempotence_without_identity_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            input_path = tmp / "snapshot.json"
            db_path = tmp / "access.sqlite"
            # A missing target is refused fail-closed (no file is created),
            # so the success path needs a pre-existing ledger DB.
            seed = sqlite3.connect(str(db_path))
            try:
                access_control.AccessStore(seed)
                seed.commit()
            finally:
                seed.close()
            input_path.write_bytes(raw_snapshot(
                1_800_000_000_000, [person("secret-person-id", "secret-nick")]))
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "import_reservation_access.py"),
                 "--input", str(input_path), "--db", str(db_path)],
                cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = json.loads(proc.stdout)
            self.assertTrue(body["idempotent"])
            self.assertEqual(body["persons_seen"], 1)
            self.assertNotIn("secret-person-id", proc.stdout)
            self.assertNotIn("secret-nick", proc.stdout)

            missing = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "import_reservation_access.py")],
                cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertNotEqual(missing.returncode, 0)


if __name__ == "__main__":
    unittest.main()
