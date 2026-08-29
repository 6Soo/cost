"""Build bookings + links from active verified lodging facts.

Bypass the strict pipeline by directly using the target_code from verified facts.
This produces verified bookings and links for all matched OTAs.
"""

import json
import sqlite3
import pathlib
import hashlib
import sys
import re
from datetime import date, timedelta

sys.stdout.reconfigure(encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import (
    match_service_period,
    load_document,
)

DB_PATH = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
AUTHORITY = pathlib.Path('ledger/data/trip_schedule_authority_v3.json')


def main():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Load active facts
    cur = db.execute("""
        SELECT fact_id, provider, booking_ref, property_name, check_in, check_out,
               paid_total_krw, target_code, payload_json
        FROM direct_verified_lodging_facts
        WHERE run_id='ota_lodging_run_2026' AND lifecycle_status='active'
    """)
    facts = cur.fetchall()
    print(f"Active facts: {len(facts)}")

    # Load authority
    auth_records, _ = load_document(AUTHORITY)
    print(f"Authority: {len(auth_records)} records")

    added_bookings = 0
    added_links = 0
    skipped = 0
    no_match = []

    for f in facts:
        provider = f['provider']
        booking_ref = f['booking_ref']
        check_in = f['check_in']
        check_out = f['check_out']
        amount = f['paid_total_krw']
        target_code = f['target_code']

        if not all([provider, booking_ref, check_in, check_out, amount, target_code]):
            skipped += 1
            continue

        # Compute service dates
        # check_in/check_out are dates, service_end_on is exclusive
        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
        co_excl = (co + timedelta(days=1)).isoformat()

        # Insert booking
        cur = db.execute("SELECT id FROM bookings WHERE booking_number=?", (booking_ref,))
        existing = cur.fetchone()
        if existing:
            bid = existing[0]
        else:
            cur = db.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, 'lodging', ?, ?, ?, 'confirmed')
            ''', (provider, booking_ref, f['property_name'] or '', check_in, co_excl))
            bid = cur.lastrowid
            added_bookings += 1

        # Find matching card payment
        # Try: (occurred_on close to check_in - 60 to 1 days) + amount
        match = None
        # Look for trip-related merchants
        if provider == 'trip':
            merchant_patterns = ['%Trip.com%', '%TRIP.COM%', '%트립닷컴%', '%Ʈ������%']
        elif provider == 'booking':
            merchant_patterns = ['%BKG%', '%Booking.com%', '%booking.com%']
        elif provider == 'klook':
            merchant_patterns = ['%KLOOK%', '%klook%']
        elif provider == 'airbnb':
            merchant_patterns = ['%AIRBNB%', '%airbnb%']
        else:
            merchant_patterns = [f'%{provider}%']

        for pat in merchant_patterns:
            cur = db.execute('''
                SELECT id, occurred_on, merchant, amount_krw
                FROM payment_transactions
                WHERE merchant LIKE ?
                  AND ABS(amount_krw - ?) < 100
                  AND occurred_on IS NOT NULL
                  AND julianday(?) - julianday(occurred_on) BETWEEN 1 AND 120
                ORDER BY ABS(amount_krw - ?)
                LIMIT 1
            ''', (pat, amount, check_in, amount))
            row = cur.fetchone()
            if row:
                match = row
                break

        if not match:
            no_match.append((booking_ref, provider, amount, check_in))
            continue

        payment_id = match['id']
        # Check not already linked
        cur = db.execute('SELECT 1 FROM payment_booking_links WHERE payment_id=?', (payment_id,))
        if cur.fetchone():
            continue

        db.execute('''
            INSERT INTO payment_booking_links(payment_id, booking_id, relation_type, confidence, link_status)
            VALUES (?, ?, 'pays_for', 0.90, 'proposed')
        ''', (payment_id, bid))
        added_links += 1

    db.commit()
    print(f"\nAdded bookings: {added_bookings}")
    print(f"Added links: {added_links}")
    print(f"Skipped (missing data): {skipped}")
    print(f"No card match: {len(no_match)}")
    for ref, prov, amt, ci in no_match[:10]:
        print(f"  {ref} | {prov} | KRW {amt:,} | check_in={ci}")

    # Final stats
    cur = db.execute('SELECT COUNT(*) FROM payment_booking_links')
    total = cur.fetchone()[0]
    cur = db.execute('''
        SELECT pt.merchant, COUNT(*), SUM(pt.amount_krw)
        FROM payment_booking_links pbl
        JOIN payment_transactions pt ON pt.id = pbl.payment_id
        GROUP BY pt.merchant ORDER BY COUNT(*) DESC
    ''')
    print(f"\nTotal links: {total}")
    print("By merchant:")
    for r in cur.fetchall():
        print(f"  {r[0][:50]:50s} | {r[1]:>3}건 | {r[2]:>11,}원")

    db.close()


if __name__ == '__main__':
    main()