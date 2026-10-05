"""BOARD-SOURCE-PREVIEW-001: show the trip's real source rows beside the ledger.

What came in: a trip with zero income and zero expense rows shows an empty
ledger, and nothing on the screen tells you whether that means "nothing
happened" or "nothing has been entered yet". The source does.

So the board shows, read only, the source rows whose sheet is *exactly* this
trip's display key. The boundaries below are the whole design:

* **The match is an exact string.** A trip is shown the source of a sheet named
  identically and nothing else. No prefix, no date range, no settlement day, no
  "only one trip could plausibly match". A wrong row shown under a trip's name
  is worse than no row, because it looks checked.
* **It is not a ledger total.** It carries its own heading and lives outside the
  totals block, so the saved sums above it cannot be read as including it.
* **It decides nothing.** No approval, no selection, no write of any kind. The
  only control is a link to the comparison screen, which is where decisions are
  made.
* **It is owner-only, and safe without a service.** No review service bound, or
  one that raises, leaves the ledger exactly as it was.
* **Everything printed is escaped.** The values come from a spreadsheet a person
  filled in, so `<` and `&` are ordinary content, not markup.

Synthetic service, synthetic sheets, synthetic names. No real source, no real
data, no network, no production browser.
"""

from __future__ import annotations

import pathlib
import sys
import urllib.parse
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import ledger_board as board  # noqa: E402
from webapp import ledger_design, real_review  # noqa: E402
from webapp.ledger_store import LedgerStore  # noqa: E402

#: Placeholders. The real sheet name used by a test is the trip's own
#: `display_key`, because the match is string equality and `create_trip`
#: derives the name from the date and destination.
OTHER_SHEET = "0520_다른합성행사"


def source_row(sheet, row, *, date, amount, description="합성 내용",
               decision="", locator_extra="", evidence="available"):
    """One source row shaped like `review_context` builds them."""
    return {
        "ref": f"{sheet}!$A${row}|$B${row} (row {row})",
        "source": {
            "date": date,
            "amount": amount,
            "fieldcells": [
                {"address": f"A{row}", "label": "날짜", "value": date},
                {"address": f"B{row}", "label": "내용", "value": description},
                {"address": f"C{row}", "label": "금액", "value": amount},
            ],
            "merchant": real_review.__dict__.get("MERCHANT_ABSENT", "-"),
            "description": description,
            "sourceLocator": f"{sheet}!$A${row}|$C${row} (row {row}){locator_extra}",
            "evidence_status": evidence,
        },
        "candidates": [],
        "decision": decision,
    }


class FakeService:
    """The smallest thing `active_service()` is asked of: a `model()`."""

    def __init__(self, rows):
        self._rows = rows

    def model(self):
        return {"rows": self._rows}


class RaisingService:
    def model(self):
        raise RuntimeError("the source could not be read")


