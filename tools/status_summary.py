import json
import hashlib
import pathlib

# 1. Authority status
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)
print(f"=== TRIP SCHEDULE AUTHORITY ===")
print(f"Total trips: {len(auth['records'])}")
print(f"Authority document SHA-256: {hashlib.sha256(pathlib.Path('ledger/data/trip_schedule_authority_v3.json').read_bytes()).hexdigest()[:16]}...")

# Group by year
from collections import Counter
year_counts = Counter(r['event_year'] for r in auth['records'])
print(f"By year: {dict(year_counts)}")

kind_counts = Counter(r['authority_kind'] for r in auth['records'])
print(f"By authority_kind: {dict(kind_counts)}")

# 2. Draft v3
with open('outputs/agoda-card-accounting-draft-v3-v5-final.audit.json', encoding='utf-8') as f:
    draft = json.load(f)
print(f"\n=== ACCOUNTING DRAFT V3 (v5) ===")
print(f"artifact_kind: {draft['artifact_kind']}")
print(f"row_count: {draft['row_count']}")
print(f"bound_unique: {draft['bound_unique_count']}")
print(f"authority_ambiguous: {draft['authority_ambiguous_count']}")
print(f"authority_missing: {draft['authority_missing_count']}")
print(f"payment_2025_count: {draft['payment_2025_count']}")
print(f"payment_2025_terminal: {draft['payment_2025_terminal_count']}")
print(f"payment_2026_count: {draft['payment_2026_count']}")
print(f"total_amount_krw: {draft['total_amount_krw']:,}")
print(f"manifest_id: {draft['manifest_id'][:16]}...")
print(f"database SHA-256: {draft['database_sha256'][:16]}...")

# 3. Journal shadow
with open('outputs/agoda-card-journal-shadow-v3-v5-final.audit.json', encoding='utf-8') as f:
    journal = json.load(f)
print(f"\n=== JOURNAL SHADOW V3 (v5) ===")
print(f"artifact_kind: {journal['artifact_kind']}")
print(f"batch_count: {journal['batch_count']}")
print(f"line_count: {journal['line_count']}")
print(f"debit_total_krw: {journal['debit_total_krw']:,}")
print(f"credit_total_krw: {journal['credit_total_krw']:,}")
print(f"balance_check: {'OK' if journal['debit_total_krw'] == journal['credit_total_krw'] else 'FAIL'}")
print(f"target_bound_count: {journal['target_bound_count']}")
print(f"target_bound_total_krw: {journal['target_bound_total_krw']:,}")
print(f"target_unresolved_count: {journal['target_unresolved_count']}")
print(f"posting_status: {journal['posting_status']}")
print(f"authoritative_posting: {journal['authoritative_posting']}")
print(f"integrity_check: {journal['integrity_check']}")
print(f"foreign_key_check: {journal['foreign_key_check']}")