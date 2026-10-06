"""SOURCE-REFRESH-001 tests: a changed source becomes a new activated review.

Synthetic only. Every workbook, master and review CSV in this file is written by
the builder below into a temporary directory, with values that are obviously not
real. No real source, customer row, credential, operational database or network
is read; the collector's fetch function is injected in the one test that needs
input from "somewhere".

The builder makes the three layouts this has to survive real: the expense block
with its date in column 1 and amount in column 7, and with its date in column 2
and the amount in column 8 or column 9. It also makes an income block above the
expense one, because that adjacency is where a scanner goes wrong.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from webapp import real_review
from webapp import review_context
from webapp import review_refresh
from tools import refresh_review_source as cli
from webapp.contracts import sha256_bytes, sha256_text

SHEET = "합성시트"
INCOME_SHEET = "합성수입"
BLOCK_HEADER = ("거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액")
INCOME_HEADER = ("일자", "적립", "내용", "비고", "금액")
MASTER_HEADERS = list(review_context.MASTER_HEADERS)

#: The three proven layouts: (date column, amount column, block width). Two are
#: width seven and one is width eight, and the width is what proves the block, so
#: a layout cannot be recognised by its date column alone.
LAYOUT_1_7 = (1, 7, 7)
LAYOUT_2_8 = (2, 8, 7)
LAYOUT_2_9 = (2, 9, 8)


def build_snapshot(entries, *, date_col=1, amount_col=7, width=7,
                   with_income=False, header_row=4, first_row=None):
    """A workbook with one expense block, and optionally an income block above.

    `entries` is a list of ``(date, item, description, amount)``; a description
    of ``None`` writes a blank cell. `first_row` places the first data row
    explicitly, which is how a moved row is built.
    """
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    if with_income:
        for column, label in enumerate(INCOME_HEADER, start=1):
            sheet.cell(row=1, column=column, value=label)
    # A width-eight block carries one column the labels do not name, and the
    # labels are in block order around it. That unnamed column is the reason the
    # width has to be proven from the header rather than assumed.
    for offset, label in enumerate(BLOCK_HEADER[:-1]):
        sheet.cell(row=header_row, column=date_col + offset, value=label)
    sheet.cell(row=header_row, column=amount_col, value=BLOCK_HEADER[-1])
    start = first_row if first_row is not None else header_row + 1
    for offset, (date, item, description, amount) in enumerate(entries):
        row = start + offset
        sheet.cell(row=row, column=date_col, value=date)
        sheet.cell(row=row, column=date_col + 1, value=item)
        if description is not None:
            sheet.cell(row=row, column=date_col + 2, value=description)
        sheet.cell(row=row, column=amount_col, value=amount)
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def build_master(rows):
    """A master with the seventeen headers, one row per ``(key, date, amount)``."""
    lines = [",".join(MASTER_HEADERS)]
    for key, date, amount, merchant in rows:
        lines.append(",".join([
            key, "합성카드사", "합성카드4", "합성", date, date, merchant,
            str(amount), "", "KRW", "합성승인번호", "아니오", "합성출처",
            "합성적재일", "아니오", "", "",
        ]))
    return "\n".join(lines) + "\n"



def repack(snapshot_bytes, stamp=(2020, 1, 1, 0, 0, 0)):
    """The same workbook bytes again, written with different ZIP timestamps.

    This is what a re-download actually produces and what the parent measured:
    a different file hash for an identical set of cells. openpyxl is
    deterministic, so building the same workbook twice gives identical bytes and
    would not reproduce the case at all.
    """
    import zipfile

    source = zipfile.ZipFile(io.BytesIO(snapshot_bytes))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            info = zipfile.ZipInfo(item.filename, date_time=stamp)
            info.compress_type = item.compress_type
            target.writestr(info, source.read(item.filename))
    source.close()
    return buffer.getvalue()

def entry(index):
    return (f"2026-04-{index:02d}", "합성항목", f"합성내용 {index}",
            100001 + index)


def master_row(index):
    return (f"합성거래키-{index:04d}", f"2026-04-{index:02d}", 100001 + index,
            "합성이용점")


class RefreshFixture(unittest.TestCase):
    """A temporary config, bundle root and the current empty review input."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.bundle_root = self.tmp / "bundles"
        self.config_path = self.tmp / "review.json"
        self.decisions_db = self.tmp / "decisions.sqlite"
        self._prev = {
            name: os.environ.get(name)
            for name in (real_review.CONFIG_ENV, "WEBLEDGER_DB")
        }
        os.environ["WEBLEDGER_DB"] = str(self.decisions_db)
        real_review.clear_real_review()
        self.addCleanup(self._restore)

    def _restore(self):
        real_review.clear_real_review()
        for name, value in self._prev.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def seed_config(self):
        """A starting config carrying only the decisions path.

        A bundle inherits the decision history from the config it replaces, and
        it refuses to invent one — a new, empty database would silently start a
        second review history beside the real one. So a first activation needs a
        config that already says where that history lives.
        """
        self.config_path.write_text(
            json.dumps({"decisions_db_path": str(self.decisions_db)},
                       ensure_ascii=False), encoding="utf-8")

    def write_config(self, bundle, digest_overrides=None):
        manifest = {
            "snapshot_path": bundle["snapshot_path"],
            "snapshot_sha256": bundle["snapshot_sha256"],
            "review_path": bundle["review_path"],
            "review_sha256": bundle["review_sha256"],
            "master_path": bundle["master_path"],
            "master_sha256": bundle["master_sha256"],
            "decisions_db_path": str(self.decisions_db),
        }
        manifest.update(digest_overrides or {})
        self.config_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return manifest


