"""OTA-extended candidate builder.

Ingest OTA lodging facts from ota_lodging_facts_v2.json and booking_info.json,
add new bookings to the candidate database, and create payment_booking_links
by matching amount + date.

This extends the Agoda-only candidate to cover Trip.com, Booking.com, KLOOK,
AIRBNB etc. based on email-derived verified facts.
"""

import json
import sys
import sqlite3
import hashlib
import pathlib

sys.stdout.reconfigure(encoding='utf-8')

OTA_FACTS_PATH = pathlib.Path('ledger/data/ota_lodging_facts_v2.json')
BOOKING_INFO_PATH = pathlib.Path('ledger/data/booking_info.json')
BOOKING_PERIODS_PATH = pathlib.Path('ledger/data/booking_periods_verified.json')
OTA_EVENT_LINKS_PATH = pathlib.Path('ledger/data/ota_event_links_verified.json')
CANDIDATE_DB = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main():
    # Load OTA facts
    with open(OTA_FACTS_PATH, encoding='utf-8') as f:
        ota_facts = json.load(f)
    print(f"OTA facts: {ota_facts['record_count']} records, {ota_facts['eligible_count']} eligible")

    # Load booking info (54 Trip.com)
    with open(BOOKING_INFO_PATH, encoding='utf-8') as f:
        booking_info = json.load(f)
    print(f"booking_info: {len(booking_info)}")

    # Load booking periods verified
    with open(BOOKING_PERIODS_PATH, encoding='utf-8') as f:
        booking_periods = json.load(f)
    print(f"booking_periods_verified: {len(booking_periods)}")

    # Load OTA event links
    with open(OTA_EVENT_LINKS_PATH, encoding='utf-8') as f:
        ota_links = json.load(f)
    print(f"ota_event_links_verified: {len(ota_links)}")

    # Open candidate DB
    db = sqlite3.connect(str(CANDIDATE_DB))
    cur = db.cursor()

    # Current bookings count
    cur.execute('SELECT COUNT(*) FROM bookings')
    print(f"\nCurrent bookings in DB: {cur.fetchone()[0]}")

    # Current payment_booking_links count
    cur.execute('SELECT COUNT(*) FROM payment_booking_links')
    print(f"Current payment_booking_links: {cur.fetchone()[0]}")

    # Strategy: add new bookings for OTA facts and link them to card payments
    # by matching amount (paid_total_krw) + service date (check_in)

    new_bookings = []
    new_links = []

    for ota in ota_facts['records']:
        if ota.get('eligibility_status') != 'eligible':
            continue

        booking_ref = ota.get('booking_ref')
        if not booking_ref:
            continue

        provider = ota.get('provider', 'unknown')
        check_in = ota.get('check_in')
        check_out = ota.get('check_out')
        amount = ota.get('paid_total_krw', 0)
        property_name = ota.get('property_name', '')

        if not check_in or not check_out or not amount:
            continue

        # Insert booking if not exists
        cur.execute('SELECT id FROM bookings WHERE booking_number=?', (booking_ref,))
        row = cur.fetchone()
        if row:
            booking_id = row[0]
        else:
            cur.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, 'lodging', ?, ?, ?, 'confirmed')
            ''', (provider, booking_ref, property_name, check_in, check_out))
            booking_id = cur.lastrowid
            new_bookings.append((booking_ref, provider, check_in, check_out, amount))

        # Find matching payment by amount + occurred_on close to check_in (1-2 month window for pre-payment)
        # Try a few windows: occurred_on within 90 days before check_in
        cur.execute('''
            SELECT pt.id, pt.occurred_on, pt.merchant
            FROM payment_transactions pt
            WHERE ABS(pt.amount_krw - ?) < 100
              AND pt.occurred_on IS NOT NULL
              AND julianday(?) - julianday(pt.occurred_on) BETWEEN 1 AND 180
            ORDER BY ABS(pt.amount_krw - ?) ASC
            LIMIT 1
        ''', (amount, check_in, amount))
        match = cur.fetchone()
        if match:
            payment_id, occurred, merchant = match
            # Check if link already exists
            cur.execute('SELECT 1 FROM payment_booking_links WHERE payment_id=?', (payment_id,))
            if not cur.fetchone():
                cur.execute('''
                    INSERT INTO payment_booking_links(payment_id, booking_id, relation_type, confidence, link_status)
                    VALUES (?, ?, 'pays_for', 0.85, 'proposed')
                ''', (payment_id, booking_id))
                new_links.append((payment_id, booking_ref, merchant, amount, occurred))

    db.commit()
    print(f"\nNew bookings added: {len(new_bookings)}")
    print(f"New payment_booking_links: {len(new_links)}")

    # Show summary by provider
    cur.execute('''
        SELECT pt.merchant, COUNT(*), SUM(pt.amount_krw)
        FROM payment_booking_links pbl
        JOIN payment_transactions pt ON pt.id = pbl.payment_id
        GROUP BY pt.merchant
    ''')
    print("\n=== Updated link status by merchant ===")
    for r in cur.fetchall():
        print(f"  {r[0][:50]:50s} | {r[1]:>3}건 | {r[2]:>11,}원")

    db.close()


if __name__ == '__main__':
    main()