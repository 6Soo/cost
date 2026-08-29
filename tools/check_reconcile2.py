import json

with open('ledger/data/ota_reconcile_report.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"mailRecords: {d['mailRecords']}")
print(f"otaCardRows: {d['otaCardRows']}")
print(f"preexistingLinks: {d['preexistingLinks']}")
print(f"autoLinked: {d['autoLinked']}")
print(f"ambiguousCount: {d['ambiguousCount']}")
print(f"unresolvedCount: {d['unresolvedCount']}")

print(f"\nambiguous sample (first 3):")
for r in d['ambiguous'][:3]:
    print(json.dumps(r, ensure_ascii=False, indent=2)[:500])

print(f"\nunresolved sample (first 3):")
for r in d['unresolved'][:3]:
    print(json.dumps(r, ensure_ascii=False, indent=2)[:500])