import json
from collections import Counter

for fname in ['matched_fresh.json', 'matched_uids.json', 'booking_info.json', 'booking_periods_verified.json']:
    print(f"\n=== {fname} ===")
    try:
        with open(f'ledger/data/{fname}', encoding='utf-8') as f:
            d = json.load(f)
        print(f"Type: {type(d).__name__}")
        if isinstance(d, dict):
            print(f"Keys: {list(d.keys())[:10]}")
            print(f"Total keys: {len(d)}")
            # show sample
            k = list(d.keys())[0]
            print(f"\nSample '{k}':")
            print(json.dumps(d[k], ensure_ascii=False, indent=2)[:500])
        elif isinstance(d, list):
            print(f"Total: {len(d)}")
            if d:
                print(f"Sample: {json.dumps(d[0], ensure_ascii=False, indent=2)[:500]}")
    except Exception as e:
        print(f"Error: {e}")