class BlockDiscoveryTests(RefreshFixture):
    """New scope comes from an explicit expense header, and only from one."""

    def blocks_for(self, snapshot):
        return {(b["sheet"], b["date_col"], b["amount_col"], b["width"])
                for b in review_refresh.discover_blocks(snapshot)}

    def test_each_of_the_three_column_layouts_is_recognised(self):
        """The date and amount columns are proven by the header, not assumed.

        A workbook that puts the amount in column 7, and one that starts a
        column later and ends at 8 or 9, are all the same expense block. Reading
        column 7 blindly would read a cell of the wrong block on two of them.
        """
        for date_col, amount_col, width in (LAYOUT_1_7, LAYOUT_2_8, LAYOUT_2_9):
            with self.subTest(layout=(date_col, amount_col)):
                snapshot = build_snapshot([entry(1), entry(2)],
                                          date_col=date_col,
                                          amount_col=amount_col, width=width)
                self.assertIn((SHEET, date_col, amount_col, width),
                              self.blocks_for(snapshot))

    def test_an_income_block_is_not_an_expense_block(self):
        """The income header sits directly above and must not be read as scope.

        Its labels are different, and its amount column is the last of five, so
        no run of seven or eight of its columns spells the expense block. If this
        ever passed, income rows would enter a card review.
        """
        snapshot = build_snapshot([entry(1)], with_income=True)
        found = self.blocks_for(snapshot)
        self.assertEqual(found, {(SHEET, 1, 7, 7)})

    def test_a_data_row_is_not_a_header(self):
        """A row of data must not create a block of its own.

        Every data row has an explicit date at the start and a number at the
        end, which is exactly the shape a header scan could mistake for one.
        """
        snapshot = build_snapshot([entry(index) for index in range(1, 6)])
        self.assertEqual(len(self.blocks_for(snapshot)), 1)

    def test_a_workbook_with_no_expense_header_proves_no_scope(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = SHEET
        sheet.cell(row=1, column=1, value="2026-04-01")
        sheet.cell(row=1, column=7, value=100)
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        self.assertEqual(self.blocks_for(buffer.getvalue()), set())


class ReviewCsvTests(RefreshFixture):
    def build(self, entries, master, previous="", **kwargs):
        snapshot = build_snapshot(entries, **kwargs)
        return review_refresh.build_review_csv(snapshot, master, previous)

    def parse(self, text):
        import csv

        rows = list(csv.reader(io.StringIO(text)))
        return rows[0], {row[0]: dict(zip(rows[0], row)) for row in rows[1:]}

    def test_every_in_scope_row_is_emitted_with_a_blank_decision(self):
        entries = [entry(1), entry(2), entry(3)]
        master = build_master([master_row(1), master_row(3)])
        header, records = self.parse(self.build(entries, master))
        self.assertEqual(len(records), 3)
        for record in records.values():
            # Nothing is decided. A new bundle starts empty, and a date and
            # amount that match is a candidate, never an approval.
            self.assertEqual(record["reviewer_decision"], "")
            self.assertEqual(record["review_note"], "")

    def test_a_row_whose_header_was_deleted_is_kept_as_a_held_row(self):
        """A deleted header must not delete the row.

        The model reports the row as insufficient, and a reviewer sees it and
        can say so. An implementation that emitted only header-proven rows would
        drop it, and a real source has hundreds of such rows.
        """
        entries = [entry(1), entry(2), entry(3)]
        master = build_master([master_row(1), master_row(2), master_row(3)])
        _, before = self.parse(self.build(entries, master))

        # A new workbook with the header row blanked out.
        snapshot = build_snapshot(entries, header_row=4, first_row=5)
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(snapshot))
        sheet = workbook[SHEET]
        # Blanked, not deleted: the rows must stay exactly where the previous
        # review said they were, so the only change under test is the header.
        for column in range(1, 8):
            sheet.cell(row=4, column=column, value="")
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()

        review_text = review_refresh.build_review_csv(
            buffer.getvalue(), master, self.build(entries, master))
        _, after = self.parse(review_text)
        self.assertEqual(set(before), set(after))

        model = review_context.build_review_context(
            buffer.getvalue(), review_text, master,
            sha256_bytes(buffer.getvalue()), sha256_text(review_text),
            sha256_text(master))
        statuses = {row["source"]["evidence_status"] for row in model["rows"]}
        self.assertIn(review_context.EVIDENCE_INSUFFICIENT, statuses)

    def test_a_deleted_row_is_dropped_and_a_new_row_appears(self):
        """A shorter workbook produces a shorter review, and a longer one longer.

        The ref is a cell address, so a row that disappears takes its address
        with it and a row that appears brings a new one. That is also why an
        address is never treated as a decision carried across bundles.
        """
        master = build_master([master_row(index) for index in range(1, 6)])
        _, before = self.parse(self.build([entry(index) for index in (1, 2, 3)],
                                          master))
        _, shorter = self.parse(self.build([entry(1), entry(2)], master))
        self.assertEqual(len(before), 3)
        self.assertEqual(len(shorter), 2)
        removed = set(before) - set(shorter)
        self.assertEqual(len(removed), 1, "the deleted row kept its address")
        self.assertIn("(row 7)", removed.pop())

        _, longer = self.parse(
            self.build([entry(index) for index in (1, 2, 3, 4)], master))
        self.assertEqual(len(longer), 4)
        added = set(longer) - set(before)
        self.assertEqual(len(added), 1)
        new_record = longer[added.pop()]
        self.assertEqual(new_record["source_amount"], "100005")
        self.assertEqual(json.loads(new_record["candidate_transaction_keys"]),
                         ["합성거래키-0004"])

    def test_a_row_replaced_in_place_keeps_its_address_and_gets_new_values(self):
        """Replacing a row is a content change, not a delete plus an add.

        The two rows share an address, so a set difference of refs shows nothing
        and only the values differ. The date and amount are re-read, so the
        review shows the row that is now there and not the row that was.
        """
        master = build_master([master_row(1), master_row(2)])
        _, before = self.parse(self.build([entry(1), entry(2)], master))
        _, after = self.parse(self.build([entry(1), entry(4)], master))
        self.assertEqual(set(before), set(after))
        changed = [ref for ref in before
                   if before[ref]["source_amount"] != after[ref]["source_amount"]]
        self.assertEqual(len(changed), 1, "the replaced row was not updated")
        self.assertIn("(row 6)", changed[0])
        self.assertEqual(after[changed[0]]["source_amount"], "100005")

    def test_a_moved_row_keeps_its_own_values(self):
        """A row that moved is the same transaction, not a new one.

        Its ref carries the new cell address, because that is where the reviewer
        has to look, and its date and amount are re-read from there.
        """
        master = build_master([master_row(1)])
        at_five = build_snapshot([entry(1)], first_row=5)
        at_nine = build_snapshot([entry(1)], first_row=9)
        _, first = self.parse(review_refresh.build_review_csv(at_five, master))
        _, second = self.parse(review_refresh.build_review_csv(at_nine, master))
        (first_ref, first_record), = first.items()
        (second_ref, second_record), = second.items()
        self.assertNotEqual(first_ref, second_ref)
        self.assertIn("(row 5)", first_ref)
        self.assertIn("(row 9)", second_ref)
        self.assertEqual(first_record["source_date"],
                         second_record["source_date"])
        self.assertEqual(first_record["source_amount"],
                         second_record["source_amount"])

    def test_a_date_and_amount_match_makes_a_candidate_not_an_approval(self):
        master = build_master([master_row(1)])
        _, records = self.parse(self.build([entry(1)], master))
        record = list(records.values())[0]
        self.assertEqual(record["disposition"], "candidate_review_required")
        self.assertEqual(record["candidate_count"], "1")
        self.assertEqual(json.loads(record["candidate_transaction_keys"]),
                         ["합성거래키-0001"])
        self.assertEqual(record["reviewer_decision"], "")

    def test_both_master_dates_are_kept_as_candidate_evidence(self):
        """승인일 and 매입일 are both the evidence, and both are carried.

        The reviewer decides which one the source row means, so the bundle keeps
        both rather than pre-selecting one.
        """
        master = build_master([master_row(1)])
        _, records = self.parse(self.build([entry(1)], master))
        record = list(records.values())[0]
        fields = json.loads(record["candidate_date_fields"])
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["key"], "합성거래키-0001")
        self.assertEqual(fields[0]["approval_date"], "2026-04-01")
        self.assertEqual(fields[0]["posting_date"], "2026-04-01")

    def test_a_row_with_no_card_match_is_unmatched_and_still_present(self):
        master = build_master([master_row(9)])
        _, records = self.parse(self.build([entry(1)], master))
        record = list(records.values())[0]
        self.assertEqual(record["disposition"], "unmatched_review_required")
        self.assertEqual(record["candidate_count"], "0")

    def test_a_duplicate_master_key_is_refused(self):
        master = build_master([master_row(1), master_row(1)])
        with self.assertRaises(review_refresh.RefreshError) as caught:
            self.build([entry(1)], master)
        self.assertEqual(caught.exception.code,
                         review_refresh.CODE_MASTER_DUPLICATE_KEY)

    def test_a_master_that_does_not_resolve_a_candidate_is_refused(self):
        """A source row that matches a key the master does not hold is refused.

        The key would reach the core and the core would refuse it with its own
        code. Refusing here instead means the collector never stages a bundle the
        core is going to reject, and the previous bundle stays active.
        """
        master = build_master([master_row(1)])
        snapshot = build_snapshot([entry(1)])
        review_text = review_refresh.build_review_csv(snapshot, master)
        # The master is then replaced with one whose key differs, which is the
        # only way a collected key can stop resolving.
        other = build_master([("합성거래키-9999", "2026-04-01", 100001,
                               "합성이용점")])
        with self.assertRaises(review_context.ReviewContextError) as caught:
            review_context.build_review_context(
                snapshot, review_text, other, sha256_bytes(snapshot),
                sha256_text(review_text), sha256_text(other))
        self.assertEqual(caught.exception.code,
                         review_context.CODE_CANDIDATE_KEY_UNRESOLVED)

    def test_an_empty_source_is_refused_and_never_empties_the_review(self):
        with self.assertRaises(review_refresh.RefreshError) as caught:
            self.build([], build_master([master_row(1)]))
        self.assertIn(caught.exception.code,
                      (review_refresh.CODE_SOURCE_EMPTY,
                       review_refresh.CODE_SCOPE_UNPROVEN))

    def test_a_date_without_an_explicit_year_is_not_a_date(self):
        """A bare month and day is refused rather than assumed to be a year.

        Guessing the year would silently move a transaction into the wrong
        period, and the amount would still match, so the guess would look right.
        """
        master = build_master([master_row(1)])
        entries = [("04-01", "합성항목", "합성내용 1", 100001)]
        with self.assertRaises(review_refresh.RefreshError):
            self.build(entries, master)

    def test_the_generated_csv_passes_the_whole_existing_core(self):
        """The proof is the core's, not this module's.

        Every generated bundle is built by ``build_review_context`` before it can
        be staged, so a shape this module liked but the core does not is refused
        rather than activated.
        """
        master = build_master([master_row(index) for index in (1, 2, 3)])
        snapshot = build_snapshot([entry(index) for index in (1, 2, 3)])
        review_text = review_refresh.build_review_csv(snapshot, master)
        model = review_context.build_review_context(
            snapshot, review_text, master, sha256_bytes(snapshot),
            sha256_text(review_text), sha256_text(master))
        self.assertEqual(len(model["rows"]), 3)
        from webapp.review_csv_adapter import normalize_review_csv

        normalized = normalize_review_csv(review_text, sha256_bytes(snapshot))
        self.assertEqual(normalized["counts"],
                         {"approved": 0, "rejected": 0, "incomplete": 3})


