import sqlite3
import re
from collections import Counter

db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()

cur.execute("""
    SELECT pt.id, pt.merchant, pt.occurred_on, pt.amount_krw
    FROM payment_transactions pt
    WHERE pt.merchant IS NOT NULL AND pt.merchant != ''
""")
all_rows = cur.fetchall()
print(f"Total: {len(all_rows)}건")

OTA_PATTERNS = {
    'AGODA': [r'^AGODA$', r'^AGODA\.', r'^AGODA_', r'^AGODA ', r'Agoda'],
    'BOOKING': [r'^BKG\*', r'Booking\.com', r'^Booking\.com', r'Partners on Booking', r'Hotel at Booking', r'HOTEL AT BOOKING'],
    'TRIP_COM': [r'^TRIP\.COM$', r'^Trip\.com$', r'^TRIP\.COM'],
    'KLOOK': [r'^KLOOK', r'Klook Travel', r'klook', r'_Klook'],
    'RAKUTEN': [r'RAKUTEN', r'rakuten', r'Rakuten Travel', r'RAKUTENTRAVEL'],
    'AIRBNB': [r'AIRBNB', r'airbnb'],
}

def is_ota(merchant):
    m = merchant.strip()
    for patterns in OTA_PATTERNS.values():
        for p in patterns:
            if re.search(p, m, re.IGNORECASE):
                return True
    return False

# Get all linked payment_ids
cur.execute("SELECT payment_id, booking_id FROM payment_booking_links")
links = cur.fetchall()
print(f"Total payment_booking_links: {len(links)}건")

# Get booking_id for each linked payment
linked_payment_ids = {r[0] for r in links}
print(f"Distinct linked payments: {len(linked_payment_ids)}건")

# Among linked payments, categorize by merchant
linked_ota_counts = Counter()
linked_ota_amounts = Counter()
for r in all_rows:
    if r[0] in linked_payment_ids:
        for name, patterns in OTA_PATTERNS.items():
            for p in patterns:
                if re.search(p, r[1], re.IGNORECASE):
                    linked_ota_counts[name] += 1
                    linked_ota_amounts[name] += r[3]
                    break
            else:
                continue
            break

print("\n=== OTA 별 booking 연결 현황 ===")
for name in OTA_PATTERNS:
    print(f"  {name:15s}: {linked_ota_counts[name]:>3}건 ({linked_ota_amounts[name]:>11,}원)")

# Get unlinked OTA
unlinked_ota = Counter()
unlinked_ota_amounts = Counter()
for r in all_rows:
    if r[0] not in linked_payment_ids:
        for name, patterns in OTA_PATTERNS.items():
            for p in patterns:
                if re.search(p, r[1], re.IGNORECASE):
                    unlinked_ota[name] += 1
                    unlinked_ota_amounts[name] += r[3]
                    break
            else:
                continue
            break

print("\n=== OTA 중 booking 미연결 ===")
for name in OTA_PATTERNS:
    print(f"  {name:15s}: {unlinked_ota[name]:>3}건 ({unlinked_ota_amounts[name]:>11,}원)")

# Show all unique linked booking_numbers
cur.execute("""
    SELECT b.booking_number, pt.merchant, pt.amount_krw, pt.occurred_on
    FROM payment_booking_links pbl
    JOIN bookings b ON b.id = pbl.booking_id
    JOIN payment_transactions pt ON pt.id = pbl.payment_id
    ORDER BY pt.occurred_on
""")
rows = cur.fetchall()
print(f"\n=== 전체 linked booking 목록 ({len(rows)}건) ===")
for r in rows:
    print(f"  {r[0]} | {r[1][:30]:30s} | {r[3]} | {r[2]:>9,}원")

# Count by merchant
print("\n=== 가맹점별 (linked) ===")
mcount = Counter(r[1] for r in rows)
for m, c in mcount.most_common(30):
    print(f"  {m[:50]:50s}: {c}")

db.close()