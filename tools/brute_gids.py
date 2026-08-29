import urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')
sheet_id="1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8"
for gid in range(0,25):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = r.read().decode('utf-8', errors='ignore')
            first = data.splitlines()[0][:120] if data.strip() else "(empty)"
            second = data.splitlines()[1][:120] if len(data.splitlines())>1 else ""
            if "html" in data.lower()[:500] and "404" in data:
                continue
            if len(data.strip())<50:
                print(f"gid {gid}: too short {len(data)}")
                continue
            print(f"gid {gid}: {first} | {second[:80]}")
    except Exception as e:
        print(f"gid {gid}: error {e}")
