import urllib.request, re, json, sys
sys.stdout.reconfigure(encoding='utf-8')

sheet_id = "1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8"
# Try to get sheet list via gviz or via feed
# First try to fetch via google sheets API without auth using export with gid
# Try brute force: fetch grid-bottom-bar html to extract sheet names
url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
import pathlib
p = pathlib.Path(r'C:\Users\kkokk\.local\share\opencode\tool-output\tool_047507730001wnjdmZ2CqLuzuH')
html = p.read_text(encoding='utf-8', errors='ignore')
# find all sheet names in the bottom bar
# look for docs-sheet-tab-name or similar
names = re.findall(r'>([^<]{2,30})</div></div></li>', html)
print("tab names found:", names[:20])
# alternative pattern
names2 = re.findall(r'docs-sheet-tab-name[^>]*>([^<]+)<', html)
print("names2:", names2[:20])
# also look for bootstrap data with _bootstrap
m = re.search(r'bootstrapData[^}]*', html)
if m:
    print(html[m.start()-100:m.start()+2000][:2000])
else:
    # look for sheets in html snippet
    idx = html.find('grid-bottom-bar')
    print(html[idx-2000:idx+10000][:5000])
