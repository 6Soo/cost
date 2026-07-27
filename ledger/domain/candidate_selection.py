"""Safe candidate selection for refunds and cancellation relations."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import TypeVar


T = TypeVar("T")


def select_unique_candidate(
    candidates: Iterable[T],
) -> tuple[T | None, str]:
    """Select only when the complete candidate set is provably unique."""
    rows = list(candidates)
    if len(rows) == 1:
        return rows[0], "unique"
    if not rows:
        return None, "missing"
    return None, "ambiguous"


def select_bidirectionally_unique_candidates(
    items: Iterable[T],
    candidates_for_item: Callable[[T], Iterable[T]],
    *,
    item_key: Callable[[T], object] = id,
    candidate_key: Callable[[T], object] = id,
) -> tuple[dict[object, T], dict[object, str]]:
    """Select only isolated 1:1 components, independent of row order."""
    item_rows = list(items)
    candidate_map = {
        item_key(item): list(candidates_for_item(item)) for item in item_rows
    }
    reverse_counts = Counter(
        candidate_key(candidate)
        for candidates in candidate_map.values()
        for candidate in candidates
    )
    selected: dict[object, T] = {}
    statuses: dict[object, str] = {}
    for item in item_rows:
        key = item_key(item)
        candidates = candidate_map[key]
        if (
            len(candidates) == 1
            and reverse_counts[candidate_key(candidates[0])] == 1
        ):
            selected[key] = candidates[0]
            statuses[key] = "bidirectional_unique"
        elif not candidates:
            statuses[key] = "missing"
        else:
            statuses[key] = "ambiguous"
    return selected, statuses
