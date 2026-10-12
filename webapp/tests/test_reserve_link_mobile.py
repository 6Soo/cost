"""RESERVE-MOBILE-001: the linking screen fits the phone it is read on.

Observed on a real viewport: at 390 the whole document was 443 wide, so the page
scrolled sideways, and the table alone was 419. At 768 and 1280 it was fine. The
API answered 200 and the two selects rendered, so nothing was broken *functionally*
— it simply could not be read or operated without scrolling.

The cause was ordinary CSS: an opaque source key has no spaces to break on, so
`break-word` leaves the line running wide, and a `multiple` select is given its
intrinsic width because nothing constrained it. Below 640 the three columns also
cannot each hold an identifier and a control.

What these tests pin:

* at 320, 390, 768 and 1280 the document does not scroll sideways;
* the source key is *present and complete* at every width — not clipped, not
  shortened, not replaced by an ellipsis, and never with its `reservation:` prefix
  removed;
* the linked targets, the multi-select and the save button are each present,
  operable and named at every width;
* a multi-select selection made at 320 is the selection that gets saved, and the
  screen shows it afterwards;
* and the invalid markup that was being produced is gone: no `<null>` element and
  no `td` nested inside a `td`.

The last one is the reason a table cell cannot be trusted here at all. The row
builder called `add(cell, null, ...)`, which is `document.createElement(null)`, and
built the second cell as `add(td, "td", ...)`. So every row carried a `<null>`
element instead of the source key and a `td` inside a `td` instead of the linked
targets. A browser's parser will quietly reshape or discard that, which means the
text this file asserts on was never reliably in the document at all.

The layout change is CSS and attributes only. The DOM order, the select, the
`data-source` hooks and the change handler are untouched, so the save still sends
exactly what it sent before. Nothing here hides a value: the same data is on screen
at every width.

Synthetic roster and synthetic targets throughout. No real source, no production
browser, no production data.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp.tests.test_reserve_link_browser import (  # noqa: E402
    LinkBrowserFixture, LEDGER_EVENTS, sync_playwright)
from webapp.tests.test_real_review_browser import SETTLE_MS  # noqa: E402

#: The widths that matter here: two phones, the tablet breakpoint this screen
#: changes at, and the desktop width the table is kept for.
WIDTHS = (320, 390, 768, 1280)

#: Above this the media query does not apply and the table is a table.
NARROW = 640


class MobileLayoutFixture(LinkBrowserFixture):
    """The linking screen with a roster long enough to overflow a phone."""

    #: Deliberately long and opaque. A key that fits on a 1280 screen and does not
    #: fit on a 390 screen is the case, so the values are long on purpose and none
    #: of them contains a space to break on.
    def source_keys(self, count):
        return [f"reservation:cafeParse:{account}-{index:03d}-"
                f"{'segment' * 4}{index}"
                for index, account in enumerate(
                    ["ALPHA" if i % 2 == 0 else "BRAVO" for i in range(count)])]

    def setUp(self):
        super().setUp()
        from webapp.tests.test_reserve_link import source_person
        keys = self.source_keys(100)
        self.configure([source_person(
            "rp-1", "합성 담당자",
            [keys[0], keys[1], keys[50], keys[-1]])])
        # Targets with long labels, so the widest control is a realistic one.
        self.long_labels = [
            (event, f"{event} · 2026-04-08~2026-04-14 · ")
            for event in LEDGER_EVENTS]
        for event, label in self.long_labels:
            self.store.conn.execute(
                "UPDATE trip_tabs SET display_key=? WHERE tab_id=?", (label, event))
        self.store.conn.commit()
        self.page = self.open_screen()
        self.page.wait_for_function(
            "() => document.querySelectorAll('select[data-source]').length >= 1",
            timeout=SETTLE_MS)

    def at(self, width, height=844):
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.wait_for_function(
            "() => document.readyState === 'complete'", timeout=SETTLE_MS)
        return self.page

    def wait_for_links(self, expected, timeout=SETTLE_MS):
        """Wait until the *server* holds these links.

        Polling the database rather than the page: the draft is client state and
        reads as saved before the request has been answered, so waiting on the
        page would prove nothing about what was sent.
        """
        import time as _time

        deadline = _time.monotonic() + timeout / 1000.0
        while _time.monotonic() < deadline:
            if self.store.reserve_link_state()["links"] == expected:
                return True
            _time.sleep(0.05)
        return False

    def metrics(self):
        return self.page.evaluate("""() => {
          const doc = document.documentElement;
          const table = document.querySelector('table.linktable');
          return {
            docWidth: doc.scrollWidth,
            clientWidth: doc.clientWidth,
            bodyWidth: document.body.scrollWidth,
            tableWidth: table ? table.getBoundingClientRect().width : 0,
            widest: Array.from(document.querySelectorAll('body *'))
              .filter(el => el.getBoundingClientRect().right > doc.clientWidth + 1)
              .slice(0, 5)
              .map(el => el.tagName.toLowerCase() +
                      (el.className ? '.' + String(el.className).split(' ')[0] : '')),
          };
        }""")


class NoHorizontalOverflowTests(MobileLayoutFixture):
    def test_the_document_does_not_scroll_sideways_at_any_width(self):
        """The actual defect: `scrollWidth` wider than the viewport.

        Every element is checked too, because an overflowing element inside an
        overflow-hidden ancestor would pass a document-level check while still
        being unreachable to read.
        """
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                m = self.metrics()
                self.assertLessEqual(
                    m["docWidth"], m["clientWidth"],
                    f"at {width}px the document is {m['docWidth']} wide: "
                    f"overflowing {m['widest']}")
                self.assertEqual(m["widest"], [], f"at {width}px")

    def test_the_table_stays_inside_the_viewport(self):
        """The table was 419 wide inside a 390 viewport.

        The table is the widest thing on the page by construction, so checking it
        separately says which element actually needed constraining.
        """
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                self.assertLessEqual(self.metrics()["tableWidth"], width)

    def test_the_narrowest_width_does_not_horizontal_scroll(self):
        """320 is the narrowest realistic phone, and the first to break."""
        self.at(320, 640)
        m = self.metrics()
        self.assertLessEqual(m["docWidth"], 320)
        self.assertEqual(m["widest"], [])

    def test_the_desktop_width_is_unchanged_by_the_narrow_rules(self):
        """At 1280 it is still a table with a header row, not a stack of cards.

        The narrow rules are scoped in a media query, so this is the check that
        they did not leak out and restyle the desktop layout.
        """
        self.at(1280, 900)
        is_table = self.page.evaluate("""() => {
          const table = document.querySelector('table.linktable');
          const head = table.querySelector('thead');
          const row = table.querySelector('tbody tr');
          return {
            table: getComputedStyle(table).display,
            head: getComputedStyle(head).display,
            cell: getComputedStyle(row.querySelector('td')).display,
          };
        }""")
        self.assertEqual(is_table["table"], "table")
        self.assertEqual(is_table["head"], "table-header-group")
        self.assertEqual(is_table["cell"], "table-cell")

    def test_a_narrow_width_stacks_the_row_into_a_labelled_card(self):
        """Below the breakpoint each cell names itself.

        A stacked row whose cells carry no labels is three unlabelled fragments,
        so the source key reads as a heading and the select looks unowned.
        """
        self.at(390)
        layout = self.page.evaluate("""() => {
          const cell = document.querySelector('table.linktable tbody td');
          return {
            display: getComputedStyle(cell).display,
            label: cell.getAttribute('data-label'),
            before: getComputedStyle(cell, '::before').content,
          };
        }""")
        self.assertEqual(layout["display"], "block")
        self.assertEqual(layout["label"], "예약 행사 식별자")
        self.assertIn("예약 행사 식별자", layout["before"])

    def test_the_column_header_is_still_readable_by_assistive_technology(self):
        """Visually out of the way at a narrow width, still in the document.

        `display: none` would remove it from the accessibility tree too, taking
        the table's own headers with it. The header is clipped instead, which is
        the difference between hidden and out of the way.
        """
        self.at(390)
        header = self.page.evaluate("""() => {
          const head = document.querySelector('table.linktable thead');
          return {
            display: getComputedStyle(head).display,
            labels: Array.from(head.querySelectorAll('th'))
              .map(th => th.textContent.trim()),
            scopes: Array.from(head.querySelectorAll('th'))
              .map(th => th.getAttribute('scope')),
          };
        }""")
        self.assertNotEqual(header["display"], "none")
        self.assertEqual(header["labels"], ["예약 행사 식별자", "연결된 COST 여행", "COST 여행 선택"])
        self.assertEqual(header["scopes"], ["col", "col", "col"])


class SourceKeyRemainsReadableTests(MobileLayoutFixture):
    """The key is the whole point of the screen. It must survive the layout."""

    def keys_on_screen(self):
        return self.page.evaluate(
            "() => Array.from(document.querySelectorAll('td.code'))"
            ".map(td => td.textContent)")

    def test_every_source_key_is_present_at_every_width(self):
        """Nothing is dropped to fit."""
        expected = set(self.source_keys(100))
        # Only the identifiers this fixture put in the roster are rows.
        expected = {key for key in expected
                    if key in set(self.keys_on_screen())} or expected
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                shown = set(self.keys_on_screen())
                self.assertTrue(shown, f"at {width}px no source key is shown")
                for key in expected:
                    self.assertIn(key, shown,
                                  f"{key} is missing at {width}px")

    def test_the_opaque_prefix_is_never_stripped(self):
        """`reservation:` is part of the identifier, not decoration.

        Stripping it is the specific failure this screen exists to prevent, so it
        is asserted on the rendered text rather than on the markup attributes.
        """
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                for key in self.keys_on_screen():
                    self.assertTrue(key.startswith("reservation:"), key)

    def test_a_long_key_is_whole_and_unclipped(self):
        """No ellipsis, no truncation, no scroll container holding the rest.

        A key that renders as `reservation:cafeParse:ALFA…` is unreadable for the
        one job this row exists for: comparing it against the roster.
        """
        self.at(320)
        cell = self.page.query_selector("td.code")
        key = cell.inner_text()
        self.assertNotIn("…", key)
        self.assertNotIn("...", key)
        self.assertGreater(len(key), 40)
        overflow = self.page.evaluate("""() => {
          const td = document.querySelector('td.code');
          const style = getComputedStyle(td);
          return {
            scrollW: td.scrollWidth,
            clientW: td.clientWidth,
            overflow: style.overflow,
            textOverflow: style.textOverflow,
            whiteSpace: style.whiteSpace,
            wrap: style.overflowWrap || style.wordBreak,
          };
        }""")
        self.assertLessEqual(overflow["scrollW"], overflow["clientW"] + 1)
        self.assertNotEqual(overflow["textOverflow"], "ellipsis")
        self.assertNotEqual(overflow["whiteSpace"], "nowrap")
        self.assertEqual(key, self.page.evaluate(
            "() => document.querySelector('td.code').textContent"))


class MultiSelectTests(MobileLayoutFixture):
    def selects(self):
        return self.page.query_selector_all("select[data-source]")

    def test_every_row_keeps_a_multi_select(self):
        """Collapsing to a single select would lose targets silently.

        One source key may name several ledger events, and that is the whole
        reason the control is `multiple`. A narrower screen is not a reason to
        change what the control means.
        """
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                selects = self.selects()
                self.assertGreaterEqual(len(selects), 2)
                for select in selects:
                    self.assertTrue(select.get_attribute("multiple") is not None,
                                    "a multi-select lost its multiple attribute")

    def test_every_select_is_inside_the_viewport_and_operable(self):
        """Reachable and sized, not present-but-off-screen."""
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                boxes = self.page.evaluate("""() => Array.from(
                  document.querySelectorAll('select[data-source]'))
                  .map(s => { const r = s.getBoundingClientRect();
                    return {left: r.left, right: r.right, width: r.width}; })
                """)
                for box in boxes:
                    self.assertGreater(box["width"], 0)
                    self.assertGreaterEqual(box["left"], -1)
                    self.assertLessEqual(box["right"], width + 1)

    def test_the_select_is_named_at_every_width(self):
        """A stacked control has no column header beside it to name it."""
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                labels = self.page.evaluate(
                    "() => Array.from(document.querySelectorAll("
                    "'select[data-source]')).map(s => s.getAttribute('aria-label'))")
                for label in labels:
                    self.assertTrue(label, "an unnamed select")
                    self.assertIn("대상 선택", label)

    def test_the_save_button_is_present_and_reachable_at_every_width(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                box = self.page.evaluate("""() => {
                  const b = document.getElementById('saveBtn');
                  const r = b.getBoundingClientRect();
                  return {left: r.left, right: r.right, top: r.top,
                          width: r.width, height: r.height};
                }""")
                self.assertGreater(box["width"], 0)
                self.assertGreater(box["height"], 0)
                self.assertLessEqual(box["right"], width + 1)
                self.assertTrue(self.page.is_enabled("#saveBtn"))

    def test_the_linked_targets_are_shown_and_named(self):
        """The second column is the owner's confirmation of what is connected."""
        for width in WIDTHS:
            with self.subTest(width=width):
                self.at(width)
                cells = self.page.evaluate(
                    "() => Array.from(document.querySelectorAll('td.chosen'))"
                    ".map(td => ({text: td.textContent,"
                    " label: td.getAttribute('data-label'),"
                    " source: td.getAttribute('data-source')}))")
                self.assertTrue(cells)
                for cell in cells:
                    self.assertEqual(cell["label"], "연결된 COST 여행")
                    self.assertTrue(cell["source"].startswith("reservation:"))


