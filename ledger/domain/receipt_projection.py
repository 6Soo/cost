"""Append-only, privacy-safe projection of physical receipt batches.

Receipt images remain outside the database.  This module stores only the
minimal structured extraction necessary for an audit trail, omitting free-text
notes, raw headers, filenames and payment-card details.  A physical receipt is
an event boundary even when it shares merchant/date/amount with another one.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ledger.domain.direct_sources import _insert_source
from ledger.receipt_pipeline.validator import load_and_validate


REDACTION_VERSION = "receipt-allowlist-v1"
PROJECTION_VERSION = "manual-receipt-v1"


def _safe_manifest(batch: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest allowlist; image names and handwritten raw headers stay local."""
    return {
        "batch_id": batch["batch_id"],
        "currency": batch["currency"],
        "conversion_policy": {
            "type": batch["conversion_policy"]["type"],
            "krw_per_jpy": batch["conversion_policy"]["krw_per_jpy"],
            "confirmed_by_user_on": batch["conversion_policy"].get("confirmed_by_user_on"),
        },
        "images": [
            {
                "image_id": image["image_id"],
                "expected_physical_receipts": image["expected_physical_receipts"],
                "header": {
                    key: image.get("header", {}).get(key)
                    for key in ("period_start", "period_end", "region", "trip_candidate", "confidence")
                },
            }
            for image in batch["images"]
        ],
    }


def _safe_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Allowlist one receipt without free text or payment-card details."""
    return {
        "physical_id": receipt["physical_id"],
        "image_id": receipt["image_id"],
        "position": receipt["position"],
        "date": receipt.get("date"),
        "merchant": {
            key: receipt.get("merchant", {}).get(key)
            for key in ("value", "status", "confidence")
        },
        "amount_jpy": {
            key: receipt.get("amount_jpy", {}).get(key)
            for key in ("value", "status", "confidence")
        },
        "payment_method": {
            key: receipt.get("payment_method", {}).get(key)
            for key in ("value", "status", "confidence")
        },
        "classification": {
            key: receipt.get("classification", {}).get(key)
            for key in ("target", "account", "status", "amount_krw")
        },
        "trip_assignment": {
            key: receipt.get("trip_assignment", {}).get(key)
            for key in (
                "trip_candidate", "header_match", "date_region_match", "status", "confidence"
            )
        },
    }


def _next_event_version(
    db: sqlite3.Connection, batch_id: str, physical_id: str
) -> int:
    row = db.execute(
        """
        SELECT COALESCE(MAX(event_version), 0)
        FROM physical_receipt_events
        WHERE batch_id=? AND physical_id=?
        """,
        (batch_id, physical_id),
    ).fetchone()
    return int(row[0]) + 1


def import_receipt_batch(db: sqlite3.Connection, batch_path: Path) -> dict[str, int]:
    """Validate then append a physical-receipt batch and eligible MAN events.

    The caller owns the surrounding transaction.  Replaying identical input is
    idempotent; an edited receipt payload appends a new immutable event version.
    """
    load_and_validate(batch_path)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch_id = str(batch["batch_id"])
    manifest = _safe_manifest(batch)
    manifest_source_id, _ = _insert_source(
        db, "physical_receipt_batch", batch_id, manifest, REDACTION_VERSION
    )
    db.execute(
        """
        INSERT OR IGNORE INTO receipt_batch_manifests(
            source_record_id, batch_id, image_count,
            expected_physical_receipt_count, currency, krw_per_jpy
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            manifest_source_id,
            batch_id,
            len(batch["images"]),
            sum(int(image["expected_physical_receipts"]) for image in batch["images"]),
            batch["currency"],
            int(batch["conversion_policy"]["krw_per_jpy"]),
        ),
    )

    appended = manual_projected = 0
    for raw_receipt in batch["receipts"]:
        receipt = _safe_receipt(raw_receipt)
        physical_id = str(receipt["physical_id"])
        source_id, created = _insert_source(
            db,
            "physical_receipt",
            f"{batch_id}:{physical_id}",
            receipt,
            REDACTION_VERSION,
        )
        if not created:
            continue
        amount = receipt["amount_jpy"]
        method = receipt["payment_method"]
        assignment = receipt["trip_assignment"]
        classification = receipt["classification"]
        version = _next_event_version(db, batch_id, physical_id)
        event_id = int(
            db.execute(
                """
                INSERT INTO physical_receipt_events(
                    source_record_id, batch_id, physical_id, image_id, event_version,
                    occurred_on, amount_jpy, amount_status, payment_method,
                    payment_status, trip_assignment_status, classification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id, batch_id, physical_id, receipt["image_id"], version,
                    receipt.get("date"), amount.get("value"), str(amount.get("status")),
                    str(method.get("value")), str(method.get("status")),
                    str(assignment.get("status")), classification.get("status"),
                ),
            ).lastrowid
        )
        appended += 1

        # Do not convert card or unreadable receipts into a second expense.
        # A MAN candidate is permitted only after both payment method and the
        # classification are explicitly confirmed by the user.
        eligible = (
            method.get("value") in {"cash", "transfer"}
            and method.get("status") == "confirmed"
            and classification.get("status") == "user_confirmed"
            and isinstance(classification.get("amount_krw"), int)
        )
        if eligible:
            db.execute(
                """
                INSERT INTO manual_receipt_projections(
                    receipt_event_id, manual_event_key, amount_krw,
                    allocation_target, expense_account, projection_status,
                    projection_version
                ) VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
                """,
                (
                    event_id,
                    f"MAN-RECEIPT:{batch_id}:{physical_id}:v{version}",
                    int(classification["amount_krw"]),
                    str(classification["target"]),
                    str(classification["account"]),
                    PROJECTION_VERSION,
                ),
            )
            manual_projected += 1

    return {
        "physical_events_appended": appended,
        "manual_events_projected": manual_projected,
        "physical_event_total": int(
            db.execute("SELECT COUNT(*) FROM physical_receipt_events").fetchone()[0]
        ),
        "manual_event_total": int(
            db.execute("SELECT COUNT(*) FROM manual_receipt_projections").fetchone()[0]
        ),
    }
