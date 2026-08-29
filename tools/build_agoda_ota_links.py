"""Add Agoda bookings from ota_event_links_verified.json to candidate DB."""

import json
import sys
import sqlite3
import pathlib
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

OTA_EVENT_LINKS_PATH = pathlib.Path('ledger/data/ota_event_links_verified.json')
CANDIDATE_DB = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')


def parse_period(period_str):
    """Parse '0417_0418' to (2026-04-17, 2026-04-18)."""
    if not period_str:
        return None, None
    parts = period_str.split('_')
    if len(parts) != 2:
        return None, None
    s_mmdd = parts[0]
    e_mmdd = parts[1]
    if len(s_mmdd) != 4 or len(e_mmdd) != 4:
        return None, None
    try:
        s = datetime.strptime(f"2026-{s_mmdd[:2]}-{s_mmdd[2:]}", "%Y-%m-%d").date()
        # If end < start, may be next month
        e = datetime.strptime(f"2026-{e_mmdd[:2]}-{e_mmdd[2:]}", "%Y-%m-%d").date()
        if e < s:
            # try next year
            e = datetime.strptime(f"2027-{e_mmdd[:2]}-{e_mmdd[2:]}", "%Y-%m-%d").date()
        return s.isoformat(), e.isoformat()
    except ValueError:
        return None, None


def main():
    with open(OTA_EVENT_LINKS_PATH, encoding='utf-8') as f:
        ota_links = json.load(f)
    print(f"ota_event_links_verified: {len(ota_links)}")

    db = sqlite3.connect(str(CANDIDATE_DB))
    cur = db.cursor()

    cur.execute('SELECT COUNT(*) FROM bookings')
    before = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM payment_booking_links')
    links_before = cur.fetchone()[0]
    print(f"Before: bookings={before}, links={links_before}")

    added_bookings = 0
    added_links = 0
    skipped = []

    for uid, info in ota_links.items():
        booking_id = info.get('booking_id')
        category = info.get('category')
        period = info.get('period')
        if not booking_id or not period:
            continue

        s, e = parse_period(period)
        if not s or not e:
            continue

        # Service end_on is exclusive checkout, so add 1 day
        s_dt = datetime.fromisoformat(s).date()
        e_dt = datetime.fromisoformat(e).date()
        checkout = (e_dt + (e_dt - s_dt + (e_dt - s_dt)).to_timedelta() if False else e_dt).isoformat() if False else None
        # service_start_on = s, service_end_on = e + 1 day
        from datetime import timedelta
        checkout_iso = (e_dt + timedelta(days=1)).isoformat()

        provider = 'agoda' if 'agoda' in str(info.get('verification_source', '')).lower() else 'unknown'
        hotel = info.get('hotel', '')

        # Insert booking if not exists
        cur.execute('SELECT id FROM bookings WHERE booking_number=?', (booking_id,))
        row = cur.fetchone()
        if row:
            bid = row[0]
        else:
            product_type = 'lodging'
            if category == '항공':
                product_type = 'flight'

            cur.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed')
            ''', (provider, booking_id, product_type, hotel, s, checkout_iso))
            bid = cur.lastrowid
            added_bookings += 1

        # Try to find payment by amount
        # Agoda payments in KRW (no foreign_amount) or JPY
        foreign_amount = info.get('foreign_amount')
        currency = info.get('currency')
        card4 = info.get('card4')

        # Try matching by foreign amount + date
        match = None
        if foreign_amount and currency == 'JPY':
            # Convert JPY to KRW roughly (rate 9.5)
            krw_est = int(foreign_amount * 9.5)
            cur.execute('''
                SELECT id, merchant, amount_krw, occurred_on
                FROM payment_transactions
                WHERE ABS(amount_krw - ?) < 5000
                  AND occurred_on IS NOT NULL
                  AND julianday(?) - julianday(occurred_on) BETWEEN 1 AND 90
                ORDER BY ABS(amount_krw - ?)
                LIMIT 1
            ''', (krw_est, s, krw_est))
            match = cur.fetchone()

        if not match:
            # Try matching by Agoda merchant pattern and date
            cur.execute('''
                SELECT id, merchant, amount_krw, occurred_on
                FROM payment_transactions
                WHERE (merchant LIKE 'AGODA%' OR merchant LIKE '%Agoda%')
                  AND occurred_on IS NOT NULL
                  AND julianday(?) - julianday(occurred_on) BETWEEN 1 AND 90
                ORDER BY ABS(julianday(occurred_on) - julianday(?))
                LIMIT 1
            ''', (s, s))
            match = cur.fetchone()

        if match:
            payment_id, merchant, amount, occurred = match
            cur.execute('SELECT 1 FROM payment_booking_links WHERE payment_id=?', (payment_id,))
            if not cur.fetchone():
                cur.execute('''
                    INSERT INTO payment_booking_links(payment_id, booking_id, relation_type, confidence, link_status)
                    VALUES (?, ?, 'pays_for', 0.80, 'proposed')
                ''', (payment_id, bid))
                added_links += 1

    db.commit()
    print(f"\nAdded bookings: {added_bookings}")
    print(f"Added links: {added_links}")
    if skipped:
        print(f"Skipped: {len(skipped)}건")

    cur.execute('SELECT COUNT(*) FROM bookings')
    after = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM payment_booking_links')
    links_after = cur.fetchone()[0]
    print(f"\nAfter: bookings={after}, links={links_after}")

    # Show distribution
    cur.execute('''
        SELECT pt.merchant, COUNT(*), SUM(pt.amount_krw)
        FROM payment_booking_links pbl
        JOIN payment_transactions pt ON pt.id = pbl.payment_id
        GROUP BY pt.merchant
        ORDER BY COUNT(*) DESC
    ''')
    print("\n=== Linked merchants ===")
    for r in cur.fetchall():
        print(f"  {r[0][:50]:50s} | {r[1]:>3}건 | {r[2]:>11,}원")

    db.close()


if __name__ == '__main__':
    main()