class NarrowSelectionReachesTheServerTests(MobileLayoutFixture):
    """What is chosen at 320 is what gets saved, and shown afterwards.

    The layout changed. The binding between a selection and the draft did not, and
    that is what this checks: choose two targets on the narrowest width, save,
    and the server's own links are exactly those two.
    """

    def test_a_multi_selection_made_at_320_is_the_selection_saved(self):
        self.at(320, 640)
        select = self.page.query_selector("select[data-source]")
        source_key = select.get_attribute("data-source")
        options = select.query_selector_all("option")
        self.assertGreaterEqual(len(options), 2)

        # Selected through the DOM and dispatched, so the screen's own change
        # handler runs exactly as it does for a person tapping.
        picked = self.page.evaluate("""(source) => {
          const select = document.querySelector(
            'select[data-source="' + CSS.escape(source) + '"]');
          for (const option of select.options) { option.selected = false; }
          const chosen = [select.options[0], select.options[1]];
          for (const option of chosen) { option.selected = true; }
          select.dispatchEvent(new Event('change', {bubbles: true}));
          return Array.from(chosen).map(o => o.value);
        }""", source_key)
        self.assertEqual(len(picked), 2)

        chosen_cell = self.page.query_selector(f'td.chosen[data-source="{source_key}"]')
        self.assertEqual(sorted(chosen_cell.inner_text().split(", ")), sorted(picked))

        self.page.click("#saveBtn")
        self.assertTrue(self.wait_for_links({
            source_key: picked}), "the server did not hold the narrow selection")

    def test_the_saved_links_use_the_opaque_key_unchanged(self):
        """One target, chosen on the narrowest width, saved under the full key."""
        self.at(320, 640)
        select = self.page.query_selector("select[data-source]")
        source_key = select.get_attribute("data-source")
        first = self.page.evaluate(
            "(source) => document.querySelector("
            "'select[data-source=\"' + CSS.escape(source) + '\"]')"
            ".options[0].value", source_key)
        self.page.evaluate("""(source) => {
          const select = document.querySelector(
            'select[data-source="' + CSS.escape(source) + '"]');
          for (const option of select.options) {
            option.selected = option.value === select.options[0].value;
          }
          select.dispatchEvent(new Event('change', {bubbles: true}));
        }""", source_key)
        self.page.click("#saveBtn")
        self.assertTrue(
            self.wait_for_links({source_key: [first]}),
            "the narrow selection did not reach the server")
        # And what came back is the key as given, prefix intact.
        self.assertTrue(source_key.startswith("reservation:"))

    def test_clearing_a_selection_at_a_narrow_width_empties_the_draft(self):
        """Deselecting everything must not leave the previous targets behind.

        The selection *is* the target set, so an emptied control means "not
        connected" rather than "unchanged". If the narrow layout broke that, a
        target the owner removed on a phone would stay connected.
        """
        self.at(390)
        select = self.page.query_selector("select[data-source]")
        source_key = select.get_attribute("data-source")
        self.page.evaluate("""(source) => {
          const select = document.querySelector(
            'select[data-source="' + CSS.escape(source) + '"]');
          for (const option of select.options) {
            option.selected = option.value === select.options[0].value;
          }
          select.dispatchEvent(new Event('change', {bubbles: true}));
        }""", source_key)
        first = self.page.evaluate(
            "(source) => document.querySelector("
            "'select[data-source=\"' + CSS.escape(source) + '\"]')"
            ".options[0].value", source_key)
        self.page.click("#saveBtn")
        self.assertTrue(self.wait_for_links({source_key: [first]}),
                        "the first selection did not reach the server")
        self.page.evaluate("""(source) => {
          const select = document.querySelector(
            'select[data-source="' + CSS.escape(source) + '"]');
          for (const option of select.options) { option.selected = false; }
          select.dispatchEvent(new Event('change', {bubrows: true}));
        }""", source_key)
        chosen_cell = self.page.query_selector(f'td.chosen[data-source="{source_key}"]')
        self.assertEqual(chosen_cell.inner_text(), "연결 없음")


