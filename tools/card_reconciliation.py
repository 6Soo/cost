import sqlite3
import json
from collections import Counter

# Open the v5 candidate database to see all card transactions
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()

# Total payment transactions
cur.execute('SELECT COUNT(*) FROM payment_transactions')
total = cur.fetchone()[0]
print(f"Total payment_transactions: {total}")

# By payment_method (card)
cur.execute('SELECT pm.issuer, pm.last4, pm.ownership_type, COUNT(*) FROM payment_transactions pt JOIN payment_methods pm ON pt.payment_method_id = pm.id GROUP BY pm.issuer, pm.last4, pm.ownership_type ORDER BY COUNT(*) DESC')
print("\nBy card (issuer/last4/ownership):")
for r in cur.fetchall():
    print(f"  {r[0]} ****{r[1]} ({r[2]}): {r[3]}")

# By ownership_type
cur.execute('SELECT pm.ownership_type, COUNT(*) FROM payment_transactions pt JOIN payment_methods pm ON pt.payment_method_id = pm.id GROUP BY pm.ownership_type')
print("\nBy ownership_type:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

# By year (occurred_on)
cur.execute("SELECT strftime('%Y', occurred_on) as yr, COUNT(*) FROM payment_transactions WHERE occurred_on IS NOT NULL GROUP BY yr")
print("\nBy payment year (occurred_on):")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

# By source_system
cur.execute('SELECT source_system, COUNT(*) FROM payment_transactions GROUP BY source_system')
print("\nBy source_system:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

# merchant top 10
cur.execute("SELECT merchant, COUNT(*) FROM payment_transactions WHERE merchant IS NOT NULL AND merchant != '' GROUP BY merchant ORDER BY COUNT(*) DESC LIMIT 10")
print("\nTop 10 merchants:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

db.close()

# Now check the v5 promoted (after link candidates)
print("\n" + "="*60)
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()

# Count linked vs unlinked
cur.execute('SELECT link_status, COUNT(*) FROM payment_booking_links GROUP BY link_status')
print("Payment-Booking link status:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

# Count distinct payment_transactions
cur.execute('SELECT COUNT(DISTINCT payment_id) FROM payment_booking_links')
linked_payments = cur.fetchone()[0]
print(f"\nDistinct linked payments: {linked_payments}")

cur.execute('SELECT COUNT(*) FROM payment_transactions')
total_payments = cur.fetchone()[0]
print(f"Unlinked payments: {total_payments - linked_payments}")

db.close()

# Now check the draft v3 (after classification)
print("\n" + "="*60)
with open('outputs/agoda-card-accounting-draft-v3-v5-final.detail.json', encoding='utf-8') as f:
    draft = json.load(f)

# By target_match_status
cnt = Counter(r['target_match_status'] for r in draft['rows'])
print(f"Draft rows by match status ({len(draft['rows'])} total):")
for k, v in cnt.most_common():
    print(f"  {k}: {v}")

# By payment_lane
lane = Counter(r['payment_lane'] for r in draft['rows'])
print("\nBy payment_lane:")
for k, v in lane.most_common():
    print(f"  {k}: {v}")

# By cost_type
cost = Counter(r['cost_type'] for r in draft['rows'])
print("\nBy cost_type:")
for k, v in cost.most_common():
    print(f"  {k}: {v}")

# By account
acc = Counter(r['account'] for r in draft['rows'])
print("\nBy account:")
for k, v in acc.most_common():
    print(f"  {k}: {v}")

# Total amounts by status
amt_by_status = {}
for r in draft['rows']:
    s = r['target_match_status']
    amt_by_status.setdefault(s, 0)
    amt_by_status[s] += r['amount_krw']
print("\nAmount by match status:")
for k, v in amt_by_status.items():
    print(f"  {k}: {v:,}원")

# Top 10 trips by count
trip_cnt = Counter(r['allocation_target'] for r in draft['rows'])
print(f"\nTop 10 allocation_target ({len(trip_cnt)} trips):")
for k, v in trip_cnt.most_common(10):
    print(f"  {k}: {v}")