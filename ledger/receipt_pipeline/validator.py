"""Validate synthetic-only v1 receipt batches.

The contract is deliberately narrow: a batch is JPY-only and uses the
user-confirmed fixed convenience rate of 10 KRW per JPY.  This module does
not interpret or classify real receipts, and never mutates its input.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


class ReceiptBatchError(ValueError):
    """Raised when a synthetic receipt batch violates the v1 contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptBatchError(message)


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _iso_date(value: Any, allow_none: bool = False) -> bool:
    if value is None:
        return allow_none
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _exact_int(value: Any, positive: bool = False) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (not positive or value > 0))


def validate_batch(batch: object) -> dict[str, int]:
    """Validate a synthetic-only v1 batch and return counts and totals only."""
    _require(isinstance(batch, dict), "batch must be an object")
    _require(_nonblank(batch.get("batch_id")), "batch_id must be nonblank")
    _require(batch.get("currency") == "JPY", "currency must be JPY")

    policy = batch.get("conversion_policy")
    _require(isinstance(policy, dict), "conversion_policy must be an object")
    _require(policy.get("type") == "fixed_convenience_rate",
             "policy type must be fixed_convenience_rate")
    _require(_exact_int(policy.get("krw_per_jpy"))
             and policy.get("krw_per_jpy") == 10,
             "krw_per_jpy must be the exact integer 10")
    _require(_iso_date(policy.get("confirmed_by_user_on")),
             "confirmed_by_user_on must be an ISO date")

    images = batch.get("images")
    receipts = batch.get("receipts")
    _require(isinstance(images, list) and images, "images must be nonempty list")
    _require(isinstance(receipts, list) and receipts,
             "receipts must be nonempty list")
    _require(all(isinstance(item, dict) for item in images),
             "every image must be an object")
    _require(all(isinstance(item, dict) for item in receipts),
             "every receipt must be an object")

    image_ids = [item.get("image_id") for item in images]
    _require(all(_nonblank(value) for value in image_ids),
             "every image needs a nonblank image_id")
    _require(len(image_ids) == len(set(image_ids)), "duplicate image_id")
    receipt_ids = [item.get("physical_id") for item in receipts]
    _require(all(_nonblank(value) for value in receipt_ids),
             "every receipt needs a nonblank physical_id")
    _require(len(receipt_ids) == len(set(receipt_ids)),
             "duplicate physical_id")

    known = set(image_ids)
    refs = [item.get("image_id") for item in receipts]
    _require(all(ref in known for ref in refs), "unknown image reference")
    observed = Counter(refs)
    for image in images:
        expected = image.get("expected_physical_receipts")
        _require(_exact_int(expected, positive=True),
                 "expected physical receipt count must be positive integer")
        _require(observed[image["image_id"]] == expected,
                 f"{image['image_id']}: expected count mismatch")

    total = 0
    confirmed = 0
    for receipt in receipts:
        rid = receipt["physical_id"]
        _require(_iso_date(receipt.get("date"), allow_none=True),
                 f"{rid}: date must be null or ISO date")
        amount = receipt.get("amount_jpy")
        _require(isinstance(amount, dict), f"{rid}: amount_jpy must be object")
        status = amount.get("status")
        _require(status in {"confirmed", "estimated", "unreadable"},
                 f"{rid}: invalid amount status")
        value = amount.get("value")
        _require(value is None or (_exact_int(value) and value >= 0),
                 f"{rid}: invalid amount value")
        if status == "confirmed":
            _require(value is not None, f"{rid}: confirmed amount needs value")
            confirmed += 1
            total += value

        assignment = receipt.get("trip_assignment")
        _require(isinstance(assignment, dict),
                 f"{rid}: trip_assignment must be object")
        trip_status = assignment.get("status")
        _require(trip_status in {"auto_assigned", "manual_confirmed",
                                 "review_required"},
                 f"{rid}: invalid trip status")
        if trip_status == "auto_assigned":
            _require(assignment.get("header_match") is True and
                     assignment.get("date_region_match") is True,
                     f"{rid}: auto assignment requires exact signals")

    return {"physical_receipt_count": len(receipts),
            "confirmed_amount_count": confirmed,
            "confirmed_total_jpy": total,
            "confirmed_total_krw": total * 10}


def load_and_validate(path: str | Path) -> dict[str, int]:
    """Load and validate one synthetic-only v1 JSON batch from *path*."""
    with Path(path).open(encoding="utf-8") as handle:
        return validate_batch(json.load(handle))


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a synthetic-only v1 JPY batch "
        "(fixed_convenience_rate: 10 KRW per JPY).")
    parser.add_argument("batch_json", type=Path,
                        help="synthetic-only v1 batch JSON file")
    args = parser.parse_args()
    print(json.dumps(load_and_validate(args.batch_json), ensure_ascii=False))


if __name__ == "__main__":
    _main()
