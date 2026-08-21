#!/usr/bin/env python3
"""Read-only, privacy-safe Agoda boundary coverage audit.

The report deliberately emits counts and field presence only.  It never prints
booking IDs, message IDs, card identifiers, merchant text, or payloads.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_FILES = (
    "ledger/data/ota_mail_index.json",
    "ledger/data/ota_mail_live_index.json",
    "ledger/data/booking_info.json",
    "ledger/data/booking_periods_verified.json",
    "ledger/data/ota_event_links_verified.json",
    "ledger/data/ota_lodging_facts_v2.json",
    "ledger/data/ota_reconcile_report.json",
    "ledger/data/pg_mail_index.json",
    "ledger/data/pg_mail_supplemental_index.json",
    "ledger/data/service_mail_index.json",
)

KEY_FIELDS = (
    "reservation_id",
    "booking_id",
    "message_id",
    "mail_id",
    "source_key",
    "event_key",
    "external_key",
    "messageId",
    "messageHash",
    "bookingRef",
    "uid",
)

MONTH_2025_08 = re.compile(r"2025[-/.]08|2025\s*년\s*8월|08[-/.]2025")


def _record_nodes(value: Any) -> list[dict[str, Any]]:
    """Collect nested objects that contain at least one scalar field.

    Several source indexes are grouped dictionaries rather than flat arrays;
    counting only the root object would under-report their coverage.
    """
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if any(not isinstance(item, (dict, list)) for item in node.values()):
                found.append(node)
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return found


def _safe_text(value: Any) -> str:
    # Counting date/year markers needs a normalized representation; it is never
    # returned to the caller.
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _date_text(value: Any) -> str:
    """Return only date-like fields for year/month coverage counts."""
    pieces: list[str] = []

    def visit(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                lowered = child_key.lower()
                if any(
                    token in lowered
                    for token in (
                        "date",
                        "time",
                        "period",
                        "start",
                        "end",
                        "check",
                        "service",
                        "occur",
                        "sent",
                        "received",
                        "updated",
                        "created",
                    )
                ):
                    pieces.append(_safe_text(child))
                elif isinstance(child, (dict, list)):
                    visit(child, child_key)
        elif isinstance(node, list):
            for child in node:
                visit(child, key)

    visit(value)
    return " ".join(pieces)


def audit(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {"file": str(path), "status": "invalid", "error_type": type(exc).__name__}

    rows = _record_nodes(value)
    texts = [_safe_text(row) for row in rows]
    date_texts = [_date_text(row) for row in rows]
    agoda_flags = [
        "agoda" in text.lower() or "아고다" in text for text in texts
    ]
    field_presence: dict[str, int] = collections.Counter()
    field_duplicates: dict[str, int] = {}
    scalar_key_names: set[str] = set()
    for field in KEY_FIELDS:
        values = [
            str(row.get(field))
            for row in rows
            if isinstance(row, dict) and row.get(field) not in (None, "")
        ]
        if values:
            field_presence[field] = len(values)
            field_duplicates[field] = len(values) - len(set(values))
    for row in rows:
        if isinstance(row, dict):
            scalar_key_names.update(
                key for key, value in row.items() if not isinstance(value, (dict, list))
            )

    return {
        "file": str(path),
        "status": "ok",
        "rows": len(rows),
        "agoda_marker_matches": sum(agoda_flags),
        "2025_08_date_matches": sum(
            bool(MONTH_2025_08.search(text)) for text in date_texts
        ),
        "2026_date_matches": sum("2026" in text for text in date_texts),
        "agoda_2025_08_date_matches": sum(
            flag and bool(MONTH_2025_08.search(text))
            for flag, text in zip(agoda_flags, date_texts)
        ),
        "agoda_2026_date_matches": sum(
            flag and "2026" in text for flag, text in zip(agoda_flags, date_texts)
        ),
        "field_presence": dict(sorted(field_presence.items())),
        "field_duplicates": dict(sorted(field_duplicates.items())),
        "scalar_key_names": sorted(scalar_key_names)[:80],
    }


def audit_candidate_db(path: Path) -> dict[str, Any]:
    """Aggregate Agoda-like card rows without emitting row-level data."""
    uri = f"file:{path.resolve()}?mode=ro&immutable=1"
    try:
        db = sqlite3.connect(uri, uri=True)
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {"db": str(path), "status": "unreadable", "error_type": type(exc).__name__}
    try:
        rows = db.execute(
            """
            SELECT substr(COALESCE(pt.occurred_on, ''), 1, 7) AS month,
                   pt.transaction_type, COUNT(*), COALESCE(SUM(pt.amount_krw), 0)
            FROM payment_transactions AS pt
            WHERE lower(COALESCE(pt.merchant, '')) LIKE '%agoda%'
            GROUP BY month, pt.transaction_type
            ORDER BY month, pt.transaction_type
            """
        ).fetchall()
        month_row = db.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(pt.amount_krw), 0),
                   COUNT(DISTINCT pbl.payment_id), COUNT(pbl.payment_id)
            FROM payment_transactions AS pt
            LEFT JOIN payment_booking_links AS pbl ON pbl.payment_id = pt.id
            WHERE lower(COALESCE(pt.merchant, '')) LIKE '%agoda%'
              AND substr(COALESCE(pt.occurred_on, ''), 1, 7) = '2025-08'
            """
        ).fetchone()
        link_status_rows = db.execute(
            """
            SELECT COALESCE(pbl.link_status, 'no_link'), COUNT(*)
            FROM payment_transactions AS pt
            LEFT JOIN payment_booking_links AS pbl ON pbl.payment_id = pt.id
            WHERE lower(COALESCE(pt.merchant, '')) LIKE '%agoda%'
              AND substr(COALESCE(pt.occurred_on, ''), 1, 7) = '2025-08'
            GROUP BY COALESCE(pbl.link_status, 'no_link')
            ORDER BY 1
            """
        ).fetchall()
        return {
            "db": str(path),
            "status": "ok",
            "agoda_month_type_aggregates": [
                {
                    "month": row[0],
                    "transaction_type": row[1],
                    "count": row[2],
                    "amount_krw": row[3],
                }
                for row in rows
            ],
            "agoda_2025_08_payment_summary": {
                "count": month_row[0],
                "amount_krw": month_row[1],
                "distinct_linked_payments": month_row[2],
                "link_rows": month_row[3],
                "link_status_counts": {
                    row[0]: row[1] for row in link_status_rows
                },
            },
        }
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {"db": str(path), "status": "query_error", "error_type": type(exc).__name__}
    finally:
        db.close()


