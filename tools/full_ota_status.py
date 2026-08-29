import json
import sqlite3
from collections import Counter
import sys
sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()

# Get linked payments
cur.execute('SELECT DISTINCT payment_id FROM payment_booking_links')
linked = {r[0] for r in cur.fetchall()}

# OTA-like merchants
cur.execute("""
    SELECT pt.id, pt.merchant, pt.occurred_on, pt.amount_krw
    FROM payment_transactions pt
    WHERE pt.merchant IS NOT NULL
""")
all_ota = cur.fetchall()

# Categorize
def is_ota(m):
    if not m:
        return False
    ml = m.lower()
    return any(p in ml for p in ['agoda', 'bkg*', 'booking.com', 'trip.com', 'klook', 'airbnb', 'rakuten', 'Ʈ������', 'Ƽ�ϰ���'])

linked_ota = Counter()
unlinked_ota = Counter()
unlinked_ota_amt = Counter()
for r in all_ota:
    pid, merchant, occurred, amount = r
    if not is_ota(merchant):
        continue
    if pid in linked:
        linked_ota[merchant] += 1
    else:
        unlinked_ota[merchant] += 1
        unlinked_ota_amt[merchant] += amount

print(f"=== OTA 가맹점 전체 5,328건 중 ===")
print(f"\nLinked (84건) merchants:")
for m, c in linked_ota.most_common(20):
    print(f"  {m[:50]:50s} | {c:>3}건")
print(f"\nUnlinked OTA merchants (top 20):")
for m, c in unlinked_ota.most_common(20):
    print(f"  {m[:50]:50s} | {c:>3}건 | {unlinked_ota_amt[m]:>11,}원")

# Total
total_ota = sum(linked_ota.values()) + sum(unlinked_ota.values())
print(f"\n=== OTA 가맹점 합계: {total_ota}건 ===")
print(f"  linked: {sum(linked_ota.values())}건 ({sum(linked_ota.values())*100//total_ota}%)")
print(f"  unlinked: {sum(unlinked_ota.values())}건 ({sum(unlinked_ota.values())*100//total_ota}%)")

# 5,328건 전체
print(f"\n=== 전체 카드 5,328건 중 OTA 비중: {total_ota*100//5328}% ===")
print(f"  그 중 linked: {sum(linked_ota.values())}건")
print(f"  non-OTA 가맹점 (식비/교통/기타): {5328 - total_ota}건")

db.close()