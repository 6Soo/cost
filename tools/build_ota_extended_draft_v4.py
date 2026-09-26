"""Simplified OTA-extended draft builder.

Reads OTA links from candidate DB and creates accounting draft rows directly
using the same trip authority matching logic.
"""

import argparse
import json
import sys
import sqlite3
import hashlib
import pathlib
from datetime import date, timedelta
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import (
    ScheduleRecord,
    canonical_json,
    file_sha256,
    load_document,
    match_service_period,
    manifest,
    sha256_value,
)

SOURCE_DB = pathlib.Path("outputs/agoda-card-link-candidate-v5-20260826.sqlite")
SOURCE_AUDIT = pathlib.Path("outputs/agoda-card-link-candidate-audit-v5-20260826.json")
OUTPUT_DB = pathlib.Path("outputs/agoda-card-accounting-draft-v5-ota-extended.sqlite")
DETAIL_JSON = pathlib.Path("outputs/agoda-card-accounting-draft-v5-ota-extended.detail.json")
AUDIT_JSON = pathlib.Path("outputs/agoda-card-accounting-draft-v5-ota-extended.audit.json")
AUTHORITY_DOC = pathlib.Path("ledger/data/trip_schedule_authority_v3.json")

RULE_ID = "agoda-linked-lodging-accounting-draft-v3-ota-extended"
UNASSIGNED_TARGET = "검토_미배정"