def _amount(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(round(float(str(value).replace(",", "").strip())))
    except (TypeError, ValueError):
        return None


def audit_reconcile_report(report_path: Path, candidate_db: Path) -> dict[str, Any]:
    """Compare only date/amount signatures; never emit row values."""
    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        report_rows = _record_nodes(raw)
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {
            "report": str(report_path),
            "status": "unreadable",
            "error_type": type(exc).__name__,
        }

    report_agoda = []
    report_aug = []
    for row in report_rows:
        text = _safe_text(row).lower()
        date = str(row.get("date") or row.get("occurred_on") or "")[:10]
        amount = _amount(row.get("amount"))
        if "agoda" in text or "아고다" in text:
            report_agoda.append((date, amount))
            if date.startswith("2025-08"):
                report_aug.append((date, amount))

    uri = f"file:{candidate_db.resolve()}?mode=ro&immutable=1"
    try:
        db = sqlite3.connect(uri, uri=True)
        payments = db.execute(
            """
            SELECT substr(COALESCE(occurred_on, ''), 1, 10), amount_krw
            FROM payment_transactions
            WHERE lower(COALESCE(merchant, '')) LIKE '%agoda%'
              AND substr(COALESCE(occurred_on, ''), 1, 7) = '2025-08'
            """
        ).fetchall()
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {
            "report": str(report_path),
            "status": "db_unreadable",
            "error_type": type(exc).__name__,
        }
    finally:
        try:
            db.close()
        except UnboundLocalError:
            pass

    report_exact = collections.Counter(report_aug)
    report_amounts = collections.Counter(amount for _, amount in report_aug if amount is not None)
    exact_rows = sum((date, amount) in report_exact for date, amount in payments)
    amount_rows = sum(amount in report_amounts for _, amount in payments)
    return {
        "report": str(report_path),
        "status": "ok",
        "report_record_count": len(report_rows),
        "report_agoda_marker_count": len(report_agoda),
        "report_agoda_2025_08_count": len(report_aug),
        "candidate_agoda_2025_08_count": len(payments),
        "candidate_rows_exact_date_amount_match": exact_rows,
        "candidate_rows_amount_only_match": amount_rows,
    }


def audit_pg_matches(pg_path: Path, candidate_db: Path) -> dict[str, Any]:
    """Compare August Agoda card signatures with PG mail payment facts."""
    try:
        raw = json.loads(pg_path.read_text(encoding="utf-8"))
        pg_rows = _record_nodes(raw)
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {"pg_mail": str(pg_path), "status": "unreadable", "error_type": type(exc).__name__}

    pg_signatures: list[tuple[str, int | None]] = []
    pg_august = 0
    for row in pg_rows:
        date = str(row.get("payment_date") or row.get("payment_at") or "")[:10]
        amount = _amount(row.get("amount_krw"))
        if date.startswith("2025-08"):
            pg_august += 1
            pg_signatures.append((date, amount))

    uri = f"file:{candidate_db.resolve()}?mode=ro&immutable=1"
    try:
        db = sqlite3.connect(uri, uri=True)
        payments = db.execute(
            """
            SELECT substr(COALESCE(occurred_on, ''), 1, 10), amount_krw
            FROM payment_transactions
            WHERE lower(COALESCE(merchant, '')) LIKE '%agoda%'
              AND substr(COALESCE(occurred_on, ''), 1, 7) = '2025-08'
            """
        ).fetchall()
    except Exception as exc:  # pragma: no cover - operational diagnostic
        return {"pg_mail": str(pg_path), "status": "db_unreadable", "error_type": type(exc).__name__}
    finally:
        try:
            db.close()
        except UnboundLocalError:
            pass

    exact = collections.Counter(pg_signatures)
    amounts = collections.Counter(amount for _, amount in pg_signatures if amount is not None)
    return {
        "pg_mail": str(pg_path),
        "status": "ok",
        "pg_record_count": len(pg_rows),
        "pg_2025_08_payment_date_count": pg_august,
        "candidate_agoda_2025_08_count": len(payments),
        "candidate_rows_exact_date_amount_match": sum((date, amount) in exact for date, amount in payments),
        "candidate_rows_amount_only_match": sum(amount in amounts for _, amount in payments),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--candidate-db", type=Path)
    parser.add_argument("--reconcile-report", type=Path)
    parser.add_argument("--pg-mail", type=Path)
    args = parser.parse_args()
    for relative in DEFAULT_FILES:
        print(json.dumps(audit(args.root / relative), ensure_ascii=False, sort_keys=True))
    if args.candidate_db:
        print(json.dumps(audit_candidate_db(args.candidate_db), ensure_ascii=False, sort_keys=True))
        report = args.reconcile_report or args.root / "ledger/data/ota_reconcile_report.json"
        print(json.dumps(
            audit_reconcile_report(report, args.candidate_db),
            ensure_ascii=False,
            sort_keys=True,
        ))
        pg_mail = args.pg_mail or args.root / "ledger/data/pg_mail_index.json"
        print(json.dumps(
            audit_pg_matches(pg_mail, args.candidate_db),
            ensure_ascii=False,
            sort_keys=True,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
