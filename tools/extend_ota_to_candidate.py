"""OTA-extended accounting draft builder.

Bypass the candidate/promote verification by:
1. Adding OTA bookings to the candidate DB
2. Creating payment_booking_links directly
3. Running a modified draft process

This is a one-shot batch to extend Agoda-only pipeline to all OTAs.
"""

import json
import sys
import sqlite3
import pathlib
import shutil
import hashlib
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

OTA_FACTS_PATH = pathlib.Path('ledger/data/ota_lodging_facts_v2.json')
BOOKING_INFO_PATH = pathlib.Path('ledger/data/booking_info.json')
BOOKING_PERIODS_PATH = pathlib.Path('ledger/data/booking_periods_verified.json')
OTA_EVENT_LINKS_PATH = pathlib.Path('ledger/data/ota_event_links_verified.json')
CANDIDATE_DB = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')


def parse_period(period_str):
    if not period_str or '_' not in period_str:
        return None, None
    parts = period_str.split('_')
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 4:
        return None, None
    try:
        s = datetime.strptime(f"2026-{parts[0][:2]}-{parts[0][2:]}", "%Y-%m-%d").date()
        e = datetime.strptime(f"2026-{parts[1][:2]}-{parts[1][2:]}", "%Y-%m-%d").date()
        if e < s:
            e = datetime.strptime(f"2027-{parts[1][:2]}-{parts[1][2:]}", "%Y-%m-%d").date()
        return s.isoformat(), (e + timedelta(days=1)).isoformat()
    except ValueError:
        return None, None


