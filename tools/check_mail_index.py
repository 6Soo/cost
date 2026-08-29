import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

for fname in ['ota_mail_index.json', 'ota_mail_live_index.json', 'pg_mail_index.json', 'pg_mail_supplemental_index.json', 'service_mail_index.json']:
    print(f"\n=== {fname} ===")
    try:
        with open(f'ledger/data/{fname}', encoding='utf-8') as f:
            d = json.load(f)
        print(f"Type: {type(d).__name__}")
        if isinstance(d, dict):
            print(f"Keys: {len(d)}")
            k0 = list(d.keys())[0]
            v0 = d[k0]
            if isinstance(v0, dict):
                print(f"Sample '{k0}' keys: {list(v0.keys())[:10]}")
                print(f"  sample: {json.dumps(v0, ensure_ascii=False)[:500]}")
            else:
                print(f"  '{k0}': {v0!r}")
    except Exception as e:
        print(f"Error: {e}")