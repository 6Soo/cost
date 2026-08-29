import sqlite3
import re
from collections import Counter

db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()

# Get all payment_transactions with merchant
cur.execute("""
    SELECT pt.id, pt.merchant, pt.occurred_on, pt.amount_krw, pt.country
    FROM payment_transactions pt
    WHERE pt.merchant IS NOT NULL AND pt.merchant != ''
""")
all_rows = cur.fetchall()
print(f"Total: {len(all_rows)}건")

# Classify merchants into OTA categories
OTA_PATTERNS = {
    'AGODA': [r'^AGODA$', r'^AGODA\.', r'^AGODA_', r'^AGODA ', r'Agoda'],
    'BOOKING': [r'^BKG\*', r'Booking\.com', r'^Booking\.com', r'Partners on Booking', r'Hotel at Booking', r'HOTEL AT BOOKING'],
    'TRIP_COM': [r'^TRIP\.COM$', r'^Trip\.com$', r'^TRIP\.COM'],
    'KLOOK': [r'^KLOOK', r'Klook Travel', r'klook', r'_Klook'],
    'RAKUTEN': [r'RAKUTEN', r'rakuten', r'Rakuten Travel', r'RAKUTENTRAVEL'],
    'TRAVEL_ARS': [r'Ʈ������\(ARS\)', r'Ʈ������\(��\)', r'Ʈ������'],
    'NICE_PAY': [r'^NICE_', r'NICE\(', r'NICE ������', r'NICE ����', r'Ƽ�ϰ���\(�¶���\)_NICE', r'KCP\(����\)', r'KCP\(', r'KICC', r'KSNET', r'NHNKCP', r'��ũ��', r'KSNET_N'],
    'AIRBNB': [r'AIRBNB', r'airbnb'],
    'AIRLINE': [r'ANA', r'JETSTAR', r'AIRASIA', r'ASIANA', r'KOREAN', r'PEGAUS', r'JEJU AIR', r'SKYMARK', r'Flix', r'Volotea', r'FDA', r'ANA AIRFOOOCM', r'ANAAIR', r'KIWI', r'AVIS', r'Hertz', r'SICILY BY CAR', r'DRIVE CAR', r'YESAWAY', r'BKG\*Booking\.com', r'esim', r'eSIM'],
}

# Patterns that are NOT OTA (excluded)
NON_OTA = [
    r'FAMILYMART', r'LAWSON', r'SEVEN-ELEVEN', r'MOSBURGER', r'MCDONALDS', r'KURA SUSHI', r'SUSHIRO', r'YOSHINOYA', r'STARBUCKS', r'DOUTOR', r'CHATERAISE', r'PEPPER LUNCH',
    r'JR EAST', r'JR ', r'TOYOTA RENT', r'TOYOTARENT', r'TIMES PARKING', r'HIGHWAY TOLL', r'CASSA PARCHEGGIO', r'PARK HOTEL', r'APAHOTEL', r'APA HOTEL',
    r'ENEOS', r'COSMO OIL', r'SHELL', r'BP ', r'PTT', r'BANGCHAK', r'BES TOLL', r'MPC ', r'TOTAL',
    r'JIN ', r'7-ELEVEN', r'MINI STOP', r'AMAZON', r'ALIEXPRESS',
]

def classify(merchant):
    m = merchant.strip()
    for name, patterns in OTA_PATTERNS.items():
        for p in patterns:
            if re.search(p, m, re.IGNORECASE):
                return name
    for p in NON_OTA:
        if re.search(p, m, re.IGNORECASE):
            return 'NON_OTA'
    return 'OTHER'

categories = Counter()
for r in all_rows:
    cat = classify(r[1])
    categories[cat] += 1

print("\n=== 가맹점 분류 (5,328건) ===")
for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
    print(f"  {cat:20s}: {cnt:>5}건 ({cnt*100//len(all_rows)}%)")

# For OTA categories, check how many have booking linkage
print("\n=== OTA/여행 카테고리 중 booking 연결 현황 ===")
cur.execute("""
    SELECT pbl.payment_id, pbl.booking_id
    FROM payment_booking_links pbl
""")
links = dict(cur.fetchall())
print(f"  Total links: {len(links)}건")

ota_breakdown = {}
for r in all_rows:
    cat = classify(r[1])
    if cat == 'NON_OTA' or cat == 'OTHER':
        continue
    ota_breakdown.setdefault(cat, {'total': 0, 'linked': 0, 'amount_total': 0, 'amount_linked': 0})
    ota_breakdown[cat]['total'] += 1
    ota_breakdown[cat]['amount_total'] += r[3]
    if r[0] in links:
        ota_breakdown[cat]['linked'] += 1
        ota_breakdown[cat]['amount_linked'] += r[3]

for cat, data in sorted(ota_breakdown.items(), key=lambda x: -x[1]['total']):
    print(f"  {cat:20s}: {data['total']:>5}건 ({data['amount_total']:>13,}원) | linked: {data['linked']:>3}건 ({data['amount_linked']:>11,}원) | unlinked: {data['total']-data['linked']:>3}건")

db.close()