"""Period-recognition rules backed only by structured booking evidence."""
from __future__ import annotations

from datetime import date
from typing import Mapping


Q2_CLOSE_ON = "2026-06-30"
REFUNDABLE_DEPOSIT_PENDING = "refundable_deposit_pending"


def structured_service_start_on(booking: Mapping[str, object]) -> str | None:
    """Return only an ISO start date stored on the structured booking record.

    Human-readable card notes and period labels are intentionally excluded:
    they are useful review evidence, but cannot on their own move a card event
    out of the closed accounting period.
    """
    explicit = str(booking.get("service_start_on") or "").strip()
    try:
        return date.fromisoformat(explicit).isoformat()
    except ValueError:
        return None


def is_refundable_deposit_pending(booking: Mapping[str, object]) -> bool:
    """A refundable deposit is a settlement condition, not a future service cost."""
    return (
        str(booking.get("settlement_condition") or "").strip().lower()
        == REFUNDABLE_DEPOSIT_PENDING
    )


def is_prepaid_future_trip(
    service_start: str | None,
    *,
    closed_through_on: str = Q2_CLOSE_ON,
) -> bool:
    """True only when a known service starts strictly after the closed period."""
    if not service_start:
        return False
    try:
        return date.fromisoformat(service_start) > date.fromisoformat(closed_through_on)
    except ValueError:
        return False