class BoardBase(unittest.TestCase):
    #: Set per test from the trip that was created.
    sheet = ""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.prev_db = __import__("os").environ.get("WEBLEDGER_DB")
        __import__("os").environ["WEBLEDGER_DB"] = str(self.tmp / "board.sqlite")
        self.store = LedgerStore(self.tmp / "board.sqlite", seed_demo=False)
        board.bind_store(self.store)
        self.trip = self.store.create_trip(
            starts_on="2026-05-01", destination="합성행선지",
            client_request_id="t1")
        self.tab_id = self.trip["tab_id"]
        self.trip_row = self.store.get_trip(self.tab_id)
        self.sheet = self.trip_row["display_key"]
        self.other = OTHER_SHEET
        # Pinned up front, because the renderer reads the role rather than being
        # handed it. A helper that set it later would let a test assert on a page
        # the renderer never believed it was drawing.
        self._prev_role = getattr(board._ROLE_LOCAL, "role", None)
        self.as_owner()
        self.addCleanup(self._restore)
        self._saved = (real_review._SERVICE, real_review._RESOLVED,
                       real_review._CONFIG_ERROR, real_review._LAST_RECHECK)

    def _restore(self):
        (real_review._SERVICE, real_review._RESOLVED,
         real_review._CONFIG_ERROR, real_review._LAST_RECHECK) = self._saved
        board.bind_store(None)
        self.store.close()
        if self.prev_db is None:
            __import__("os").environ.pop("WEBLEDGER_DB", None)
        else:
            __import__("os").environ["WEBLEDGER_DB"] = self.prev_db
        if self._prev_role is None:
            if hasattr(board._ROLE_LOCAL, "role"):
                del board._ROLE_LOCAL.role
            if hasattr(board._ROLE_LOCAL, "session"):
                del board._ROLE_LOCAL.session
        else:
            board._ROLE_LOCAL.role = self._prev_role

    def use_service(self, service):
        real_review.bind_real_review(service)

    def as_owner(self):
        board._ROLE_LOCAL.role = "owner"
        board._ROLE_LOCAL.session = None

    def as_viewer(self):
        board._ROLE_LOCAL.role = "viewer"
        board._ROLE_LOCAL.session = None

    def preview(self):
        self.as_owner()
        return ledger_design._source_preview_html(self.trip_row)