class ContentNoOpTests(RefreshFixture):
    """A re-download that says the same thing must not rotate the review.

    The parent measured this on the real source: HTTP 200, a valid workbook, a
    different file hash, and 43 sheets with not one added, removed or changed
    cell. A workbook is a ZIP, so a new download has new entry timestamps. On the
    byte hash alone every collection would replace the bundle, and replacing the
    bundle resets the review's decisions to blank — so a reviewer would be made
    to decide the same 1,734 transactions again, for no change in any of them.
    """

    def staged(self, entries, master, previous=""):
        snapshot = build_snapshot(entries)
        bundle = review_refresh.collect(self.config_path, self.bundle_root,
                                        snapshot, master, previous)
        self.write_config(bundle)
        return bundle

    def previous_input(self, entries, master):
        """The review input the *next* collection will read as its previous one."""
        return review_refresh.build_review_csv(build_snapshot(entries), master)

    def test_the_same_content_reached_by_different_bytes_is_a_no_op(self):
        """A different file, the same cells: nothing happens.

        The bytes differ on purpose — the workbook is re-saved rather than
        reused — because that is what a re-download does.
        """
        entries = [entry(1), entry(2)]
        master = build_master([master_row(1), master_row(2)])
        previous = self.previous_input(entries, master)
        first = self.staged(entries, master, previous)
        self.assertFalse(first["no_op"])

        # The same cells, written again with different ZIP timestamps: exactly
        # what a second download of an unchanged export produces.
        again = repack(build_snapshot(entries))
        self.assertNotEqual(again, build_snapshot(entries))
        self.assertEqual(review_refresh.content_digest(again),
                         review_refresh.content_digest(build_snapshot(entries)))
        active = review_refresh.read_content_marker(self.config_path)
        result = review_refresh.collect(
            self.config_path, self.bundle_root, again, master, previous,
            active_content=active)
        self.assertTrue(result["no_op"])
        # Nothing moved: the config still names the first bundle, so the binding
        # the review is using is unchanged and no decision is lost.
        self.assertEqual(json.loads(self.config_path.read_text(
            encoding="utf-8"))["snapshot_sha256"], first["snapshot_sha256"])

    def test_a_master_that_gained_a_transaction_is_not_a_no_op(self):
        """The no-op decision covers all three inputs, not only the workbook.

        An identical workbook with one more card transaction is a real change, and
        the review has to move to see it. Deciding on the workbook alone would
        keep serving a review that is silently missing that transaction.
        """
        entries = [entry(1), entry(2)]
        master = build_master([master_row(1), master_row(2)])
        previous = self.previous_input(entries, master)
        self.staged(entries, master, previous)
        active = review_refresh.read_content_marker(self.config_path)

        grown = build_master([master_row(1), master_row(2), master_row(3)])
        result = review_refresh.collect(
            self.config_path, self.bundle_root, build_snapshot(entries), grown,
            previous, active_content=active)
        self.assertFalse(result["no_op"])
        # The master part of the marker is what moved, and the workbook part did
        # not: the change is a new card transaction, not a new workbook.
        self.assertNotEqual(result["content"]["master"], active["master"])
        self.assertEqual(result["content"]["workbook"], active["workbook"])

    def test_a_master_with_the_same_rows_in_another_order_is_a_no_op(self):
        """A re-exported master is the same content.

        The order of rows in a CSV export is not a fact about any transaction, so
        re-ordering it must not blank every decision either.
        """
        entries = [entry(1), entry(2)]
        master = build_master([master_row(1), master_row(2)])
        previous = self.previous_input(entries, master)
        self.staged(entries, master, previous)
        active = review_refresh.read_content_marker(self.config_path)
        reordered = build_master([master_row(2), master_row(1)])
        result = review_refresh.collect(
            self.config_path, self.bundle_root, build_snapshot(entries),
            reordered, previous, active_content=active)
        self.assertTrue(result["no_op"])

    def test_a_changed_formula_is_not_hidden_by_identical_cached_values(self):
        """Both passes matter, and this is the case only one pass would miss.

        A cell whose formula changed but whose last-saved cached result did not
        has identical data_only values. Comparing only those would call it a
        no-op and keep serving a source nobody reviewed, so the raw stored value
        is part of the digest too.
        """
        from openpyxl import Workbook

        def with_formula(formula):
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = SHEET
            for column, label in enumerate(BLOCK_HEADER, start=1):
                sheet.cell(row=4, column=column, value=label)
            sheet.cell(row=5, column=1, value="2026-04-01")
            sheet.cell(row=5, column=2, value="합성항목")
            sheet.cell(row=5, column=3, value="합성내용 1")
            sheet.cell(row=5, column=7, value=100001)
            sheet.cell(row=9, column=1, value=formula)
            buffer = io.BytesIO()
            workbook.save(buffer)
            workbook.close()
            return buffer.getvalue()

        first = with_formula("=SUM(1,1)")
        second = with_formula("=SUM(1,2)")
        self.assertNotEqual(review_refresh.content_digest(first),
                            review_refresh.content_digest(second))

    def test_merged_ranges_and_sheet_names_are_part_of_the_content(self):
        from openpyxl import Workbook

        def with_layout(second_sheet, merged):
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = SHEET
            for column, label in enumerate(BLOCK_HEADER, start=1):
                sheet.cell(row=4, column=column, value=label)
            sheet.cell(row=5, column=1, value="2026-04-01")
            sheet.cell(row=5, column=7, value=100001)
            if merged:
                sheet.merge_cells("C5:D5")
            other = workbook.create_sheet(second_sheet)
            other.cell(row=1, column=1, value="합성")
            buffer = io.BytesIO()
            workbook.save(buffer)
            workbook.close()
            return buffer.getvalue()

        base = review_refresh.content_digest(with_layout("합성둘", False))
        self.assertNotEqual(
            base, review_refresh.content_digest(with_layout("합성셋", False)))
        self.assertNotEqual(
            base, review_refresh.content_digest(with_layout("합성둘", True)))


class ScopeUnionTests(RefreshFixture):
    """Additions, removals and moves inside a range with no header."""

    def previous_review(self, entries, master, **kwargs):
        snapshot = build_snapshot(entries, **kwargs)
        return review_refresh.build_review_csv(snapshot, master), snapshot

    def test_a_new_row_inside_a_headerless_range_is_found(self):
        """A range whose header is gone is re-scanned, not just its old rows.

        Taking the previous rows one by one would find the previous rows and
        nothing else, so a transaction added inside a header-less range would be
        invisible to the next bundle. That is the range with the most real rows
        in it.
        """
        master = build_master([master_row(index) for index in range(1, 5)])
        review_text, snapshot = self.previous_review(
            [entry(1), entry(2)], master)
        self.assertIn("(row 5)", review_text)

        # The header is blanked and a third row is added underneath.
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(snapshot))
        sheet = workbook[SHEET]
        for column in range(1, 8):
            sheet.cell(row=4, column=column, value="")
        sheet.cell(row=7, column=1, value="2026-04-03")
        sheet.cell(row=7, column=2, value="합성항목")
        sheet.cell(row=7, column=3, value="합성내용 3")
        sheet.cell(row=7, column=7, value=100003)
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()

        after = review_refresh.build_review_csv(buffer.getvalue(), master,
                                                review_text)
        self.assertIn("(row 7)", after, "a new row in a headerless range was lost")
        self.assertIn("(row 5)", after)
        self.assertIn("(row 6)", after)

    def test_a_deleted_row_is_reported_as_a_removal_rather_than_failing(self):
        """A row that is genuinely gone must be able to leave the review.

        It used to be a hard failure, which meant a source could never shrink:
        the only bundle that could prove the row was gone was the bundle that
        was refused. The removal is now named, so it is a fact the status file
        reports.
        """
        master = build_master([master_row(index) for index in range(1, 4)])
        review_text, _snapshot = self.previous_review(
            [entry(1), entry(2), entry(3)], master)
        shorter = build_snapshot([entry(1)])
        records, removed = review_refresh._build_rows(shorter, master,
                                                      review_text)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(removed), 2)
        self.assertTrue(all("(row " in ref for ref in removed))

    def test_a_shrinking_source_is_collected_and_the_removals_named(self):
        """End to end, through the collector, with no operator floor set.

        A blanket refusal on any decrease would make a verified deletion
        impossible to ever collect. The bundle is staged, the removals are
        reported, and the row count genuinely drops.
        """
        master = build_master([master_row(index) for index in range(1, 4)])
        review_text, _snapshot = self.previous_review(
            [entry(1), entry(2), entry(3)], master)
        bundle = review_refresh.collect(self.config_path, self.bundle_root,
                                        build_snapshot([entry(1)]), master,
                                        review_text)
        self.assertEqual(bundle["rows"], 1)
        self.assertEqual(len(bundle["removed_refs"]), 2)

    def test_a_truncated_source_with_no_provable_scope_is_still_refused(self):
        """The difference between a deletion and a truncation is provable scope.

        A workbook with no expense header and no previous scope proves nothing at
        all, and that is refused — so the removal path cannot become a way to
        empty the review.
        """
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = SHEET
        sheet.cell(row=1, column=1, value="합성")
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        with self.assertRaises(review_refresh.RefreshError) as caught:
            review_refresh.collect(self.config_path, self.bundle_root,
                                   buffer.getvalue(),
                                   build_master([master_row(1)]))
        self.assertIn(caught.exception.code,
                      (review_refresh.CODE_SCOPE_UNPROVEN,
                       review_refresh.CODE_SOURCE_EMPTY))


class SheetNameAuthorityTests(RefreshFixture):
    def test_a_mixed_sheet_is_not_excluded_by_its_name(self):
        """A sheet name is not evidence, and income and expense share sheets.

        The earlier version skipped any sheet whose name contained 수입, which
        discarded a real expense block. The blocks are separated by their own
        headers now, so a mixed sheet keeps its expense rows and loses its
        income ones.
        """
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "2026년 수입및지출"
        for column, label in enumerate(INCOME_HEADER, start=1):
            sheet.cell(row=1, column=column, value=label)
        sheet.cell(row=2, column=1, value="2026-04-01")
        sheet.cell(row=2, column=5, value=100001)
        for column, label in enumerate(BLOCK_HEADER, start=1):
            sheet.cell(row=4, column=column, value=label)
        sheet.cell(row=5, column=1, value="2026-04-02")
        sheet.cell(row=5, column=2, value="합성항목")
        sheet.cell(row=5, column=3, value="합성내용 2")
        sheet.cell(row=5, column=7, value=100002)
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()

        master = build_master([master_row(2)])
        text = review_refresh.build_review_csv(buffer.getvalue(), master)
        # The expense block on the mixed sheet is found, and the income row above
        # it — same sheet, same columns, different header — is not.
        self.assertIn("2026년 수입및지출!A5", text)
        self.assertNotIn("(row 2)", text)
        self.assertEqual(text.count("(row "), 1)


class CollectorLockTests(RefreshFixture):
    def test_a_second_collector_is_refused_while_one_holds_the_lock(self):
        """Two collectors must not both pass validation and race the swap.

        The lock is an OS lock on a real file, so it is held across processes and
        not only across threads — which is the case that matters, because a
        scheduled run and a manual one are two processes.
        """
        master = build_master([master_row(1)])
        snapshot = build_snapshot([entry(1)])
        review_refresh.collect(self.config_path, self.bundle_root, snapshot,
                               master)
        with review_refresh.collector_lock(self.config_path):
            with self.assertRaises(review_refresh.RefreshError) as caught:
                review_refresh.collect(self.config_path, self.bundle_root,
                                       snapshot, master)
        self.assertEqual(caught.exception.code,
                         review_refresh.CODE_COLLECTOR_BUSY)

    def test_the_lock_is_released_for_the_next_collector(self):
        master = build_master([master_row(1)])
        snapshot = build_snapshot([entry(1)])
        for _attempt in range(2):
            review_refresh.collect(self.config_path, self.bundle_root, snapshot,
                                   master)


