#!/usr/bin/env python3
"""Build a privacy-safe disposition report for every pending cost item."""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

from ledger.domain.direct_sources import import_all
from ledger.domain.ledger_db import (
    DEFAULT_BOOKINGS,
    DEFAULT_CSV,
    DEFAULT_TRIPS,
    LEDGER_DIR,
    connect,
    import_legacy,
    initialize,
)


def provider_of(row: dict[str, str]) -> str:
    text = f"{row.get('merchant', '')} {row.get('note', '')}".upper()
    if any(token in text for token in ("마이트립", "MYTRIP", "고투게이트")):
        return "mytrip"
    if any(token in text for token in ("트립닷컴", "TRIP.COM", "CTRIP")):
        return "trip"
    if any(token in text for token in ("AGODA", "아고다")):
        return "agoda"
    if "BOOKING.COM" in text:
        return "booking"
    if any(token in text for token in ("트래블로버", "TRAVELROVER")):
        return "travelrover"
    return ""


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else [
        "uid", "provider", "date", "merchant", "amount_krw", "bucket",
        "disposition", "reason_code",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_report(output_dir: Path) -> dict[str, object]:
    classified = list(
        csv.DictReader(
            (LEDGER_DIR / "data" / "classified_v14.csv").open(
                encoding="utf-8-sig"
            )
        )
    )
    verified_path = LEDGER_DIR / "data" / "ota_event_links_verified.json"
    verified = json.loads(verified_path.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as dirname:
        db = connect(Path(dirname) / "pending-review.db")
        try:
            initialize(db)
            import_legacy(db, DEFAULT_CSV, DEFAULT_TRIPS, DEFAULT_BOOKINGS)
            import_result = import_all(
                db,
                LEDGER_DIR,
                LEDGER_DIR / "data" / "manual_v4.csv",
                LEDGER_DIR / "data" / "ota_mail_index.json",
            )
            direct_confirmed = {
                str(row["external_key"])
                for row in db.execute(
                    """
                    SELECT DISTINCT payment.external_key
                    FROM current_payment_booking_links link
                    JOIN payment_transactions payment
                      ON payment.id=link.payment_id
                    WHERE link.link_status='confirmed'
                    """
                ).fetchall()
            }
            direct_conflicts = {
                str(row["external_key"])
                for row in db.execute(
                    """
                    SELECT DISTINCT payment.external_key
                    FROM current_match_group_projection projection
                    JOIN match_group_payments member
                      ON member.group_id=projection.group_id
                    JOIN payment_transactions payment
                      ON payment.id=member.payment_id
                    WHERE projection.status='conflict'
                    """
                ).fetchall()
            }
        finally:
            db.close()

    rows: list[dict[str, object]] = []
    for row in classified:
        provider = provider_of(row)
        if not provider:
            continue
        uid = row["uid"]
        if uid in verified:
            disposition = "confirmed_existing"
            reason = "existing_verified_link"
        elif uid in direct_confirmed:
            disposition = "confirmed_direct"
            reason = "unique_direct_payment_intersection"
        elif uid in direct_conflicts:
            disposition = "hold"
            reason = "non_unique_repeated_amount"
        else:
            disposition = "hold"
            reason = "no_unique_direct_evidence"
        rows.append(
            {
                "uid": uid,
                "provider": provider,
                "date": row.get("use_date", ""),
                "merchant": row.get("merchant", ""),
                "amount_krw": int(round(float(row.get("krw") or 0))),
                "bucket": row.get("bucket", ""),
                "disposition": disposition,
                "reason_code": reason,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "ota_dispositions.csv", rows)
    counts = Counter(str(row["disposition"]) for row in rows)
    by_provider: dict[str, dict[str, int]] = {}
    for provider in sorted({str(row["provider"]) for row in rows}):
        provider_rows = [row for row in rows if row["provider"] == provider]
        provider_counts = Counter(
            str(row["disposition"]) for row in provider_rows
        )
        by_provider[provider] = {
            "total": len(provider_rows),
            "confirmed_existing": provider_counts["confirmed_existing"],
            "confirmed_direct": provider_counts["confirmed_direct"],
            "hold": provider_counts["hold"],
        }

    hana_holds = [
        {
            "scope": "hana_snapshot",
            "merchant": "AVIS",
            "approval_number": "107633",
            "final_billed_amount_krw": 393383,
            "reason_code": "existing_event_final_amount_snapshot_conflict",
        },
        {
            "scope": "hana_snapshot",
            "merchant": "SICILY BY CAR",
            "approval_number": "407242",
            "final_billed_amount_krw": 227861,
            "reason_code": "existing_event_final_amount_snapshot_conflict",
        },
        {
            "scope": "hana_snapshot",
            "merchant": "HERTZ",
            "approval_number": "305072",
            "final_billed_amount_krw": 423524,
            "reason_code": "existing_event_final_amount_snapshot_conflict",
        },
        {
            "scope": "hana_cancellation",
            "merchant": "KUROSHIONOMORIMANGROVEPAR",
            "date": "2026-02-26",
            "card_last4": "6741",
            "amount_krw": -56666,
            "reason_code": "blank_approval_original_not_inferred",
        },
    ]
    non_ota = [
        {
            "uid": "KBD-0403",
            "disposition": "confirmed_overhead",
            "allocation_target": "기타비용",
            "expense_type": "주차비",
            "amount_krw": 2400,
        },
        {
            "uid": "CORP-2005",
            "disposition": "confirmed_cancellation_clearing",
            "allocation_target": "취소환불_정산",
            "amount_krw": 0,
        },
    ]
    summary: dict[str, object] = {
        "schema_version": 1,
        "ota": {
            "total": len(rows),
            "confirmed_existing": counts["confirmed_existing"],
            "confirmed_direct": counts["confirmed_direct"],
            "hold": counts["hold"],
            "by_provider": by_provider,
            "direct_match_engine": import_result["direct_ota_matches"],
        },
        "hana_hold_count": len(hana_holds),
        "non_ota_resolved_count": len(non_ota),
        "rules": [
            "all card events retained",
            "only unique direct intersections confirmed",
            "N:M and missing evidence remain HOLD",
            "refunds and cancellations remain independent events",
        ],
    }
    for name, value in (
        ("summary.json", summary),
        ("hana_holds.json", hana_holds),
        ("non_ota_resolved.json", non_ota),
    ):
        (output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/20260727_all_pending_review"),
    )
    args = parser.parse_args()
    print(json.dumps(build_report(args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
