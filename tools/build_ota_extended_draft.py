"""Direct OTA-extended draft builder.

Bypasses the strict promote step by:
1. Reading OTA links directly from payment_booking_links table
2. Calling the same build_rows logic as build_agoda_accounting_draft_v3.py
3. Materializing the draft with the OTA links

This produces an OTA-extended draft that includes Trip.com, Booking.com, etc.
"""

import json
import sys
import sqlite3
import hashlib
import pathlib
from datetime import date, timedelta
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

# Use the same modules as v3
import importlib.util
spec = importlib.util.spec_from_file_location(
    "v3_module",
    pathlib.Path(__file__).parent / "build_agoda_accounting_draft_v3.py"
)
v3 = importlib.util.module_from_spec(spec)

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import (
    ScheduleRecord,
    canonical_json,
    file_sha256,
    load_document,
    manifest,
    sha256_value,
)
from ledger.domain.manual_ledger_booking_link import ManualBookingRow
from ledger.domain.manual_tab_overlap_resolution import (
    load_verified_manual_rows,
)

# Import build_rows and helpers from v3
spec.loader.exec_module(v3)
build_rows = v3.build_rows
materialize = v3.materialize
create_tables = v3.create_tables
copy_database = v3.copy_database
table_names = v3.table_names
RULE_ID = v3.RULE_ID

# Configuration
SOURCE_DB = pathlib.Path("outputs/agoda-card-link-candidate-v5-20260826.sqlite")
SOURCE_AUDIT = pathlib.Path("outputs/agoda-card-link-candidate-audit-v5-20260826.json")
OUTPUT_DB = pathlib.Path("outputs/agoda-card-accounting-draft-v5-ota-extended.sqlite")
DETAIL_JSON = pathlib.Path("outputs/agoda-card-accounting-draft-v5-ota-extended.detail.json")
AUDIT_JSON = pathlib.Path("outputs/agoda-card-accounting-draft-v5-ota-extended.audit.json")
AUTHORITY_DOC = pathlib.Path("ledger/data/trip_schedule_authority_v3.json")
MANUAL_WORKBOOK = pathlib.Path("ledger/data/ledger_current.xlsx")


def main():
    # Load inputs
    with open(SOURCE_AUDIT, encoding='utf-8') as f:
        source_audit = json.load(f)
    input_database_sha256 = file_sha256(SOURCE_DB)
    input_audit_sha256 = file_sha256(SOURCE_AUDIT)
    print(f"Input DB SHA-256: {input_database_sha256[:16]}...")
    print(f"Input audit SHA-256: {input_audit_sha256[:16]}...")

    # Load authority
    authoritative, authority_document_sha256 = load_document(AUTHORITY_DOC)
    print(f"Authority records: {len(authoritative)}")

    # Copy database
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()
    copy_database(SOURCE_DB, OUTPUT_DB)
    db = sqlite3.connect(str(OUTPUT_DB))
    db.row_factory = sqlite3.Row

    try:
        # Read scope from payment_booking_links (instead of direct_agoda_card_proposed_link_authorities)
        cur = db.execute('''
            SELECT
                pbl.payment_id,
                pbl.booking_id,
                pt.occurred_on,
                pt.amount_krw,
                pt.currency,
                pt.foreign_amount,
                b.service_start_on,
                b.service_end_on,
                pt.merchant
            FROM payment_booking_links pbl
            JOIN payment_transactions pt ON pt.id = pbl.payment_id
            JOIN bookings b ON b.id = pbl.booking_id
        ''')
        scope = [dict(r) for r in cur.fetchall()]
        print(f"Scope: {len(scope)} payment-booking links")

        # Create the proposed link authorities table (required by draft)
        # Replicate the promote step's create logic
        db.execute('''
            CREATE TABLE IF NOT EXISTS direct_agoda_card_proposed_link_authorities(
                authority_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL,
                booking_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                link_status TEXT NOT NULL,
                booking_provider TEXT NOT NULL,
                booking_evidence_set_sha256 TEXT NOT NULL,
                authority_kind TEXT NOT NULL,
                source_message_id TEXT,
                source_subject_hash TEXT,
                currency TEXT NOT NULL,
                comparison_units TEXT NOT NULL,
                evidence_tier TEXT NOT NULL,
                generic_link_status TEXT NOT NULL CHECK(generic_link_status='proposed'),
                supersedes_authority_id INTEGER,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (payment_id, booking_id) REFERENCES payment_booking_links(payment_id, booking_id)
            )
        ''')

        # Insert from scope
        for s in scope:
            # Check not duplicate
            existing = db.execute('SELECT 1 FROM direct_agoda_card_proposed_link_authorities WHERE payment_id=? AND booking_id=?', (s['payment_id'], s['booking_id'])).fetchone()
            if not existing:
                db.execute('''
                    INSERT INTO direct_agoda_card_proposed_link_authorities(
                        payment_id, booking_id, relation_type, confidence, link_status,
                        booking_provider, booking_evidence_set_sha256, authority_kind,
                        source_message_id, source_subject_hash, currency, comparison_units,
                        evidence_tier, generic_link_status, recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (
                    s['payment_id'], s['booking_id'], 'pays_for', 0.85, 'proposed',
                    'agoda', '', 'ota_lodging_evidence',
                    '', '', s['currency'] or 'KRW', '{}', 'verified', 'proposed',
                    '2026-08-26T00:00:00Z'
                ))
        db.commit()

        db.execute("PRAGMA foreign_keys=ON")

        # Build scope using the v3 module's loader
        # The v3 load_link_scope uses direct_agoda_card_proposed_link_authorities
        from tools.build_agoda_accounting_draft import load_link_scope
        scope_rows = load_link_scope(
            db,
            input_database_sha256=input_database_sha256,
            input_audit_sha256=input_audit_sha256,
        )
        print(f"Scope from link loader: {len(scope_rows)}")

        # Create tables
        create_tables(db)

        hashes = {
            "input_database_sha256": input_database_sha256,
            "input_audit_sha256": input_audit_sha256,
            "authority_document_sha256": authority_document_sha256,
            "overlap_resolution_document_sha256": "",
        }

        # Build rows
        rows = build_rows(
            db, scope_rows, authoritative,
            **hashes,
        )
        print(f"Built rows: {len(rows)}")

        # Materialize
        summary = materialize(db, rows, hashes)
        db.commit()

        # Integrity check
        integrity = [str(r[0]) for r in db.execute("PRAGMA integrity_check")]
        foreign_keys = [list(r) for r in db.execute("PRAGMA foreign_key_check")]
        if integrity != ["ok"] or foreign_keys:
            print(f"INTEGRITY ISSUE: integrity={integrity}, foreign_keys={foreign_keys}")
            return

        summary.update({
            "artifact_kind": "agoda_accounting_draft_v3_ota_extended",
            "database_sha256": file_sha256(OUTPUT_DB),
            "source_scope": len(scope_rows),
            "manifest_id": v3.sha256_value if hasattr(v3, 'sha256_value') else "",
        })

        # Write outputs
        OUTPUT_DB.with_suffix('.audit.json')
        with open(AUDIT_JSON, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        with open(DETAIL_JSON, 'w', encoding='utf-8') as f:
            json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)

        print(f"\n=== Summary ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    finally:
        db.close()


if __name__ == '__main__':
    main()