class ActivationTests(RefreshFixture):
    def test_activation_replaces_the_config_and_keeps_the_decisions_path(self):
        master = build_master([master_row(1), master_row(2)])
        self.seed_config()
        bundle = review_refresh.collect(self.config_path, self.bundle_root,
                                        build_snapshot([entry(1), entry(2)]),
                                        master)
        code = review_refresh.activate(self.config_path, bundle)
        self.assertEqual(code, review_refresh.CODE_CONFIG_REPLACED)
        manifest = json.loads(self.config_path.read_text(encoding="utf-8"))
        # The seven keys the core's contract fixes, and the same decision history.
        self.assertEqual(sorted(manifest), [
            "decisions_db_path", "master_path", "master_sha256", "review_path",
            "review_sha256", "snapshot_path", "snapshot_sha256"])
        self.assertEqual(manifest["decisions_db_path"], str(self.decisions_db))
        self.assertEqual(manifest["snapshot_sha256"], bundle["snapshot_sha256"])

    def test_a_source_failure_leaves_the_previous_config_untouched(self):
        """A failed collection must not move the active source.

        The previous bundle stays exactly as it is, and the failure is reported
        by code, so an operator can see the source did not refresh rather than
        assume it did.
        """
        master = build_master([master_row(1)])
        self.seed_config()
        good = review_refresh.collect(self.config_path, self.bundle_root,
                                      build_snapshot([entry(1)]), master)
        review_refresh.activate(self.config_path, good)
        before = self.config_path.read_bytes()

        review_refresh.write_status(self.bundle_root,
                                    review_refresh.CODE_SOURCE_EMPTY, None)
        self.assertEqual(self.config_path.read_bytes(), before)
        status = review_refresh.load_status(self.bundle_root)
        self.assertEqual(status["code"], review_refresh.CODE_SOURCE_EMPTY)

    def test_a_validation_failure_stages_nothing_and_names_its_code(self):
        """The core's verdict is the only one that activates a bundle.

        A duplicate master key is refused by the collector before anything is
        written, so there is no half-staged bundle for a later run to activate.
        """
        master = build_master([master_row(1), master_row(1)])
        with self.assertRaises(review_refresh.RefreshError) as caught:
            review_refresh.collect(self.config_path, self.bundle_root,
                                   build_snapshot([entry(1)]), master)
        self.assertEqual(caught.exception.code,
                         review_refresh.CODE_MASTER_DUPLICATE_KEY)
        self.assertFalse(self.bundle_root.exists())

    def test_collect_and_activate_reports_a_no_op_without_touching_anything(self):
        master = build_master([master_row(1)])
        self.seed_config()
        previous = review_refresh.build_review_csv(
            build_snapshot([entry(1)]), master)
        first = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, build_snapshot([entry(1)]),
            master, previous)
        self.assertFalse(first["no_op"])
        before = self.config_path.read_bytes()

        second = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root,
            repack(build_snapshot([entry(1)])), master, previous)
        self.assertTrue(second["no_op"])
        self.assertFalse(second.get("activated", False))
        self.assertEqual(self.config_path.read_bytes(), before)


def dates_and_amounts(review_text):
    """The (date, amount) pairs a review CSV lists, sorted.

    The ref is a cell address, so it moves when a row is inserted above. The
    transaction is the pair, and that is what has to survive a reshape.
    """
    import csv

    rows = list(csv.reader(io.StringIO(review_text)))
    header = rows[0]
    date_index = header.index("source_date")
    amount_index = header.index("source_amount")
    return sorted((row[date_index], row[amount_index]) for row in rows[1:])


class MidBlockContentTests(RefreshFixture):
    """The real workbook is not a clean list of rows, and the range must survive it.

    The parent measured this against the real source: 1,234 rows generated where
    1,734 existed, 514 of the previous review's refs missing. Two causes, both
    here. A memo line, a section title or a subtotal inside a block was read as a
    header and ended the range, so everything below it was dropped. And a range
    that a header proved was skipped for the legacy scan, so rows above that
    header — or below a memo inside it — were never looked for at all. 520 of the
    real rows have no header above them, so they had no second chance.
    """

    def workbook(self, layout, *, memo_rows=(), header_row=4, first_row=5,
                 extra_header_row=None, width=7):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = SHEET
        for offset, label in enumerate(BLOCK_HEADER[:-1]):
            sheet.cell(row=header_row, column=layout[0] + offset, value=label)
        sheet.cell(row=header_row, column=layout[2], value=BLOCK_HEADER[-1])
        for index, (row, text) in enumerate(memo_rows):
            sheet.cell(row=row, column=1, value=text)
        for offset in range(3):
            row = first_row + offset
            date, item, description, amount = entry(offset + 1)
            sheet.cell(row=row, column=layout[0], value=date)
            sheet.cell(row=row, column=layout[0] + 1, value=item)
            sheet.cell(row=row, column=layout[0] + 2, value=description)
            sheet.cell(row=row, column=layout[2], value=amount)
        if extra_header_row is not None:
            for offset, label in enumerate(BLOCK_HEADER[:-1]):
                sheet.cell(row=extra_header_row,
                           column=layout[0] + offset, value=label)
            sheet.cell(row=extra_header_row, column=layout[2],
                       value=BLOCK_HEADER[-1])
        buffer = io.BytesIO()
        book.save(buffer)
        book.close()
        return buffer.getvalue()

    def rows_in(self, text):
        return text.count("(row ")

    def test_a_memo_line_inside_a_block_does_not_end_the_range(self):
        """A title or a note in the middle of a block is content, not a header."""
        master = build_master([master_row(index) for index in range(1, 4)])
        clean = self.workbook(LAYOUT_1_7)
        memo = self.workbook(LAYOUT_1_7, memo_rows=((6, "3월 지출 메모"),))
        previous = review_refresh.build_review_csv(clean, master)
        after = review_refresh.build_review_csv(memo, master, previous)
        self.assertEqual(self.rows_in(after), 3)
        self.assertIn("(row 7)", after, "a row below the memo was lost")

    def test_a_subtotal_row_inside_a_block_does_not_end_the_range(self):
        """합계 in an amount column is a subtotal, and not an income header.

        The income-header test needs a date label in the date column as well, so a
        subtotal that only writes a total cannot be mistaken for a block starting.
        """
        from openpyxl import Workbook

        def with_subtotal():
            book = Workbook()
            sheet = book.active
            sheet.title = SHEET
            for offset, label in enumerate(BLOCK_HEADER[:-1]):
                sheet.cell(row=4, column=1 + offset, value=label)
            sheet.cell(row=4, column=7, value=BLOCK_HEADER[-1])
            for offset in range(3):
                row = 5 + offset
                date, item, description, amount = entry(offset + 1)
                sheet.cell(row=row, column=1, value=date)
                sheet.cell(row=row, column=2, value=item)
                sheet.cell(row=row, column=3, value=description)
                sheet.cell(row=row, column=7, value=amount)
            # A subtotal below the rows, which is where one is written.
            sheet.cell(row=9, column=7, value="합계")
            buffer = io.BytesIO()
            book.save(buffer)
            book.close()
            return buffer.getvalue()

        master = build_master([master_row(index) for index in range(1, 4)])
        snapshot = with_subtotal()
        text = review_refresh.build_review_csv(snapshot, master)
        self.assertEqual(self.rows_in(text), 3)

    def previous_review_text(self, rows, snapshot_sha):
        """A review CSV naming rows the core recorded on an earlier pass.

        Written rather than generated, because the case under test is precisely a
        row that no header covers: on the real source the input is the existing
        1,734-row review file, full of refs for rows with no header above them.
        A generated one could only ever describe rows a header proved.
        """
        import csv as _csv

        from webapp.review_csv_adapter import RAW_CANDIDATE
        from webapp.review_csv_adapter import REQUIRED_HEADERS
        from webapp.review_csv_adapter import REVIEW_SCHEMA_VERSION

        buffer = io.StringIO(newline="")
        writer = _csv.writer(buffer, lineterminator="\n")
        writer.writerow(list(REQUIRED_HEADERS))
        for row, date, amount in rows:
            writer.writerow([
                f"{SHEET}!A{row}|G{row} (row {row})", date, amount, "0", "[]",
                "[]", RAW_CANDIDATE, "", "", REVIEW_SCHEMA_VERSION,
                snapshot_sha,
            ])
        return buffer.getvalue()

    def test_rows_above_the_explicit_header_are_still_collected(self):
        """Data before the header is in the range, and the previous review knows it.

        The legacy scan used to be skipped whenever a block with the same columns
        was proven, so rows above that block's header were only found if the block
        scan reached them — and it starts below its own header. On the real source
        that is where much of the 514 missing rows were.
        """
        from openpyxl import Workbook

        from webapp.contracts import sha256_bytes

        def shaped(header_row):
            book = Workbook()
            sheet = book.active
            sheet.title = SHEET
            if header_row:
                for offset, label in enumerate(BLOCK_HEADER[:-1]):
                    sheet.cell(row=header_row, column=1 + offset, value=label)
                sheet.cell(row=header_row, column=7, value=BLOCK_HEADER[-1])
            for row, index in ((1, 1), (2, 2), (9, 3)):
                date, item, description, amount = entry(index)
                sheet.cell(row=row, column=1, value=date)
                sheet.cell(row=row, column=2, value=item)
                sheet.cell(row=row, column=3, value=description)
                sheet.cell(row=row, column=7, value=amount)
            buffer = io.BytesIO()
            book.save(buffer)
            book.close()
            return buffer.getvalue()

        master = build_master([master_row(index) for index in range(1, 4)])
        # The baseline: three rows and no header at all, as the real one is.
        headerless = shaped(0)
        previous = self.previous_review_text(
            [(1, entry(1)[0], entry(1)[3]), (2, entry(2)[0], entry(2)[3]),
             (9, entry(3)[0], entry(3)[3])], sha256_bytes(headerless))
        self.assertEqual(self.rows_in(
            review_refresh.build_review_csv(headerless, master, previous)), 3)

        # The header arrives, pushed to the bottom of the two leading rows.
        after = review_refresh.build_review_csv(shaped(6), master, previous)
        self.assertEqual(self.rows_in(after), 3)
        self.assertIn("(row 1)", after)
        self.assertIn("(row 9)", after)

    def test_a_repeated_header_starts_a_new_range_and_both_are_read(self):
        """A block printed twice on a sheet is two blocks, and both are scope.

        The second header is an explicit header, so it ends the first range and
        starts another, and the rows under both are transactions.
        """
        from openpyxl import Workbook

        book = Workbook()
        book.remove(book.active)
        for index, header_row in ((1, 4), (3, 20)):
            sheet = book.create_sheet(f"{SHEET}{index}")
            for offset, label in enumerate(BLOCK_HEADER[:-1]):
                sheet.cell(row=header_row, column=1 + offset, value=label)
            sheet.cell(row=header_row, column=7, value=BLOCK_HEADER[-1])
            date, item, description, amount = entry(index)
            sheet.cell(row=header_row + 1, column=1, value=date)
            sheet.cell(row=header_row + 1, column=2, value=item)
            sheet.cell(row=header_row + 1, column=3, value=description)
            sheet.cell(row=header_row + 1, column=7, value=amount)
        buffer = io.BytesIO()
        book.save(buffer)
        book.close()
        master = build_master([master_row(1), master_row(3)])
        text = review_refresh.build_review_csv(buffer.getvalue(), master)
        self.assertEqual(self.rows_in(text), 2)

    def test_an_income_header_still_ends_an_expense_range(self):
        """The boundary rule is narrow in both directions.

        A memo is not a boundary and an income block is, so the expense range
        stops where the income block starts and does not run on through it.
        """
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = SHEET
        for offset, label in enumerate(BLOCK_HEADER[:-1]):
            sheet.cell(row=4, column=1 + offset, value=label)
        sheet.cell(row=4, column=7, value=BLOCK_HEADER[-1])
        date, item, description, amount = entry(1)
        sheet.cell(row=5, column=1, value=date)
        sheet.cell(row=5, column=2, value=item)
        sheet.cell(row=5, column=3, value=description)
        sheet.cell(row=5, column=7, value=amount)
        # An income block below, sharing the same columns.
        sheet.cell(row=9, column=1, value="일자")
        sheet.cell(row=9, column=7, value="입금액")
        date, item, description, amount = entry(2)
        sheet.cell(row=10, column=1, value=date)
        sheet.cell(row=10, column=2, value=item)
        sheet.cell(row=10, column=3, value=description)
        sheet.cell(row=10, column=7, value=amount)
        buffer = io.BytesIO()
        book.save(buffer)
        book.close()
        master = build_master([master_row(1), master_row(2)])
        text = review_refresh.build_review_csv(buffer.getvalue(), master)
        self.assertEqual(self.rows_in(text), 1)
        self.assertIn("(row 5)", text)
        self.assertNotIn("(row 10)", text)

    def test_every_previous_ref_survives_a_reshaped_workbook(self):
        """The measurement the parent asked for, in miniature.

        Same three transactions, a memo line moved in, a subtotal added, and the
        explicit header pushed down. Every ref the previous review listed is still
        listed, and nothing extra appears.
        """
        from openpyxl import Workbook

        def shaped(with_noise):
            book = Workbook()
            sheet = book.active
            sheet.title = SHEET
            header_row = 9 if with_noise else 4
            for offset, label in enumerate(BLOCK_HEADER[:-1]):
                sheet.cell(row=header_row, column=1 + offset, value=label)
            sheet.cell(row=header_row, column=7, value=BLOCK_HEADER[-1])
            first = 1 if with_noise else 5
            if with_noise:
                sheet.cell(row=3, column=1, value="지출 메모")
            for offset in range(3):
                row = first + offset
                date, item, description, amount = entry(offset + 1)
                sheet.cell(row=row, column=1, value=date)
                sheet.cell(row=row, column=2, value=item)
                sheet.cell(row=row, column=3, value=description)
                sheet.cell(row=row, column=7, value=amount)
            if with_noise:
                sheet.cell(row=6, column=7, value="합계")
            buffer = io.BytesIO()
            book.save(buffer)
            book.close()
            return buffer.getvalue()

        master = build_master([master_row(index) for index in range(1, 4)])
        before = review_refresh.build_review_csv(shaped(False), master)
        self.assertEqual(self.rows_in(before), 3)
        after = review_refresh.build_review_csv(shaped(True), master, before)
        self.assertEqual(self.rows_in(after), 3)
        # The same three refs, at the addresses the new workbook gives them.
        import csv as _csv

        def refs(text):
            rows = list(_csv.reader(io.StringIO(text)))
            return sorted(row[0] for row in rows[1:])

        self.assertEqual(len(refs(after)), 3)
        # The same three transactions, at whatever addresses the reshaped workbook
        # gives them. The addresses are expected to move when rows are inserted
        # above; the transactions are what must not be lost.
        self.assertEqual(dates_and_amounts(after), dates_and_amounts(before))
        self.assertNotEqual(refs(after), refs(before))


