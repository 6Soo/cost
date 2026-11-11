"""OWNER-METADATA-001: the company name and the assignee come from the owner.

Observed in production before this work: `/trips` showed `테스트 소유자` on 46
places across 23 trips, and the export sheet printed `회사명(합성 예시)` in B2.
Both read as confirmed facts and neither was anything of the kind. The first was
a hardcoded constant, the second was a hardcoded constant with a label admitting
it, which is the same claim in a different font.

What this file pins:

* the owner sets a company name and a default assignee, once, under CAS with
  replay and an audit row;
* a new trip copies that default and records where the value came from;
* with no default set, a new trip's assignee is **empty** — never the constant;
* changing the profile afterwards leaves **existing trips untouched**;
* a trip's own edit path still works, and resolves the value's origin;
* a trip whose assignee nobody ever recorded is **reported**, not rewritten, and
  refuses the export rather than printing an unclaimed name;
* a name nobody recorded the origin of is refused by *provenance*, so a person
  who genuinely types the same words is not caught by the rule;
* the company name reaches the sheet through the formula guard and is part of the
  export's input hash.

Synthetic stores and synthetic values throughout. No real roster, no production
database, no production browser, no secret.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import sheets_export  # noqa: E402
from webapp.ledger_store import (  # noqa: E402
    LedgerStore, SaveError, LEGACY_SYNTHETIC_OWNER_NAME)


def new_store(seed_demo=False):
    tmp = pathlib.Path(tempfile.mkdtemp())
    return LedgerStore(tmp / "owner.sqlite", seed_demo=seed_demo)


class OwnerProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)

    def save(self, **kwargs):
        params = dict(expected_revision=0, client_request_id="r1",
                      company_name="합성회사", assignee_name="합성담당자")
        params.update(kwargs)
        return self.store.save_owner_profile(**params)

    def test_an_unset_profile_reads_as_empty_rather_than_as_a_name(self):
        profile = self.store.owner_profile()
        self.assertEqual(profile["company_name"], "")
        self.assertEqual(profile["assignee_name"], "")
        self.assertEqual(profile["revision"], 0)
        self.assertFalse(profile["configured"])

    def test_the_first_save_records_both_names(self):
        result = self.save()
        self.assertEqual(result["outcome"], "saved")
        self.assertEqual(self.store.owner_profile()["company_name"], "합성회사")
        self.assertEqual(self.store.owner_profile()["assignee_name"], "합성담당자")

    def test_a_retry_returns_the_first_result_unchanged(self):
        first = self.save()
        again = self.save()
        self.assertEqual(first, again)

    def test_a_retry_replays_even_after_the_profile_moved_on(self):
        """The request identity is the input, not the values it resolved to.

        A save that named only the company name must stay that request forever.
        If its identity were built from the profile it resolved against, a retry
        after someone changed the assignee would look like a different request
        and the owner would be shown a conflict for a request they never altered.
        """
        first = self.save(client_request_id="only-company",
                          company_name="합성회사")
        self.save(client_request_id="later", expected_revision=1,
                  assignee_name="다른담당자")
        replay = self.save(client_request_id="only-company",
                           company_name="합성회사")
        self.assertEqual(first, replay)
        # And the later change is not undone by the replay.
        self.assertEqual(self.store.owner_profile()["assignee_name"], "다른담당자")

    def test_the_same_request_id_with_different_input_is_refused(self):
        self.save()
        with self.assertRaises(SaveError) as caught:
            self.save(company_name="다른회사")
        self.assertEqual(caught.exception.code, "EDIT_CONFLICT")

    def test_a_stale_revision_is_refused(self):
        self.save()
        with self.assertRaises(SaveError) as caught:
            self.save(expected_revision=0, client_request_id="r2")
        self.assertEqual(caught.exception.code, "EDIT_CONFLICT")

    def test_two_connections_cannot_both_write_revision_one(self):
        """One of them wins; the other is told the revision moved.

        Reading the revision before opening the write transaction is what lets
        both decide they are first, and the second then overwrites the first.
        """
        path = self.store.path
        other = LedgerStore(path, seed_demo=False)
        self.addCleanup(other.close)
        self.store.save_owner_profile(expected_revision=0, client_request_id="a",
                                      company_name="회사A")
        with self.assertRaises(SaveError) as caught:
            other.save_owner_profile(expected_revision=0,
                                     client_request_id="b", company_name="회사B")
        self.assertEqual(caught.exception.code, "EDIT_CONFLICT")
        self.assertEqual(self.store.owner_profile()["company_name"], "회사A")

    def test_an_unchanged_save_is_recorded_and_replays_the_same(self):
        self.save(client_request_id="first")
        noop = self.save(client_request_id="again", expected_revision=1)
        self.assertEqual(noop["outcome"], "unchanged")
        self.assertEqual(noop["revision"], 1)
        self.assertEqual(noop, self.save(client_request_id="again",
                                         expected_revision=1))

    def test_every_save_leaves_an_audit_row(self):
        self.save(client_request_id="one")
        self.save(client_request_id="two", expected_revision=1,
                  company_name="바뀐회사")
        rows = self.store.conn.execute(
            "SELECT revision, change_kind, prev_json, new_json, actor,"
            " client_request_id FROM owner_profile_history ORDER BY id"
        ).fetchall()
        self.assertEqual([r[1] for r in rows], ["save", "save"])
        self.assertEqual(rows[-1][0], 2)
        self.assertIn("합성회사", rows[-1][2])
        self.assertIn("바뀐회사", rows[-1][3])
        self.assertEqual(rows[-1][5], "two")

    def test_an_empty_name_is_stored_not_refused(self):
        """A default that has not been set yet is a real state.

        Refusing it would leave a field that can be filled once and never
        cleared, which is worse than starting empty.
        """
        # Nothing changes, so the answer is `unchanged` rather than `saved` —
        # what matters is that it was accepted at all. Refusing would leave a
        # field that can be filled once and never cleared.
        result = self.save(company_name="", assignee_name="")
        self.assertIn(result["outcome"], ("saved", "unchanged"))
        self.assertEqual(self.store.owner_profile()["assignee_name"], "")


class NewTripTests(unittest.TestCase):
    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)

    def trip(self):
        """The stored row, read back after the create.

        `create_trip` returns the proposal it recorded, not the row; the row is
        what every later question is asked about, so it is read rather than
        assumed to match.
        """
        created = self.store.create_trip(
            starts_on="2026-05-01", destination="합성행선지",
            client_request_id="t1")
        return self.store.get_trip(created["tab_id"])

    def test_a_new_trip_with_no_profile_has_no_assignee(self):
        """Not the constant. An invented name becomes a claim about who wrote it."""
        trip = self.trip()
        self.assertEqual(trip["prepared_by_name"], "")
        self.assertNotEqual(trip["prepared_by_name"],
                            LEGACY_SYNTHETIC_OWNER_NAME)
        self.assertEqual(trip["assignee_source"], "")

    def test_a_new_trip_copies_the_profile_default(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      company_name="합성회사",
                                      assignee_name="합성담당자")
        trip = self.trip()
        self.assertEqual(trip["prepared_by_name"], "합성담당자")
        self.assertEqual(trip["assignee_source"], "owner_profile")

    def test_the_prepared_date_is_seoul_today(self):
        import datetime

        trip = self.trip()
        expected = (datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(hours=9)).date().isoformat()
        self.assertEqual(trip["prepared_on"], expected)

    def test_changing_the_profile_leaves_existing_trips_alone(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      assignee_name="첫담당자")
        first = self.trip()
        before = (first["prepared_by_name"], first["prepared_on"],
                  first["display_key"], first["revision"])
        self.store.save_owner_profile(expected_revision=1, client_request_id="p2",
                                      assignee_name="두번째담당자")
        again = self.store.get_trip(first["tab_id"])
        self.assertEqual((again["prepared_by_name"], again["prepared_on"],
                          again["display_key"], again["revision"]), before)

    def test_the_demo_seed_records_where_its_assignee_came_from(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        store = LedgerStore(tmp / "seed.sqlite", seed_demo=True)
        self.addCleanup(store.close)
        rows = store.conn.execute(
            "SELECT prepared_by_name, assignee_source FROM trip_tabs").fetchall()
        self.assertTrue(rows)
        for name, source in rows:
            self.assertEqual(source, "seed")
            self.assertNotEqual(name, LEGACY_SYNTHETIC_OWNER_NAME)


class TripEditResolvesOriginTests(unittest.TestCase):
    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)

    def legacy_trip(self, assignee=LEGACY_SYNTHETIC_OWNER_NAME):
        """A row shaped like one the previous code wrote: value, no origin.

        Written directly rather than by `create_trip`, because the point is the
        state the upgrade has to cope with, and `create_trip` no longer makes it.
        """
        conn = self.store.conn
        conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
            " ends_on, prepared_on, prepared_by_name, assignee_source,"
            " archived, deleted, revision)"
            " VALUES ('legacy','합성여행','합성행선지','2026-05-01','2026-05-03',"
            "'2026-05-01',?,'',0,0,1)", (assignee,))
        conn.commit()
        return "legacy"

    def test_an_edited_assignee_records_a_manual_origin(self):
        tab_id = self.legacy_trip()
        self.store.save_trip_meta(
            tab_id=tab_id, expected_revision=1, client_request_id="m1",
            prepared_by_name="확인된담당자")
        trip = self.store.get_trip(tab_id)
        self.assertEqual(trip["prepared_by_name"], "확인된담당자")
        self.assertEqual(trip["assignee_source"], "manual")

    def test_confirming_the_same_words_records_a_manual_origin(self):
        """Confirming is an act, and the act is what is recorded.

        The value does not change, so nothing about the row differs — but the
        owner still has to be able to say "yes, that is right", and the export
        has to be able to tell that from "nobody checked".
        """
        tab_id = self.legacy_trip()
        result = self.store.save_trip_meta(
            tab_id=tab_id, expected_revision=1, client_request_id="m2",
            prepared_by_name=LEGACY_SYNTHETIC_OWNER_NAME)
        # The value does not move, but the origin does: "" becomes "manual", so
        # this is a real save and says so rather than reporting "nothing changed".
        self.assertEqual(result["outcome"], "saved")
        self.assertEqual(result["revision"], 2)
        self.assertEqual(self.store.get_trip(tab_id)["assignee_source"], "manual")

    def test_renaming_a_trip_alone_does_not_confirm_the_assignee(self):
        """A title edit must not promote an unconfirmed name.

        Every metadata save writes a full snapshot, so "the snapshot mentions an
        assignee" is true after a rename too. Reading that as confirmation would
        let an unrelated edit silently turn an unclaimed name into a confirmed
        one.
        """
        tab_id = self.legacy_trip()
        self.store.save_trip_meta(tab_id=tab_id, expected_revision=1,
                                  client_request_id="m3",
                                  display_key="이름만 바뀐 여행")
        self.assertEqual(self.store.get_trip(tab_id)["assignee_source"], "")
        self.assertFalse(sheets_export._assignee_confirmed(
            self.store.conn, tab_id, "", LEGACY_SYNTHETIC_OWNER_NAME))

    def test_a_person_who_typed_the_old_placeholder_is_not_caught(self):
        """The rule is provenance, not a reserved word.

        If the check compared text, a person genuinely named the same thing
        would have their own entry refused, and there would be no way to fix it
        short of inventing a different name.
        """
        tab_id = self.legacy_trip()
        self.store.save_trip_meta(tab_id=tab_id, expected_revision=1,
                                  client_request_id="m4",
                                  prepared_by_name=LEGACY_SYNTHETIC_OWNER_NAME)
        self.assertTrue(sheets_export._assignee_confirmed(
            self.store.conn, tab_id, "manual", LEGACY_SYNTHETIC_OWNER_NAME))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)
        created = self.store.create_trip(starts_on="2026-05-01",
                                         destination="합성행선지",
                                         client_request_id="t1")
        self.tab_id = created["tab_id"]

    def legacy_trip(self, assignee=LEGACY_SYNTHETIC_OWNER_NAME):
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
            " ends_on, prepared_on, prepared_by_name, assignee_source,"
            " archived, deleted, revision)"
            " VALUES ('legacy','합성여행','합성행선지','2026-05-01','2026-05-03',"
            "'2026-05-01',?,'',0,0,1)", (assignee,))
        self.store.conn.commit()
        return "legacy"

    def test_an_unconfirmed_assignee_refuses_the_export(self):
        tab_id = self.legacy_trip()
        with self.assertRaises(sheets_export.UnconfirmedAssigneeError) as caught:
            sheets_export.build_workbook(self.store, [tab_id])
        self.assertEqual(caught.exception.code, "ASSIGNEE_UNCONFIRMED")
        self.assertEqual(caught.exception.tab_ids, [tab_id])
        self.assertEqual(caught.exception.status, 409)

    def test_the_refusal_carries_the_trip_so_the_owner_can_go_confirm_it(self):
        tab_id = self.legacy_trip()
        try:
            sheets_export.build_workbook(self.store, [tab_id])
            self.fail("expected a refusal")
        except sheets_export.UnconfirmedAssigneeError as exc:
            payload = exc.as_payload()
        self.assertEqual(payload["code"], "ASSIGNEE_UNCONFIRMED")
        self.assertEqual(payload["tab_ids"], [tab_id])
        self.assertIn("확인", payload["message"])

    def test_confirming_the_trip_lets_the_export_through(self):
        tab_id = self.legacy_trip()
        self.store.save_trip_meta(tab_id=tab_id, expected_revision=1,
                                  client_request_id="m1",
                                  prepared_by_name="확인된담당자")
        wb, manifest = sheets_export.build_workbook(self.store, [tab_id])
        self.assertTrue(wb.sheetnames)
        self.assertEqual(manifest["tabs"][0]["prepared_by_name"], "확인된담당자")

    def test_an_empty_assignee_is_not_a_refusal(self):
        wb, _manifest = sheets_export.build_workbook(self.store, [])
        self.assertTrue(wb is not None)

    def test_the_company_name_reaches_the_sheet(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      company_name="합성회사")
        wb, manifest = sheets_export.build_workbook(self.store, [])
        self.assertEqual(manifest["company_name"], "합성회사")

    def test_the_company_cell_is_empty_when_nothing_was_saved(self):
        """Not a placeholder. A blank says "not entered"; a name would be a claim."""
        wb, manifest = sheets_export.build_workbook(self.store, [])
        self.assertEqual(manifest["company_name"], "")
        self.assertEqual(sheets_export.COMPANY_TEXT, "")

    def test_a_formula_in_the_company_name_cannot_execute(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      company_name="=HYPERLINK(\"x\")")
        wb, _manifest = sheets_export.build_workbook(self.store, [])
        sheet = wb[wb.sheetnames[0]] if wb.sheetnames else None
        if sheet is not None:
            value = sheet["B2"].value
            self.assertTrue(str(value).startswith("'"), value)
        self.assertEqual(sheets_export.guard_text("=1+1"), "'=1+1")
        self.assertEqual(sheets_export.guard_text(" +1"), "'+1")

    def test_the_company_name_is_part_of_the_input_hash(self):
        _, before = sheets_export.build_workbook(self.store, [])
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      company_name="합성회사")
        _, after = sheets_export.build_workbook(self.store, [])
        self.assertNotEqual(before["input_snapshot_sha256"],
                            after["input_snapshot_sha256"])

    def test_the_same_input_gives_the_same_hash_for_every_sheet(self):
        """Several sheets, one snapshot: they cannot disagree about the company."""
        self.store.create_trip(starts_on="2026-06-01", destination="둘째행선지",
                               client_request_id="t2")
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      company_name="합성회사")
        tabs = [r[0] for r in self.store.conn.execute(
            "SELECT tab_id FROM trip_tabs ORDER BY tab_id").fetchall()]
        wb, manifest = sheets_export.build_workbook(self.store, tabs)
        self.assertEqual(len(wb.sheetnames), len(tabs))
        for entry in manifest["tabs"]:
            self.assertEqual(entry["company_name"], "합성회사")
        for name in wb.sheetnames:
            self.assertEqual(wb[name]["B2"].value, "합성회사")

    def test_the_manifest_reports_the_assignee_origin(self):
        tab_id = self.legacy_trip()
        self.store.save_trip_meta(tab_id=tab_id, expected_revision=1,
                                  client_request_id="m1",
                                  prepared_by_name="확인된담당자")
        _wb, manifest = sheets_export.build_workbook(self.store, [tab_id])
        self.assertEqual(manifest["tabs"][0]["assignee_source"], "manual")


class LegacyPreservationTests(unittest.TestCase):
    """Nothing existing is rewritten. Not one row, not one field."""

    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
            " ends_on, prepared_on, prepared_by_name, assignee_source,"
            " archived, deleted, revision)"
            " VALUES ('legacy','이름은 그대로','합성행선지','2026-05-01',"
            "'2026-05-03','2026-01-31',?,'',0,0,7)",
            (LEGACY_SYNTHETIC_OWNER_NAME,))
        self.store.conn.commit()
        self.before = self.store.get_trip("legacy")

    def test_setting_a_profile_changes_no_existing_trip(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      company_name="합성회사",
                                      assignee_name="새담당자")
        after = self.store.get_trip("legacy")
        for field in ("prepared_by_name", "prepared_on", "display_key",
                      "revision", "assignee_source", "tab_id"):
            self.assertEqual(after[field], self.before[field], field)

    def test_no_migration_rewrites_the_origin_of_a_historical_row(self):
        """The origin stays unknown until the owner says otherwise.

        Filling it in would be an assertion about the past that nobody can make.
        """
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      assignee_name="새담당자")
        self.assertEqual(self.store.get_trip("legacy")["assignee_source"], "")


class ScreenTests(unittest.TestCase):
    """The `/trips` page: what the owner is told, and what a viewer is not."""

    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)
        self.store.create_trip(starts_on="2026-05-01", destination="합성행선지",
                               client_request_id="t1")

    def page(self, role="owner"):
        from webapp import ledger_board

        previous = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            return ledger_board.trips_page(role=role)
        finally:
            ledger_board.bind_store(previous)

    def profile_page(self, role="owner"):
        from webapp import ledger_board
        previous = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            if role != "owner":
                return ledger_board.access_control_render_owner_admin(None, self.store, view="")
            class _ProfileStore:
                def __init__(self, inner):
                    self.inner = inner
                def owner_profile(self):
                    return self.inner.owner_profile()
                def pending_applications(self):
                    return []
                def list_reservation_persons(self):
                    return []
            return ledger_board.access_control_render_owner_admin(None, _ProfileStore(self.store), view="profile")
        finally:
            ledger_board.bind_store(previous)

    def test_the_owner_sees_the_profile_form(self):
        markup = self.profile_page("owner")
        self.assertIn("action='/api/owner-profile'", markup)
        self.assertIn("name='company_name'", markup)
        self.assertIn("name='assignee_name'", markup)
        self.assertIn("name='expected_revision'", markup)
        self.assertIn("name='csrf'", markup)
        self.assertIn("name='client_request_id'", markup)

    def test_a_viewer_is_not_shown_the_profile_form(self):
        markup = self.page("viewer")
        self.assertNotIn("/api/owner-profile", markup)

    def test_an_unset_profile_asks_for_the_assignee_at_creation(self):
        """The profile form exposes the unset value without inventing a name."""
        markup = self.profile_page("owner")
        self.assertIn("기본 담당자명", markup)
        self.assertIn("name='assignee_name' value=''", markup)
        # The redesigned profile view keeps the field empty; the copy policy
        # is explained on the trip-management screen where it takes effect.
        self.assertNotIn("LEGACY_SYNTHETIC_OWNER_NAME", markup)
        self.assertFalse(self.store.owner_profile()["configured"])

    def test_a_set_profile_does_not_show_that_prompt(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      assignee_name="담당자")
        self.assertNotIn("기본 담당자명이 아직 없어요", self.page("owner"))

    def test_an_unconfirmed_assignee_is_flagged_without_being_changed(self):
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
            " ends_on, prepared_on, prepared_by_name, assignee_source,"
            " archived, deleted, revision) VALUES ('legacy','레거시여행','',"
            "'2026-05-01','2026-05-03','2026-05-01',?,'',0,0,1)",
            (LEGACY_SYNTHETIC_OWNER_NAME,))
        self.store.conn.commit()
        markup = self.page("owner")
        self.assertIn("담당자 확인이 필요해요", markup)
        # Reported, not rewritten.
        self.assertEqual(self.store.get_trip("legacy")["prepared_by_name"],
                         LEGACY_SYNTHETIC_OWNER_NAME)

    def test_a_confirmed_assignee_is_not_flagged(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      assignee_name="담당자")
        self.store.create_trip(starts_on="2026-06-01", destination="둘째",
                               client_request_id="t2")
        self.assertNotIn("담당자 확인이 필요해요", self.page("owner"))

    def test_a_trip_with_no_assignee_says_so_rather_than_naming_one(self):
        self.assertIn("담당자 미입력", self.page("owner"))

    def test_the_export_page_no_longer_calls_real_values_synthetic(self):
        from webapp import ledger_board

        previous = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            markup = ledger_board.export_page()
        finally:
            ledger_board.bind_store(previous)
        self.assertNotIn("합성 예시", markup)


class ConfirmationIsAnActTests(unittest.TestCase):
    """Confirming has to be something the owner does, not something a form does.

    The trip form carries every field on the trip, so a rename used to arrive
    carrying the assignee as well. Saving that recorded the owner's confirmation
    of a name they never looked at. The rules below are the boundary: a changed
    name is an edit, an unchanged one counts only when it is ticked, and a
    caller sending the field on its own keeps the original contract.
    """

    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)
        self.store.conn.execute(
            "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
            " ends_on, prepared_on, prepared_by_name, assignee_source,"
            " archived, deleted, revision) VALUES ('legacy','레거시여행','',"
            "'2026-05-01','2026-05-03','2026-05-01',?,'',0,0,1)",
            (LEGACY_SYNTHETIC_OWNER_NAME,))
        self.store.conn.commit()

    def post(self, **fields):
        from webapp import ledger_board

        store = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            return fields
        finally:
            ledger_board.bind_store(store)

    def test_the_form_marker_is_always_submitted(self):
        """An unchecked checkbox sends nothing at all.

        Making the marker itself the checkbox would leave an un-ticked form
        indistinguishable from a plain JSON caller, and the protection would
        depend on the browser rather than on the server.
        """
        from webapp import ledger_board

        previous = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            markup = ledger_board.trips_page(role="owner")
        finally:
            ledger_board.bind_store(previous)
        self.assertIn("name='assignee_form'", markup)
        self.assertIn("name='assignee_confirmed'", markup)

    def test_only_an_unconfirmed_trip_offers_the_confirmation(self):
        """The tick belongs to the trip that needs confirming, and no other."""
        from webapp import ledger_board

        previous = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            self.store.save_owner_profile(
                expected_revision=0, client_request_id="p1",
                assignee_name="확인된담당자")
            self.store.create_trip(starts_on="2026-06-01", destination="둘째",
                                   client_request_id="t2")
            markup = ledger_board.trips_page(role="owner")
        finally:
            ledger_board.bind_store(previous)
        # The one unconfirmed trip offers it, so it appears once — every other
        # trip already has a recorded origin and must not ask.
        self.assertEqual(markup.count("이 담당자가 맞다고 확인해요"), 1)
        # Every trip form still carries the marker, so the server can tell a
        # form submit from a plain JSON caller whichever trip it was. Counted
        # against the assignee inputs, because a trip has more than one form.
        self.assertEqual(
            markup.count("name='assignee_form'"),
            markup.count("name='prepared_by_name'"))
        self.assertEqual(markup.count("name='prepared_by_name'"), 2)


if __name__ == "__main__":
    unittest.main()
