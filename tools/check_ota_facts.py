import json
with open('ledger/data/ota_lodging_facts_v2.json', encoding='utf-8') as f:
    d = json.load(f)
print('Type:', type(d).__name__)
if isinstance(d, dict):
    print('Keys:', list(d.keys())[:20])
    for k, v in d.items():
        print(f'  {k}: type={type(v).__name__}, len={len(v) if hasattr(v, "__len__") else "?"}')
elif isinstance(d, list):
    print(f'  total: {len(d)}')
    if d:
        print(f'  sample[0] keys: {list(d[0].keys()) if isinstance(d[0], dict) else d[0]}')