class CollectorCliTests(RefreshFixture):
    """The command, with the fetch injected and no network involved."""

    def setUp(self):
        super().setUp()
        self.seed_config()
        self.entries = [entry(1), entry(2)]
        self.master = build_master([master_row(1), master_row(2)])
        self.snapshot = build_snapshot(self.entries)
        # The first activation, so there is a live review to read as the previous
        # input and a live bundle to compare against.
        self.previous = review_refresh.build_review_csv(self.snapshot,
                                                        self.master)
        self.first = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, self.snapshot, self.master,
            self.previous)

    def args(self, **overrides):
        import argparse

        argv = ["--config", str(self.config_path),
                "--master", str(self.tmp / "master.csv"),
                "--bundle-root", str(self.bundle_root),
                "--snapshot", str(self.tmp / "snapshot.xlsx")]
        for key, value in overrides.items():
            argv += [f"--{key.replace('_', '-')}", str(value)]
        return cli.build_parser().parse_args(argv)

    def write_inputs(self, snapshot=None, master=None):
        (self.tmp / "snapshot.xlsx").write_bytes(snapshot or self.snapshot)
        (self.tmp / "master.csv").write_text(master or self.master,
                                             encoding="utf-8")

    def test_a_changed_source_is_collected_and_activated(self):
        self.write_inputs(snapshot=build_snapshot(
            [entry(1), entry(2), entry(3)]),
            master=build_master([master_row(index) for index in range(1, 4)]))
        code = cli.run_once(self.args())
        self.assertEqual(code, review_refresh.CODE_CONFIG_REPLACED)
        live = json.loads(self.config_path.read_text(encoding="utf-8"))
        model = review_context.build_review_context(
            pathlib.Path(live["snapshot_path"]).read_bytes(),
            pathlib.Path(live["review_path"]).read_bytes().decode("utf-8"),
            pathlib.Path(live["master_path"]).read_bytes().decode("utf-8"),
            live["snapshot_sha256"], live["review_sha256"],
            live["master_sha256"])
        self.assertEqual(len(model["rows"]), 3)

    def test_an_unchanged_source_is_a_no_op_and_the_config_does_not_move(self):
        self.write_inputs()
        before = self.config_path.read_bytes()
        code = cli.run_once(self.args())
        self.assertEqual(code, "REFRESH_NO_CHANGE")
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_three_runs_of_the_same_export_activate_once(self):
        """The convergence the coordinator asked for.

        The first run activates. The second reads the new review CSV as its input,
        so the scope it was given is the one the marker was written from, and the
        third is the same again. A marker bound to the *input* scope instead would
        have re-activated on run two, for a source that had not changed.
        """
        grown = build_snapshot([entry(1), entry(2), entry(3)])
        grown_master = build_master([master_row(index) for index in range(1, 4)])
        self.write_inputs(snapshot=grown, master=grown_master)
        self.assertEqual(cli.run_once(self.args()),
                         review_refresh.CODE_CONFIG_REPLACED)
        live_after_first = self.config_path.read_bytes()
        self.assertEqual(cli.run_once(self.args()), "REFRESH_NO_CHANGE")
        self.assertEqual(self.config_path.read_bytes(), live_after_first)
        # The third run re-downloads the same export with new ZIP timestamps, which
        # is what the real source does and what must not move the binding.
        self.write_inputs(snapshot=repack(grown), master=grown_master)
        self.assertEqual(cli.run_once(self.args()), "REFRESH_NO_CHANGE")
        self.assertEqual(self.config_path.read_bytes(), live_after_first)

    def test_a_fetch_failure_keeps_the_last_good_and_records_a_code(self):
        def unreachable(*_args, **_kwargs):
            # What the real fetcher raises after its own attempts are exhausted.
            raise cli.SourceUnavailable(cli.CODE_SOURCE_UNREACHABLE)

        self.write_inputs()
        args = self.args()
        args.source_url = "https://synthetic.invalid/export.xlsx"
        args.snapshot = None
        code = cli.run_once(args, fetcher=unreachable)
        self.assertEqual(code, cli.CODE_SOURCE_UNREACHABLE)
        # The live source is untouched, and the failure is readable by the web app
        # from the one place both sides look.
        self.assertEqual(json.loads(self.config_path.read_text(
            encoding="utf-8"))["snapshot_sha256"], self.first["snapshot_sha256"])
        # The one place both sides look: the web app's own path, derived from the
        # config rather than from the bundle root, so a failure the collector
        # recorded is a failure the owner can be shown.
        status_path = real_review.refresh_status_path(str(self.config_path))
        self.assertEqual(status_path,
                         str(self.config_path) + ".refresh-status.json")
        status = json.loads(pathlib.Path(status_path).read_text(
            encoding="utf-8"))
        self.assertEqual(status["code"], cli.CODE_SOURCE_UNREACHABLE)
        os.environ[real_review.REFRESH_STATUS_ENV] = status_path
        self.addCleanup(os.environ.pop, real_review.REFRESH_STATUS_ENV, None)
        self.assertEqual(real_review.refresh_status()["code"],
                         cli.CODE_SOURCE_UNREACHABLE)

    def test_an_oversized_source_is_refused_before_it_is_read(self):
        class Response:
            headers = {"Content-Length": "2048"}

            def read(self, _limit):
                raise AssertionError("the body was read after the size was known")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(_request, timeout=None):
            return Response()

        with self.assertRaises(cli.SourceUnavailable) as caught:
            cli.fetch_snapshot("https://synthetic.invalid/x.xlsx",
                                    timeout=1.0, max_bytes=1024, attempts=1,
                                    opener=opener)
        self.assertEqual(caught.exception.code, cli.CODE_SOURCE_TOO_LARGE)

    def test_a_response_that_is_not_a_workbook_is_refused(self):
        class Response:
            headers = {"Content-Type": "text/html", "Content-Length": "5"}

            def read(self, _limit):
                return b"<html>"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with self.assertRaises(cli.SourceUnavailable) as caught:
            cli.fetch_snapshot("https://synthetic.invalid/x.xlsx",
                                    timeout=1.0, max_bytes=1024, attempts=1,
                                    opener=lambda *a, **k: Response())
        self.assertEqual(caught.exception.code, cli.CODE_SOURCE_WRONG_TYPE)

    def test_the_remote_path_fetches_without_an_injected_fetcher(self):
        """The path the parent found unrunnable: a remote source with no fetcher.

        `run_once` called `fetcher(url)` with the parameter at its default of
        None, so a URL was accepted by the parser and then failed with a
        TypeError. The default is the bounded fetch now, and this drives it with a
        synthetic opener so the real path is exercised without a network.
        """
        grown = build_snapshot([entry(1), entry(2), entry(3)])
        grown_master = build_master([master_row(index) for index in range(1, 4)])
        (self.tmp / "master.csv").write_text(grown_master, encoding="utf-8")
        asked = {}

        class Response:
            headers = {"Content-Type": "application/vnd.openxmlformats-"
                                       "officedocument.spreadsheetml.sheet",
                       "Content-Length": str(len(grown))}

            def read(self, limit):
                return grown[:limit]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout=None):
            asked["url"] = request.full_url
            asked["timeout"] = timeout
            asked["agent"] = request.get_header("User-agent")
            return Response()

        original = cli.urllib.request.urlopen
        cli.urllib.request.urlopen = opener
        self.addCleanup(setattr, cli.urllib.request, "urlopen", original)

        args = self.args()
        args.source_url = "https://synthetic.invalid/export.xlsx"
        args.snapshot = None
        args.timeout = 12.0
        code = cli.run_once(args)
        self.assertEqual(code, review_refresh.CODE_CONFIG_REPLACED)
        self.assertEqual(asked["url"], "https://synthetic.invalid/export.xlsx")
        self.assertEqual(asked["timeout"], 12.0)
        # The agent the working probe used, and not the default Python one.
        self.assertTrue(str(asked["agent"]).startswith("Mozilla/5.0"),
                        asked["agent"])
        live = json.loads(self.config_path.read_text(encoding="utf-8"))
        model = review_context.build_review_context(
            pathlib.Path(live["snapshot_path"]).read_bytes(),
            pathlib.Path(live["review_path"]).read_bytes().decode("utf-8"),
            pathlib.Path(live["master_path"]).read_bytes().decode("utf-8"),
            live["snapshot_sha256"], live["review_sha256"],
            live["master_sha256"])
        self.assertEqual(len(model["rows"]), 3)

    def test_an_out_of_range_bound_is_refused_before_anything_is_read(self):
        for overrides in ({"timeout": 0}, {"timeout": -1}, {"timeout": float("inf")},
                          {"max_bytes": 0}, {"attempts": 0}, {"attempts": 99},
                          {"interval": 0}, {"interval": 10 ** 9},
                          {"minimum_rows": -1}):
            with self.subTest(**overrides):
                # The bounds are refused before any file is opened, so a bad
                # number cannot be read as "no bound".
                self.assertEqual(cli.main(self.argv(**overrides)), 2)

    def argv(self, **overrides):
        argv = ["--config", str(self.config_path),
                "--master", str(self.tmp / "master.csv"),
                "--bundle-root", str(self.bundle_root),
                "--snapshot", str(self.tmp / "snapshot.xlsx")]
        for key, value in overrides.items():
            argv += [f"--{key.replace('_', '-')}", str(value)]
        return argv

    def test_the_watch_interval_defaults_to_thirty_seconds(self):
        """Long enough not to hammer the source, short enough to be useful.

        The web app re-reads its config every two seconds, so a collector
        interval much longer than that means a refreshed source sits unseen for
        minutes. An operator who wants it faster passes 15.
        """
        parsed = cli.build_parser().parse_args(self.argv())
        self.assertEqual(parsed.interval, 30.0)
        self.assertEqual(cli.DEFAULT_INTERVAL, 30.0)

    def test_the_output_is_a_fixed_code_and_nothing_else(self):
        """A log that carried a URL or a path would carry the data with it."""
        import io as _io

        self.write_inputs()
        stream = _io.StringIO()
        cli.report("REFRESH_NO_CHANGE", stream)
        self.assertEqual(json.loads(stream.getvalue()),
                         {"code": "REFRESH_NO_CHANGE"})


