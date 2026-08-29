import sqlite3
from collections import Counter

db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()

# All merchants - top 30
cur.execute("""
    SELECT merchant, COUNT(*) as cnt
    FROM payment_transactions
    WHERE merchant IS NOT NULL AND merchant != ''
    GROUP BY merchant
    ORDER BY cnt DESC
    LIMIT 30
""")
print("=== Top 30 merchants (전체 카드 5,328건 중) ===")
total_count = 0
for r in cur.fetchall():
    print(f"  {r[0][:60]:<60} | {r[1]:>5}건")
    total_count += r[1]
print(f"  ... (상위 30개 합계: {total_count}건)")

# Agoda merchants only
cur.execute("""
    SELECT merchant, COUNT(*) as cnt
    FROM payment_transactions
    WHERE merchant IS NOT NULL
      AND (merchant LIKE 'AGODA%' OR merchant LIKE '%Agoda%' OR merchant = 'AGODA')
    GROUP BY merchant
    ORDER BY cnt DESC
""")
print("\n=== Agoda 가맹점 전체 ===")
agoda_total = 0
for r in cur.fetchall():
    print(f"  {r[0][:60]:<60} | {r[1]:>5}건")
    agoda_total += r[1]
print(f"  Agoda 합계: {agoda_total}건")

# Non-Agoda
cur.execute("""
    SELECT COUNT(*)
    FROM payment_transactions
    WHERE merchant IS NOT NULL
      AND NOT (merchant LIKE 'AGODA%' OR merchant LIKE '%Agoda%' OR merchant = 'AGODA')
""")
non_agoda = cur.fetchone()[0]
total_all = 5328
print(f"\n비-Agoda: {non_agoda}건 (전체 {total_all}건, {non_agoda*100//total_all}%)")

# Check pipeline scope
print("\n=== 파이프라인 범위 (tools/build_agoda_card_link_candidate.py) ===")
print("Agoda 가맹점만 candidate 생성 (independently_valid_agoda_merchant)")
print("- AGODA")
print("- AGODA.*")
print("- AGODA_*")
print("- AGODA 공백")
print("- *Agoda*")

# 그 외 OTA/숙박
cur.execute("""
    SELECT merchant, COUNT(*) as cnt
    FROM payment_transactions
    WHERE merchant IS NOT NULL
      AND (merchant LIKE 'BKG%' OR merchant LIKE 'Booking%' OR merchant LIKE '%hotel%' OR merchant LIKE '%HOTEL%' OR merchant LIKE '%HOTERU%' OR merchant LIKE 'Trip.com%' OR merchant LIKE 'AIRBNB%' OR merchant LIKE 'Klook%' OR merchant LIKE '%NICE%' OR merchant LIKE '%travel%' OR merchant LIKE '%Travel%')
    GROUP BY merchant
    ORDER BY cnt DESC
    LIMIT 20
""")
print("\n=== 기타 OTA/숙박 가맹점 ===")
for r in cur.fetchall():
    print(f"  {r[0][:60]:<60} | {r[1]:>5}건")

db.close()