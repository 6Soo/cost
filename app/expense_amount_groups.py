"""Pure grouping for read-only COST ↔ Google expense count reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence


def _amount(row: Mapping) -> int | None:
    value = row.get("amount_krw")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _unique_rows(rows: Sequence[Mapping], id_field: str, trip_id: str):
    """Validate rows before collapsing identical explicit source projections.

    The first valid projection is retained; its source identity is also used to
    annotate every valid alias COST row with the same status. Conflicting or
    invalid projections sharing an identity fail the whole comparison closed.
    """
    unique = []
    identity_rows = {}
    identity_aliases = defaultdict(list)
    ids = set()
    invalid = False
    for row in rows:
        if not isinstance(row, Mapping):
            invalid = True
            continue
        row_id = row.get(id_field)
        try:
            if not isinstance(row_id, (str, int)) or isinstance(row_id, bool) or not row_id:
                raise TypeError
            hash(row_id)
        except (TypeError, ValueError):
            invalid = True
            continue
        if row_id in ids:
            # A repeated logical identifier cannot be represented unambiguously.
            invalid = True
            continue
        ids.add(row_id)
        identity = row.get("source_identity")
        has_identity = identity is not None and identity != ""
        if has_identity:
            try:
                identity_key = (type(identity), identity)
                hash(identity_key)
            except TypeError:
                invalid = True
                continue
        currency = row.get("currency")
        amount = _amount(row)
        row_trip = row.get("trip_id")
        if row_trip != trip_id or currency != "KRW" or amount is None:
            invalid = True
            if has_identity and identity_key in identity_rows:
                invalid = True
            continue
        item = dict(row)
        item["amount_krw"] = amount
        if has_identity:
            if identity_key in identity_rows:
                prior = identity_rows[identity_key]
                # Descriptive fields may differ; all grouping facts must agree.
                if (prior["trip_id"], prior["currency"], prior["amount_krw"]) != (
                    item["trip_id"], item["currency"], item["amount_krw"]
                ):
                    invalid = True
                    continue
                identity_aliases[identity_key].append(row_id)
                continue
            identity_rows[identity_key] = item
        identity_key = (type(identity), identity) if has_identity else None
        item["_source_identity_key"] = identity_key
        unique.append(item)
    return unique, invalid, identity_aliases


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
        cost_aliases = {}
    else:
        cost_rows, cost_invalid, cost_aliases = _unique_rows(cost_rows, "row_id", trip_id)
    if not isinstance(google_rows, Sequence) or isinstance(google_rows, (str, bytes)):
        google_rows = []
        google_invalid = True
    else:
        google_rows, google_invalid, _ = _unique_rows(google_rows, "ref", trip_id)

    costs_by_amount = defaultdict(list)
    google_by_amount = defaultdict(list)
    for row in cost_rows:
        costs_by_amount[row["amount_krw"]].append(row)
    for row in google_rows:
        google_by_amount[row["amount_krw"]].append(row)

    groups = []
    by_cost_id = {}
    summary = {s: 0 for s in ("matched", "partial", "unrecorded", "google_only", "unavailable")}
    amounts = dict.fromkeys((*costs_by_amount.keys(), *google_by_amount.keys()))
    aliases_by_identity = cost_aliases
    for amount in amounts:
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
        for row in google:
            row.pop("_source_identity_key", None)
        for row in costs:
            annotation = {
                "group_id": group_id,
                "status": status,
                "cost_count": len(costs),
                "google_count": len(google),
                "candidate_count": len(costs) * len(google),
            }
            by_cost_id[row["row_id"]] = annotation
            identity = row.get("_source_identity_key")
            if identity is not None:
                for alias_id in aliases_by_identity.get(identity, ()):
                    by_cost_id[alias_id] = dict(annotation)
            row.pop("_source_identity_key", None)

    any_invalid = cost_invalid or google_invalid
    return {
        "available": not any_invalid,
        "reason": (reason or "INVALID_OR_UNCERTAIN_ROW") if any_invalid else reason,
        "last_success_at": last_success_at,
        "groups": groups,
        "by_cost_id": by_cost_id,
        "summary": summary,
    }
