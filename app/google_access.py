"""Per-viewer filter for the Google trip view. Default deny, minimal fields, no route.

Owner sees every trip with both copies. A viewer sees only the trips the owner granted,
and only the trip-level figures and check codes, never the copy comparison.
"""

from __future__ import annotations

VIEWER_FIELDS = ("key", "closure", "closure_current", "income_total", "expense_total", "net", "verified", "review")


def visible_trips(view: list[dict], *, is_owner: bool, allowed_keys: set) -> list[dict]:
    if is_owner:
        return [dict(trip) for trip in view]
    return [{field: trip[field] for field in VIEWER_FIELDS} for trip in view if trip["key"] in allowed_keys]
