"""Import non-Agoda OTA emails (Booking.com, Trip.com, KLOOK) into direct_source_records."""

import json
import sys
import sqlite3
import hashlib
import pathlib

sys.stdout.reconfigure(encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = pathlib.Path("outputs/agoda-card-link-candidate-v5-20260826.sqlite")
LIVE = pathlib.Path("ledger/data/ota_mail_live_index.json")
FULL = pathlib.Path("ledger/data/ota_mail_index.json")
RUN_ID = "ota_mail_non_agoda_2026"


def main():
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row

    inserted = 0
    skipped = 0
    for path in [LIVE, FULL]:
        if not path.exists():
            continue
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        records = d.get('records', [])
        print(f"{path.name}: {len(records)} records")
        for r in records:
            provider = (r.get('provider') or '').strip().casefold()
            if provider == 'agoda':
                continue  # handled by import_agoda_mail_index
            if not provider:
                skipped += 1
                continue

            message_id = r.get('messageId') or r.get('message_id')
            if not message_id:
                continue

            # Check if already exists
            cur = db.execute('SELECT 1 FROM direct_source_records WHERE source_kind=? AND source_key=?', ('ota_mail_non_agoda', message_id))
            if cur.fetchone():
                continue

            # Build payload
            payload = dict(r)
            payload['provider'] = r.get('provider', '')
            payload['source_file'] = path.name
            payload['run_id'] = RUN_ID
            payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            payload_sha = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()

            db.execute('''
                INSERT INTO direct_source_records(
                    source_kind, source_key, source_sha256, payload_json, redaction_version
                ) VALUES (?, ?, ?, ?, ?)
            ''', ('ota_mail_non_agoda', message_id, payload_sha, payload_str, 1))
            inserted += 1

    db.commit()
    print(f"\nInserted: {inserted}")
    print(f"Skipped: {skipped}")

    # Final state
    cur = db.execute("SELECT source_kind, COUNT(*) FROM direct_source_records GROUP BY source_kind")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")
    db.close()


if __name__ == '__main__':
    main()