def normalize_service_period(start, end):
    """Convert start/end to (start, end_exclusive, last_service)."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    last = e - timedelta(days=1)
    return s, e, last


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-db", default=str(OUTPUT_DB))
    parser.add_argument("--detail", default=str(DETAIL_JSON))
    parser.add_argument("--audit", default=str(AUDIT_JSON))
    args = parser.parse_args()
    output_db = pathlib.Path(args.output_db)
    detail_json = pathlib.Path(args.detail)
    audit_json = pathlib.Path(args.audit)
    for target in (output_db, detail_json, audit_json):
        if target.exists():
            raise SystemExit(f"output exists, refusing to overwrite: {target}")
    input_database_sha256 = file_sha256(SOURCE_DB)
    input_audit_sha256 = file_sha256(SOURCE_AUDIT)
    print(f"Input DB: {input_database_sha256[:16]}...")

    # Load authority
    authoritative, authority_document_sha256 = load_document(AUTHORITY_DOC)
    print(f"Authority: {len(authoritative)} records")

    # Open source DB and read links
    db = sqlite3.connect(str(SOURCE_DB))
    db.row_factory = sqlite3.Row
    cur = db.execute('''
        SELECT
            pbl.payment_id,
            pbl.booking_id,
            pbl.link_status,
            b.booking_number,
            b.provider
        FROM payment_booking_links pbl
        JOIN bookings b ON b.id = pbl.booking_id
        WHERE pbl.link_status != 'rejected'
    ''')
    link_meta = {r['payment_id']: dict(r) for r in cur.fetchall()}

    # held (OTA에 결제 청구 없는 booking): v5 JSON에서 로드
    held_map = {}
    source_json = pathlib.Path(str(SOURCE_DB)).with_suffix('.json')
    if source_json.exists():
        with open(source_json, 'r', encoding='utf-8') as f:
            jd = json.load(f)
        for h in jd.get('held', []):
            if isinstance(h, dict) and h.get('reason') == 'no_actual_charge_claim':
                held_map[h['booking_id']] = h
    print(f"Held (no_actual_charge_claim): {len(held_map)}")

    cur = db.execute('''
        SELECT
            pbl.payment_id,
            pbl.booking_id,
            pt.occurred_on,
            pt.amount_krw,
            pt.currency,
            b.service_start_on,
            b.service_end_on,
            pt.merchant
        FROM payment_booking_links pbl
        JOIN payment_transactions pt ON pt.id = pbl.payment_id
        JOIN bookings b ON b.id = pbl.booking_id
        WHERE pbl.link_status != 'rejected'
    ''')
    scope = [dict(r) for r in cur.fetchall()]
    print(f"Scope: {len(scope)} links")
    db.close()

    # Build draft rows
    rows = []
    for s in sorted(scope, key=lambda x: (x['occurred_on'], x['payment_id'])):
        payment_id = s['payment_id']
        booking_id = s['booking_id']
        occurred_on = s['occurred_on']
        amount = s['amount_krw']
        currency = s['currency']
        merchant = s['merchant']
        # Strip T00:00:00 from datetime
        service_start = str(s['service_start_on'])[:10]
        service_end = str(s['service_end_on'])[:10]

        # Payment year
        try:
            pay_year = int(occurred_on[:4])
        except:
            pay_year = 2026

        payment_lane = f"{pay_year}년 경리"

        # Match service period against authority (candidate 권위도 매칭: payment_year_terminal용)
        try:
            matches = match_service_period(service_start, service_end, authoritative, authoritative_only=False)
        except Exception as e:
            matches = []

        # v4 가드 v2: 매칭 우선순위 재정의
        # 1) 명시 여행 권위(매칭 가능) → 종결 (held 무관)
        # 2) payment_year_terminal(2025 종결) → 종결 (held 무관)
        # 3) OTA no_actual_charge + 식별자약함 + 권위 매칭 없음 → review_needed
        # 4) 그 외 → authority_missing
        AUTHORITATIVE_KINDS = {"official_event_schedule", "explicit_trip_registry", "user_confirmed_schedule"}
        explicit_matches = [m for m in matches if getattr(m, 'authority_kind', '') in AUTHORITATIVE_KINDS]
        terminal_matches = [m for m in matches if getattr(m, 'authority_kind', '') == 'payment_year_terminal']

        if len(explicit_matches) == 1:
            target_trip = explicit_matches[0].trip_code
            target_status = "bound_unique"
            target_authority = "authoritative_explicit_period"
        elif len(explicit_matches) > 1:
            target_trip = explicit_matches[0].trip_code
            target_status = "authority_ambiguous"
            target_authority = "authoritative_explicit_period"
        elif len(terminal_matches) == 1:
            target_trip = terminal_matches[0].trip_code
            target_status = "payment_year_terminal"
            target_authority = "payment_year_terminal"
        else:
            # 권위 매칭 안 될 때만 가드 적용
            held_info = held_map.get(booking_id)
            identifiers = []
            cur2 = sqlite3.connect(str(SOURCE_DB)).execute(
                "SELECT identifier_type FROM booking_identifiers WHERE booking_id=?", (booking_id,))
            identifiers = [r[0] for r in cur2.fetchall()]
            has_strong_identifier = any(t in identifiers for t in ('reference_code', 'agoda_reference'))
            if held_info and not has_strong_identifier:
                target_trip = UNASSIGNED_TARGET
                target_status = "review_needed"
                target_authority = "portal_no_charge_claim"
            else:
                target_trip = UNASSIGNED_TARGET
                target_status = "authority_missing"
                target_authority = "none"

        # Service year
        try:
            service_year = int(service_start[:4])
        except:
            service_year = 2026

        row = {
            "rule_id": RULE_ID,
            "draft_id": sha256_value({"p": payment_id, "b": booking_id, "r": RULE_ID}),
            "draft_sha256": "",  # filled later
            "payment_id": payment_id,
            "booking_id": booking_id,
            "external_key": f"ota-extended:{payment_id}:{booking_id}",
            "event_year": service_year,
            "payment_year": pay_year,
            "service_year": service_year,
            "service_start_on": service_start,
            "service_end_on": service_end,
            "occurred_on": occurred_on,
            "payment_lane": payment_lane,
            "merchant": merchant,
            "currency": currency or "KRW",
            "amount_krw": amount,
            "account": "숙박비",
            "cost_type": "여행경비",
            "allocation_target": target_trip,
            "target_trip_candidates": [m.trip_code for m in matches],
            "target_authority": target_authority,
            "target_match_status": target_status,
            "target_type": "trip",
            "decision_status": "proposed",
            "posting_eligible": False,
            "link_authority_id": sha256_value({"p": payment_id, "b": booking_id}),
            "input_database_sha256": input_database_sha256,
            "input_audit_sha256": input_audit_sha256,
            "authority_document_sha256": authority_document_sha256,
            "authority_manifest_sha256": "",
            "authority_candidate_targets": [m.trip_code for m in matches],
            "booking_evidence_set_sha256": "",
            "overlap_resolution": None,
            "overlap_resolution_document_sha256": "",
        }
        rows.append(row)

    # Compute manifest sha
    manifest_sha = sha256_value([r["target_trip_candidates"] for r in rows])
    for r in rows:
        r["authority_manifest_sha256"] = manifest_sha
        r["draft_sha256"] = sha256_value(r)

    # Summary
    cnt = Counter(r['target_match_status'] for r in rows)
    by_provider = Counter(r['merchant'] for r in rows)
    by_trip = Counter(r['allocation_target'] for r in rows)
    total = sum(r['amount_krw'] for r in rows)

    print(f"\n=== Summary ===")
    print(f"Total rows: {len(rows)}")
    print(f"Total amount: {total:,}원")
    print(f"\nBy match status:")
    for k, v in cnt.most_common():
        print(f"  {k}: {v}건")
    print(f"\nBy trip (top 20):")
    for k, v in by_trip.most_common(20):
        print(f"  {k}: {v}건")
    print(f"\nBy merchant (top 20):")
    for k, v in by_provider.most_common(20):
        print(f"  {k[:50]}: {v}건")

    # Write outputs
    audit = {
        "artifact_kind": "agoda_accounting_draft_v3_ota_extended",
        "rule_id": RULE_ID,
        "row_count": len(rows),
        "source_scope": len(rows),
        "authority_document_sha256": authority_document_sha256,
        "input_database_sha256": input_database_sha256,
        "input_audit_sha256": input_audit_sha256,
        "manifest_id": manifest_sha,
        "bound_unique_count": cnt.get('bound_unique', 0),
        "authority_ambiguous_count": cnt.get('authority_ambiguous', 0),
        "authority_missing_count": cnt.get('authority_missing', 0),
        "payment_year_terminal_count": cnt.get('payment_year_terminal', 0),
        "total_amount_krw": total,
    }

    with open(audit_json, 'w', encoding='utf-8') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    with open(detail_json, 'w', encoding='utf-8') as f:
        json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)

    # Build minimal SQLite database
    db = sqlite3.connect(str(output_db))
    db.execute('''CREATE TABLE draft_rows(
        rule_id TEXT, payment_id INTEGER, booking_id INTEGER,
        allocation_target TEXT, target_match_status TEXT,
        amount_krw INTEGER, service_start_on TEXT, service_end_on TEXT,
        occurred_on TEXT, merchant TEXT
    )''')
    for r in rows:
        db.execute('''INSERT INTO draft_rows VALUES (?,?,?,?,?,?,?,?,?,?)''', (
            r['rule_id'], r['payment_id'], r['booking_id'],
            r['allocation_target'], r['target_match_status'],
            r['amount_krw'], r['service_start_on'], r['service_end_on'],
            r['occurred_on'], r['merchant']
        ))
    db.commit()
    db.close()

    print(f"\nFiles written:")
    print(f"  {output_db}")
    print(f"  {detail_json}")
    print(f"  {audit_json}")


if __name__ == '__main__':
    main()