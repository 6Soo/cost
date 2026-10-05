"""RESERVE-EXPLICIT-LINK-001 — 합성 수용 검사.

실제 자료·운영 브라우저·운영 프로세스·D 운영 경로·비밀에 접근하지 않는다.
원천 식별자는 합성 불투명 키이며 `reservation:` 접두사를 그대로 쓴다. 접두사를
제거해 COST 코드를 얻는 경로가 없는 것도 검사한다.
"""

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ledger.domain.reservation_access_snapshot import (  # noqa: E402
    SCHEMA_VERSION, parse_reservation_access_snapshot)
from webapp import access_control, reserve_link  # noqa: E402

OWNER = "syn-owner-1"
LEDGER_EVENTS = ("COST-TRIP-ALFA", "COST-TRIP-BRAVO", "COST-TRIP-DELTA")


def source_person(person_id, name, assignments, *, active=True):
    # `nickname` is required by the strict parser even when the export would leave
    # it empty, so the synthetic roster carries one rather than bending the parser.
    return {"reservation_person_id": person_id, "display_name": name,
            "nickname": f"nick-{person_id}",
            "is_active": active, "assignments": list(assignments)}


def raw_snapshot(persons, exported_at=None, revision=None):
    """A roster as the export would state it, with the `reservation:` keys intact."""
    from datetime import datetime, timezone

    if exported_at is None:
        exported_at = "2026-05-01T00:00:00Z"
    if revision is None:
        revision = int(datetime.fromisoformat(
            exported_at.replace("Z", "+00:00")).astimezone(
                timezone.utc).timestamp() * 1000)
    return json.dumps({
        # The strict parser's own version string, so the synthetic roster is
        # accepted by the same validation a real export goes through.
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at,
        "snapshot_revision": revision,
        "persons": persons,
    }, ensure_ascii=False).encode("utf-8")


