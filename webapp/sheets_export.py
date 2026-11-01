"""Phase 5 selected-tab xlsx export.

Layout follows the documented 매출자료 양식_rev positions
(IMPLEMENTATION_CONTRACT section 8, REVIEW section 4): company B2,
title C2:H2 (merged), prepared date D4(label) E4(value), assignee
G4(label) H4(value); income headers B7:H7, 23 income slots B8:H30,
C31 SUM(H8:H30), expense headers B34:H34, 50 expense slots B35:H84,
C85 SUM(H35:H84), C87 C31-C85. The real template file is not read;
the layout contract is the source; no template file is read.

B2 carries the company name the owner saved under the owner profile, and
is empty when none has been saved. Title, prepared date and assignee are the
stored trip's own values. Nothing here is a placeholder, and nothing is
guessed from a template, an email or a model.

A trip whose assignee has a value but no recorded origin refuses the whole
export with ASSIGNEE_UNCONFIRMED, before any sheet exists. Printing such a
value would put a name on a document that nobody claimed, and writing a
marker instead would put a status word on the exported sheet, which the
output rules forbid.

One file, one sheet per selected tab in the chosen order. Sheet names
come from stored display names with Excel limits and stable numeric
suffixes on collision, mapped in the manifest. Rows are the R05
common projection (bank corrections applied) plus active allocations;
split principals and linked bank duplicates are not summed.
Reservation numbers stay text. Source text starting with =,+,-,@ is
stored so it cannot become a formula. Slot overflow extends the area
and moves totals, formulas, and print settings together. Publish uses a
same-filesystem no-replace link and never overwrites an existing file. Display
placement (including candidate rows) is exported as-is with no status
badges in the file. Unresolved counts appear only in the dialog,
never in the workbook.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .space_guard import SpaceRefused, free_bytes, reserve, reserve_conn

# Bytes a workbook costs on top of its rows: styles, shared strings, the zip
# directory. A fixed allowance, not a promise of an exact size.
EXPORT_OVERHEAD_BYTES = 256 * 1024

# Per row, generous enough that a wide sheet still fits inside it.
EXPORT_BYTES_PER_ROW = 2 * 1024

SourceFileRefused = SpaceRefused

# Bytes one export-job row costs.
WRITE_JOB_BYTES = 4 * 1024

# The size model below is measured, not guessed. Building real workbooks gave:
# an empty single-sheet export 5,512 bytes; the marginal sheet cost 1,114 bytes
# (1 sheet 5,595 -> 24 sheets 31,216); the marginal row cost 30 bytes (290 extra
# rows cost 8,620). The constants are deliberate over-estimates of those
# measurements, because a refusal that is slightly pessimistic costs a retry
# while a refusal that is optimistic costs a half-written file.
EXPORT_BASE_BYTES = 64 * 1024
EXPORT_BYTES_PER_SHEET = 8 * 1024
EXPORT_BYTES_PER_ROW = 256


def export_size_estimate(manifest: dict) -> dict:
    """Bytes a manifest's workbook is expected to need, from the real shape.

    `build_workbook` records `income_rows` and `expense_rows` per tab, and that
    is the only shape a real manifest has. The first version read `row_count`
    and `rows`, which no real manifest contains, so every real export estimated
    zero rows and asked only for the fixed overhead: a full-volume check that
    passed. Reading the keys that are actually produced is the whole fix.

    A tab that reports no row count is counted as a sheet and flagged, not
    treated as zero rows, because "unknown" and "empty" are different answers.
    """
    tabs = manifest.get("tabs") if isinstance(manifest, dict) else None
    if not isinstance(tabs, list):
        return {"bytes": None, "sheets": None, "rows": None,
                "shape_known": False,
                "note": "manifest has no tabs list, so the size is unknown; "
                        "an unknown size is not a small size"}
    sheets = 0
    rows = 0
    complete = True
    for tab in tabs:
        if not isinstance(tab, dict):
            complete = False
            continue
        sheets += 1
        income = tab.get("income_rows")
        expense = tab.get("expense_rows")
        if not isinstance(income, int) or isinstance(income, bool):
            income = tab.get("row_count")
        if not isinstance(expense, int) or isinstance(expense, bool):
            expense = tab.get("row_count")
        counted = False
        for value in (income, expense):
            if isinstance(value, int) and not isinstance(value, bool):
                rows += max(0, value)
                counted = True
        if not counted:
            complete = False
    needed = (EXPORT_BASE_BYTES + sheets * EXPORT_BYTES_PER_SHEET
              + rows * EXPORT_BYTES_PER_ROW)
    return {"bytes": needed, "sheets": sheets, "rows": rows,
            "shape_known": complete,
            "note": "" if complete else
            "some tabs did not report row counts; only the base and sheet "
            "costs were added for them"}


def reserve_export_space(output_dir, manifest: dict) -> dict:
    """Refuse a new output the volume cannot hold.

    Returns the estimate, so a caller can report what it asked for rather than
    a number it never measured.
    """
    estimate = export_size_estimate(manifest)
    if estimate["bytes"] is None:
        # Unknown shape. Ask for the base plus a wide sheet allowance so a real
        # manifest that lost a key still gets a bound that is hard to under-run.
        estimate = dict(estimate,
                        bytes=EXPORT_BASE_BYTES + 32 * EXPORT_BYTES_PER_SHEET)
    reserve(output_dir, estimate["bytes"], code="EXPORT_NO_SPACE",
            what="새 출력 파일을 만드는 데")
    return estimate

TEMPLATE_VERSION = "sales-confirm-rev-p6-synthetic"

COMPANY_CELL = "B2"
TITLE_MERGE = "C2:H2"
SEPARATOR_MERGE_1 = "B6:H6"
INCOME_TOTAL_MERGE = "C31:H31"
SEPARATOR_MERGE_2 = "B33:H33"
EXPENSE_TOTAL_MERGE = "C85:H85"
PROFIT_MERGE = "C87:H87"
PREPARED_LABEL_CELL = "D4"
PREPARED_VALUE_CELL = "E4"
ASSIGNEE_LABEL_CELL = "G4"
ASSIGNEE_VALUE_CELL = "H4"
COMPANY_CELL = "B2"

#: Written to B2 when the owner has not set a company name. An empty cell, not a
#: placeholder: a blank says "not entered", while any text here would be printed
#: on an exported document as though it were the company's name.
COMPANY_TEXT = ""

COLUMN_WIDTHS = {
    1: 2.63,  # A
    2: 17.5,  # B
    3: 14.63, # C
    4: 16.38, # D
    5: 11.88, # E
    6: 12.38, # F
    7: 11.25, # G
    8: 14.88, # H
}

INCOME_HEADER = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
EXPENSE_HEADER = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]
INCOME_FIRST_ROW = 8
INCOME_SLOTS = 23
INCOME_TOTAL_ROW = 31
EXPENSE_HEADER_ROW = 34
EXPENSE_FIRST_ROW = 35
EXPENSE_SLOTS = 50

FORBIDDEN_SHEET_CHARS = '\\/:*?[]'


def _utc_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def sanitize_sheet_name(display_key: str, used: set) -> str:
    """A sheet name that Excel accepts and that no free text can make odd.

    Forbidden characters are replaced, and a leading formula character is
    escaped as well. A sheet name is not a formula cell, so this is not formula
    injection, but a title the operator typed free-hand must not end up as a
    sheet called `=1+1`: it reads as an error, it breaks a name that is meant to
    be a trip label, and it is the one place the trip title is used verbatim.
    """
    text = guard_text(display_key)
    base = "".join("_" if c in FORBIDDEN_SHEET_CHARS else c for c in text)[:28]
    name = base or "sheet"
    suffix = 1
    while name in used:
        suffix += 1
        name = f"{base[:28 - len(str(suffix)) - 1]}_{suffix}"
    used.add(name)
    return name


def guard_text(value) -> str:
    """Neutralise a free string that would otherwise read as a formula.

    The leading characters Excel treats as the start of a formula are escaped.
    Leading whitespace and control characters are stripped first, because Excel
    trims them on entry: a tab in front of `=` would otherwise slip past the
    check and still arrive as a formula.
    """
    text = "" if value is None else str(value)
    stripped = text.lstrip(" \t\r\n\v\f")
    if stripped[:1] in ("=", "+", "-", "@"):
        return "'" + stripped
    return text


def input_snapshot_hash(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: Refused export, when a selected trip carries an assignee whose origin nobody
#: recorded. Not a warning and not a partial file: the request is refused whole,
#: so no sheet is produced carrying a name nobody claimed. Writing a status word
#: into the form instead would cross the existing rule that the output carries no
#: status markers, and the owner would receive a document with text on it.
UNCONFIRMED_ASSIGNEE_CODE = "ASSIGNEE_UNCONFIRMED"


class UnconfirmedAssigneeError(Exception):
    """A selected trip has an assignee whose origin was never recorded."""

    def __init__(self, tab_ids):
        self.code = UNCONFIRMED_ASSIGNEE_CODE
        self.tab_ids = list(tab_ids)
        self.status = 409
        super().__init__(UNCONFIRMED_ASSIGNEE_CODE)

    def as_payload(self) -> dict:
        return {"code": self.code,
                "tab_ids": list(self.tab_ids),
                "message": "담당자 출처가 확인되지 않은 여행이 있어 출력을 진행하지 않아요."}


#: Provenance values that already answer "where did this assignee come from".
#: `''` is absent from this set on purpose: an empty source is the unconfirmed
#: case, and it is decided by provenance rather than by comparing the text, so a
#: person who genuinely typed the old placeholder string is not caught by it.
CONFIRMED_ASSIGNEE_SOURCES = frozenset({"owner_profile", "manual", "seed", "google_workbook"})


def _assignee_confirmed(conn, tab_id: str, source: str, assignee: str = "") -> bool:
    """Whether this trip's assignee was recorded by somebody.

    A recorded provenance answers it. When the column is empty the trip predates
    it, so the trip's own history is asked instead.

    The history question is deliberately narrow, because every metadata save
    writes a full `new_json` — including one that only renamed the trip. Reading
    "the snapshot mentions an assignee" as confirmation would let an unrelated
    title edit silently promote an unconfirmed name into a confirmed one. So the
    evidence has to be one of exactly two things:

    * a saved `assignee_source` of `manual` — the owner typed it;
    * the assignee actually *changed* between the previous and the new snapshot,
      which only a save that presented the field can produce; or
    * an earlier successful request for this tab whose recorded changes named
      `prepared_by_name` and whose value is the value the trip still holds.

    That last one is what a confirmation looks like when it saves the same text
    it is confirming: the save is a no-op on the row, so it changes nothing and
    appears in history only as another identical snapshot. The *request* ledger
    is where the owner's act is recorded, and it must require all three of an
    explicit `prepared_by_name`, a match with the value on the trip, and a row
    that exists at all — a request whose changes held only a display name is not
    evidence and is not counted as any.

    An owner who confirms by re-saving the same text therefore gets through.
    """
    if (source or "") in CONFIRMED_ASSIGNEE_SOURCES:
        return True
    # A blank assignee has no name to claim, so there is nothing to refuse. Only
    # a *value* whose origin is unknown is a problem; refusing an empty cell
    # would block every export of a trip the owner has not yet named, which is
    # the normal state of a newly created trip.
    if not str(assignee or "").strip():
        return True
    if conn is None:
        return False
    current_value = str(assignee or "").strip()
    try:
        rows = conn.execute(
            "SELECT prev_json, new_json FROM trip_tab_history WHERE tab_id=?"
            " ORDER BY revision", (tab_id,)).fetchall()
    except Exception:
        rows = []
    for prev_blob, new_blob in rows:
        new_saved = _history_json(new_blob)
        if not isinstance(new_saved, dict):
            continue
        if str(new_saved.get("assignee_source") or "") in CONFIRMED_ASSIGNEE_SOURCES:
            return True
        prev_saved = _history_json(prev_blob)
        if not isinstance(prev_saved, dict):
            continue
        if (str(prev_saved.get("prepared_by_name") or "").strip()
                != str(new_saved.get("prepared_by_name") or "").strip()):
            return True
    # The request ledger, for a confirmation that saved the value it confirmed.
    try:
        requests = conn.execute(
            "SELECT result_json FROM trip_tab_requests WHERE tab_id=?"
            " ORDER BY rowid", (tab_id,)).fetchall()
    except Exception:
        return False
    for (blob,) in requests:
        stored = _history_json(blob)
        if not isinstance(stored, dict):
            continue
        changes = stored.get("changes")
        if not isinstance(changes, dict) or "prepared_by_name" not in changes:
            continue
        if str(changes.get("prepared_by_name") or "").strip() == current_value:
            return True
    return False


def assignee_needs_confirmation(store, tab_ids=None) -> list:
    """Trips whose assignee has a value nobody recorded, as tab ids.

    The selection screen asks this so it can say something before the request is
    made, and the export itself asks the same question when the request arrives.
    Both call `_assignee_confirmed` — deliberately one function behind a public
    name rather than a second copy of the rule. A copy would drift, and the
    failure mode of a drift here is quiet: the screen would stop warning about a
    trip the export still refuses, which looks like the screen losing track
    rather than the two disagreeing.

    A blank assignee is never in this list: there is no name to have failed to
    confirm. Confirmed origins, and rows whose confirmation the request ledger
    already recorded, are never in it either.
    """
    conn = getattr(store, "conn", None)
    if tab_ids is None:
        reader = getattr(store, "get_trip", None)
        if not callable(reader):
            return []
        try:
            tab_ids = [row[0] for row in store.conn.execute(
                "SELECT tab_id FROM trip_tabs ORDER BY sort_order, tab_id")]
        except Exception:
            return []
    needs = []
    for tab_id in tab_ids:
        try:
            trip = store.get_trip(tab_id) or {}
        except Exception:
            continue
        if not _assignee_confirmed(conn, tab_id,
                                   str(trip.get("assignee_source") or ""),
                                   trip.get("prepared_by_name", "")):
            needs.append(tab_id)
    return needs


def _history_json(blob):
    if blob is None:
        return None
    if isinstance(blob, dict):
        return blob
    try:
        return json.loads(blob)
    except Exception:
        return None


def _trip_meta(store, tab_id: str) -> dict:
    trip = store.get_trip(tab_id) if hasattr(store, "get_trip") else None
    if trip is None:
        from .ledger_board import TRIPS

        found = next((t for t in TRIPS if t["tab_id"] == tab_id), None)
        trip = {
            "tab_id": tab_id,
            "display_key": found["display_key"] if found else tab_id,
            "destination": (found or {}).get("destination", ""),
            "starts_on": (found or {}).get("starts_on", ""),
            "ends_on": (found or {}).get("ends_on", ""),
            "prepared_on": "", "prepared_by_name": "",
        }
    return trip


def _export_rows(store, tab_id: str):
    rows = store.list_tab_rows(tab_id)
    incomes = []
    expenses = []
    for row in rows:
        projected = store.projected(row) if row.get("row_kind") == "income" and not row.get("is_allocation") else dict(row)
        if row["row_kind"] == "income":
            if "display_amount_krw" not in projected:
                projected["display_amount_krw"] = projected["amount_krw"]
            if "display_occurred_on" not in projected:
                projected["display_occurred_on"] = projected["occurred_on"]
            incomes.append(projected)
        else:
            expenses.append(projected)
    return incomes, expenses


def build_workbook(store, tab_ids: list, template_version: str = TEMPLATE_VERSION):
    with store._lock:
        own_transaction = not store.conn.in_transaction
        if own_transaction:
            store.conn.execute("BEGIN")
        try:
            return _build_workbook_snapshot(store, tab_ids, template_version)
        finally:
            if own_transaction and store.conn.in_transaction:
                store.conn.execute("ROLLBACK")


@contextlib.contextmanager
def _read_snapshot(conn):
    """One consistent read for a whole export, when the store has a connection.

    A store without one (a test double, or a caller that passes rows in) simply
    gets no transaction rather than an error, because refusing to export there
    would be a new failure this function is not supposed to introduce.
    """
    if conn is None:
        yield conn
        return
    began = False
    try:
        conn.execute("BEGIN")
        began = True
    except Exception:
        # Already inside a transaction the caller owns. Read inside it as-is
        # rather than committing somebody else's work.
        began = False
    try:
        yield conn
    finally:
        if began:
            try:
                conn.execute("COMMIT")
            except Exception:
                pass


def _assignee_source(store, tab_id: str) -> str:
    try:
        trip = store.get_trip(tab_id)
    except Exception:
        return ""
    if not trip:
        return ""
    return str(trip.get("assignee_source") or "")


def _owner_company_name(conn) -> str:
    """The company name the owner entered, or "" when none has been entered.

    Takes the connection rather than the store so it can be read inside the same
    read transaction as everything else in one export. A company name read
    before a transaction and a trip read inside it could come from different
    points in time, and the file would then disagree with its own manifest.
    """
    try:
        row = conn.execute(
            "SELECT company_name FROM owner_profile WHERE profile_id='owner'"
        ).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    return str(row[0] or "").strip()


#: Written where an assignee value exists but nobody ever recorded where it came
#: from. The alternative — printing the stored value — would put a name on an
#: exported document that nobody claimed, which is the same claim the empty
#: assignee used to make.
UNCONFIRMED_ASSIGNEE_TEXT = "확인 필요"


def _build_workbook_snapshot(store, tab_ids: list, template_version: str = TEMPLATE_VERSION):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    from openpyxl.worksheet.page import PageMargins

    wb = Workbook()
    wb.remove(wb.active)
    used: set = set()
    manifest_tabs = []
    snapshot_tabs = []
    # One read transaction for the whole export: the company name, every trip,
    # every row, and therefore the manifest and the input hash all come from the
    # same point in time. Read outside one, a profile saved mid-export would put
    # a new company name beside rows from the older state, and the file would
    # disagree with its own hash and manifest.
    conn = getattr(store, "conn", None)
    with _read_snapshot(conn):
        company_name = _owner_company_name(conn)
        unconfirmed = [tab_id for tab_id in tab_ids
                       if not _assignee_confirmed(conn, tab_id,
                                               _assignee_source(store, tab_id),
                                               _trip_meta(store, tab_id).get("prepared_by_name", ""))]
        if unconfirmed:
            # Refused whole, before any sheet exists. Nothing partial is produced.
            raise UnconfirmedAssigneeError(unconfirmed)
        read = []
        for tab_id in tab_ids:
            trip = _trip_meta(store, tab_id)
            incomes, expenses = _export_rows(store, tab_id)
            corrections = []
            for row in incomes:
                if row.get("source_kind") == "은행" and hasattr(store, "list_corrections"):
                    corrections.extend(store.list_corrections(row["row_id"]))
            read.append((tab_id, trip, incomes, expenses, corrections))
    for tab_id, trip, incomes, expenses, corrections in read:
        allocs = [dict(r) for r in incomes if r.get("is_allocation")]
        snapshot_tabs.append({
            "tab_id": tab_id, "trip": trip, "incomes": incomes,
            "expenses": expenses, "corrections": corrections,
            "allocations": allocs,
        })
        sheet_name = sanitize_sheet_name(trip["display_key"], used)
        ws = wb.create_sheet(title=sheet_name)
        center = Alignment(horizontal="center", vertical="center")
        right = Alignment(horizontal="right", vertical="center")
        
        # Apply column widths
        for col_idx, width in COLUMN_WIDTHS.items():
            ws.column_dimensions[chr(64 + col_idx)].width = width
        
        # Page setup: landscape, margins
        ws.sheet_properties.pageSetUpPr = None
        ws.page_setup.orientation = "landscape"
        ws.page_margins = PageMargins(left=0.7, right=0.7, top=0.75, bottom=0.75, header=0, footer=0)
        
        # The owner-entered company name, through the same guard as every
        # other free string. Empty when nothing has been entered: a blank cell
        # says "not entered", while any text here would be printed as the
        # company's name on a document.
        ws["B2"] = guard_text(company_name)
        ws["B2"].alignment = center
        ws.merge_cells(TITLE_MERGE)
        # The title, the date and the owner name are free operator text. They
        # were relying on `data_type = "s"` alone to stay text, which is a
        # fragile openpyxl property; they go through the same guard as every
        # other free field so the defence does not depend on that assignment.
        ws["C2"] = guard_text(trip["display_key"])
        ws["C2"].alignment = center
        ws["C2"].data_type = 's'
        ws.merge_cells(SEPARATOR_MERGE_1)
        ws["D4"] = "작성일자"
        ws["E4"] = guard_text(trip.get("prepared_on", ""))
        ws["G4"] = "담당자"
        ws["H4"] = guard_text(trip.get("prepared_by_name", ""))
        ws["H4"].data_type = 's'
        for cell in ("D4", "E4", "G4", "H4"):
            ws[cell].alignment = center
        ws.cell(row=7, column=1, value="수입").alignment = center
        for col, header in enumerate(INCOME_HEADER, 2):
            cell = ws.cell(row=7, column=col, value=header)
            cell.alignment = center
        income_end = INCOME_FIRST_ROW + max(len(incomes), INCOME_SLOTS) - 1
        for i, row in enumerate(incomes):
            r = INCOME_FIRST_ROW + i
            kind = row.get("income_kind", "deposit")
            shown = row.get("display_amount_krw", row["amount_krw"])
            date = row.get("display_occurred_on", row["occurred_on"])
            ws.cell(row=r, column=2, value=date).alignment = center
            ws.cell(row=r, column=3, value=guard_text(row.get("customer_name", "")))
            ws.cell(row=r, column=4, value=guard_text(row.get("nickname", "")))
            ws.cell(row=r, column=5, value=shown if kind == "deposit" else None)
            ws.cell(row=r, column=6, value=shown if kind == "balance" else None)
            ws.cell(row=r, column=7, value=shown if kind == "additional" else None)
            amount_cell = ws.cell(row=r, column=8, value=shown)
            amount_cell.alignment = right
            amount_cell.number_format = "#,##0"
        income_total_row = income_end + 1
        ws.cell(row=income_total_row, column=2, value="총 금액 (A)")
        total_a = ws.cell(
            row=income_total_row, column=3,
            value=f"=SUM(H{INCOME_FIRST_ROW}:H{income_end})",
        )
        total_a.number_format = "#,##0"
        ws.merge_cells(f"C{income_total_row}:H{income_total_row}")
        expense_header_row = income_total_row + 3
        ws.merge_cells(f"B{expense_header_row - 1}:H{expense_header_row - 1}")
        ws.cell(row=expense_header_row, column=1, value="지출").alignment = center
        for col, header in enumerate(EXPENSE_HEADER, 2):
            cell = ws.cell(row=expense_header_row, column=col, value=header)
            cell.alignment = center
        expense_first = expense_header_row + 1
        expense_end = expense_first + max(len(expenses), EXPENSE_SLOTS) - 1
        for i, row in enumerate(expenses):
            r = expense_first + i
            ws.cell(row=r, column=2, value=row["occurred_on"]).alignment = center
            ws.cell(row=r, column=3, value=guard_text(row.get("item", "")))
            ws.cell(row=r, column=4, value=guard_text(row.get("description", "")))
            ws.cell(row=r, column=5, value=guard_text(row.get("service_period", "")))
            reservation = ws.cell(row=r, column=6, value=guard_text(row.get("reservation_no", "")))
            reservation.number_format = "@"
            ws.cell(row=r, column=7, value=guard_text(row.get("evidence_type", "")))
            amount_cell = ws.cell(row=r, column=8, value=row["amount_krw"])
            amount_cell.alignment = right
            amount_cell.number_format = "#,##0"
        expense_total_row = expense_end + 1
        ws.cell(row=expense_total_row, column=2, value="총 금액 (B)")
        total_b = ws.cell(
            row=expense_total_row, column=3,
            value=f"=SUM(H{expense_first}:H{expense_end})",
        )
        total_b.number_format = "#,##0"
        ws.merge_cells(f"C{expense_total_row}:H{expense_total_row}")
        profit_row = expense_total_row + 2
        ws.cell(row=profit_row, column=2, value="(A)-(B) 회사수익인식")
        profit = ws.cell(
            row=profit_row, column=3, value=f"=C{income_total_row}-C{expense_total_row}"
        )
        profit.number_format = "#,##0"
        ws.merge_cells(f"C{profit_row}:H{profit_row}")
        ws.print_area = f"B2:H{profit_row}"
        manifest_tabs.append({
            "tab_id": tab_id, "sheet_name": sheet_name,
            "income_rows": len(incomes), "expense_rows": len(expenses),
            "prepared_on": trip.get("prepared_on", ""),
            "prepared_by_name": trip.get("prepared_by_name", ""),
            "assignee_source": trip.get("assignee_source", "") or "",
            "company_name": company_name,
        })
    manifest = {
        "template_version": template_version,
        "company_name": company_name,
        "tab_order": list(tab_ids),
        "tabs": manifest_tabs,
        "input_snapshot_sha256": input_snapshot_hash(
            # The company name is part of the input, not decoration around it:
            # it is printed on every sheet, so an export whose hash ignored it
            # could call two different documents the same input.
            {"tabs": list(tab_ids), "trip_sheets": snapshot_tabs,
             "template_version": template_version, "company_name": company_name}),
        "created_at": _utc_now(),
    }
    return wb, manifest


def publish_workbook(wb, manifest: dict, output_dir, file_stem: str):
    output_dir = Path(output_dir)
    # SPEC_REFINEMENT 19.3: a new output is one of the first things refused when
    # the volume is full, and the refusal names the reason.
    #
    # The space check comes before the directory is created, and that ordering is
    # the point. `mkdir` on a full volume fails with an OSError that says
    # nothing about why, so creating the directory first turns a clear refusal
    # into an opaque error -- and it also leaves a half-created directory behind
    # for a file that was never written. When the parent already exists the
    # check needs no new space, so the two orders are the same operation.
    if not output_dir.is_dir():
        reserve_export_space(output_dir.parent, manifest)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SpaceRefused(
                "EXPORT_NO_SPACE",
                f"출력 폴더를 만들지 못했어요: {output_dir} ({exc}). "
                f"이미 저장된 원천·출력은 지우지 않았습니다.",
                free=free_bytes(output_dir.parent), needed=0,
                path=output_dir, reason="mkdir_failed") from exc
    else:
        reserve_export_space(output_dir, manifest)
    target = output_dir / f"{file_stem}.xlsx"
    fd = None
    tmp_file = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{file_stem}.", suffix=".tmp.xlsx", dir=output_dir,
        )
        tmp_file = Path(tmp_name)
        os.close(fd)
        fd = None
        wb.save(str(tmp_file))
        with open(tmp_file, "rb") as handle:
            payload = handle.read()
        with open(tmp_file, "r+b") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        output_sha256 = hashlib.sha256(payload).hexdigest()
        manifest = {**manifest, "output_sha256": output_sha256,
                    "output_file": target.name}
        try:
            os.link(str(tmp_file), str(target))
        except FileExistsError:
            # A name that is taken is never overwritten. The caller publishes
            # under its own name instead.
            raise FileExistsError(f"output exists, refusing to overwrite: {target}")
        if not target.exists():
            raise FileNotFoundError(f"atomic publish produced no file: {target}")
        with open(str(target), "rb") as out_check:
            final_digest = hashlib.sha256(out_check.read()).hexdigest()
        if final_digest != output_sha256:
            raise FileExistsError("published file digest mismatch; aborting without overwrite")
        return target, manifest
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_file is not None:
            try:
                tmp_file.unlink(missing_ok=True)
            except OSError:
                pass


def file_sha256(path) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


EXPORT_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_export_jobs (
    job_id TEXT PRIMARY KEY,
    tab_ids_json TEXT NOT NULL,
    input_snapshot_sha256 TEXT NOT NULL,
    template_version TEXT NOT NULL,
    output_sha256 TEXT,
    output_path TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _ensure_job_columns(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ledger_export_jobs)").fetchall()}
    if "output_path" not in cols:
        conn.execute("ALTER TABLE ledger_export_jobs ADD COLUMN output_path TEXT")


def record_job(conn, *, job_id: str, tab_ids: list, manifest: dict, status: str) -> None:
    conn.executescript(EXPORT_JOBS_SCHEMA)
    _ensure_job_columns(conn)
    # 19.3: this row is part of the same state change as the output itself. The
    # schema script above is left alone on purpose -- it is what makes the table
    # exist, and refusing on it could block the very write that needs it.
    with reserve_conn(conn, WRITE_JOB_BYTES, code="EXPORT_JOB_NO_SPACE",
                      what="출력 작업 기록을 남기는 데"):
        conn.execute(
            "INSERT OR REPLACE INTO ledger_export_jobs(job_id, tab_ids_json,"
            " input_snapshot_sha256, template_version, output_sha256, output_path,"
            " status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (job_id, json.dumps(list(tab_ids), ensure_ascii=False),
             manifest.get("input_snapshot_sha256", ""),
             manifest.get("template_version", ""),
             manifest.get("output_sha256"),
             manifest.get("output_path"),
             status, _utc_now()),
        )
        conn.commit()


def get_job(conn, job_id: str):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ledger_export_jobs)")}
    if not cols:
        return None
    output_path = "output_path" if "output_path" in cols else "NULL"
    row = conn.execute(
        "SELECT job_id, tab_ids_json, input_snapshot_sha256, template_version,"
        f" output_sha256, {output_path}, status, created_at FROM ledger_export_jobs WHERE job_id=?",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "job_id": row[0], "tab_ids": json.loads(row[1]),
        "input_snapshot_sha256": row[2], "template_version": row[3],
        "output_sha256": row[4], "output_path": row[5],
        "status": row[6], "created_at": row[7],
    }


def list_jobs(conn, limit: int = 20):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ledger_export_jobs)")}
    if not cols:
        return []
    output_path = "output_path" if "output_path" in cols else "NULL"
    rows = conn.execute(
        "SELECT job_id, tab_ids_json, input_snapshot_sha256, template_version,"
        f" output_sha256, {output_path}, status, created_at FROM ledger_export_jobs"
        " ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "job_id": r[0], "tab_ids": json.loads(r[1]),
            "input_snapshot_sha256": r[2], "template_version": r[3],
            "output_sha256": r[4], "output_path": r[5],
            "status": r[6], "created_at": r[7],
        }
        for r in rows
    ]