class ConvergenceTests(RefreshFixture):
    """Three collections in a row, with the second and third changing nothing.

    The marker is bound to the review that was *generated*. After an activation the
    next run reads that new review CSV as its input, so a marker written from the
    input's scope would never match and every run would re-activate a bundle for a
    source that had not changed — blanking the decisions each time. This is the
    check that the design converges rather than oscillating.
    """

    def setUp(self):
        super().setUp()
        self.seed_config()
        self.master = build_master([master_row(index) for index in range(1, 5)])
        self.previous = review_refresh.build_review_csv(
            build_snapshot([entry(1), entry(2)]), self.master)
        first = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root,
            build_snapshot([entry(1), entry(2), entry(3)]),
            build_master([master_row(index) for index in range(1, 4)]),
            self.previous)
        self.assertFalse(first["no_op"])
        self.settled = self.config_path.read_bytes()

    def active_review_text(self):
        manifest = json.loads(self.config_path.read_text(encoding="utf-8"))
        return pathlib.Path(manifest["review_path"]).read_bytes().decode("utf-8")

    def test_three_identical_collections_activate_once(self):
        """Run two and three read the *activated* review as their input.

        That is the whole point: the input scope is now the generated scope, so
        the marker matches it and both runs are no-ops.
        """
        snapshot = build_snapshot([entry(1), entry(2), entry(3)])
        master = build_master([master_row(index) for index in range(1, 4)])
        for attempt in (2, 3):
            with self.subTest(attempt=attempt):
                result = review_refresh.collect_and_activate(
                    self.config_path, self.bundle_root, snapshot, master,
                    self.active_review_text())
                self.assertTrue(result["no_op"])
                self.assertEqual(self.config_path.read_bytes(), self.settled)

    def test_a_re_download_with_new_zip_timestamps_is_still_a_no_op(self):
        """The real source's behaviour: same cells, different file bytes."""
        snapshot = build_snapshot([entry(1), entry(2), entry(3)])
        master = build_master([master_row(index) for index in range(1, 4)])
        again = repack(snapshot)
        self.assertNotEqual(again, snapshot)
        result = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, again, master,
            self.active_review_text())
        self.assertTrue(result["no_op"])
        self.assertEqual(self.config_path.read_bytes(), self.settled)

    def test_a_new_card_transaction_still_activates(self):
        """The no-op is about the content, so a changed master still moves it."""
        master = build_master([master_row(index) for index in range(1, 5)])
        result = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root,
            build_snapshot([entry(1), entry(2), entry(3)]), master,
            self.active_review_text())
        self.assertFalse(result["no_op"])
        self.assertNotEqual(self.config_path.read_bytes(), self.settled)

    def test_a_new_source_row_still_activates(self):
        snapshot = build_snapshot([entry(1), entry(2), entry(3), entry(4)])
        master = build_master([master_row(index) for index in range(1, 5)])
        result = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, snapshot, master,
            self.active_review_text())
        self.assertFalse(result["no_op"])
        self.assertNotEqual(self.config_path.read_bytes(), self.settled)


