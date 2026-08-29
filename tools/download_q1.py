import urllib.request, pathlib, sys
sys.stdout.reconfigure(encoding='utf-8')
sid="1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8"
url=f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
out=pathlib.Path(r"C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx")
out.parent.mkdir(parents=True, exist_ok=True)
print(f"downloading {url}")
req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as r:
    data=r.read()
    out.write_bytes(data)
    print(f"saved {len(data)} bytes to {out}")
# now list sheets
from openpyxl import load_workbook
wb=load_workbook(out, read_only=True, data_only=True)
print(f"sheets ({len(wb.sheetnames)}): {wb.sheetnames}")
for name in wb.sheetnames:
    ws=wb[name]
    vals=[]
    for row in ws.iter_rows(min_row=1, max_row=3, values_only=True):
        vals.append([str(v)[:30] if v else "" for v in row[:6]])
    print(f"\n{name}: {vals}")
wb.close()
