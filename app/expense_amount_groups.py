"""Pure grouping for read-only COST ↔ Google expense count reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import math


def _amount(row: Mapping) -> int | None:
    value = row.get("amount_krw")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _unique_rows(rows: Sequence[Mapping], id_field: str, trip_id: str):
    """Validate rows and collapse only explicitly identified same-source copies."""
    unique = []
    seen_identity = set()
    ids = set()
    invalid = False
    for row in rows:
        if not isinstance(row, Mapping):
            invalid = True
            continue
        row_id = row.get(id_field)
        if row_id is None or isinstance(row_id, (dict, list, set)):
            invalid = True
            continue
        if row_id in ids:
            # A repeated logical identifier cannot be represented unambiguously.
            invalid = True
            continue
        ids.add(row_id)
        identity = row.get("source_identity")
        if identity is not None:
            try:
                identity_key = (type(identity), identity)
                hash(identity_key)
            except TypeError:
                invalid = True
                continue
            if identity_key in seen_identity:
                continue
            seen_identity.add(identity_key)
        currency = row.get("currency")
        amount = _amount(row)
        row_trip = row.get("trip_id")
        if row_trip != trip_id or currency != "KRW" or amount is None:
            invalid = True
            continue
        item = dict(row)
        item["amount_krw"] = amount
        unique.append(item)
    return unique, invalid


def reconcile_expense_amount_groups(
    trip_id,
    cost_rows,
    google_rows,
    *,
    available=True,
    reason="",
    last_success_at=None,
) -> dict:
    """Group exact signed KRW expenses by trip and amount in O(m+n).

    A matching count indicates only group cardinality, never row identity. The
    candidate relationships are represented by each side's row list and the
    ``candidate_count`` product; no pairwise cross-product is constructed.
    """
    if not isinstance(trip_id, str) or not trip_id.strip():
        available = False
        reason = reason or "INVALID_TRIP_ID"
        trip_id = trip_id if isinstance(trip_id, str) else ""
    if not available:
        out_reason = reason or "SOURCE_UNAVAILABLE"
        return {
            "available": False,
            "reason": out_reason,
            "last_success_at": last_success_at,
            "groups": [],
            "by_cost_id": {},
            "summary": {s: 0 for s in ("matched", "partial", "unrecorded", "google_only", "unavailable")},
        }

    if not isinstance(cost_rows, Sequence) or isinstance(cost_rows, (str, bytes)):
        cost_rows = []
        cost_invalid = True
    else:
        cost_rows, cost_invalid = _unique_rows(cost_rows, "row_id", trip_id)
    if not isinstance(google_rows, Sequence) or isinstance(google_rows, (str, bytes)):
        google_rows = []
        google_invalid = True
    else:
        google_rows, google_invalid = _unique_rows(google_rows, "ref", trip_id)

    costs_by_amount = defaultdict(list)
    google_by_amount = defaultdict(list)
    for row in cost_rows:
        costs_by_amount[row["amount_krw"]].append(row)
    for row in google_rows:
        google_by_amount[row["amount_krw"]].append(row)

    groups = []
    by_cost_id = {}
    summary = {s: 0 for s in ("matched", "partial", "unrecorded", "google_only", "unavailable")}
    for amount in sorted(set(costs_by_amount) | set(google_by_amount)):
        costs = costs_by_amount.get(amount, [])
        google = google_by_amount.get(amount, [])
        if cost_invalid or google_invalid:
            status = "unavailable"
        elif costs and google:
            status = "matched" if len(costs) == len(google) else "partial"
        elif costs:
            status = "unrecorded"
        else:
            status = "google_only"
        group_id = f"{trip_id}:{amount}"
        group = {
            "group_id": group_id,
            "trip_id": trip_id,
            "amount_krw": amount,
            "status": status,
            "cost_count": len(costs),
            "google_count": len(google),
            "candidate_count": len(costs) * len(google),
            "cost_rows": costs,
            "google_rows": google,
        }
        groups.append(group)
        summary[status] += 1
        for row in costs:
            by_cost_id[row["row_id"]] = {
                "group_id": group_id,
                "status": status,
                "cost_count": len(costs),
                "google_count": len(google),
                "candidate_count": len(costs) * len(google),
            }

    any_invalid = cost_invalid or google_invalid
    return {
        "available": not any_invalid,
        "reason": (reason or "INVALID_OR_UNCERTAIN_ROW") if any_invalid else reason,
        "last_success_at": last_success_at,
        "groups": groups,
        "by_cost_id": by_cost_id,
        "summary": summary,
    }