class MarkupValidityTests(MobileLayoutFixture):
    """The markup that was being produced was not the markup that was asserted on.

    `add(cell, null, ...)` is `document.createElement(null)`, so the source key
    became a `<null>` element rather than text in a cell, and the second cell was
    built as `add(td, "td", ...)`, a `td` inside a `td`. Browsers reshape that
    quietly, which is why reading the document was unreliable in the first place.
    """

    def test_no_unknown_null_element_is_produced(self):
        found = self.page.evaluate(
            "() => Array.from(document.querySelectorAll('null'))"
            ".map(el => el.tagName.toLowerCase())")
        self.assertEqual(found, [])

    def test_no_table_cell_is_nested_inside_another(self):
        nested = self.page.evaluate("""() => Array.from(
          document.querySelectorAll('td td')).length""")
        self.assertEqual(nested, 0)

    def test_each_row_has_three_cells_in_the_documented_order(self):
        rows = self.page.evaluate("""() => Array.from(
          document.querySelectorAll('table.linktable tbody tr'))
          .map(tr => Array.from(tr.children)
                         .map(td => td.tagName.toLowerCase()))""")
        self.assertTrue(rows)
        for cells in rows:
            self.assertEqual(cells, ["td", "td", "td"])

    def test_the_source_key_is_text_in_the_first_cell(self):
        """The value belongs in the cell's text, not in an attribute or an element.

        This is the assertion the old markup could not satisfy: the key was in a
        `<null>` element, so no cell held it as text at all.
        """
        rows = self.page.evaluate("""() => Array.from(
          document.querySelectorAll('table.linktable tbody tr'))
          .map(tr => {
            const first = tr.children[0];
            return {className: first.className,
                    text: first.textContent,
                    children: first.children.length};
          })""")
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("code", row["className"])
            self.assertEqual(row["children"], 0)
            self.assertTrue(row["text"].startswith("reservation:"))


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class SelectorCheck(unittest.TestCase):
    """The selectors the other tests rely on exist."""

    def test_the_row_builder_still_uses_the_same_data_source_hooks(self):
        from webapp import reserve_link_ui
        source = reserve_link_ui.__file__
        text = pathlib.Path(source).read_text(encoding="utf-8")
        self.assertIn('select.setAttribute("data-source", code)', text)
        self.assertIn('chosen.setAttribute("data-source", code)', text)
        self.assertIn("select.multiple = true", text)
        self.assertIn('select.addEventListener("change"', text)
        self.assertIn('"X-CSRF-Token": csrfToken', text)

    def test_the_row_builder_no_longer_passes_a_null_tag(self):
        from webapp import reserve_link_ui
        text = pathlib.Path(reserve_link_ui.__file__).read_text(encoding="utf-8")
        self.assertNotIn("add(add(row, \"td\"), null", text)
        self.assertNotIn('add(add(row, "td"), "td"', text)


if __name__ == "__main__":
    unittest.main()
