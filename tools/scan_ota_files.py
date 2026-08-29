import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Check all OTA-related files
import pathlib

for f in pathlib.Path('ledger/data').glob('*.json'):
    try:
        with open(f, encoding='utf-8') as fp:
            d = json.load(fp)
        if isinstance(d, dict) and len(d) > 0:
            # check first key
            k = list(d.keys())[0]
            v = d[k]
            # Look for provider/source info
            if isinstance(v, dict):
                keys = list(v.keys())
                if any('provider' in str(k).lower() or 'ota' in str(k).lower() or 'source' in str(k).lower() for k in keys):
                    print(f"\n=== {f.name} === ({len(d)} keys)")
                    print(f"Sample: {json.dumps(v, ensure_ascii=False, indent=2)[:400]}")
    except:
        pass