class MatchingTests(BoardBase):
    def test_the_rows_of_this_trip_sheet_are_shown(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000"),
            source_row(self.sheet, 9, date="2026-05-01", amount="80000"),
        ]))
        markup = self.preview()
        self.assertIn("120000", markup)
        self.assertIn("80000", markup)
        self.assertEqual(markup.count("class='src-row'"), 2)

    def test_another_trip_sheet_is_not_shown(self):
        """The wrong trip's source under this trip's name would look checked."""
        self.use_service(FakeService([
            source_row(self.other, 8, date="2026-05-20", amount="999999"),
        ]))
        markup = self.preview()
        self.assertNotIn("999999", markup)
        self.assertEqual(markup, "")

    def test_a_prefix_of_the_sheet_name_is_not_a_match(self):
        self.use_service(FakeService([
            source_row(self.sheet + "_후속", 8, date="2026-05-01", amount="555555"),
        ]))
        self.assertEqual(self.preview(), "")

    def test_a_sheet_name_with_the_trip_name_inside_it_is_not_a_match(self):
        self.use_service(FakeService([
            source_row("합성" + self.sheet, 8, date="2026-05-01", amount="555555"),
        ]))
        self.assertEqual(self.preview(), "")

    def test_rows_are_split_keeping_each_trip_to_its_own(self):
        self.use_service(FakeService([
            source_row(self.other, 8, date="2026-05-20", amount="999999"),
            source_row(self.sheet, 8, date="2026-05-01", amount="120000"),
        ]))
        markup = self.preview()
        self.assertIn("120000", markup)
        self.assertNotIn("999999", markup)

    def test_the_heading_names_the_source(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        markup = self.preview()
        self.assertIn("실제 원천 자료", markup)
        self.assertIn("입금과 지출", markup)
        self.assertIn("저장된 장부 합계와 별도로", markup)

    def test_the_review_link_carries_the_exact_sheet(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        markup = self.preview()
        self.assertIn("href='/review?q=" + urllib.parse.quote(self.sheet, safe="")
                      + "'", markup)

    def test_the_locator_and_the_review_state_are_shown(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000",
                       decision="확인함")]))
        markup = self.preview()
        self.assertIn("원본 위치", markup)
        self.assertIn(f"{self.sheet}!$A$8", markup)
        self.assertIn("확인함", markup)

    def test_an_unreviewed_row_says_so_rather_than_being_blank(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        self.assertIn("미검토", self.preview())


class EmptyLedgerTests(BoardBase):
    def test_a_trip_with_no_ledger_rows_still_shows_its_source(self):
        """The case this exists for: an empty ledger with real source rows."""
        self.assertEqual(
            self.store.tab_totals(self.tab_id)["income"], 0)
        self.assertEqual(
            self.store.tab_totals(self.tab_id)["expense"], 0)
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        self.as_owner()
        markup = ledger_design.render(
            ledger_design.page(self.tab_id))
        self.assertIn("실제 원천 자료", markup)
        self.assertIn("120000", markup)


class LedgerTotalsTests(BoardBase):
    def test_the_preview_is_outside_the_totals_block(self):
        """Otherwise the source could be read as part of the saved sums."""
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        self.as_owner()
        markup = ledger_design.render(ledger_design.page(self.tab_id))
        sums = markup[markup.index("id='live-sum'"):]
        sums = sums[:sums.index("id='src-preview'")]
        self.assertNotIn("120000", sums)

    def test_the_saved_totals_are_unchanged_by_the_preview(self):
        before = self.store.tab_totals(self.tab_id)
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        self.as_owner()
        markup = ledger_design.render(ledger_design.page(self.tab_id))
        self.assertIn("합계 상태", markup)
        self.assertEqual(self.store.tab_totals(self.tab_id), before)


class SafetyTests(BoardBase):
    def test_a_viewer_is_shown_nothing(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        self.as_viewer()
        self.assertEqual(
            ledger_design._source_preview_html(self.trip_row), "")

    def test_no_service_leaves_the_ledger_as_it_was(self):
        self.use_service(None)
        self.assertEqual(self.preview(), "")

    def test_a_service_that_raises_leaves_the_ledger_as_it_was(self):
        self.use_service(RaisingService())
        self.as_owner()
        self.assertEqual(
            ledger_design._source_preview_html(self.trip_row), "")

    def test_a_row_with_no_source_is_skipped_rather_than_crashing(self):
        self.use_service(FakeService([
            {"ref": "x", "source": None, "decision": ""},
            source_row(self.sheet, 8, date="2026-05-01", amount="120000"),
        ]))
        self.assertIn("120000", self.preview())

    def test_the_preview_writes_nothing(self):
        """Read only, and it says so by leaving no trace."""
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        before = self.store.get_trip(self.tab_id)
        before_requests = self.store.conn.execute(
            "SELECT COUNT(*) FROM trip_tab_requests").fetchone()[0]
        self.preview()
        after = self.store.get_trip(self.tab_id)
        after_requests = self.store.conn.execute(
            "SELECT COUNT(*) FROM trip_tab_requests").fetchone()[0]
        for field in ("prepared_by_name", "prepared_on", "revision",
                      "assignee_source", "display_key"):
            self.assertEqual(after[field], before[field], field)
        # Creating the trip already recorded a request, so this compares rather
        # than asserting zero — the point is that reading changed nothing.
        self.assertEqual(after_requests, before_requests)


class EscapingTests(BoardBase):
    def test_markup_in_a_source_value_is_escaped(self):
        hostile = "<script>alert(1)</script>"
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000",
                       description=hostile)]))
        markup = self.preview()
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)

    def test_a_quote_in_a_value_cannot_break_the_review_link(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000",
                       description="a\" onclick='x'")]))
        markup = self.preview()
        self.assertNotIn("onclick='x'", markup.replace("&quot;", ""))

    def test_an_ampersand_in_a_value_is_escaped(self):
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000",
                       description="a & b")]))
        self.assertIn("a &amp; b", self.preview())


class LocatorTests(unittest.TestCase):
    def test_a_locator_without_a_sheet_names_none(self):
        self.assertEqual(ledger_design._source_sheet_name("no bang here"), "")

    def test_the_sheet_is_everything_before_the_first_bang(self):
        self.assertEqual(
            ledger_design._source_sheet_name("이름!$A$5|$C$5 (row 5)"), "이름")

    def test_an_empty_locator_names_none(self):
        self.assertEqual(ledger_design._source_sheet_name(""), "")
        self.assertEqual(ledger_design._source_sheet_name(None), "")