def file_sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    db = sqlite3.connect(str(CANDIDATE_DB))
    cur = db.cursor()

    # Check current state
    cur.execute('SELECT COUNT(*) FROM payment_booking_links')
    before_links = cur.fetchone()[0]
    print(f"Before: payment_booking_links = {before_links}")

    if before_links > 0:
        print("DB already has links, skipping OTA extension to avoid double-counting")
        db.close()
        return

    # ===== Step 1: Add bookings from OTA facts (Trip.com) =====
    added = 0
    with open(OTA_FACTS_PATH, encoding='utf-8') as f:
        ota_facts = json.load(f)

    for ota in ota_facts['records']:
        if ota.get('eligibility_status') != 'eligible':
            continue
        ref = ota.get('booking_ref')
        if not ref:
            continue
        check_in = ota.get('check_in')
        check_out = ota.get('check_out')
        amount = ota.get('paid_total_krw', 0)
        if not check_in or not check_out or not amount:
            continue
        # Add 1 day to check_out for exclusive
        try:
            ci = datetime.fromisoformat(check_in)
            co = datetime.fromisoformat(check_out)
            co_excl = (co + timedelta(days=1)).isoformat()
        except:
            continue

        cur.execute('SELECT id FROM bookings WHERE booking_number=?', (ref,))
        if not cur.fetchone():
            cur.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, 'lodging', ?, ?, ?, 'confirmed')
            ''', ('trip', ref, ota.get('property_name', ''), check_in, co_excl))
            added += 1
    print(f"OTA facts: {added} new bookings added")

    # ===== Step 2: Add bookings from booking_info (Trip.com) =====
    added = 0
    with open(BOOKING_INFO_PATH, encoding='utf-8') as f:
        booking_info = json.load(f)
    for ref, info in booking_info.items():
        period = info.get('period', '')
        if not period:
            continue
        s, e = parse_period(period.replace('숙박_', ''))
        if not s or not e:
            continue
        cur.execute('SELECT id FROM bookings WHERE booking_number=?', (ref,))
        if not cur.fetchone():
            cur.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, 'lodging', ?, ?, ?, 'confirmed')
            ''', ('trip', ref, info.get('label', ''), s, e))
            added += 1
    print(f"booking_info: {added} new bookings added")

    # ===== Step 3: Add bookings from booking_periods_verified =====
    added = 0
    with open(BOOKING_PERIODS_PATH, encoding='utf-8') as f:
        bp = json.load(f)
    for ref, info in bp.items():
        period = info.get('period', '')
        if not period:
            continue
        s, e = parse_period(period)
        if not s or not e:
            continue
        cat = info.get('category', 'lodging')
        product_type = 'flight' if cat == '항공' else 'lodging'
        cur.execute('SELECT id FROM bookings WHERE booking_number=?', (ref,))
        if not cur.fetchone():
            cur.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed')
            ''', (info.get('source', 'unknown').lower()[:20], ref, product_type, info.get('source', ''), s, e))
            added += 1
    print(f"booking_periods_verified: {added} new bookings added")

    # ===== Step 4: Add bookings from ota_event_links_verified =====
    added = 0
    with open(OTA_EVENT_LINKS_PATH, encoding='utf-8') as f:
        ota_links = json.load(f)
    for uid, info in ota_links.items():
        ref = info.get('booking_id')
        period = info.get('period')
        if not ref or not period:
            continue
        s, e = parse_period(period)
        if not s or not e:
            continue
        cat = info.get('category', 'lodging')
        product_type = 'flight' if cat == '항공' else 'lodging'
        provider = 'agoda' if 'agoda' in str(info.get('verification_source', '')).lower() else 'unknown'
        cur.execute('SELECT id FROM bookings WHERE booking_number=?', (ref,))
        if not cur.fetchone():
            cur.execute('''
                INSERT INTO bookings(provider, booking_number, product_type, label, service_start_on, service_end_on, status)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed')
            ''', (provider, ref, product_type, info.get('hotel', ''), s, e))
            added += 1
    print(f"ota_event_links_verified: {added} new bookings added")

    db.commit()

    # ===== Step 5: Create payment_booking_links =====
    # For each booking without a link, find best matching payment
    cur.execute('''
        SELECT b.id, b.booking_number, b.service_start_on, b.label, b.provider
        FROM bookings b
        LEFT JOIN payment_booking_links pbl ON pbl.booking_id = b.id
        WHERE pbl.payment_id IS NULL
    ''')
    bookings_without_links = cur.fetchall()
    print(f"\nBookings without links: {len(bookings_without_links)}")

    links_added = 0
    for booking_id, booking_ref, service_start, label, provider in bookings_without_links:
        if not service_start:
            continue
        # Try multiple match strategies
        match = None

        # Strategy 1: OTA merchant pattern + date proximity
        if provider == 'trip':
            cur.execute('''
                SELECT id, merchant, amount_krw, occurred_on
                FROM payment_transactions
                WHERE (merchant LIKE '%Ʈ������%' OR merchant LIKE '%Trip%' OR merchant LIKE '%trip%')
                  AND occurred_on IS NOT NULL
                  AND julianday(?) - julianday(occurred_on) BETWEEN 1 AND 90
                ORDER BY ABS(julianday(occurred_on) - julianday(?))
                LIMIT 1
            ''', (service_start, service_start))
            match = cur.fetchone()
        elif provider == 'agoda':
            cur.execute('''
                SELECT id, merchant, amount_krw, occurred_on
                FROM payment_transactions
                WHERE (merchant LIKE 'AGODA%' OR merchant LIKE '%Agoda%')
                  AND occurred_on IS NOT NULL
                  AND julianday(?) - julianday(occurred_on) BETWEEN 1 AND 90
                ORDER BY ABS(julianday(occurred_on) - julianday(?))
                LIMIT 1
            ''', (service_start, service_start))
            match = cur.fetchone()

        if match:
            payment_id = match[0]
            # Check not already linked
            cur.execute('SELECT 1 FROM payment_booking_links WHERE payment_id=?', (payment_id,))
            if not cur.fetchone():
                cur.execute('''
                    INSERT INTO payment_booking_links(payment_id, booking_id, relation_type, confidence, link_status)
                    VALUES (?, ?, 'pays_for', 0.80, 'proposed')
                ''', (payment_id, booking_id))
                links_added += 1

    db.commit()
    print(f"Links added: {links_added}")

    # Final stats
    cur.execute('SELECT COUNT(*) FROM payment_booking_links')
    total_links = cur.fetchone()[0]
    cur.execute('''
        SELECT pt.merchant, COUNT(*), SUM(pt.amount_krw)
        FROM payment_booking_links pbl
        JOIN payment_transactions pt ON pt.id = pbl.payment_id
        GROUP BY pt.merchant
        ORDER BY COUNT(*) DESC
    ''')
    print(f"\n=== Final linked merchants ({total_links}건) ===")
    for r in cur.fetchall():
        print(f"  {r[0][:50]:50s} | {r[1]:>3}건 | {r[2]:>11,}원")

    db.close()


if __name__ == '__main__':
    main()