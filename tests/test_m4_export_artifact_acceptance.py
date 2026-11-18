"""Synthetic acceptance of the real HTTP XLSX route and downloaded artifact."""

from __future__ import annotations

import io
import json
import threading
import urllib.request
import zipfile

from openpyxl import load_workbook


def test_http_xlsx_export_keeps_all_paged_rows_signs_totals_and_selected_tab(
    tmp_path, monkeypatch,
):
    from webapp import ledger_board
    db_path = tmp_path / "m4-export-synthetic.sqlite"
    export_dir = tmp_path / "m4-exports"
    monkeypatch.setenv("WEBLEDGER_DB", str(db_path))
    monkeypatch.setenv("WEBLEDGER_EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "0")
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "0")

    previous_store = ledger_board._STORE
    previous_importer = ledger_board._IMPORTER
    server = ledger_board.serve(port=0, with_worker=False)
    store = server.card_store
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    page_sizes = (401, 407, 413)
    pages = []
    expected_rows = []
    index = 0
    for page_size in page_sizes:
        page = []
        for _ in range(page_size):
            index += 1
            amount = -(index * 11) if index % 9 == 0 else index * 11
            row = {
                "row_id": f"m4-xlsx-synthetic-{index:04d}",
                "row_kind": "expense",
                "display_tab_id": "trip-demo-a",
                "occurred_on": f"2026-11-{1 + (index % 28):02d}",
                "amount_krw": amount,
                "item": f"synthetic-row-{index:04d}",
                "description": f"synthetic-page-row-{index:04d}",
                "service_period": "",
                "reservation_no": "",
                "evidence_type": "현금",
            }
            page.append(row)
            expected_rows.append(row)
        pages.append(page)

    source_page_reads = []
    requested_tabs = []

    def paged_list_tab_rows(tab_id: str):
        requested_tabs.append(tab_id)
        if tab_id != "trip-demo-a":
            return []
        rows = []
        for page_number, page in enumerate(pages, start=1):
            source_page_reads.append((tab_id, page_number, len(page)))
            rows.extend(page)
        return rows

    store.list_tab_rows = paged_list_tab_rows

    try:
        payload = {
            "csrf": ledger_board.CSRF_TOKEN,
            "client_request_id": "m4-synthetic-xlsx-acceptance",
            "tab_ids": ["trip-demo-a"],
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/exports/xlsx",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
            job = json.loads(response.read().decode("utf-8"))

        assert job["status"] == "ready"
        assert job["tab_ids"] == ["trip-demo-a"]
        assert requested_tabs == ["trip-demo-a"]
        assert source_page_reads == [
            ("trip-demo-a", 1, 401),
            ("trip-demo-a", 2, 407),
            ("trip-demo-a", 3, 413),
        ]

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/exports/{job['job_id']}/download"
        ) as response:
            assert response.status == 200
            assert "spreadsheet" in response.headers.get("Content-Type", "")
            artifact = response.read()

        assert zipfile.is_zipfile(io.BytesIO(artifact))
        workbook = load_workbook(io.BytesIO(artifact), read_only=True, data_only=False)
        try:
            assert len(workbook.sheetnames) == 1
            sheet = workbook[workbook.sheetnames[0]]
            expense_header_row = next(
                row for row in range(1, sheet.max_row + 1)
                if sheet.cell(row=row, column=1).value == "지출"
            )
            first_row = expense_header_row + 1
            last_row = first_row + len(expected_rows) - 1
            exported = list(sheet.iter_rows(
                min_row=first_row,
                max_row=last_row,
                min_col=3,
                max_col=8,
                values_only=True,
            ))
            exported_ids = [row[0] for row in exported]
            exported_amounts = [row[5] for row in exported]

            assert len(exported) == 1221
            assert exported_ids == [row["item"] for row in expected_rows]
            assert len(set(exported_ids)) == len(expected_rows)
            assert exported_amounts == [row["amount_krw"] for row in expected_rows]
            assert sum(exported_amounts) == sum(row["amount_krw"] for row in expected_rows)

            expense_end = last_row
            total_row = expense_end + 1
            assert sheet.cell(row=total_row, column=3).value == (
                f"=SUM(H{first_row}:H{expense_end})"
            )
        finally:
            workbook.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        ledger_board.bind_store(previous_store)
        ledger_board.bind_importer(previous_importer)
        store.close()