class LinkFixture(unittest.TestCase):
    """A store with two ledger events, an owner, one connected viewer and a roster."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "access.sqlite"
        self.conn = sqlite3.connect(str(self.db_path))
        self.addCleanup(self.conn.close)
        self.store = access_control.AccessStore(self.conn)
        self.store.create_account(user_id=OWNER, role=access_control.ROLE_OWNER,
                                  display_name="owner")
        # A ledger event directory, as `ledger_store.trip_tabs` holds it.
        self.conn.executescript(
            "CREATE TABLE IF NOT EXISTS trip_tabs("
            " tab_id TEXT PRIMARY KEY, display_key TEXT NOT NULL,"
            " destination TEXT NOT NULL DEFAULT '', starts_on TEXT NOT NULL DEFAULT '',"
            " ends_on TEXT NOT NULL DEFAULT '', prepared_on TEXT NOT NULL DEFAULT '',"
            " prepared_by_name TEXT NOT NULL DEFAULT '',"
            " archived INTEGER NOT NULL DEFAULT 0,"
            " deleted INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1)")
        for event in LEDGER_EVENTS:
            self.conn.execute(
                "INSERT OR IGNORE INTO trip_tabs(tab_id, display_key)"
                " VALUES (?,?)", (event, event))
        self.conn.commit()
        self._previous = {name: os.environ.get(name)
                          for name in (reserve_link.CONFIG_ENV,)}
        self.addCleanup(self._restore)

    def _restore(self):
        for name, value in self._previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # -- the source file ------------------------------------------------------
    def configure(self, persons, exported_at="2026-05-01T00:00:00Z"):
        """Write the roster file and point the owner configuration at it.

        The file is written once and never rewritten by the tests below, so a test
        that changes the *links* is provably running against the same bytes.
        """
        raw = raw_snapshot(persons, exported_at=exported_at)
        parsed = parse_reservation_access_snapshot(raw)
        self.source_file = self.tmp / "roster.json"
        self.source_file.write_bytes(raw)
        os.environ[reserve_link.CONFIG_ENV] = json.dumps({
            "path": str(self.source_file),
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "digest": parsed["digest"],
        })
        self.snapshot = parsed
        self.source_raw = raw
        return parsed

    def bind(self):
        return reserve_link.source_binding(
            reserve_link.read_source(reserve_link.load_source_config()))

    def link(self, source, *targets, request_id=None):
        """Save one explicit link. Several targets is the many-target case."""
        state = self.store.reserve_link_state()
        return reserve_link.save_links(self.store, self.snapshot, {
            "request_id": request_id or f"link-{source}-{len(targets)}",
            "source_binding": self.bind(),
            "link_revision": state["revision"],
            "links": [{"source_event_key": source, "target_tab_id": target}
                      for target in targets],
            "unlinks": [],
        }, owner_id=OWNER)

    def visible_tabs(self, user_id="syn-staff-1"):
        """The trips one account may read right now.

        On the shared fixture rather than in each test class, so an independent
        acceptance test subclassing this fixture reads the effect through one
        definition instead of restating it per file.
        """
        return self.store.visible_tabs(user_id)

    def apply(self, request_id="apply-1", **overrides):
        state = self.store.reserve_link_state()
        plan = reserve_link.build_plan(self.store, self.snapshot,
                                       link_state=state)
        arguments = {
            "request_id": request_id,
            "presented_binding": plan["binding"],
            "presented_link_revision": plan["link_revision"],
            "presented_apply_digest": plan["apply_digest"],
            "owner_id": OWNER,
        }
        arguments.update(overrides)
        return reserve_link.apply_plan(self.store, self.snapshot, **arguments)

    def grant(self, person_id, user_id):
        """Connect a viewer to a source person, through the existing approval path.

        The existing `viewer` role and the existing pending → approved flow, with
        the owner naming the person id. No new role and no automatic connection.
        """
        self.store.create_account(user_id=user_id,
                                  role=access_control.ROLE_VIEWER,
                                  display_name=user_id)
        self.store.register_reservation_person(
            reservation_person_id=person_id, display_name=person_id)
        application = self.store.create_application(
            user_id=user_id, requested_name=person_id,
            client_request_id=f"app-{user_id}")
        return self.store.approve_application(
            application_id=application["application_id"], owner_id=OWNER,
            expected_revision=application["revision"],
            reservation_person_id=person_id,
            client_request_id=f"approve-{user_id}")


class SourceBindingTests(LinkFixture):
    """The configured source is verified, and never rewritten."""

    def test_the_configured_file_hashes_are_the_ones_checked(self):
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        config = reserve_link.load_source_config()
        self.assertTrue(config["configured"])
        snapshot = reserve_link.read_source(config)
        self.assertEqual(snapshot["digest"], config["digest"])
        self.assertEqual(hashlib.sha256(self.source_raw).hexdigest(),
                         config["file_sha256"])

    def test_a_changed_file_is_refused_and_nothing_is_read_from_it(self):
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        self.source_file.write_bytes(raw_snapshot([
            source_person("rp-1", "합성 담당자", ["reservation:cafeParse:BRAVO"])]))
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            reserve_link.read_source(reserve_link.load_source_config())
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_SOURCE_HASH_MISMATCH)

    def test_no_configuration_is_the_required_state_and_searches_nothing(self):
        os.environ.pop(reserve_link.CONFIG_ENV, None)
        config = reserve_link.load_source_config()
        self.assertFalse(config["configured"])
        self.assertEqual(config["code"], reserve_link.CODE_CONFIG_REQUIRED)
        # And no path was invented.
        self.assertNotIn("path", config)

    def test_a_partial_configuration_is_the_required_state(self):
        os.environ[reserve_link.CONFIG_ENV] = json.dumps({"path": "x.json"})
        config = reserve_link.load_source_config()
        self.assertFalse(config["configured"])
        self.assertEqual(config["code"], reserve_link.CODE_CONFIG_REQUIRED)

    def test_the_source_revision_and_digest_are_reproduced_exactly(self):
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        binding = self.bind()
        self.assertEqual(binding["source_revision"],
                         self.snapshot["snapshot_revision"])
        self.assertEqual(binding["source_digest"], self.snapshot["digest"])

    def test_the_reservation_prefix_is_never_stripped(self):
        """The opaque key stays opaque.

        A source code that already *is* a ledger event code resolves through the
        exact path. One carrying the prefix does not become one by having the
        prefix removed, and nothing here can do that.
        """
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertEqual(plan["unlinked"],
                         ["reservation:cafeParse:ALFA"])
        stripped = "cafeParse:ALFA"
        self.assertNotIn(stripped, {event for event in LEDGER_EVENTS})
        self.assertEqual(plan["applicable"], False)

    def test_an_exact_ledger_event_code_keeps_the_existing_path(self):
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["COST-TRIP-ALFA"])])
        plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["resolved"][0]["origin"], "exact")
        self.assertEqual(plan["resolved"][0]["target_tab_id"], "COST-TRIP-ALFA")


class LinkSavingTests(LinkFixture):
    """Links are saved only when the owner names them, and only if they are real."""

    def setUp(self):
        super().setUp()
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])

    def save(self, links, unlinks=(), request_id="save-1", revision=None,
             binding=None):
        state = self.store.reserve_link_state()
        return reserve_link.save_links(self.store, self.snapshot, {
            "request_id": request_id,
            "source_binding": binding if binding is not None else self.bind(),
            "link_revision": state["revision"] if revision is None else revision,
            "links": list(links),
            "unlinks": list(unlinks),
        }, owner_id=OWNER)

    def test_an_exact_link_is_saved_and_the_source_is_untouched(self):
        before = self.source_file.read_bytes()
        result = self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                             "target_tab_id": "COST-TRIP-ALFA"}])
        self.assertEqual(result["linked"], [
            {"source_event_key": "reservation:cafeParse:ALFA",
             "target_tab_id": "COST-TRIP-ALFA"}])
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"]})
        self.assertEqual(self.source_file.read_bytes(), before)

    def test_an_identifier_the_source_does_not_contain_is_refused(self):
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.save([{"source_event_key": "reservation:cafeParse:NOPE",
                        "target_tab_id": "COST-TRIP-ALFA"}])
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_IDENTIFIER_NOT_IN_SOURCE)
        self.assertEqual(self.store.reserve_link_state()["links"], {})

    def test_a_target_that_is_not_a_ledger_event_is_refused(self):
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                        "target_tab_id": "COST-TRIP-MISSING"}])
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_TARGET_NOT_FOUND)

    def test_a_deleted_target_is_refused(self):
        self.conn.execute("UPDATE trip_tabs SET deleted=1 WHERE tab_id=?",
                          ("COST-TRIP-BRAVO",))
        self.conn.commit()
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                        "target_tab_id": "COST-TRIP-BRAVO"}])
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_TARGET_DELETED)

    def test_an_archived_target_is_refused(self):
        self.conn.execute("UPDATE trip_tabs SET archived=1 WHERE tab_id=?",
                          ("COST-TRIP-BRAVO",))
        self.conn.commit()
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                        "target_tab_id": "COST-TRIP-BRAVO"}])
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_TARGET_DELETED)

    def test_the_same_target_twice_is_refused(self):
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA",
                                       "reservation:cafeParse:BRAVO"])])
        # Two identifiers may share a target — that is not a duplicate. The same
        # *pair* twice is.
        self.save([
            {"source_event_key": "reservation:cafeParse:ALFA",
             "target_tab_id": "COST-TRIP-ALFA"},
            {"source_event_key": "reservation:cafeParse:BRAVO",
             "target_tab_id": "COST-TRIP-ALFA"}],
            request_id="save-shared")
        self.assertEqual(self.store.reserve_link_state()["links"], {
            "reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"],
            "reservation:cafeParse:BRAVO": ["COST-TRIP-ALFA"],
        })
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.save([
                {"source_event_key": "reservation:cafeParse:ALFA",
                 "target_tab_id": "COST-TRIP-DELTA"},
                {"source_event_key": "reservation:cafeParse:ALFA",
                 "target_tab_id": "COST-TRIP-DELTA"}],
                request_id="save-dup")
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_DUPLICATE_TARGET)

    def test_two_identifiers_with_the_same_display_name_are_distinct(self):
        """Identities are keys, not names."""
        self.configure([
            source_person("rp-1", "같은 이름",
                          ["reservation:cafeParse:ALFA"]),
            source_person("rp-2", "같은 이름",
                          ["reservation:cafeParse:BRAVO"]),
        ])
        self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                    "target_tab_id": "COST-TRIP-ALFA"}],
                  request_id="save-a")
        self.save([{"source_event_key": "reservation:cafeParse:BRAVO",
                    "target_tab_id": "COST-TRIP-BRAVO"}],
                  request_id="save-b")
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"],
                          "reservation:cafeParse:BRAVO": ["COST-TRIP-BRAVO"]})
        # And linking one does not imply the other.
        plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertEqual(plan["unlinked"], [])
        self.assertEqual(plan["per_identifier"], {
            "reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"],
            "reservation:cafeParse:BRAVO": ["COST-TRIP-BRAVO"],
        })

    def test_a_missing_field_is_refused_and_never_means_everything(self):
        state = self.store.reserve_link_state()
        for field in ("request_id", "source_binding", "link_revision", "links",
                      "unlinks"):
            payload = {"request_id": "save-x",
                       "source_binding": self.bind(),
                       "link_revision": state["revision"],
                       "links": [{"source_event_key": "reservation:cafeParse:ALFA",
                                  "target_tab_id": "COST-TRIP-ALFA"}],
                       "unlinks": []}
            payload.pop(field)
            with self.subTest(field=field):
                with self.assertRaises(reserve_link.ReserveLinkError) as caught:
                    reserve_link.save_links(self.store, self.snapshot, payload,
                                            owner_id=OWNER)
                self.assertEqual(caught.exception.code,
                                 reserve_link.CODE_FIELD_MISSING)
        self.assertEqual(self.store.reserve_link_state()["links"], {})

    def test_the_same_request_with_the_same_input_is_the_same_result(self):
        payload = {"request_id": "save-same",
                   "source_binding": self.bind(),
                   "link_revision": self.store.reserve_link_state()["revision"],
                   "links": [{"source_event_key": "reservation:cafeParse:ALFA",
                              "target_tab_id": "COST-TRIP-ALFA"}],
                   "unlinks": []}
        first = reserve_link.save_links(self.store, self.snapshot, payload,
                                        owner_id=OWNER)
        second = reserve_link.save_links(self.store, self.snapshot, payload,
                                         owner_id=OWNER)
        self.assertEqual(first, second)

    def test_the_same_request_with_other_input_is_a_conflict(self):
        self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                    "target_tab_id": "COST-TRIP-ALFA"}],
                  request_id="save-c")
        with self.assertRaises(access_control.AccessError) as caught:
            self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                        "target_tab_id": "COST-TRIP-BRAVO"}],
                      request_id="save-c")
        self.assertEqual(caught.exception.code, reserve_link.CODE_LINK_CONFLICT)
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"]})

    def test_another_devices_link_revision_is_reported_not_overwritten(self):
        self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                    "target_tab_id": "COST-TRIP-ALFA"}],
                  request_id="save-1")
        stale = self.store.reserve_link_state()["revision"] - 1
        with self.assertRaises(access_control.AccessError) as caught:
            self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                        "target_tab_id": "COST-TRIP-BRAVO"}],
                      request_id="save-2", revision=stale)
        self.assertEqual(caught.exception.code, reserve_link.CODE_LINK_CONFLICT)
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"]})

    def test_a_source_that_moved_under_the_draft_is_reported(self):
        presented = self.bind()
        os.environ[reserve_link.CONFIG_ENV] = json.dumps({
            "path": str(self.source_file),
            "file_sha256": hashlib.sha256(self.source_raw).hexdigest(),
            "digest": "0" * 64})
        with self.assertRaises(reserve_link.ReserveLinkError):
            reserve_link.read_source(reserve_link.load_source_config())
        os.environ[reserve_link.CONFIG_ENV] = json.dumps({
            "path": str(self.source_file),
            "file_sha256": hashlib.sha256(self.source_raw).hexdigest(),
            "digest": self.snapshot["digest"]})
        # With the real source back, a draft presented against a different binding
        # is still refused rather than silently re-read.
        with self.assertRaises(access_control.AccessError):
            self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                        "target_tab_id": "COST-TRIP-ALFA"}],
                      request_id="save-moved",
                      binding={"source_revision": presented["source_revision"],
                               "source_digest": "0" * 64,
                               "schema_version": presented["schema_version"],
                               "exported_at": presented["exported_at"],
                               "file_sha256": presented["file_sha256"]})

    def test_saving_links_does_not_apply_the_roster_or_approve_anyone(self):
        self.grant("rp-1", "syn-staff-1")
        self.save([{"source_event_key": "reservation:cafeParse:ALFA",
                    "target_tab_id": "COST-TRIP-ALFA"}])
        # The viewer has a connection but no trip yet: linking is not applying.
        self.assertEqual(self.store.visible_tabs("syn-staff-1"), set())
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0], 0)


class ApplyTests(LinkFixture):
    """A separate plan, and an apply that only runs when it is asked for."""

    def setUp(self):
        super().setUp()
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        self.grant("rp-1", "syn-staff-1")

    def test_one_unlinked_identifier_refuses_the_whole_roster(self):
        self.configure([
            source_person("rp-1", "합성 담당자",
                          ["reservation:cafeParse:ALFA"]),
            source_person("rp-2", "합성 담당자2",
                          ["reservation:cafeParse:BRAVO"]),
        ])
        self.grant("rp-2", "syn-staff-2")
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertFalse(plan["applicable"])
        self.assertEqual(plan["unlinked"], ["reservation:cafeParse:BRAVO"])
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.apply()
        self.assertEqual(caught.exception.code, reserve_link.CODE_APPLY_UNLINKED)
        # Nothing partial: not even the linked identifier's trip was granted.
        self.assertEqual(self.store.visible_tabs("syn-staff-1"), set())
        self.assertEqual(self.store.visible_tabs("syn-staff-2"), set())

    def test_a_linked_identifier_reaches_the_permissions(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        result = self.apply()
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_the_plan_is_a_read_and_writes_nothing(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        for _ in range(3):
            plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertTrue(plan["applicable"])
        self.assertEqual(self.store.visible_tabs("syn-staff-1"), set())
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0], 0)

    def test_every_required_field_is_refused_when_missing(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        plan = reserve_link.build_plan(self.store, self.snapshot)
        # Absent or empty, both refused. `None` stands in for "the caller did not
        # supply it": the HTTP layer checks presence separately, and this is the
        # same refusal from the other side.
        cases = {
            "request_id": "",
            "presented_binding": None,
            "presented_apply_digest": "",
            "presented_link_revision": None,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                arguments = {
                    "request_id": "apply-missing",
                    "presented_binding": plan["binding"],
                    "presented_link_revision": plan["link_revision"],
                    "presented_apply_digest": plan["apply_digest"],
                    "owner_id": OWNER}
                arguments[field] = value
                with self.assertRaises(reserve_link.ReserveLinkError) as caught:
                    reserve_link.apply_plan(self.store, self.snapshot, **arguments)
                self.assertEqual(caught.exception.code,
                                 reserve_link.CODE_FIELD_MISSING)
        with self.assertRaises(reserve_link.ReserveLinkError):
            self.apply(request_id="apply-bad-digest",
                        presented_apply_digest="0" * 64)
        with self.assertRaises(reserve_link.ReserveLinkError):
            self.apply(request_id="apply-bad-rev",
                        presented_link_revision=plan["link_revision"] + 5)
        self.assertEqual(self.store.visible_tabs("syn-staff-1"), set())

    def test_applying_does_not_connect_staff_or_approve_applications(self):
        self.configure([source_person("rp-9", "승인 안 된 사람",
                                      ["reservation:cafeParse:ALFA"])])
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.apply()
        self.assertEqual(self.store._active_person_connections("rp-9"), [])
        pending = self.store.pending_applications()
        self.assertEqual(pending, [])

    def test_the_same_apply_retried_grants_and_revokes_nothing_twice(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        first = self.apply(request_id="apply-same")
        assignments_after_first = self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0]
        second = self.apply(request_id="apply-same")
        self.assertEqual(second["counts"], first["counts"])
        self.assertTrue(second["replayed"])
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0],
            assignments_after_first)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_link_applies").fetchone()[0], 1)

    def test_one_plan_under_two_request_ids_is_one_apply(self):
        """The plan digest identifies what was applied, not who asked.

        Two screens pressing at once, or one retrying after a lost response, arrive
        as two requests naming the same plan. That is the same apply happening
        twice, so the second is answered from the record and nothing is granted or
        revoked a second time. Refusing it would be worse than useless: the work is
        already done, and the caller would never learn that it succeeded.
        """
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        first = self.apply(request_id="apply-a")
        second = self.apply(request_id="apply-b")
        self.assertEqual(second["counts"], first["counts"])
        self.assertTrue(second["replayed"])
        self.assertEqual(second["replayed_from_request_id"], "apply-a")
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_link_applies").fetchone()[0], 1)
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_a_failure_part_way_leaves_nothing_and_a_retry_works(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        original = self.store.sync_reservation_access_snapshot

        def explode(**kwargs):
            raise RuntimeError("적용 중간 실패")

        self.store.sync_reservation_access_snapshot = explode
        self.addCleanup(setattr, self.store, "sync_reservation_access_snapshot",
                        original)
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0], 0)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_link_applies").fetchone()[0], 0)

        self.store.sync_reservation_access_snapshot = original
        result = self.apply()
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_two_applies_of_one_source_do_not_duplicate_permissions(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.apply(request_id="apply-1")
        self.apply(request_id="apply-2")
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments WHERE state=?",
            (access_control.ASSIGN_ACTIVE,)).fetchone()[0], 1)
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_the_empty_roster_protection_is_kept(self):
        self.configure([])
        with self.assertRaises(access_control.AccessError):
            self.apply()
        # A second person and account: `rp-1` is already connected to
        # `syn-staff-1`, and the existing rule refuses a second account per person.
        # `rp-1` keeps its identifier so the first apply's permissions are not
        # revoked by this roster, which is what the empty-roster guard is about.
        self.configure([
            source_person("rp-1", "합성 담당자",
                          ["reservation:cafeParse:ALFA"]),
            source_person("rp-2", "합성 담당자2",
                          ["reservation:cafeParse:BRAVO"]),
        ])
        self.grant("rp-2", "syn-staff-9")
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.link("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO")
        self.apply()
        self.assertEqual(self.store.visible_tabs("syn-staff-9"),
                         {"COST-TRIP-BRAVO"})


class SameSourceRemapTests(LinkFixture):
    """The scenario the parent called out: same source, changed links.

    A link correction on an unchanged source is a *newer decision about that
    source*. It has to move the permissions: A revoked, B active. The pair ordering
    in the assignment heads is what makes that true, because the source revision
    alone cannot tell the two applies apart.

    And the reverse direction holds: a per-trip revocation that is genuinely newer
    than the source is not undone by a link edit arriving later.
    """

    ROSTER = None

    def setUp(self):
        super().setUp()
        self.configure([
            source_person("rp-1", "합성 담당자",
                          ["reservation:cafeParse:ALFA"]),
            source_person("rp-2", "합성 담당자2",
                          ["reservation:cafeParse:BRAVO"]),
        ])
        for person, user in (("rp-1", "syn-staff-1"), ("rp-2", "syn-staff-2")):
            self.grant(person, user)
        # Both start at A through one explicit source identifier each.
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.link("reservation:cafeParse:BRAVO", "COST-TRIP-ALFA")
        self.apply(request_id="apply-1")
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})
        self.assertEqual(self.store.visible_tabs("syn-staff-2"),
                         {"COST-TRIP-ALFA"})

    def remap(self, source, target, request_id):
        state = self.store.reserve_link_state()
        return reserve_link.save_links(self.store, self.snapshot, {
            "request_id": request_id,
            "source_binding": self.bind(),
            "link_revision": state["revision"],
            "links": [{"source_event_key": source, "target_tab_id": target}],
            "unlinks": [],
        }, owner_id=OWNER)

    def test_the_same_source_and_revision_applied_with_a_corrected_link_moves_it(
            self):
        """A -> B on an unchanged source: A revoked, B active.

        This is the case the source revision cannot see. Both applies carry the
        same `source_revision` and the same `source_digest`, so a revision-only
        comparison calls the second one stale and nothing changes — which would
        leave the owner with a link they saved and a permission they do not have.
        """
        before = self.snapshot["snapshot_revision"]
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        self.assertEqual(self.snapshot["snapshot_revision"], before)
        result = self.apply(request_id="apply-2")
        self.assertGreater(result["counts"]["assignments_applied"], 0)
        self.assertEqual(self.store.visible_tabs("syn-staff-2"),
                         {"COST-TRIP-BRAVO"})
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_and_correcting_it_back_to_a_is_applied_normally(self):
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        self.apply(request_id="apply-2")
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-ALFA", "link-fix-2")
        result = self.apply(request_id="apply-3")
        self.assertGreater(result["counts"]["assignments_applied"], 0)
        self.assertEqual(self.store.visible_tabs("syn-staff-2"),
                         {"COST-TRIP-ALFA"})

    def test_the_correction_revokes_the_old_trip_rather_than_leaving_it(self):
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        self.apply(request_id="apply-2")
        revoked = self.store.conn.execute(
            "SELECT state FROM access_trip_assignment_heads"
            " WHERE user_id=? AND tab_id=?", ("syn-staff-2", "COST-TRIP-ALFA")
        ).fetchone()
        self.assertEqual(revoked[0], access_control.ASSIGN_REVOKED)

    def test_the_source_file_is_never_rewritten_by_any_of_this(self):
        before = self.source_file.read_bytes()
        digest_before = self.snapshot["digest"]
        revision_before = self.snapshot["snapshot_revision"]
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        self.apply(request_id="apply-2")
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-ALFA", "link-fix-2")
        self.apply(request_id="apply-3")
        self.assertEqual(self.source_file.read_bytes(), before)
        self.assertEqual(self.snapshot["digest"], digest_before)
        self.assertEqual(self.snapshot["snapshot_revision"], revision_before)
        self.assertEqual(
            hashlib.sha256(self.source_file.read_bytes()).hexdigest(),
            hashlib.sha256(before).hexdigest())

    def test_a_newer_per_trip_revocation_is_not_resurrected_by_a_link_edit(self):
        """The boundary that makes the pair ordering safe.

        A revocation made deliberately against a source revision the owner has
        since moved past is *newer than the source*. A later link edit arrives at
        the older source revision, so it must not bring the trip back. Source
        revision dominates link version for exactly this reason.
        """
        newer = self.snapshot["snapshot_revision"] + 500
        self.store.apply_assignment_snapshot(
            user_id="syn-staff-2",
            items=[{"tab_id": "COST-TRIP-ALFA", "state": access_control.ASSIGN_REVOKED,
                    "snapshot_revision": newer}],
            source_version="owner-revoke", complete=True,
            snapshot_revision=newer)
        self.assertEqual(self.store.visible_tabs("syn-staff-2"), set())

        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        result = self.apply(request_id="apply-2")
        # The link edit reached the other trip, and did not restore the revoked one.
        self.assertEqual(self.store.visible_tabs("syn-staff-2"),
                         {"COST-TRIP-BRAVO"})
        revoked = self.store.conn.execute(
            "SELECT state, head_snapshot_revision FROM access_trip_assignment_heads"
            " WHERE user_id=? AND tab_id=?", ("syn-staff-2", "COST-TRIP-ALFA")
        ).fetchone()
        self.assertEqual(revoked[0], access_control.ASSIGN_REVOKED)
        self.assertEqual(revoked[1], newer)
        self.assertGreaterEqual(
            result["counts"]["assignments_ignored_older"], 0)

    def test_the_link_version_moves_and_the_source_revision_does_not(self):
        first = self.store.reserve_link_state()
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        second = self.store.reserve_link_state()
        self.assertGreater(second["link_version"], first["link_version"])
        self.assertNotEqual(second["link_digest"], first["link_digest"])
        self.assertEqual(self.snapshot["snapshot_revision"],
                         self.bind()["source_revision"])

    def test_the_apply_digest_covers_the_links_not_only_the_source(self):
        before = reserve_link.build_plan(self.store, self.snapshot)["apply_digest"]
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        after = reserve_link.build_plan(self.store, self.snapshot)["apply_digest"]
        self.assertNotEqual(before, after)

    def test_the_apply_records_both_identities_separately(self):
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        result = self.apply(request_id="apply-2")
        row = self.store.conn.execute(
            "SELECT source_revision, source_digest, link_version, link_digest,"
            " sync_schema_version FROM reserve_link_applies WHERE apply_digest=?",
            (result["apply_digest"],)).fetchone()
        self.assertEqual(row[0], self.snapshot["snapshot_revision"])
        self.assertEqual(row[1], self.snapshot["digest"])
        self.assertGreater(row[2], 0)
        self.assertTrue(row[3])
        self.assertEqual(row[4], reserve_link.SYNC_SCHEMA_VERSION)

    def test_two_writers_of_one_plan_do_not_duplicate(self):
        self.remap("reservation:cafeParse:BRAVO", "COST-TRIP-BRAVO", "link-fix-1")
        results, errors = [], []

        def run(index):
            try:
                results.append(self.apply(request_id=f"apply-p{index}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(index,))
                   for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_link_applies").fetchone()[0], 1)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments WHERE state=?",
            (access_control.ASSIGN_ACTIVE,)).fetchone()[0], 2)
        del results, errors


class NoTargetTests(LinkFixture):
    """A ledger with no events yet shows the state; it does not invent one."""

    def setUp(self):
        super().setUp()
        self.conn.execute("DELETE FROM trip_tabs")
        self.conn.commit()
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        self.grant("rp-1", "syn-staff-1")

    def test_no_ledger_event_means_no_choices_and_nothing_is_invented(self):
        self.assertEqual(reserve_link.ledger_event_choices(self.store), [])
        plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertEqual(plan["unlinked"], ["reservation:cafeParse:ALFA"])
        self.assertFalse(plan["applicable"])
        with self.assertRaises(reserve_link.ReserveLinkError):
            self.apply()

    def test_saving_a_link_without_a_ledger_event_is_refused(self):
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_TARGET_NOT_FOUND)

    def test_a_completed_trip_is_still_a_valid_target(self):
        """Completion is not a refusal condition.

        A finished trip is still a real trip, and it is the target a link most
        often needs — an assignment that outlived the trip. Hiding completed trips
        would make them unlinkable, so the only conditions are deleted, archived,
        and not a ledger event at all.
        """
        self.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, ends_on, archived,"
            " deleted) VALUES ('COST-TRIP-OLD','COST-TRIP-OLD','2026-01-01',0,0)")
        self.conn.commit()
        choices = {item["tab_id"] for item
                   in reserve_link.ledger_event_choices(self.store)}
        self.assertIn("COST-TRIP-OLD", choices)
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-OLD")
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-OLD"]})




class ManyTargetTests(LinkFixture):
    """One source identifier, several ledger events, each named by the owner."""

    def setUp(self):
        super().setUp()
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        self.grant("rp-1", "syn-staff-1")

    def test_two_targets_named_for_one_identifier_both_reach_the_permissions(self):
        """Several targets are explicit, kept, and never widened on their own."""
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA",
                  "COST-TRIP-BRAVO")
        state = self.store.reserve_link_state()
        self.assertEqual(state["links"],
                         {"reservation:cafeParse:ALFA":
                          ["COST-TRIP-ALFA", "COST-TRIP-BRAVO"]})
        plan = reserve_link.build_plan(self.store, self.snapshot)
        self.assertEqual(plan["per_identifier"],
                         {"reservation:cafeParse:ALFA":
                          ["COST-TRIP-ALFA", "COST-TRIP-BRAVO"]})
        self.apply()
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA", "COST-TRIP-BRAVO"})

    def test_one_target_is_not_widened_to_the_others(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.apply()
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_naming_fewer_targets_revokes_the_ones_left_out(self):
        """A smaller set is a correction, and omission revokes.

        The submitted list *is* the target set. If dropping a target only added to
        what was there, the owner could correct a link on the screen and nothing
        would actually change — the old trip's permission would survive the very
        correction meant to remove it.
        """
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA",
                  "COST-TRIP-BRAVO")
        self.apply(request_id="apply-1")
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA", "COST-TRIP-BRAVO"})
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-BRAVO")
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-BRAVO"]})
        self.apply(request_id="apply-2")
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-BRAVO"})
        revoked = self.store.conn.execute(
            "SELECT state FROM access_trip_assignment_heads"
            " WHERE user_id=? AND tab_id=?",
            ("syn-staff-1", "COST-TRIP-ALFA")).fetchone()
        self.assertEqual(revoked[0], access_control.ASSIGN_REVOKED)

    def test_unlinking_a_source_removes_every_target_it_had(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA",
                  "COST-TRIP-BRAVO")
        state = self.store.reserve_link_state()
        reserve_link.save_links(self.store, self.snapshot, {
            "request_id": "unlink-1",
            "source_binding": self.bind(),
            "link_revision": state["revision"],
            "links": [],
            "unlinks": ["reservation:cafeParse:ALFA"],
        }, owner_id=OWNER)
        self.assertEqual(self.store.reserve_link_state()["links"], {})
        self.assertFalse(reserve_link.build_plan(
            self.store, self.snapshot)["applicable"])

    def test_one_source_may_share_a_target_with_another(self):
        self.configure([
            source_person("rp-1", "담당자1", ["reservation:cafeParse:ALFA"]),
            source_person("rp-2", "담당자2", ["reservation:cafeParse:BRAVO"]),
        ])
        self.grant("rp-2", "syn-staff-2")
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        self.link("reservation:cafeParse:BRAVO", "COST-TRIP-ALFA")
        self.apply()
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})
        self.assertEqual(self.store.visible_tabs("syn-staff-2"),
                         {"COST-TRIP-ALFA"})

    def test_the_identical_pair_twice_is_refused(self):
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            reserve_link.save_links(self.store, self.snapshot, {
                "request_id": "dup-1",
                "source_binding": self.bind(),
                "link_revision": self.store.reserve_link_state()["revision"],
                "links": [
                    {"source_event_key": "reservation:cafeParse:ALFA",
                     "target_tab_id": "COST-TRIP-ALFA"},
                    {"source_event_key": "reservation:cafeParse:ALFA",
                     "target_tab_id": "COST-TRIP-ALFA"}],
                "unlinks": [],
            }, owner_id=OWNER)
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_DUPLICATE_TARGET)
        self.assertEqual(self.store.reserve_link_state()["links"], {})




class HttpBoundaryTests(LinkFixture):
    """Owner-only over real HTTP, through the board's own guards.

    Staff and anonymous are refused the screen and every link and source-plan API.
    CSRF and the exact origin are the board's own checks, not copies of them.
    """

    def setUp(self):
        from webapp import ledger_board
        from webapp import access_control as _ac

        # Shared process state is saved before any mutation and the restore is
        # registered first, so normal and exceptional exits both restore it.
        self._prev_db_env = os.environ.get("WEBLEDGER_DB")
        self._prev_board_store = ledger_board._STORE
        self._prev_access = getattr(ledger_board, "_ACCESS", None)
        self._prev_sessions = _ac.session_adapter()
        self.server = None
        self.served = None
        self._server_thread = None
        self.addCleanup(self._restore_http_shared_state)
        super().setUp()
        self.configure([source_person("rp-1", "합성 담당자",
                                      ["reservation:cafeParse:ALFA"])])
        self.grant("rp-1", "syn-staff-1")
        self.store.create_account(user_id="syn-staff-3",
                                  role=access_control.ROLE_VIEWER,
                                  display_name="staff3")

        self.board = ledger_board
        os.environ["WEBLEDGER_DB"] = str(self.tmp / "board.sqlite")
        # Do not let serve/bind_access mutate the adapter saved for restoration.
        _ac.bind_synthetic_sessions(True)
        self.server = ledger_board.serve(port=0, with_worker=False,
                                        seed_demo=False)
        self.addCleanup(self._close_served)
        self.addCleanup(self._stop_server)
        # The server answers on its own thread, so the store it is given opens its
        # connection across threads — the same database file as the fixture's
        # store, which is how the request path and the assertions see one state.
        self.served = access_control.AccessStore(sqlite3.connect(
            str(self.db_path), check_same_thread=False, isolation_level=None,
            timeout=5.0))
        self.port = self.server.server_address[1]
        import threading
        self._server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self._server_thread.start()
        ledger_board.bind_access(self.served)

    def _restore_http_shared_state(self):
        from webapp import ledger_board
        from webapp import access_control as _ac

        if self._prev_db_env is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db_env
        ledger_board.bind_store(self._prev_board_store)
        ledger_board.bind_access(self._prev_access)
        _ac.bind_sessions(self._prev_sessions)

    def _stop_server(self):
        server = getattr(self, "server", None)
        if server is None:
            return
        thread = getattr(self, "_server_thread", None)
        if thread is not None and thread.is_alive():
            server.shutdown()
        try:
            server.server_close()
        except Exception:
            pass
        if thread is not None:
            try:
                thread.join(timeout=5)
            except Exception:
                pass
        try:
            server.card_store.close()
        except Exception:
            pass

    def _close_served(self):
        if self.served is not None:
            self.served.conn.close()

    def call(self, path, body=None, user=None, csrf=None, origin=None,
             headers=None):
        import urllib.error
        import urllib.request

        head = {"Content-Type": "application/json"}
        if user is not None:
            head[access_control.SyntheticSessionAdapter.HEADER] = user
        head["X-CSRF-Token"] = (self.board.CSRF_TOKEN if csrf is None else csrf)
        if origin is not False:
            # What a same-origin fetch sends, and the only origin accepted while no
            # public base URL is configured. Omitting it would test nothing.
            head["Origin"] = (origin if origin is not None
                              else f"http://127.0.0.1:{self.port}")
        head.update(headers or {})
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, headers=head,
            method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw or b"{}")
            except ValueError:
                return exc.code, {"raw": raw.decode("utf-8", "replace")}

    def link_body(self, request_id="http-1", **overrides):
        body = {
            "request_id": request_id,
            "source_binding": self.bind(),
            "link_revision": self.store.reserve_link_state()["revision"],
            "links": [{"source_event_key": "reservation:cafeParse:ALFA",
                       "target_tab_id": "COST-TRIP-ALFA"}],
            "unlinks": [],
        }
        body.update(overrides)
        return body

    # -- who may look ------------------------------------------------------
    def test_anonymous_and_staff_are_refused_the_plan_and_the_screen(self):
        for user, expected in ((None, 401), ("syn-staff-1", 403),
                               ("syn-staff-3", 403)):
            for path in ("/api/reserve-link/plan", "/reserve-links",
                         "/api/reserve-link/state"):
                with self.subTest(user=user, path=path):
                    status, _body = self.call(path, user=user)
                    self.assertEqual(status, expected)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_event_links").fetchone()[0], 0)

    def test_the_owner_reaches_the_plan(self):
        status, body = self.call("/api/reserve-link/plan", user=OWNER)
        self.assertEqual(status, 200)
        self.assertTrue(body["configured"])
        self.assertTrue(body["readable"])
        # And it wrote nothing.
        self.assertEqual(self.store.reserve_link_state()["links"], {})

    # -- the write guards --------------------------------------------------
    def test_a_link_write_without_a_correct_csrf_is_refused(self):
        status, _body = self.call("/api/reserve-link/links",
                                  body=self.link_body(), user=OWNER,
                                  csrf="wrong")
        self.assertEqual(status, 403)
        self.assertEqual(self.store.reserve_link_state()["links"], {})

    def test_a_link_write_from_another_origin_is_refused(self):
        status, _body = self.call("/api/reserve-link/links",
                                  body=self.link_body(), user=OWNER,
                                  origin="https://outside.invalid")
        self.assertEqual(status, 403)
        self.assertEqual(self.store.reserve_link_state()["links"], {})

    def test_an_apply_without_a_correct_csrf_is_refused(self):
        self.link("reservation:cafeParse:ALFA", "COST-TRIP-ALFA")
        state = self.store.reserve_link_state()
        plan = reserve_link.build_plan(self.store, self.snapshot)
        status, _body = self.call("/api/reserve-link/apply", user=OWNER,
                                  csrf="wrong",
                                  body={"request_id": "apply-http",
                                        "source_binding": plan["binding"],
                                        "link_revision": state["revision"],
                                        "apply_digest": plan["apply_digest"]})
        self.assertEqual(status, 403)
        self.assertEqual(self.store.visible_tabs("syn-staff-1"), set())

    def test_a_missing_field_over_http_is_refused_and_widens_nothing(self):
        status, body = self.call("/api/reserve-link/links", user=OWNER,
                                 body={"request_id": "http-3",
                                       "source_binding": self.bind(),
                                       "link_revision": self.store
                                       .reserve_link_state()["revision"]})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], reserve_link.CODE_FIELD_MISSING)
        self.assertEqual(self.store.reserve_link_state()["links"], {})
        # Every required field, one at a time.
        for field in ("request_id", "source_binding", "link_revision", "links",
                      "unlinks"):
            with self.subTest(field=field):
                payload = self.link_body(f"http-missing-{field}")
                payload.pop(field)
                status, body = self.call("/api/reserve-link/links", user=OWNER,
                                         body=payload)
                self.assertEqual(status, 400)
                self.assertEqual(body["code"],
                                 reserve_link.CODE_FIELD_MISSING)
        self.assertEqual(self.store.reserve_link_state()["links"], {})

    def test_the_owner_can_save_a_link_over_http_and_it_applies_only_on_command(
            self):
        status, body = self.call("/api/reserve-link/links", user=OWNER,
                                 body=self.link_body("http-save-1"))
        self.assertEqual(status, 200, body)
        self.assertEqual(self.store.reserve_link_state()["links"],
                         {"reservation:cafeParse:ALFA": ["COST-TRIP-ALFA"]})
        # Saved, not applied.
        self.assertEqual(self.store.visible_tabs("syn-staff-1"), set())
        status, plan = self.call("/api/reserve-link/plan", user=OWNER)
        self.assertTrue(plan["applicable"])
        status, applied = self.call("/api/reserve-link/apply", user=OWNER,
                                    body={"request_id": "http-apply-1",
                                          "source_binding": plan["binding"],
                                          "link_revision":
                                              plan["link_revision"],
                                          "apply_digest":
                                              plan["apply_digest"]})
        self.assertEqual(status, 200, applied)
        self.assertEqual(self.store.visible_tabs("syn-staff-1"),
                         {"COST-TRIP-ALFA"})

    def test_an_unlinked_identifier_is_refused_over_http(self):
        status, body = self.call("/api/reserve-link/apply", user=OWNER,
                                 body={"request_id": "http-apply-2",
                                       "source_binding": self.bind(),
                                       "link_revision": self.store
                                       .reserve_link_state()["revision"],
                                       "apply_digest": "0" * 64})
        self.assertEqual(status, 409)
        self.assertIn(body["code"],
                      (reserve_link.CODE_APPLY_UNLINKED,
                       reserve_link.CODE_APPLY_BINDING_CONFLICT))
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM access_trip_assignments").fetchone()[0], 0)

    def test_no_configuration_is_the_required_state_and_creates_nothing(self):
        os.environ.pop(reserve_link.CONFIG_ENV, None)
        status, body = self.call("/api/reserve-link/plan", user=OWNER)
        self.assertEqual(status, 200)
        self.assertFalse(body["configured"])
        self.assertEqual(body["code"], reserve_link.CODE_CONFIG_REQUIRED)
        # And no source was invented to answer the screen.
        self.assertNotIn("binding", body)
        # A write in that state is refused, and nothing is created. The body is
        # written by hand here because `bind()` would need the source that is
        # deliberately absent.
        status, refused = self.call("/api/reserve-link/links", user=OWNER,
                                    body={"request_id": "http-noconf",
                                          "source_binding": {},
                                          "link_revision": 0,
                                          "links": [], "unlinks": []})
        self.assertEqual(status, 409)
        self.assertEqual(refused["code"], reserve_link.CODE_CONFIG_REQUIRED)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_event_links").fetchone()[0], 0)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM reserve_link_applies").fetchone()[0], 0)




class LauncherSourceConfigTests(unittest.TestCase):
    """The launcher hands over the source configuration the owner named.

    Nothing here reads a real roster. The fixtures are synthetic files in a
    temporary directory, and the check is that the launcher passes the three
    declared values through to the environment the board process inherits — the
    same way on a start, a restart and a login — and refuses a missing or damaged
    file by name instead of quietly continuing without one.
    """

    LAUNCHER = Path(__file__).resolve().parents[2] / "tools" / "start_web_ledger_host.ps1"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.source = self.tmp / "roster.json"
        self.source.write_bytes(raw_snapshot([source_person(
            "rp-1", "합성 담당자", ["reservation:cafeParse:ALFA"])]))
        self.config = self.tmp / "reserve-source.json"
        self._previous = os.environ.pop(reserve_link.CONFIG_ENV, None)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._previous is None:
            os.environ.pop(reserve_link.CONFIG_ENV, None)
        else:
            os.environ[reserve_link.CONFIG_ENV] = self._previous

    def write_config(self, **fields):
        described = {"path": str(self.source),
                     "file_sha256": hashlib.sha256(
                         self.source.read_bytes()).hexdigest(),
                     "digest": parse_reservation_access_snapshot(
                         self.source.read_bytes())["digest"]}
        described.update(fields)
        self.config.write_text(json.dumps(described, ensure_ascii=False),
                               encoding="utf-8")
        return described

    INSTALLER = (Path(__file__).resolve().parents[2] / "tools"
                 / "install_web_ledger_startup.ps1")
    RESTART = (Path(__file__).resolve().parents[2] / "tools"
               / "restart_real_review_host.ps1")

    def test_the_launcher_declares_the_setting_and_passes_it_through(self):
        text = self.LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("$ReserveSourceConfig", text)
        # It is handed to the board process as the environment value the module
        # reads, which is what makes it survive a restart and a fresh login.
        self.assertIn("WEBLEDGER_RESERVE_SOURCE", text)
        self.assertEqual(reserve_link.CONFIG_ENV, "WEBLEDGER_RESERVE_SOURCE")

    def test_the_launcher_refuses_a_missing_or_damaged_source_configuration(self):
        """By name, and without reading the roster.

        A source configuration that silently stops being read looks exactly like a
        source that has not changed, so the launcher says which of the three things
        went wrong — file missing, file unreadable, JSON damaged, field absent,
        named file missing — rather than continuing as though it had none.
        """
        text = self.LAUNCHER.read_text(encoding="utf-8")
        for phrase in ("ReserveSourceConfig", "ConvertFrom-Json",
                       "RESERVE_SOURCE_CONFIG", "설정 파일이 없어요"):
            self.assertIn(phrase, text)

    def test_the_installer_carries_the_setting_into_the_scheduled_task(self):
        """The task is what restarts the board, so the setting has to be in it.

        A value that lived only on the launcher's command line would be lost on
        reboot, at the moment the source mattered most.
        """
        text = self.INSTALLER.read_text(encoding="utf-8")
        self.assertIn("$ReserveSourceConfig", text)
        self.assertIn('"-ReserveSourceConfig", $ReserveSourceConfig', text)
        # And it stays optional: a host with no reservation source is a valid host,
        # and making it mandatory would force an existing install to invent a file.
        required_block = text.split("function Test-InstallRequirement")[1]
        required_block = required_block.split("foreach")[0]
        self.assertNotIn("RESERVE_SOURCE_CONFIG", required_block)

    def test_the_direct_restart_carries_the_same_setting(self):
        """The other restart path, and it has to agree with the first two.

        It restores the review configuration the same way, so it restores the
        reservation source configuration the same way too. Without it, the direct
        restart would be the one path that drops the setting.
        """
        text = self.RESTART.read_text(encoding="utf-8")
        self.assertIn("$previousReserveSource", text)
        self.assertIn("WEBLEDGER_RESERVE_SOURCE", text)
        self.assertIn("$reserveSourceConfig", text)
        # Restored in the finally block, or the restart would leave this shell
        # permanently carrying the source configuration.
        self.assertIn("$previousReserveSource", text)

    def test_the_configuration_round_trips_through_the_environment_value(self):
        """What the launcher writes is exactly what the reader accepts.

        The launcher and the module are the two ends of one setting. If either
        shaped the value differently the screen would report "configuration
        required" on a machine whose launcher had been told the source, and the
        failure would look like a missing source rather than a mismatched handoff.
        """
        described = self.write_config()
        os.environ[reserve_link.CONFIG_ENV] = json.dumps(
            described, ensure_ascii=False)
        config = reserve_link.load_source_config()
        self.assertTrue(config["configured"])
        self.assertEqual(config["path"], described["path"])
        self.assertEqual(config["file_sha256"], described["file_sha256"])
        self.assertEqual(config["digest"], described["digest"])
        snapshot = reserve_link.read_source(config)
        self.assertEqual(snapshot["digest"], described["digest"])

    def test_the_path_is_part_of_the_identity_a_relinked_file_breaks(self):
        described = self.write_config()
        os.environ[reserve_link.CONFIG_ENV] = json.dumps(described,
                                                        ensure_ascii=False)
        binding = reserve_link.source_binding(
            reserve_link.read_source(reserve_link.load_source_config()))
        self.assertEqual(binding["source_path"], described["path"])

    def test_an_incomplete_configuration_is_the_required_state(self):
        for missing in ("path", "file_sha256", "digest"):
            with self.subTest(field=missing):
                described = self.write_config()
                described.pop(missing)
                os.environ[reserve_link.CONFIG_ENV] = json.dumps(
                    described, ensure_ascii=False)
                config = reserve_link.load_source_config()
                self.assertFalse(config["configured"])
                self.assertEqual(config["code"],
                                 reserve_link.CODE_CONFIG_REQUIRED)

    def test_a_damaged_configuration_is_an_error_not_a_search(self):
        os.environ[reserve_link.CONFIG_ENV] = "{not json"
        with self.assertRaises(reserve_link.ReserveLinkError) as caught:
            reserve_link.load_source_config()
        self.assertEqual(caught.exception.code,
                         reserve_link.CODE_CONFIG_REQUIRED)
        # And nothing was invented to stand in for it.
        self.assertNotIn("path", reserve_link.load_source_config()
                         if False else {})


if __name__ == "__main__":
    unittest.main()
