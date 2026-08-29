from openpyxl import load_workbook
import re, sys
sys.stdout.reconfigure(encoding='utf-8')
path=r"C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx"
wb=load_workbook(path, read_only=True, data_only=True)
YEAR_RE=re.compile(r'(\d{4})년')
DATE_RANGE_RE=re.compile(r'(?<![0-9])(\d{2})(\d{2})[_-](\d{2})(\d{2})(?![0-9])')
for name in wb.sheetnames:
    if "기타" in name or "총괄" in name:
        continue
    ws=wb[name]
    title=None
    for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
        for v in row:
            if v and "매출 확인자료" in str(v):
                title=str(v)
                break
        if title:
            break
    print(f"{name}: title='{title}'")
    if title:
        ym=YEAR_RE.search(title)
        rm=DATE_RANGE_RE.search(title)
        print(f"  year={ym.group(1) if ym else None}, range={rm.groups() if rm else None}")
wb.close()
