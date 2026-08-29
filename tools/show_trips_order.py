import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('ledger/data/trips.json', encoding='utf-8') as f:
    trips = json.load(f)

print(f"trips.json 전체 {len(trips)}건 (저장소 순서):\n")
for i, t in enumerate(trips):
    mm, dd = t['mm'], t['dd']
    window = t.get('window', '?')
    print(f"  {i+1:2d}. {t['tab']:20s} | mm={mm:2d} dd={dd:2d} | window={window:3d} | {t['region']}")
