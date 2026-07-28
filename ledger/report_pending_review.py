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
from ledger.domain.ota_reporting import (
    classify_accounting_state,
    classify_payment_state,
    current_payment_decision_states,
    direct_evidence_inventory,
)
from ledger.domain.p0_release_guard import file_sha256, validate_frozen_stage


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
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_report(output_dir: Path) -> dict[str, object]:
    root = LEDGER_DIR.parent
    input_gate = validate_frozen_stage(root, "ota_pending_report")
    classified = list(
        csv.DictReader(
            (LEDGER_DIR / "data" / "classified_v14.csv").open(
                encoding="utf-8-sig"
            )
        )
    )
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
            decision_states = current_payment_decision_states(db)
            evidence_inventory = direct_evidence_inventory(db)
        finally:
            db.close()

    rows: list[dict[str, object]] = []
    for row in classified:
        provider = provider_of(row)
        if not provider:
            continue
        uid = row["uid"]
        state = classify_payment_state(uid, provider, decision_states)
        accounting = classify_accounting_state(row)
        rows.append(
            {
                "uid": uid,
                "provider": provider,
                "date": row.get("use_date", ""),
                "merchant": row.get("merchant", ""),
                "amount_krw": int(round(float(row.get("krw") or 0))),
                "bucket": row.get("bucket", ""),
                "account": row.get("account", ""),
                "cost_type": row.get("cost_type", ""),
                "confidence": row.get("confidence", ""),
                "tax_conf": row.get("tax_conf", ""),
                **accounting,
                **state,
            }
        )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise FileExistsError(f"기존 보고서를 덮어쓰지 않습니다: {output_dir}")
    publish_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    write_csv(publish_dir / "ota_dispositions.csv", rows)
    counts = Counter(str(row["evidence_disposition"]) for row in rows)
    state_counts = Counter(str(row["evidence_state"]) for row in rows)
    accounting_counts = Counter(str(row["accounting_state"]) for row in rows)
    by_provider: dict[str, dict[str, int]] = {}
    for provider in sorted({str(row["provider"]) for row in rows}):
        provider_rows = [row for row in rows if row["provider"] == provider]
        provider_counts = Counter(
            str(row["evidence_disposition"]) for row in provider_rows
        )
        provider_states = Counter(str(row["evidence_state"]) for row in provider_rows)
        provider_accounting = Counter(
            str(row["accounting_state"]) for row in provider_rows
        )
        by_provider[provider] = {
            "total": len(provider_rows),
            "direct_link_confirmed": provider_counts["direct_link_confirmed"],
            "direct_link_conflict": provider_counts["direct_link_conflict"],
            "direct_link_unproven": provider_counts["direct_link_unproven"],
            "classified": provider_accounting["classified"],
            "travel_unassigned": provider_accounting["travel_unassigned"],
            "states": dict(sorted(provider_states.items())),
        }

    accounting_unassigned = [
        row for row in rows if row["accounting_state"] == "travel_unassigned"
    ]
    evidence_conflicts = [
        row for row in rows if row["evidence_disposition"] == "direct_link_conflict"
    ]
    action_rows = []
    for row in rows:
        actions: list[str] = []
        if row["accounting_state"] == "travel_unassigned":
            actions.append("assign_travel_bucket")
        if row["evidence_disposition"] == "direct_link_conflict":
            actions.append("resolve_direct_link_conflict")
        if actions:
            action_rows.append({**row, "required_actions": actions})
    with (publish_dir / "ota_action_queue.json").open(
        "x", encoding="utf-8"
    ) as handle:
        handle.write(json.dumps(action_rows, ensure_ascii=False, indent=2) + "\n")

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
        "schema_version": 3,
        "release_status": "post_filing_audit_open",
        "provenance": {
            "report_code_sha256": file_sha256(Path(__file__)),
            "canonical_sha256": file_sha256(
                LEDGER_DIR / "data" / "classified_v14.csv"
            ),
            "ota_verified_links_sha256": file_sha256(
                LEDGER_DIR / "data" / "ota_event_links_verified.json"
            ),
        },
        "input_gate": input_gate,
        "accounting": {
            "total": len(rows),
            "included_in_canonical": len(rows),
            "classified": accounting_counts["classified"],
            "travel_unassigned": accounting_counts["travel_unassigned"],
            "travel_unassigned_amount_krw": sum(
                int(row["amount_krw"]) for row in accounting_unassigned
            ),
        },
        "direct_link_audit": {
            "total": len(rows),
            "confirmed": counts["direct_link_confirmed"],
            "conflict": counts["direct_link_conflict"],
            "unproven": counts["direct_link_unproven"],
            "states": dict(sorted(state_counts.items())),
            "by_provider": by_provider,
            "direct_evidence_inventory": evidence_inventory,
            "direct_match_engine": import_result["direct_ota_matches"],
        },
        "action_queue": {
            "total_distinct": len(action_rows),
            "total_amount_krw": sum(int(row["amount_krw"]) for row in action_rows),
            "travel_unassigned": len(accounting_unassigned),
            "direct_link_conflicts": len(evidence_conflicts),
            "artifact": "ota_action_queue.json",
        },
        "ota": {
            "deprecated": True,
            "note": "Use accounting and direct_link_audit; unproven is not filing-unresolved.",
            "total": len(rows),
            "confirmed": counts["direct_link_confirmed"],
            "hold": counts["direct_link_conflict"],
            "pending": counts["direct_link_unproven"],
        },
        "hana_hold_count": len(hana_holds),
        "non_ota_resolved_count": len(non_ota),
        "rules": [
            "all card events retained",
            "only current append-only decisions can confirm a payment",
            "legacy verified-link membership remains proposed or conflict",
            "only actual conflicts remain HOLD; unprocessed rows remain pending",
            "direct-link unproven does not mean accounting or filing unresolved",
            "portal display currency or display amount alone never proves a charge",
            "refunds and cancellations remain independent events",
        ],
    }
    for name, value in (
        ("summary.json", summary),
        ("hana_holds.json", hana_holds),
        ("non_ota_resolved.json", non_ota),
    ):
        with (publish_dir / name).open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    publish_dir.replace(output_dir)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/20260728_decision_authoritative_review_v10"),
    )
    args = parser.parse_args()
    print(json.dumps(build_report(args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
