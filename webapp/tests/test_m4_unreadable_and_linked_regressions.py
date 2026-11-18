"""Independent-review regressions: F1 (unreadable amount renders) and F2 (R06).

Two defects found by the independent review on 2026-11-19:

F1 — an unreadable Google income amount (``amount_krw=None``) reached the legacy
``_table_html`` / ``_mobile_html`` renderers and raised ``TypeError`` from
``int(None)``, so the whole trip board answered 500. SPEC §11.2.1 계약 4 /
GGL-014 requires the state be *shown* (미확인) and never raised or shown as 0원.

F2 — a bank source row linked as evidence to a direct income (R06) was summed as
a second income by the shared ``display_totals``/``trip_summary`` and by the
legacy non-trip summary, so React/the viewer rail said 2,000,000 while the
baseline (``store.tab_totals``) and the legacy KPI said 1,000,000.

Synthetic store only; no production access, no Google write.
"""
from __future__ import annotations

import re

import pytest

from webapp import ledger_design, ledger_query, ledger_store as ledger_store_mod
from webapp.ledger_store import LedgerStore


BANK_KEY_HEAD = "abc123evidencekey000"


def _google_unknown_row(tab: str = "t") -> dict:
    """A Google income row exactly as ``plush_income.load`` builds an unknown one."""
    return dict(
        row_id=f"google-income|{tab}|main|6", row_kind="income",
        display_tab_id=tab, occurred_on="2026-11-11", customer_name="합성",
        description="", amount_krw=None, google_income=True,
        amount_missing=True, source_event_id="main:x:6", source_kind="Google",
        evidence_type="Google 수입 장부", revision=1,
    )


# --------------------------------------------------------------------------- F1

def test_legacy_table_renders_an_unreadable_google_amount_as_mi확인():
    """F1: the table must not raise and must print 미확인 on the row, never 0원."""
    row = _google_unknown_row()
    html = ledger_design._tables_html([row], [], selected="", unclassified=False)
    # The row's own amount cell — not the empty COST group header, which is
    # legitimately 0원 because that group really holds no rows.
    cell = re.search(
        r"data-id='google-income[^']*'.*?</tr>", html, re.S)
    assert cell, html
    row_html = cell.group(0)
    assert "미확인" in row_html, row_html
    assert "0원" not in row_html, row_html
    # The element keeps its shape, but carries no amount to compare as zero.
    assert "data-amount=''" in row_html, row_html


def test_legacy_mobile_renders_an_unreadable_google_amount_as_mi확인():
    """F1: the mobile list must not raise and must print 미확인, never 0원."""
    row = _google_unknown_row()
    html = ledger_design._mobile_html([row], [], selected="", unclassified=False)
    item = re.search(r"data-id='google-income[^']*'.*?</li>", html, re.S)
    assert item, html
    row_html = item.group(0)
    assert "미확인" in row_html, row_html
    assert "0원" not in row_html, row_html
    assert "data-amount=''" in row_html, row_html
    # An unknown amount carries no sign class that would read as a value.
    assert ledger_design._row_amount_class(row) == "a-unknown"


def test_rows_region_survives_an_unreadable_google_amount():
    """F1 through the real region renderer the page and live refresh share."""
    row = _google_unknown_row()
    # _tables_html/_mobile_html are what rows_region calls; drive the same pair.
    tables = ledger_design._tables_html([row], [], selected="", unclassified=False)
    mobile = ledger_design._mobile_html([row], [], selected="", unclassified=False)
    assert "미확인" in tables and "미확인" in mobile, (tables[:200], mobile[:200])


# --------------------------------------------------------------------------- F2