class HotReloadTests(RefreshFixture):
    """The app picks a new bundle up without a restart, and says so when it cannot.

    A refresh is only finished when the owner can see it. These go through the
    app's own entry point rather than the collector, because the thing that has to
    work is the web side reading a config the collector replaced underneath it.
    """

    def setUp(self):
        super().setUp()
        self.seed_config()
        os.environ[real_review.CONFIG_ENV] = str(self.config_path)

    def collect(self, entries, master, previous=None):
        snapshot = build_snapshot(entries)
        if previous is None:
            previous = review_refresh.build_review_csv(snapshot, master)
        return review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, snapshot, master, previous)

    def due(self):
        """Make the next lookup's bounded re-read due, as two seconds would."""
        real_review._LAST_RECHECK = 0.0
        return real_review.active_service()

    def test_a_new_config_replaces_the_service_and_the_binding(self):
        """The bounded re-read is what makes a refresh visible at all."""
        master = build_master([master_row(1), master_row(2)])
        self.collect([entry(1)], master)
        before = self.due()
        old_binding = before.model_binding()

        self.collect([entry(1), entry(2)], master)
        after = self.due()
        self.assertNotEqual(after.model_binding(), old_binding)
        # And the service on screen is now serving the new rows.
        self.assertEqual(len(after.model()["rows"]), 2)

    def test_an_invalid_new_config_keeps_the_last_good_service(self):
        """A config the core refuses must not become the service that answers.

        The whole model is built before the swap for exactly this reason. If the
        swap came first, the failure would surface as a broken page rather than as
        a rejected refresh — the owner would lose a working review to learn that
        a collection had failed.
        """
        master = build_master([master_row(1)])
        self.collect([entry(1)], master)
        before = self.due()
        old_binding = before.model_binding()

        # Well formed enough to be read, and naming files that are not there.
        self.config_path.write_text(json.dumps({
            "snapshot_path": str(self.tmp / "missing.xlsx"),
            "snapshot_sha256": "0" * 64,
            "review_path": str(self.tmp / "missing.csv"),
            "review_sha256": "0" * 64,
            "master_path": str(self.tmp / "missing-master.csv"),
            "master_sha256": "0" * 64,
            "decisions_db_path": str(self.decisions_db),
        }, ensure_ascii=False), encoding="utf-8")
        after = self.due()
        self.assertEqual(after.model_binding(), old_binding)
        self.assertEqual(len(after.model()["rows"]), 1)
        # And the owner is told the source did not move.
        # And the owner is told, in fixed terms, that the source did not take:
        # a drift code rather than a blank page.
        shown = after.state_only_payload()["refresh"]
        self.assertEqual(shown["code"], real_review.CODE_SOURCE_DRIFT)
        self.assertTrue(shown["code"].startswith("REVIEW_"))

    def test_a_collector_failure_is_shown_even_though_the_source_did_not_move(self):
        """A failed collection never writes the config, so the config alone lies.

        With nothing else the screen would keep showing the last good rows and the
        owner would read that as "the source has not changed". The collector's own
        record is what makes the difference between an unchanged source and a
        source nobody managed to read.
        """
        import argparse

        master = build_master([master_row(1)])
        self.collect([entry(1)], master)
        service = self.due()
        cli._record(argparse.Namespace(config=str(self.config_path),
                                       bundle_root=str(self.bundle_root)),
                    cli.CODE_SOURCE_UNREACHABLE, None)
        state = real_review.refresh_status()
        self.assertEqual(state["code"], cli.CODE_SOURCE_UNREACHABLE)
        shown = service.state_only_payload()["refresh"]
        self.assertEqual(shown["code"], cli.CODE_SOURCE_UNREACHABLE)
        # The screen still serves the last good rows.
        self.assertEqual(len(service.model()["rows"]), 1)

    def test_a_save_presented_against_a_previous_bundle_is_refused_with_a_fixed_code(
            self):
        """The name says what it checks, because that is the whole point.

        A request holds one service for its whole life, so a collector can activate
        a new bundle while a save is being prepared. That old service's own binding
        check still passes — it is internally consistent, it is just no longer the
        live one — so before writing it re-reads the config and refuses with the
        fixed code. Without that second check a decision made against the previous
        rows would be written into the new dataset, where the row it refers to may
        no longer mean the same thing.
        """
        master = build_master([master_row(1), master_row(2)])
        self.collect([entry(1)], master)
        old_service = self.due()
        old_binding = old_service.model_binding()
        row = old_service.model()["rows"][0]
        ref, value = row["ref"], row["candidates"][0]["key"]
        self.assertNotIn(value, {"", None})

        # A new bundle becomes live while that service is still in hand.
        self.collect([entry(1), entry(2)], master)
        self.due()

        with self.assertRaises(real_review.RealReviewError) as caught:
            old_service.save_decisions(
                [{"ref": ref, "value": "APPROVE:" + value}], 0, old_binding)
        self.assertEqual(caught.exception.code,
                         real_review.CODE_BINDING_CONFLICT)
        self.assertEqual(caught.exception.code,
                         "REVIEW_SOURCE_BINDING_CONFLICT")
        # And nothing landed in the new bundle.
        fresh = real_review.active_service()
        self.assertEqual(fresh.state()["counts"]["selected"], 0)

    def test_the_previous_bundles_decisions_are_not_written_into_the_new_one(self):
        """The store is per binding, so a new dataset starts with nothing decided.

        A decision made against the old rows must not reappear in the new review
        even where a cell address happens to be the same. Keying the store by
        binding is what makes that true.
        """
        master = build_master([master_row(1), master_row(2)])
        self.collect([entry(1)], master)
        service = self.due()
        row = service.model()["rows"][0]
        service.save_decisions(
            [{"ref": row["ref"], "value": "APPROVE:" + row["candidates"][0]["key"]}],
            0, service.model_binding())
        self.assertEqual(service.state()["counts"]["selected"], 1)

        self.collect([entry(1), entry(2)], master)
        fresh = self.due()
        self.assertNotEqual(fresh.model_binding(), service.model_binding())
        self.assertEqual(fresh.state()["counts"]["selected"], 0)
        self.assertEqual(fresh.state()["counts"]["held"], 2)


class RefreshStatusPrecedenceTests(RefreshFixture):
    """What the owner is told, when the collector's record and the service disagree.

    The collector's file is the *last* collection. A config the service refuses
    never becomes one, so the last successful collection can be older than the
    failure now in front of the user. Reporting that success would say the source
    is fine while the app is serving the previous bundle.
    """

    def setUp(self):
        super().setUp()
        self.seed_config()
        os.environ[real_review.CONFIG_ENV] = str(self.config_path)
        master = build_master([master_row(1)])
        bundle = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, build_snapshot([entry(1)]),
            master, review_refresh.build_review_csv(
                build_snapshot([entry(1)]), master))
        # The collector leaves its own record behind; written the way it writes it.
        import argparse

        cli._record(argparse.Namespace(config=str(self.config_path),
                                       bundle_root=str(self.bundle_root)),
                    review_refresh.CODE_CONFIG_REPLACED, bundle)
        real_review._LAST_RECHECK = 0.0
        self.service = real_review.active_service()
        self.assertIsNotNone(self.service)
        # A past success, exactly as the collector left it.
        self.assertEqual(real_review.refresh_status()["code"],
                         review_refresh.CODE_CONFIG_REPLACED)

    def break_the_config(self):
        self.config_path.write_text(json.dumps({
            "snapshot_path": str(self.tmp / "missing.xlsx"),
            "snapshot_sha256": "0" * 64,
            "review_path": str(self.tmp / "missing.csv"),
            "review_sha256": "0" * 64,
            "master_path": str(self.tmp / "missing-master.csv"),
            "master_sha256": "0" * 64,
            "decisions_db_path": str(self.decisions_db),
        }, ensure_ascii=False), encoding="utf-8")
        real_review._LAST_RECHECK = 0.0
        return real_review.active_service()

    def test_the_live_failure_is_not_hidden_by_the_last_successful_collection(self):
        after = self.break_the_config()
        # The last good service still serves, which is the point.
        self.assertEqual(after.model_binding(), self.service.model_binding())
        status = real_review.refresh_status()
        self.assertEqual(status["source"], "service")
        self.assertEqual(status["code"], real_review.CODE_SOURCE_DRIFT)
        self.assertNotEqual(status["code"], review_refresh.CODE_CONFIG_REPLACED)
        # And the page carries that code, not the old success.
        self.assertEqual(after.state_only_payload()["refresh"]["code"],
                         real_review.CODE_SOURCE_DRIFT)

    def test_restoring_the_config_clears_the_failure(self):
        """A fixed problem must stop being reported.

        The config the service was built from is put back byte for byte. That is
        the same comparison the re-read already makes, so the code has to be
        cleared on the same branch — otherwise an owner who fixed it is still told
        it is broken.
        """
        good = self.config_path.read_bytes()
        self.break_the_config()
        self.assertNotEqual(real_review.refresh_status()["code"],
                            review_refresh.CODE_CONFIG_REPLACED)
        self.config_path.write_bytes(good)
        real_review._LAST_RECHECK = 0.0
        after = real_review.active_service()
        self.assertEqual(after.model_binding(), self.service.model_binding())
        self.assertEqual(real_review.config_error(), "")
        self.assertEqual(real_review.refresh_status()["code"],
                         review_refresh.CODE_CONFIG_REPLACED)

    def test_a_fixed_config_is_picked_up_within_the_bounded_interval(self):
        """The whole point of the two second re-read, in one assertion."""
        good = self.config_path.read_bytes()
        self.assertEqual(real_review.RECHECK_SECONDS, 2.0)
        self.break_the_config()
        self.config_path.write_bytes(good)
        real_review._LAST_RECHECK = 0.0
        service = real_review.active_service()
        self.assertTrue(service.is_available())
        self.assertEqual(real_review.config_error(), "")


class RefreshStatusVisibilityTests(RefreshFixture):
    """A failed collection changes no config, so the screen needs to be told."""

    def test_the_state_the_page_reads_carries_the_collectors_code(self):
        self.seed_config()
        bundle = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root,
            build_snapshot([entry(1)]), build_master([master_row(1)]),
            review_refresh.build_review_csv(
                build_snapshot([entry(1)]), build_master([master_row(1)])))
        self.assertFalse(bundle["no_op"])
        service = real_review.RealReviewService(
            json.loads(self.config_path.read_text(encoding="utf-8")))
        # The app finds the status file through the same environment variable that
        # points it at the config, so the test points itself the same way.
        os.environ[real_review.CONFIG_ENV] = str(self.config_path)
        self.addCleanup(os.environ.pop, real_review.CONFIG_ENV, None)
        service.config_path = str(self.config_path)
        # Recorded the way the command records it, so the screen is reading a file
        # that exists and holds what a collection would have put there.
        import argparse

        cli._record(argparse.Namespace(config=str(self.config_path),
                                       bundle_root=str(self.bundle_root)),
                    review_refresh.CODE_CONFIG_REPLACED, bundle)
        state = service.state_only_payload()
        self.assertIn("refresh", state)
        self.assertEqual(state["refresh"]["source"], "collector")
        self.assertEqual(state["refresh"]["code"],
                         review_refresh.CODE_CONFIG_REPLACED)


