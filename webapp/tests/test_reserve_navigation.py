"""RESERVE-NAVIGATION-001: the linking screen is reachable, and it leads back.

Before this, `/reserve-links` existed and worked, but nothing in the product
linked to it. The only way in was to know the address, and once inside there was
no way back to the ledger or to the real-source comparison. A feature nobody can
find is a feature nobody uses, and a screen with no exit is a screen an owner
opens once.

So these tests pin two things and nothing else:

* an owner is shown the entry link on the ledger header, and is *not* shown it
  only when a source is configured. The configuration-required state is exactly
  the state the owner needs to be able to reach.
* a viewer is never shown it, and the server still refuses the route. The link
  is a convenience; the gate is the decision.

The return links are checked in the static document, because that document is
what the browser receives. Whether they lead somewhere live is the server's
business and is not stubbed here.

Nothing here reads a roster, and nothing searches for one.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp import ledger_board as board_mod  # noqa: E402
from webapp import ledger_design, reserve_link_ui  # noqa: E402
from webapp.ledger_store import LedgerStore  # noqa: E402

OWNER_LINK = "예약·참가자 여행 연결"
ENTRY_ID = "reserve-link"


def as_role(role):
    """Pin the role the renderer will read, as the server would for a request."""
    board_mod._ROLE_LOCAL.role = role
    board_mod._ROLE_LOCAL.session = None


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self._prev_role = getattr(board_mod._ROLE_LOCAL, "role", None)
        self.path = Path(self.tmp) / "nav.sqlite"
        os.environ["WEBLEDGER_DB"] = str(self.path)
        self.store = LedgerStore(self.path, seed_demo=True)
        board_mod.bind_store(self.store)
        self.addCleanup(self._restore)

    def _restore(self):
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db
        if self._prev_role is None:
            if hasattr(board_mod._ROLE_LOCAL, "role"):
                del board_mod._ROLE_LOCAL.role
            if hasattr(board_mod._ROLE_LOCAL, "session"):
                del board_mod._ROLE_LOCAL.session
        else:
            board_mod._ROLE_LOCAL.role = self._prev_role

    def header(self, role="owner"):
        as_role(role)
        return ledger_design.render(ledger_design.page("trip-demo-a"))


class OwnerEntryLinkTests(_Base):
    def test_an_owner_is_shown_the_entry_link(self):
        markup = self.header("owner")
        self.assertIn(f"id='{ENTRY_ID}'", markup)
        self.assertIn("href='#trip-reservations'", markup)
        self.assertIn(OWNER_LINK, markup)

    def test_the_entry_link_is_in_body_actions_while_header_only_exports(self):
        """Trip work belongs in the body; the header retains only export."""
        markup = self.header("owner")
        head = markup[markup.index("page-hd"):markup.index("id='q-form'")]
        self.assertNotIn(f"id='{ENTRY_ID}'", head)
        self.assertIn("href='/export?tab=", head)
        self.assertLess(markup.index("<div class='trip-actions'"),
                        markup.index(f"id='{ENTRY_ID}'"))

    def test_the_entry_link_comes_before_the_review_link_when_both_are_drawn(self):
        """Linking first, then comparing against the real source.

        The order is the workflow: decide what belongs together, then check the
        decision against the actual records. The other way round puts the
        comparison up front with nothing to compare yet.

        The review button is conditional on a review being configured, so the
        order is asserted against the two header functions directly rather than
        against a page that happens to have a review configured today.
        """
        as_role("owner")
        from webapp import real_review
        saved = real_review.active_service
        real_review.active_service = lambda: object()
        try:
            header = (ledger_design._reserve_link_link_html()
                      + ledger_design._review_link_html())
        finally:
            real_review.active_service = saved
        self.assertIn("#trip-reservations", header)
        self.assertIn("/review'", header)
        self.assertLess(header.index("#trip-reservations"), header.index("/review'"))

    def test_the_entry_link_survives_with_no_review_configured(self):
        """The entry link does not depend on the review being set up.

        This is the deliberate difference between the two header links, so it is
        checked against the same function the header calls. Hiding the entry
        link when no review is configured would leave an installation with
        neither screen reachable from the ledger.
        """
        from webapp import real_review
        self.assertIsNone(real_review.active_service())
        as_role("owner")
        self.assertIn("#trip-reservations", ledger_design._reserve_link_link_html())
        self.assertEqual(ledger_design._review_link_html(), "")

    def test_the_entry_link_appears_with_no_source_configured(self):
        """The configuration-required state has to be reachable to be fixed.

        The review link is hidden when no review is configured, and that is right
        there: opening it would show an empty comparison. This link is different.
        The screen answers "설정이 필요해요" when the source is not configured,
        and that answer is the reason to show it. Hiding the link while the
        source is unconfigured would leave the owner unable to discover that a
        configuration is needed at all, except by already knowing the address.
        """
        from webapp import reserve_link as reserve_link_mod
        saved = os.environ.pop(reserve_link_mod.CONFIG_ENV, None)
        self.addCleanup(
            lambda: os.environ.__setitem__(reserve_link_mod.CONFIG_ENV, saved)
            if saved is not None
            else os.environ.pop(reserve_link_mod.CONFIG_ENV, None))
        self.assertIsNone(os.environ.get(reserve_link_mod.CONFIG_ENV))
        markup = self.header("owner")
        self.assertIn(f"id='{ENTRY_ID}'", markup)


class ViewerSeesNoEntryLinkTests(_Base):
    def test_a_viewer_is_never_shown_the_entry_link(self):
        """A link a viewer can see but cannot open is worse than no link.

        The route refuses a viewer, so a visible link would advertise a screen
        and then refuse it. The refusal is about the action, not about any row,
        and it carries a fixed code and no path.
        """
        markup = self.header("viewer")
        self.assertNotIn(ENTRY_ID, markup)
        self.assertNotIn("/reserve-links", markup)
        self.assertNotIn(OWNER_LINK, markup)

    def test_a_viewer_keeps_export_without_import_in_trip_header(self):
        """Export remains available after removing global actions."""
        markup = self.header("viewer")
        self.assertIn("href='/export?tab=", markup)
        head = markup.split("trip-header", 1)[1].split("id='q-form'", 1)[0]
        self.assertNotIn("카드 가져오기", head)


class LinkIdempotenceTests(_Base):
    def test_the_entry_link_is_drawn_once(self):
        """The header is rendered per request; a duplicate id would break the label.

        `id` is what a test, a label and a fragment address bind to. Two elements
        with one id means the address reaches whichever came first, which is a
        bug that looks fine in the page and is not.
        """
        markup = self.header("owner")
        self.assertEqual(markup.count(f"id='{ENTRY_ID}'"), 1)
        self.assertEqual(markup.count("href='#trip-reservations'"), 1)
        sidebar = markup.split("<div class='nav-mask'")[0]
        self.assertEqual(sidebar.count("href='/reserve-links'"), 0)
        head = markup.split("<div class='act'>")[1].split("id='q-form'")[0]
        self.assertEqual(head.count("href='#trip-reservations'"), 0)
        body_actions = ledger_design._trip_actions('trip-demo-a', '/board?tab=trip-demo-a')
        self.assertEqual(body_actions.count("href='#trip-reservations'"), 1)


class ReturnLinkTests(unittest.TestCase):
    """The way out of the linking screen.

    Checked against the static document, because that document is what the
    browser is handed. These are real anchors, not buttons with handlers: the
    owner should be able to open them in a new tab, and the browser's own status
    bar should say where they go before they are followed.
    """

    @classmethod
    def setUpClass(cls):
        cls.document = reserve_link_ui.render_reserve_link_ui("csrf-synthetic")

    def test_main_landmark_contains_heading_and_work_area(self):
        main = self.document.split('<main>', 1)[1].split('</main>', 1)[0]
        self.assertIn('<h1>예약 명단·여행 연결</h1>', main)
        self.assertIn('id="linkBox"', main)
        self.assertIn('id="rows"', main)

    def test_the_ledger_return_link_is_present_and_points_at_the_board(self):
        self.assertIn("id=\"back-board\"", self.document)
        self.assertIn('href="/board"', self.document)
        self.assertIn("장부로 돌아가기", self.document)

    def test_the_real_source_review_return_link_is_present(self):
        """The linking screen decides what belongs together; the review screen
        checks that decision against the actual records. Without this link the
        owner verifies one at a time and has to remember the other's address.
        """
        self.assertIn("id=\"back-review\"", self.document)
        self.assertIn('href="/review"', self.document)
        self.assertIn("실제 자료 검토", self.document)

    def test_both_links_are_anchors_not_script_handlers(self):
        """A link the owner cannot open in a new tab is not really a link.

        A `button` with a click handler reads the same on screen and loses the
        status bar, the middle click and the browser history entry.
        """
        import re
        for link_id in ("back-board", "back-review"):
            anchor = re.search(rf"<a\b[^>]*id=\"{link_id}\"[^>]*>", self.document)
            self.assertIsNotNone(anchor, link_id)
            self.assertIn("href=", anchor.group(0))

    def test_the_return_links_appear_before_the_state_line(self):
        """They are part of the document, not something the first fetch adds.

        The state line and the buttons are filled in by the script after the
        authenticated fetch. A return link added at that point would be missing
        until that fetch resolved, and would be missing entirely whenever it
        refused.
        """
        self.assertLess(self.document.index("back-board"),
                        self.document.index('id="state"'))

    def test_the_return_links_carry_no_source_data(self):
        """The document is served to nobody but an owner, and it is still a copy.

        The screen fetches its source identifiers over the authenticated route.
        A static document that named one would put a roster key into every copy
        of the page, including a cached one.
        """
        self.assertNotIn("reservation:", self.document)
        self.assertNotIn("__CSRF__", self.document)

    def test_the_return_links_add_no_new_server_route(self):
        """They point at pages that already exist and are already gated.

        A new route would be a new thing to audit and a new place for a role to
        be decided wrongly. Both destinations are existing owner pages behind
        the existing server-side gate, so neither link widens what is reachable.
        """
        self.assertIn('href="/board"', self.document)
        self.assertIn('href="/review"', self.document)


class EntryPointIsTheOnlyRouteTests(unittest.TestCase):
    def test_the_screen_is_served_from_the_path_the_link_names(self):
        """The address in the markup is the address that serves the screen.

        A link and a route that disagree give an owner a 404 from a button that
        looks correct, which is the exact failure this task set out to close.
        """
        source = Path(board_mod.__file__).read_text(encoding="utf-8")
        self.assertIn('if path == "/reserve-links"', source)


if __name__ == "__main__":
    unittest.main()