class EncodingAndPlacementTests(BoardBase):
    """A sheet name is free text, and it goes into a query string."""

    HOSTILE_SHEET = "0616_레분토&리시리"

    def rename_trip_to(self, sheet):
        """The trip's display key IS the sheet name, by the contract.

        A hostile sheet name has to be renamed onto the trip or the preview
        correctly shows nothing, and the test would be asserting about a page
        that never had a row to show.
        """
        self.store.save_trip_meta(
            tab_id=self.tab_id, expected_revision=self.trip_row["revision"],
            client_request_id="rename-" + str(abs(hash(sheet)) % 10**6),
            display_key=sheet)
        self.trip_row = self.store.get_trip(self.tab_id)
        self.sheet = sheet
        return sheet

    def preview_for(self, sheet):
        self.rename_trip_to(sheet)
        self.use_service(FakeService([
            source_row(sheet, 8, date="2026-06-16", amount="50000")]))
        saved = real_review.bind_real_review
        return self.preview(), sheet

    def test_an_ampersand_in_a_sheet_name_is_percent_encoded(self):
        """A real sheet name carries `&`, which means something else in a query.

        Escaping alone is not encoding: `&` would be read as the start of the next
        parameter, and the review screen would open with a truncated term.
        """
        markup, _sheet = self.preview_for(self.HOSTILE_SHEET)
        self.assertIn("q=0616_%EB%A0%88%EB%B6%84%ED%86%A0%26%EB%A6%AC%EC%8B%9C%EB%A6%AC",
                      markup)
        # The raw `&` must not sit unencoded inside the href.
        href = markup[markup.index("href='"):]
        href = href[:href.index("'")]
        self.assertNotIn("&", href)

    def test_the_link_round_trips_back_to_the_same_sheet(self):
        import urllib.parse

        markup, sheet = self.preview_for(self.HOSTILE_SHEET)
        href = markup[markup.index("href='") + 6:]
        href = href[:href.index("'")]
        self.assertEqual(
            urllib.parse.parse_qs(urllib.parse.urlparse(href).query)["q"],
            [sheet])

    def test_a_space_in_a_sheet_name_is_encoded(self):
        markup, _sheet = self.preview_for("합성 행사 A")
        href = markup[markup.index("href='") + 6:]
        href = href[:href.index("'")]
        self.assertNotIn(" ", href)

    def test_the_review_link_sits_with_the_heading(self):
        """Not after the rows.

        A trip with dozens of source rows pushes a trailing link past the fold,
        and the control a reader wants first becomes the one they must scroll to.
        """
        rows = [source_row(self.sheet, row, date="2026-05-01", amount="1")
                for row in range(8, 40)]
        self.use_service(FakeService(rows))
        markup = self.preview()
        self.assertIn("src-hd", markup)
        heading_at = markup.index("실제 원천 자료")
        link_at = markup.index("id='src-review-link'")
        last_row_at = markup.rindex("class='src-row'")
        self.assertLess(heading_at, link_at)
        self.assertLess(link_at, last_row_at)

    def test_the_wording_does_not_claim_a_row_is_unapplied(self):
        """Not "아직 반영되지 않은" for every row.

        A row that *has* been applied would then read as unapplied, and the owner
        would be sent to reconcile a difference that does not exist.
        """
        self.use_service(FakeService([
            source_row(self.sheet, 8, date="2026-05-01", amount="120000")]))
        markup = self.preview()
        self.assertIn("원천 자료입니다", markup)
        self.assertIn("저장된 장부 합계와 별도로", markup)
        self.assertIn("검토에서 차이를 확인하세요", markup)
        self.assertNotIn("아직 반영되지 않은", markup)
        self.assertNotIn("반영되지 않은", markup)


