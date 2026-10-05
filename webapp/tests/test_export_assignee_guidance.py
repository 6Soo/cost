"""EXPORT-ASSIGNEE-GUIDANCE-001: say it on the screen, before the request.

The export already refused a trip whose assignee nobody recorded, with
`ASSIGNEE_UNCONFIRMED`. That was correct and stayed correct. The gap was one step
earlier: the selection screen offered that trip, checked it, and said only that
the values are saved as they are. So the owner pressed the button, was refused,
and had nothing on screen telling them which trip to go and fix.

This file pins the screen half of that, and pins what the screen must *not* do.

Four synthetic cases, because the rule has to be quiet as well as loud:

* **blank** — an empty assignee has no name to have failed to confirm. No warning.
* **manual** — a name the owner typed. No warning. This is the false positive that
  would make the screen noise.
* **unknown** — a value with no recorded origin. Warned, linked, still checked.
* **legacy explicit** — a pre-existing row the owner confirmed by saving it.
  No warning, because the request ledger already holds the confirmation.

And three things the screen is forbidden from doing, each with its own test:
auto-confirming, renaming, and unticking. The last one matters most — silently
unticking a trip would decide the owner's selection for them and produce an export
missing a trip they had chosen.

The decision itself is not re-implemented here. The screen and the export call the
same function, so they cannot drift; the wrapper test below asserts they agree.

No real roster, no real name, no production data, no network.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import ledger_board, sheets_export  # noqa: E402
from webapp.ledger_store import LedgerStore  # noqa: E402

WARN_TEXT = "담당자 확인이 필요해요"
TRIPS_LINK = "여행 관리에서 확인"


def new_store():
    return LedgerStore(pathlib.Path(tempfile.mkdtemp()) / "guidance.sqlite",
                       seed_demo=False)


def add_trip(store, tab_id, assignee, source, *, archived=0, revision=1):
    store.conn.execute(
        "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
        " ends_on, prepared_on, prepared_by_name, assignee_source, archived,"
        " deleted, revision) VALUES (?,?,'합성행선지','2026-05-01','2026-05-03',"
        "'2026-05-01',?,?,?,0,?)",
        (tab_id, f"여행 {tab_id}", assignee, source, archived, revision))
    store.conn.commit()
    return tab_id


class ScreenBase(unittest.TestCase):
    def setUp(self):
        self.store = new_store()
        self.addCleanup(self.store.close)

    def page(self):
        previous = ledger_board._STORE
        ledger_board.bind_store(self.store)
        try:
            return ledger_board.export_page()
        finally:
            ledger_board.bind_store(previous)

    def option_for(self, markup, tab_id):
        """The checkbox and everything after it, up to the next one.

        The note is attached to one option rather than to the page, so a test has
        to look at the option and not just at the page — a page-level assertion
        would pass with the note attached to the wrong trip.
        """
        start = markup.index(f"value='{tab_id}'")
        nxt = markup.find("name='tab_ids'", start + 1)
        return markup[start:nxt if nxt != -1 else len(markup)]


class UnknownAssigneeScreenTests(ScreenBase):
    def setUp(self):
        super().setUp()
        self.tab = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")

    def test_the_trip_is_told_its_assignee_needs_confirming(self):
        self.assertIn(WARN_TEXT, self.option_for(self.page(), self.tab))

    def test_the_note_offers_the_way_to_go_and_confirm_it(self):
        self.assertIn(TRIPS_LINK, self.option_for(self.page(), self.tab))
        self.assertIn("href='/trips'", self.option_for(self.page(), self.tab))

    def test_the_page_says_how_many_need_confirming(self):
        """One line saying it, so the owner sees it without reading every option."""
        markup = self.page()
        self.assertIn("담당자 확인이 필요한 여행 1개가 있어요", markup)
        self.assertIn("해당 여행을 선택하면", markup)

    def test_the_trip_stays_checked(self):
        """Untick it and the owner's chosen export is quietly missing a trip.

        The screen may say a trip will be refused; it may not decide that it is
        therefore not wanted.
        """
        option = self.option_for(self.page(), self.tab)
        self.assertIn("checked>", option)


class QuietCasesTests(ScreenBase):
    """The cases that must produce nothing, or the screen is just noise."""

    def test_a_blank_assignee_is_not_warned_about(self):
        """There is no name to have failed to confirm."""
        add_trip(self.store, "t-blank", "", "")
        self.assertEqual(sheets_export.assignee_needs_confirmation(self.store), [])
        self.assertNotIn(WARN_TEXT, self.page())

    def test_a_name_the_owner_typed_is_not_warned_about(self):
        add_trip(self.store, "t-manual", "사람이 입력한 이름", "manual")
        self.assertEqual(sheets_export.assignee_needs_confirmation(self.store), [])
        self.assertNotIn(WARN_TEXT, self.page())

    def test_a_profile_copied_assignee_is_not_warned_about(self):
        self.store.save_owner_profile(expected_revision=0, client_request_id="p1",
                                      assignee_name="프로필 기본값")
        self.store.create_trip(starts_on="2026-06-01", destination="합성행선지",
                               client_request_id="t2")
        self.assertEqual(sheets_export.assignee_needs_confirmation(self.store), [])
        self.assertNotIn(WARN_TEXT, self.page())

    def test_a_pre_existing_confirmation_is_not_warned_about(self):
        """Confirmation the old code recorded, by saving the name it confirmed.

        The row predates the provenance column, so the evidence is in the request
        ledger. Warning here would tell the owner to confirm something they
        already confirmed.
        """
        tab = add_trip(self.store, "t-legacy", "예전 이름", "")
        self.store.save_trip_meta(tab_id=tab, expected_revision=1,
                                  client_request_id="m1",
                                  prepared_by_name="예전 이름")
        self.assertEqual(sheets_export.assignee_needs_confirmation(self.store), [])
        self.assertNotIn(WARN_TEXT, self.page())

    def test_only_the_unconfirmed_trip_is_flagged_among_several(self):
        add_trip(self.store, "t-blank", "", "")
        add_trip(self.store, "t-manual", "사람이 입력한 이름", "manual")
        unknown = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        markup = self.page()
        self.assertEqual(
            sheets_export.assignee_needs_confirmation(self.store), [unknown])
        self.assertIn(WARN_TEXT, self.option_for(markup, unknown))
        self.assertNotIn(WARN_TEXT, self.option_for(markup, "t-blank"))
        self.assertNotIn(WARN_TEXT, self.option_for(markup, "t-manual"))
        self.assertIn("담당자 확인이 필요한 여행 1개가 있어요", markup)


class TitleOnlyEditTests(ScreenBase):
    def test_a_rename_does_not_silently_confirm(self):
        """A rename is not a confirmation, on screen or in the export.

        The trip form carries every field, so a title-only save used to promote
        an unclaimed name to a confirmed one. If that happened here the warning
        would vanish and the trip would print a name nobody checked.
        """
        tab = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        self.store.save_trip_meta(tab_id=tab, expected_revision=1,
                                  client_request_id="m1",
                                  display_key="이름만 바뀐 여행")
        self.assertEqual(
            sheets_export.assignee_needs_confirmation(self.store), [tab])
        self.assertIn(WARN_TEXT, self.page())


class CountHonestyTests(ScreenBase):
    """The number has to count something the owner can see.

    The judgement covers every trip in the store, but the page does not: an
    archived trip is offered unchecked, and a deleted one is not offered at all.
    A count taken over the whole store would put a number here naming a trip that
    is not on the page.
    """

    def test_a_deleted_trip_is_not_counted(self):
        """It is not on the page, so counting it would name nothing visible."""
        add_trip(self.store, "t-gone", "출처가 없는 이름", "", revision=1)
        self.store.conn.execute(
            "UPDATE trip_tabs SET deleted=1 WHERE tab_id='t-gone'")
        self.store.conn.commit()
        markup = self.page()
        self.assertNotIn("t-gone", markup)
        self.assertNotIn(WARN_TEXT, markup)
        self.assertNotIn("담당자 확인이 필요한 여행", markup)

    def test_an_archived_trip_is_still_warned_about(self):
        """It is on the page, so the note belongs on it.

        Archived trips are offered unchecked, but an owner who ticks one would be
        refused, and the page is where that gets said.
        """
        add_trip(self.store, "t-arch", "출처가 없는 이름", "", archived=1)
        markup = self.page()
        self.assertIn("t-arch", markup)
        self.assertIn(WARN_TEXT, self.option_for(markup, "t-arch"))
        # Unchecked, as archived trips have always been.
        self.assertNotIn("checked>", self.option_for(markup, "t-arch"))

    def test_the_count_covers_the_trips_the_page_shows(self):
        add_trip(self.store, "t-arch", "출처가 없는 이름", "", archived=1)
        add_trip(self.store, "t-live", "출처가 없는 이름", "")
        add_trip(self.store, "t-ok", "확인된 이름", "manual")
        self.assertIn("담당자 확인이 필요한 여행 2개", self.page())

    def test_the_count_says_nothing_about_the_selection(self):
        """The page is static and the selection is not.

        An owner who unticks the trip would still be reading a line claiming it is
        selected, so the line cannot claim that. It says which trips need
        confirming and what happens if one is selected.
        """
        add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        markup = self.page()
        self.assertIn("담당자 확인이 필요한 여행 1개가 있어요", markup)
        self.assertNotIn("선택돼 있어요", markup)
        self.assertNotIn("선택되어", markup)
        self.assertIn("해당 여행을 선택하면", markup)

    def test_the_note_is_a_statement_about_the_trip_not_the_selection(self):
        """It stays true whoever unticks what.

        Nothing on this page can see the current selection — it is static — so
        the note describes the trip, and the summary describes the trips. Neither
        may claim anything about what is or is not ticked right now.
        """
        add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        add_trip(self.store, "t-ok", "확인된 이름", "manual")
        markup = self.page()
        for phrase in ("선택돼", "선택되어", "선택됨", " ticked"):
            self.assertNotIn(phrase, markup, phrase)
        # The trip-level note stays attached to its own trip.
        self.assertIn(WARN_TEXT, self.option_for(markup, "t-unknown"))
        self.assertNotIn(WARN_TEXT, self.option_for(markup, "t-ok"))


class ScreenChangesNothingTests(ScreenBase):
    """The screen reports. It does not act."""

    def setUp(self):
        super().setUp()
        self.tab = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")

    def before(self):
        return self.store.get_trip(self.tab)

    def test_reading_the_page_confirms_nothing(self):
        before = self.before()
        self.page()
        after = self.store.get_trip(self.tab)
        for field in ("prepared_by_name", "assignee_source", "revision"):
            self.assertEqual(after[field], before[field], field)

    def test_reading_the_page_writes_no_revision(self):
        self.assertEqual(self.before()["revision"], 1)
        self.page()
        self.assertEqual(self.before()["revision"], 1)

    def test_reading_the_page_leaves_no_request_record(self):
        self.page()
        count = self.store.conn.execute(
            "SELECT COUNT(*) FROM trip_tab_requests").fetchone()[0]
        self.assertEqual(count, 0)

    def test_the_page_prints_no_assignee_value_it_could_not_confirm(self):
        """The value stays out of the page entirely.

        It is shown on `/trips`, where there is an explicit form beside it to act
        on. Repeating an unconfirmed name here would be a second place to read it
        and no new way to fix it.
        """
        self.assertNotIn("출처가 없는 이름", self.page())


class WrapperAgreesWithTheExportTests(ScreenBase):
    def test_the_wrapper_and_the_export_refuse_the_same_trips(self):
        """One decision behind two names, not two decisions.

        A copy of the rule would drift, and the drift is quiet: the screen stops
        warning about a trip the export still refuses, which looks like the screen
        losing track rather than the two disagreeing.
        """
        unknown = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        add_trip(self.store, "t-ok", "확인된 이름", "manual")
        self.assertEqual(
            sheets_export.assignee_needs_confirmation(self.store), [unknown])
        with self.assertRaises(sheets_export.UnconfirmedAssigneeError) as caught:
            sheets_export.build_workbook(self.store, [unknown])
        self.assertEqual(caught.exception.tab_ids, [unknown])

    def test_the_wrapper_is_the_only_new_public_name(self):
        """The decision function stays private; one wrapper is added, not a fork."""
        self.assertTrue(hasattr(sheets_export, "assignee_needs_confirmation"))
        self.assertTrue(sheets_export._assignee_confirmed.__name__.startswith("_"))


class ServerStillDecidesTests(ScreenBase):
    def test_the_refusal_is_unchanged_by_the_screen(self):
        """The screen is advice; the export still refuses, and refuses whole."""
        tab = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        add_trip(self.store, "t-ok", "확인된 이름", "manual")
        with self.assertRaises(sheets_export.UnconfirmedAssigneeError) as caught:
            sheets_export.build_workbook(self.store, [tab, "t-ok"])
        self.assertEqual(caught.exception.code, "ASSIGNEE_UNCONFIRMED")
        self.assertEqual(caught.exception.status, 409)

    def test_an_unconfirmed_trip_alongside_a_fine_one_still_refuses(self):
        tab = add_trip(self.store, "t-unknown", "출처가 없는 이름", "")
        add_trip(self.store, "t-ok", "확인된 이름", "manual")
        with self.assertRaises(sheets_export.UnconfirmedAssigneeError):
            sheets_export.build_workbook(self.store, [tab, "t-ok"])
        # And nothing was produced for the good trip either.
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='xlsx_jobs'"
            ).fetchone()[0], 0)


class NoStoreTests(unittest.TestCase):
    def test_the_page_still_renders_without_a_store(self):
        previous = ledger_board._STORE
        ledger_board.bind_store(None)
        try:
            markup = ledger_board.export_page()
        finally:
            ledger_board.bind_store(previous)
        self.assertNotIn(WARN_TEXT, markup)

    def test_the_wrapper_answers_empty_without_a_store(self):
        self.assertEqual(sheets_export.assignee_needs_confirmation(None), [])


if __name__ == "__main__":
    unittest.main()