class SignedAmountTests(RefreshFixture):
    """A signed amount and its sign are facts about the source, kept as they are.

    The coordinator's aggregate of the rows this task newly found: 28 in the
    2/8 layout and 6 in 1/7, nine of them at zero and twenty-five negative. A
    negative amount is how a cancellation or a refund is written in a ledger, and
    a zero is how a fully offset one is. Neither is a reason to drop a row, and
    neither is this module's to interpret: reading a negative as a cancellation
    would be a decision about money, and a row quietly removed would be a decision
    about the reviewer's work. Both stay, with the sign as the source wrote it and
    with no decision made.
    """

    def rows_for(self, amounts):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = SHEET
        for offset, label in enumerate(BLOCK_HEADER[:-1]):
            sheet.cell(row=4, column=1 + offset, value=label)
        sheet.cell(row=4, column=7, value=BLOCK_HEADER[-1])
        for offset, amount in enumerate(amounts):
            row = 5 + offset
            date = "2026-04-{:02d}".format(offset + 1)
            sheet.cell(row=row, column=1, value=date)
            sheet.cell(row=row, column=2, value="합성항목")
            sheet.cell(row=row, column=3, value="합성내용 {}".format(offset + 1))
            sheet.cell(row=row, column=7, value=amount)
        buffer = io.BytesIO()
        book.save(buffer)
        book.close()
        return buffer.getvalue()

    def test_a_zero_and_a_negative_amount_are_kept_with_their_sign(self):
        # The amounts sit on the rows the builder writes them on: 100001 on
        # 2026-04-01, -100001 on 2026-04-02 and 0 on 2026-04-03.
        master = build_master([("합성거래키-0001", "2026-04-02", -100001,
                               "합성이용점"),
                              ("합성거래키-0002", "2026-04-03", 0,
                               "합성이용점")])
        text = review_refresh.build_review_csv(
            self.rows_for([100001, -100001, 0]), master)
        import csv as _csv

        rows = list(_csv.reader(io.StringIO(text)))
        header = rows[0]
        records = [dict(zip(header, row)) for row in rows[1:]]
        self.assertEqual(len(records), 3)
        amounts = [record["source_amount"] for record in records]
        self.assertIn("-100001", amounts, "a negative amount was dropped or signed")
        self.assertIn("0", amounts, "a zero amount was dropped")

        # The negative row is a candidate when the master holds the same signed
        # amount, and nothing is decided either way.
        by_amount = {record["source_amount"]: record for record in records}
        negative = by_amount["-100001"]
        self.assertEqual(negative["disposition"], "candidate_review_required")
        self.assertEqual(json.loads(negative["candidate_transaction_keys"]),
                         ["합성거래키-0001"])
        self.assertEqual(negative["reviewer_decision"], "")
        self.assertEqual(negative["review_note"], "")

    def test_the_core_still_agrees_with_a_signed_amount(self):
        """The sign has to survive all the way through the existing core too.

        The core parses the amount and compares it with the value the review CSV
        carries, so a sign dropped anywhere on the way would be caught by it.
        """
        from webapp.contracts import sha256_bytes, sha256_text
        from webapp.review_csv_adapter import normalize_review_csv

        master = build_master([("합성거래키-0001", "2026-04-02", -100001,
                               "합성이용점")])
        snapshot = self.rows_for([100001, -100001])
        review_text = review_refresh.build_review_csv(snapshot, master)
        model = review_context.build_review_context(
            snapshot, review_text, master, sha256_bytes(snapshot),
            sha256_text(review_text), sha256_text(master))
        amounts = {row["source"]["amount"] for row in model["rows"]}
        self.assertIn("-100001", amounts)
        normalized = normalize_review_csv(review_text, sha256_bytes(snapshot))
        self.assertEqual(normalized["counts"],
                         {"approved": 0, "rejected": 0, "incomplete": 2})
        for row in model["rows"]:
            # No merchant, no trip and no classification is invented from a sign.
            self.assertEqual(row["source"]["merchant"],
                             review_context.MERCHANT_ABSENT)
            self.assertEqual(row["decision"], "")


class DigestStructureTests(RefreshFixture):
    """A digest must not be forgeable by a value that contains a separator."""

    def test_a_master_field_containing_the_separator_changes_the_digest(self):
        """Two masters differing only by a moved separator are different content.

        Joining fields with a pipe cannot tell a 가맹점 holding a pipe from a row
        split in two, so the digest is taken over a JSON array of arrays instead.
        """
        first = build_master([("합성거래키-0001", "2026-04-01", 100001,
                               "가맹점|나머지")])
        second = build_master([("합성거래키-0001", "2026-04-01", 100001,
                                "가맹점나머지")])
        self.assertNotEqual(review_refresh.master_semantic_digest(first),
                            review_refresh.master_semantic_digest(second))

    def test_a_cell_containing_a_tab_or_newline_changes_the_workbook_digest(self):
        from openpyxl import Workbook

        def with_value(value):
            book = Workbook()
            sheet = book.active
            sheet.title = SHEET
            for offset, label in enumerate(BLOCK_HEADER[:-1]):
                sheet.cell(row=4, column=1 + offset, value=label)
            sheet.cell(row=4, column=7, value=BLOCK_HEADER[-1])
            date, item, description, amount = entry(1)
            sheet.cell(row=5, column=1, value=date)
            sheet.cell(row=5, column=3, value=value)
            sheet.cell(row=5, column=7, value=amount)
            buffer = io.BytesIO()
            book.save(buffer)
            book.close()
            return buffer.getvalue()

        plain = review_refresh.content_digest(with_value("내용"))
        for value in ("내용\t표", "내용\n줄", "내용|표"):
            with self.subTest(value=value):
                self.assertNotEqual(plain,
                                    review_refresh.content_digest(
                                        with_value(value)))


class ActivationVerificationTests(RefreshFixture):
    """Nothing is activated on the strength of a digest written earlier."""

    def staged(self, entries, master):
        self.seed_config()
        return review_refresh.collect(self.config_path, self.bundle_root,
                                       build_snapshot(entries), master)

    def test_a_bundle_whose_file_was_touched_after_staging_is_not_activated(self):
        """The digests were true at staging time and are not evidence now.

        A bundle is staged and activated as separate moments. If a file in
        between changed on disk, the config would then name a source that does not
        hash to what the config says, and the app would serve a drifted bundle
        under a binding that claims otherwise.
        """
        master = build_master([master_row(1)])
        bundle = self.staged([entry(1)], master)
        pathlib.Path(bundle["master_path"]).write_text(
            build_master([master_row(1), ("합성거래키-0002", "2026-04-02",
                                          100002, "합성이용점")]),
            encoding="utf-8")
        with self.assertRaises(review_refresh.RefreshError) as caught:
            review_refresh.activate(self.config_path, bundle)
        self.assertEqual(caught.exception.code,
                         review_refresh.CODE_BUNDLE_WRITE_FAILED)

    def test_activating_over_a_config_another_collector_replaced_is_refused(self):
        """The compare-and-swap: an older bundle must not overwrite a newer one.

        Two collectors, one lock at a time. The second activates while the first
        one's bundle is still staged, and the first must find that the config is
        no longer the one it read, and refuse rather than put its older source
        back over the newer one.
        """
        master = build_master([master_row(1), master_row(2)])
        older = self.staged([entry(1)], master)
        newer = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, build_snapshot([entry(2)]),
            master, review_refresh.build_review_csv(
                build_snapshot([entry(2)]), master))
        self.assertFalse(newer["no_op"])
        live = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(live["snapshot_sha256"], newer["snapshot_sha256"])

        # The other collector's activation happened after this bundle was staged.
        older["expected_base_config_sha256"] = "0" * 64
        with self.assertRaises(review_refresh.RefreshError) as caught:
            review_refresh.activate(self.config_path, older)
        self.assertEqual(caught.exception.code,
                         review_refresh.CODE_BASE_CONFIG_CHANGED)
        # And the live source is still the newer one.
        self.assertEqual(
            json.loads(self.config_path.read_text(encoding="utf-8"))[
                "snapshot_sha256"], newer["snapshot_sha256"])

    def test_a_no_op_needs_the_active_inputs_to_be_intact(self):
        """A marker alone is not proof that the live source still is what it was.

        If the active workbook were truncated in place, its content marker would
        still match the newly collected one and the collector would report a
        successful no-op while the app serves a source nobody verified.
        """
        entries = [entry(1)]
        master = build_master([master_row(1)])
        self.seed_config()
        previous = review_refresh.build_review_csv(build_snapshot(entries),
                                                  master)
        first = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, build_snapshot(entries),
            master, previous)
        self.assertFalse(first["no_op"])
        self.assertTrue(first.get("activated"))

        # Corrupt the active workbook in place: the marker still says the content
        # is what it was, and the config's digest no longer matches the file.
        pathlib.Path(first["snapshot_path"]).write_bytes(b"PK-not-a-workbook")
        second = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root,
            repack(build_snapshot(entries)), master, previous)
        self.assertFalse(second["no_op"], "a corrupted active source was a no-op")




@unittest.skipUnless(os.name == "nt", "Windows config permissions")
class ConfigPermissionReplacementTests(unittest.TestCase):
    def test_atomic_replacement_preserves_explicit_dacl(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "config.json"
            replacement = pathlib.Path(directory) / "config.new"
            target.write_text("old", encoding="utf-8")
            replacement.write_text("new", encoding="utf-8")
            command = r"""
$p = $env:COST_TEST_CONFIG
$a = Get-Acl -LiteralPath $p
$a.SetAccessRuleProtection($true, $false)
$s = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$r = [System.Security.AccessControl.FileSystemAccessRule]::new($s, 'FullControl', 'Allow')
$a.AddAccessRule($r)
Set-Acl -LiteralPath $p -AclObject $a
(Get-Acl -LiteralPath $p).GetSecurityDescriptorSddlForm('Access')
"""
            environment = dict(os.environ, COST_TEST_CONFIG=str(target))
            before = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-Command", command],
                env=environment, text=True).strip()
            review_refresh._replace_config_file(replacement, target)
            after = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-Command",
                 "(Get-Acl -LiteralPath $env:COST_TEST_CONFIG).GetSecurityDescriptorSddlForm('Access')"],
                env=environment, text=True).strip()
            self.assertEqual(before, after)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(replacement.exists())
            self.assertEqual(list(pathlib.Path(directory).glob("*.backup")), [])

    def test_failed_replacement_keeps_original_config(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "config.json"
            target.write_text("original", encoding="utf-8")
            with self.assertRaises(OSError):
                review_refresh._replace_config_file(
                    pathlib.Path(directory) / "missing.new", target)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
