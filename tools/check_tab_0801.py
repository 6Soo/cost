import sys
from openpyxl import load_workbook

sys.stdout.reconfigure(encoding='utf-8')

wb = load_workbook("ledger/data/ledger_current.xlsx", read_only=True, data_only=True)

# Find 0801 tab
for name in wb.sheetnames:
    if "0801" in name:
        print(f"Found tab: {name}")
        ws = wb[name]
        # Print first 10 rows to see structure
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), 1):
            print(f"  row {i}: {row}")
        print()
        
# Also check if there's a year in the tab
import re
for name in wb.sheetnames:
    if "노리쿠라" in name or "0801" in name:
        year_match = re.search(r'(\d{4})년', name)
        date_range = re.search(r'(\d{2})(\d{2})[_-](\d{2})(\d{2})', name)
        print(f"Tab '{name}': year={year_match.group(1) if year_match else 'NONE'}, date_range={date_range.group(0) if date_range else 'NONE'}")
