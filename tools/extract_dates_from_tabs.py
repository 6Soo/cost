import sys, re
from openpyxl import load_workbook

sys.stdout.reconfigure(encoding='utf-8')

targets = [
    "0206_오쿠타다미", "0721_황금해안", "0801_노리쿠라",
    "1020_알펜루트", "1104_아오모리", "5월_유럽"
]

wb = load_workbook("ledger/data/ledger_current.xlsx", read_only=True, data_only=True)

date_re = re.compile(r'(\d{2})\.(\d{2})\.(\d{2})')

for code in targets:
    if code not in wb.sheetnames:
        print(f"=== {code}: 없음 ===\n")
        continue
    
    ws = wb[code]
    print(f"=== {code} ===")
    
    dates_found = []
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        for cell in row:
            if cell is None:
                continue
            s = str(cell)
            m = date_re.search(s)
            if m:
                # YY.MM.DD format
                yy, mm, dd = m.group(1), m.group(2), m.group(3)
                full = f"20{yy}-{mm}-{dd}"
                dates_found.append((i, full, s[:50]))
    
    if dates_found:
        first = dates_found[0]
        last = dates_found[-1]
        print(f"  첫 날짜: row {first[0]} -> {first[1]} ('{first[2]}')")
        print(f"  마지막 날짜: row {last[0]} -> {last[1]} ('{last[2]}')")
        print(f"  전체 날짜 {len(dates_found)}개:")
        for row_num, dt, ctx in dates_found[:5]:
            print(f"    row {row_num}: {dt} ({ctx})")
        if len(dates_found) > 5:
            print(f"    ... 외 {len(dates_found)-5}개")
    else:
        print("  날짜 없음")
    print()
