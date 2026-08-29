import urllib.request, sys, re
sys.stdout.reconfigure(encoding='utf-8')
sid="1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8"
urls=[
 f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv",
 f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=Sheet1",
 f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx",
]
for url in urls:
    print(f"TRY {url}")
    try:
        req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data=r.read()
            print(f"  ok {len(data)} bytes, head: {data[:300]}")
    except Exception as e:
        print(f"  err {e}")

# Try to extract sheet names from html via different regex
import pathlib
p=pathlib.Path(r'C:\Users\kkokk\.local\share\opencode\tool-output\tool_047507730001wnjdmZ2CqLuzuH')
html=p.read_text(encoding='utf-8', errors='ignore')
# find all occurrences of "sheetName" or tab names
for pat in [r'sheetName[^"]*\"([^\"]+)\"', r'\"title\":\"([^\"]+)\"', r'gridId\":(\d+)']:
    vals=re.findall(pat, html)
    if vals:
        print(f"pattern {pat}: {vals[:10]}")
# also look for docs-sheet
idx=html.find('docs-sheet')
print(html[idx:idx+5000][:5000] if idx>=0 else "no docs-sheet")