class SavedChoiceTests(BoardBase):
    """A saved decision is shown; it is never written, cleared or chosen."""

    def test_a_saved_choice_is_reflected_in_what_is_shown(self):
        ref = f"{self.sheet}!$A$8|$C$8 (row 8)"
        self.use_service(FakeService([
            {"ref": ref,
             "source": source_row(self.sheet, 8, date="2026-05-01",
                                  amount="120000")["source"],
             "decision": ""}]))
        markup = self.preview()
        self.assertIn("미검토", markup)

    def test_a_saved_choice_wins_over_a_blank_snapshot_decision(self):
        ref = f"{self.sheet}!$A$8|$C$8 (row 8)"
        service = FakeService([
            {"ref": ref,
             "source": source_row(self.sheet, 8, date="2026-05-01",
                                  amount="120000")["source"],
             "decision": ""}])

        def state():
            return {"choices": {ref: "expense:9001"}, "revision": 3,
                    "updated_at": "2026-05-01T00:00:00Z", "counts": {},
                    "binding": "b"}

        service.state = state
        self.use_service(service)
        self.assertIn("expense:9001", self.preview())

    def test_reading_saved_choices_changes_nothing(self):
        ref = f"{self.sheet}!$A$8|$C$8 (row 8)"
        service = FakeService([
            {"ref": ref,
             "source": source_row(self.sheet, 8, date="2026-05-01",
                                  amount="120000")["source"],
             "decision": ""}])
        service.state = lambda: {"choices": {}, "revision": 1,
                                 "updated_at": "", "counts": {}, "binding": "b"}
        self.use_service(service)
        before = self.store.get_trip(self.tab_id)
        self.preview()
        after = self.store.get_trip(self.tab_id)
        self.assertEqual(after, before)


class IncomeSourcePreviewTests(BoardBase):
    def test_income_is_named_and_escaped_without_a_card_review_status(self):
        row = source_row(self.sheet, 8, date="2026-05-01", amount="120000")
        row["source"].update({
            "block_kind": "income", "customer_name": "<script>alert(1)</script>",
            "nickname": "합성닉네임", "income_components": {
                "예약금": "120000", "잔금": "", "추가금": ""}})
        self.use_service(FakeService([row]))
        markup = self.preview()
        self.assertIn("data-block-kind='income'", markup)
        self.assertIn("입금 원본 조회", markup)
        self.assertIn("예약금 120000원", markup)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("미검토", markup)


class ReviewQueryTests(unittest.TestCase):
    """`/review?q=` opens the comparison already narrowed."""

    def document(self):
        from webapp import real_review_ui

        return real_review_ui.render_real_review_ui("csrf-synthetic")

    def test_the_review_document_reads_q_from_the_address(self):
        doc = self.document()
        self.assertIn("URLSearchParams(window.location.search).get(\"q\")", doc)

    def test_it_is_applied_before_the_first_load(self):
        """Otherwise the screen shows one thing and searches for another."""
        doc = self.document()
        self.assertLess(doc.index("applyInitialTerm"), doc.rindex("load();"))

    def test_the_term_goes_through_value_not_the_markup(self):
        """An owner-supplied term is text; it is never interpolated into HTML."""
        doc = self.document()
        self.assertIn("field.value = term", doc)
        self.assertNotIn("__Q__", doc)

    def test_the_search_state_is_set_as_well_as_the_box(self):
        """The box alone changes nothing about what is drawn.

        `renderPage()` filters on the `filter` variable, not on the input, so a
        screen with a term in the box and an empty variable would show every row
        and read as "the search found nothing".
        """
        doc = self.document()
        self.assertIn("filter = term;", doc)
        self.assertIn("page = 0;", doc)

    def test_a_term_is_trimmed_rather_than_searched_for_verbatim(self):
        doc = self.document()
        self.assertIn("found.trim()", doc)

    def test_the_review_screen_still_renders_without_a_query(self):
        self.assertIn("body", self.document())


if __name__ == "__main__":
    unittest.main()
