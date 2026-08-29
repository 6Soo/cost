import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

for fname in ['ota_mail_index.json', 'ota_mail_live_index.json', 'pg_mail_index.json']:
    print(f"\n=== {fname} ===")
    try:
        with open(f'ledger/data/{fname}', encoding='utf-8') as f:
            d = json.load(f)
        for k, v in d.items():
            if isinstance(v, list):
                print(f"  {k}: list, len={len(v)}")
                if v:
                    print(f"    sample[0] type: {type(v[0]).__name__}")
                    if isinstance(v[0], dict):
                        print(f"    sample[0] keys: {list(v[0].keys())[:10]}")
            elif isinstance(v, dict):
                print(f"  {k}: dict, keys={list(v.keys())[:5]}, sub-len={len(v)}")
                # show first sub
                if v:
                    sk = list(v.keys())[0]
                    sv = v[sk]
                    print(f"    '{sk}': {type(sv).__name__} {str(sv)[:200]}")
            else:
                print(f"  {k}: {v}")
    except Exception as e:
        print(f"Error: {e}")