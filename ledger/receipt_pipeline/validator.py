"""Standard-library validation for lossless receipt extraction.

This intentionally does not deduplicate on date, merchant, or amount.  The
physical receipt is the event boundary (P21); trip auto-assignment requires
both the page-header signal and receipt-level date/region signal (P23).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


class ReceiptBatchError(ValueError):
    """Raised when a receipt batch violates a lossless invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptBatchError(message)


def _valid_date(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_batch(batch: dict[str, Any]) -> dict[str, int]:
    _require(isinstance(batch, dict), "batch must be an object")
    _require(batch.get("currency") == "JPY", "batch currency must be JPY")
    conversion = batch.get("conversion_policy")
    _require(isinstance(conversion, dict), "conversion_policy missing")
    _require(conversion.get("type") == "fixed_convenience_rate",
             "unsupported conversion policy")
    krw_per_jpy = conversion.get("krw_per_jpy")
    _require(krw_per_jpy == 10, "user-confirmed convenience rate must be 10")
    images = batch.get("images")
    receipts = batch.get("receipts")
    _require(isinstance(images, list) and images, "images must be non-empty")
    _require(isinstance(receipts, list) and receipts, "receipts must be non-empty")

    image_ids = [image.get("image_id") for image in images]
    _require(all(isinstance(value, str) and value for value in image_ids),
             "every image needs an image_id")
    _require(len(image_ids) == len(set(image_ids)), "duplicate image_id")

    physical_ids = [receipt.get("physical_id") for receipt in receipts]
    _require(all(isinstance(value, str) and value for value in physical_ids),
             "every receipt needs a physical_id")
    _require(len(physical_ids) == len(set(physical_ids)),
             "duplicate physical_id would lose a physical event")

    observed = Counter(receipt.get("image_id") for receipt in receipts)
    known_images = set(image_ids)
    _require(set(observed).issubset(known_images),
             "receipt refers to an unknown image")
    for image in images:
        image_id = image["image_id"]
        expected = image.get("expected_physical_receipts")
        _require(isinstance(expected, int) and expected > 0,
                 f"{image_id}: invalid expected physical count")
        _require(observed[image_id] == expected,
                 f"{image_id}: expected {expected} physical receipts, "
                 f"observed {observed[image_id]}")

    total_jpy = 0
    confirmed_amount_count = 0
    for receipt in receipts:
        physical_id = receipt["physical_id"]
        _require(_valid_date(receipt.get("date")),
                 f"{physical_id}: invalid ISO date")
        amount = receipt.get("amount_jpy")
        _require(isinstance(amount, dict), f"{physical_id}: amount_jpy missing")
        amount_value = amount.get("value")
        _require(amount_value is None or
                 (isinstance(amount_value, int) and amount_value >= 0),
                 f"{physical_id}: invalid JPY amount")
        if amount.get("status") == "confirmed":
            _require(amount_value is not None,
                     f"{physical_id}: confirmed amount needs a value")
            total_jpy += amount_value
            confirmed_amount_count += 1

        assignment = receipt.get("trip_assignment")
        _require(isinstance(assignment, dict),
                 f"{physical_id}: trip_assignment missing")
        if assignment.get("status") == "auto_assigned":
            _require(assignment.get("header_match") is True,
                     f"{physical_id}: P23 forbids auto assignment without "
                     "header match")
            _require(assignment.get("date_region_match") is True,
                     f"{physical_id}: P23 forbids auto assignment without "
                     "receipt-level date/region match")

    return {
        "physical_receipt_count": len(receipts),
        "confirmed_amount_count": confirmed_amount_count,
        "confirmed_total_jpy": total_jpy,
        "confirmed_total_krw": total_jpy * krw_per_jpy,
    }


def load_and_validate(path: str | Path) -> dict[str, int]:
    with Path(path).open(encoding="utf-8") as handle:
        return validate_batch(json.load(handle))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("batch_json", type=Path)
    args = parser.parse_args()
    print(json.dumps(load_and_validate(args.batch_json), ensure_ascii=False))
