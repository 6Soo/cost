import sys, re
from openpyxl import load_workbook

sys.stdout.reconfigure(encoding='utf-8')

missing = [
    "0206_오쿠타다미", "0704_아키타", "0719_의왕", "0721_황금해안",
    "0801_노리쿠라", "1020_알펜루트", "1104_아오모리", "5월_유럽"
]

wb = load_workbook("ledger/data/ledger_current.xlsx", read_only=True, data_only=True)
tabs = {name.strip(): name for name in wb.sheetnames}

for code in missing:
    found = code in tabs
    if not found:
        # fuzzy match
        matches = [t for t in tabs if code.split('_')[0] in t or code.split('_', 1)[1] in t]
        print(f"{code}: workbook에 없음 (유사 탭: {matches if matches else '없음'})")
    else:
        ws = wb[tabs[code]]
        # Print first 5 rows
        print(f"{code}: workbook에 있음")
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), 1):
            vals = [str(v)[:40] if v else '' for v in row[:6]]
            print(f"  row {i}: {vals}")
    print()