@pytest.fixture
def linked_store(tmp_path):
    """One trip, a direct income, and the same money as a linked bank evidence row."""
    store = LedgerStore(tmp_path / "r06.sqlite", seed_demo=False)
    # The bank import table is created by the income ledger importer in production;
    # this fixture stands in for it so ``linked_bank_row_ids`` can resolve the id.
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS bank_import_rows (batch_id TEXT, row_index INTEGER,"
        " stable_key TEXT, raw_json TEXT, status TEXT)")
    tab = store.create_trip(starts_on="2026-11-10", ends_on="2026-11-20",
                            destination="합성 R06", client_request_id="r06-trip")["tab_id"]
    store.create_direct_income(fields={
        "display_tab_id": tab, "occurred_on": "2026-11-11", "customer_name": "합성",
        "income_kind": "deposit", "amount_krw": 1000000, "source_kind": "수기",
    }, client_request_id="r06-direct")
    store.create_direct_income(fields={
        "display_tab_id": tab, "occurred_on": "2026-11-11", "customer_name": "합성은행",
        "income_kind": "deposit", "amount_krw": 1000000, "source_kind": "은행",
    }, client_request_id="r06-bank")
    linked_id = f"bnk-{BANK_KEY_HEAD[:16]}"
    bank_row = store.conn.execute(
        "SELECT row_id FROM board_rows WHERE row_kind='income'"
        " AND payload_json LIKE '%은행%'").fetchone()[0]
    store.conn.execute("UPDATE board_rows SET row_id=? WHERE row_id=?", (linked_id, bank_row))
    store.conn.execute("INSERT INTO bank_import_rows VALUES ('b1',0,?, '{}','ok')",
                       (BANK_KEY_HEAD,))
    store.conn.execute("INSERT INTO income_source_links VALUES (?, 'b1', 0, '2026-11-11')",
                       (linked_id,))
    store.conn.commit()
    yield store, tab, linked_id
    store.close()


def test_shared_totals_exclude_a_linked_bank_row(linked_store):
    """F2: display_totals must match store.tab_totals, not double the income."""
    store, tab, linked_id = linked_store
    assert linked_id in store.linked_bank_row_ids(), store.linked_bank_row_ids()
    rows = ledger_query.recorded_rows(store, tab)
    assert len([r for r in rows if r.get("row_kind") == "income"]) == 2, rows
    baseline = store.tab_totals(tab)["income"]
    assert baseline == 1000000, baseline
    totals = ledger_query.display_totals(rows, linked=store.linked_bank_row_ids())
    assert int(totals["income"]) == baseline, totals
    # The linked row never became a second income count either.
    assert int(totals["income_count"]) == 1, totals


def test_trip_summary_excludes_a_linked_bank_row(linked_store):
    """F2: the React trip summary must agree with the baseline and the KPI."""
    from webapp import plush_projection

    store, tab, _linked_id = linked_store
    rows = ledger_query.recorded_rows(store, tab)
    baseline = store.tab_totals(tab)["income"]
    summary = plush_projection.trip_summary(
        {"tab_id": tab}, rows, linked=store.linked_bank_row_ids())
    assert summary["income"] == str(baseline), summary
    assert summary["profit"] == str(baseline - store.tab_totals(tab)["expense"]), summary


def test_owner_legacy_kpi_and_shared_totals_agree_on_a_linked_tab(linked_store):
    """F2 across the two owner screens: the KPI and the shared sum must match."""
    from webapp import ledger_board

    store, tab, _linked_id = linked_store
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    try:
        ledger_board._ROLE_LOCAL.role = "owner"
        ledger_board._ROLE_LOCAL.session = None
        kpi_html = ledger_design._trip_kpi_html(tab)
        rows = ledger_query.recorded_rows(store, tab)
        totals = ledger_query.display_totals(rows, linked=store.linked_bank_row_ids())
        match = re.search(r"<dt>수입</dt><dd>(.*?)</dd>", kpi_html, re.S)
        assert match, kpi_html[:300]
        kpi_income = int(match.group(1).replace("원", "").replace("−", "-").replace(",", ""))
        assert kpi_income == int(totals["income"]) == store.tab_totals(tab)["income"], (
            kpi_income, totals, store.tab_totals(tab)["income"])
    finally:
        ledger_board.bind_store(previous)
