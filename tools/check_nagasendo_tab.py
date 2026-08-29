import sys, re
from openpyxl import load_workbook

sys.stdout.reconfigure(encoding='utf-8')

wb = load_workbook("ledger/data/ledger_current.xlsx", read_only=True, data_only=True)

for name in wb.sheetnames:
    if "나가센도" in name:
        ws = wb[name]
        print(f"Tab: {name}")
        print()
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True), 1):
            vals = [str(v)[:50] if v else '' for v in row[:8]]
            print(f"  row {i}: {vals}")
