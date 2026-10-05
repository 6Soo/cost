"""BOARD-SOURCE-PREVIEW-001, in a real browser: `?q=` actually narrows.

The board's preview links to `/review?q=<sheet>`. The first version of this set
the search box's value from the address and stopped there — and that is not
enough, because the comparison screen does not filter on the input. It filters on
a `filter` variable inside its own script, and `renderPage()` reads that. Setting
the box alone left the variable empty, so the screen showed a term in the box
and every unfiltered row, which reads to a person as "the search found nothing"
rather than "the search never ran".

So these tests do not check the document for a string. They load the page with a
term in the address and count the rows that actually render.

Synthetic review fixture, synthetic sheets, synthetic rows. No real source, no
production data, no network beyond loopback.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp.tests.test_real_review_browser import (  # noqa: E402
    OWNER, ReviewBrowserFixture, SETTLE_MS)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the environment has it
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class InitialTermTests(ReviewBrowserFixture):
    def open_with_term(self, term):
        import urllib.parse

        context = self._browser.new_context(
            viewport={"width": 1280, "height": 900})
        self.pages.append(context)
        from webapp import access_control

        context.set_extra_http_headers(
            {access_control.SyntheticSessionAdapter.HEADER: OWNER})
        page = context.new_page()
        url = f"http://127.0.0.1:{self.port}/review"
        if term is not None:
            url += "?q=" + urllib.parse.quote(term, safe="")
        page.goto(url)
        page.wait_for_function(
            "() => typeof window.__realReview !== 'undefined'",
            timeout=SETTLE_MS)
        # Wait for the model to have landed and been drawn, so the count is of
        # rendered rows rather than of an empty page caught mid-fetch.
        page.wait_for_function(
            "() => window.__realReview.rows() > 0", timeout=SETTLE_MS)
        page.wait_for_function(
            "() => !window.__realReview.loading()", timeout=SETTLE_MS)
        page.wait_for_timeout(200)
        return page

    def rendered_count(self, page):
        return page.evaluate(
            "() => document.querySelectorAll('#rows .card').length")

    def test_the_term_lands_in_the_search_box(self):
        page = self.open_with_term("A1")
        self.assertEqual(page.evaluate("() => document.getElementById('q').value"),
                         "A1")

    def test_the_search_variable_is_set_not_only_the_box(self):
        """The box alone changes nothing about what is drawn."""
        page = self.open_with_term("A1")
        self.assertEqual(page.evaluate("() => window.__realReview.filter()"), "A1")

    def test_the_rendered_rows_are_fewer_than_the_whole_model(self):
        """The check that matters: the DOM, not the document.

        If only the input were set, the rendered count would equal the total.
        """
        page = self.open_with_term("A1")
        total = page.evaluate("() => window.__realReview.rows()")
        self.assertGreater(total, 0, "the fixture rendered no rows at all")
        self.assertLess(
            self.rendered_count(page), total,
            "the term did not narrow the rows actually drawn")

    def test_a_term_nobody_has_still_renders_no_rows_rather_than_every_row(self):
        page = self.open_with_term("ZZZ-no-such-term-ZZZ")
        self.assertEqual(self.rendered_count(page), 0)

    def test_a_surrounding_space_is_trimmed(self):
        page = self.open_with_term("  A1  ")
        self.assertEqual(page.evaluate("() => window.__realReview.filter()"), "A1")

    def test_no_term_leaves_everything_shown(self):
        page = self.open_with_term(None)
        self.assertEqual(page.evaluate("() => window.__realReview.filter()"), "")
        self.assertEqual(self.rendered_count(page),
                         page.evaluate("() => window.__realReview.rows()"))


if __name__ == "__main__":
    unittest.main()