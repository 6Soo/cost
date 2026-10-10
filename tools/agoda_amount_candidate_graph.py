"""Pure deterministic graph rules for Agoda amount reconciliation.

This module has no database or browser side effects.  Exact amount creates
candidate edges; only closed, balanced components can be promoted.  A forced
card4 edge may become an individual relation, a residual singleton may become
an amount-only individual relation, and an ambiguous N:N component remains an
unordered group.  Row order is never used to invent a pairing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable


EVENT_KINDS = {"charge", "refund", "chargeback"}


class CandidateGraphError(ValueError):
    pass


@dataclass(frozen=True)
class ReservationAmount:
    key: str
    currency: str
    amount_minor_units: int
    event_kind: str = "charge"
    card4: str | None = None
    competes_for_payment: bool = True
    promotion_eligible: bool = True
    hold_reason: str | None = None

    @property
    def signature(self) -> tuple[str, str, int]:
        return (
            self.event_kind,
            self.currency.upper(),
            abs(self.amount_minor_units),
        )


@dataclass(frozen=True)
class PaymentAmount:
    key: str
    currency: str
    amount_minor_units: int
    event_kind: str = "charge"
    card4: str | None = None
    promotion_eligible: bool = True
    hold_reason: str | None = None

    @property
    def signature(self) -> tuple[str, str, int]:
        return (
            self.event_kind,
            self.currency.upper(),
            abs(self.amount_minor_units),
        )


def _validate_nodes(
    reservations: Iterable[ReservationAmount],
    payments: Iterable[PaymentAmount],
) -> tuple[list[ReservationAmount], list[PaymentAmount]]:
    left = list(reservations)
    right = list(payments)
    keys = [node.key for node in left] + [node.key for node in right]
    if len(keys) != len(set(keys)):
        raise CandidateGraphError("candidate_graph_node_key_not_unique")
    for node in [*left, *right]:
        if node.event_kind not in EVENT_KINDS:
            raise CandidateGraphError("candidate_graph_event_kind_invalid")
        if not node.currency or node.amount_minor_units == 0:
            raise CandidateGraphError("candidate_graph_amount_invalid")
        if node.card4 is not None and (
            len(node.card4) != 4 or not node.card4.isdigit()
        ):
            raise CandidateGraphError("candidate_graph_card4_invalid")
    return left, right


def _card4_compatible(
    reservation: ReservationAmount, payment: PaymentAmount
) -> bool:
    return (
        reservation.card4 is None
        or payment.card4 is None
        or reservation.card4 == payment.card4
    )


def _maximum_matching_size(
    reservation_keys: set[str],
    payment_keys: set[str],
    edges: set[tuple[str, str]],
) -> int:
    adjacency = {
        reservation: sorted(
            payment
            for left, payment in edges
            if left == reservation and payment in payment_keys
        )
        for reservation in reservation_keys
    }
    matched_payment: dict[str, str] = {}

    def augment(reservation: str, seen: set[str]) -> bool:
        for payment in adjacency[reservation]:
            if payment in seen:
                continue
            seen.add(payment)
            owner = matched_payment.get(payment)
            if owner is None or augment(owner, seen):
                matched_payment[payment] = reservation
                return True
        return False

    return sum(
        augment(reservation, set()) for reservation in sorted(reservation_keys)
    )


def _has_perfect_matching(
    reservation_keys: set[str],
    payment_keys: set[str],
    edges: set[tuple[str, str]],
) -> bool:
    return len(reservation_keys) == len(payment_keys) and (
        _maximum_matching_size(reservation_keys, payment_keys, edges)
        == len(reservation_keys)
    )


def _components(
    reservation_keys: set[str],
    payment_keys: set[str],
    edges: set[tuple[str, str]],
) -> list[tuple[set[str], set[str]]]:
    left_adjacency = {
        key: {payment for reservation, payment in edges if reservation == key}
        for key in reservation_keys
    }
    right_adjacency = {
        key: {reservation for reservation, payment in edges if payment == key}
        for key in payment_keys
    }
    unseen_left = set(reservation_keys)
    unseen_right = set(payment_keys)
    result: list[tuple[set[str], set[str]]] = []
    while unseen_left or unseen_right:
        pending_left = [min(unseen_left)] if unseen_left else []
        pending_right = [min(unseen_right)] if not pending_left else []
        component_left: set[str] = set()
        component_right: set[str] = set()
        while pending_left or pending_right:
            while pending_left:
                key = pending_left.pop()
                if key in component_left:
                    continue
                component_left.add(key)
                unseen_left.discard(key)
                pending_right.extend(left_adjacency.get(key, set()) - component_right)
            while pending_right:
                key = pending_right.pop()
                if key in component_right:
                    continue
                component_right.add(key)
                unseen_right.discard(key)
                pending_left.extend(right_adjacency.get(key, set()) - component_left)
        result.append((component_left, component_right))
    return result


def _group_id(
    signature: tuple[str, str, int],
    reservation_keys: set[str],
    payment_keys: set[str],
) -> str:
    payload = json.dumps(
        {
            "signature": signature,
            "reservations": sorted(reservation_keys),
            "payments": sorted(payment_keys),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_candidate_graph(
    reservations: Iterable[ReservationAmount],
    payments: Iterable[PaymentAmount],
    *,
    universe_sealed: bool,
) -> dict[str, object]:
    """Resolve exact-amount candidates without inventing arbitrary pairs."""
    left, right = _validate_nodes(reservations, payments)
    left_by_key = {node.key: node for node in left}
    right_by_key = {node.key: node for node in right}
    signatures = sorted(
        {node.signature for node in left if node.competes_for_payment}
        | {node.signature for node in right}
    )
    candidates: list[dict[str, object]] = []
    individuals: list[dict[str, object]] = []
    groups: list[dict[str, object]] = []
    held: list[dict[str, object]] = []

    for signature in signatures:
        signature_left = {
            node.key
            for node in left
            if node.competes_for_payment and node.signature == signature
        }
        signature_right = {
            node.key for node in right if node.signature == signature
        }
        edges = {
            (reservation_key, payment_key)
            for reservation_key in signature_left
            for payment_key in signature_right
            if _card4_compatible(
                left_by_key[reservation_key], right_by_key[payment_key]
            )
        }
        candidates.extend(
            {
                "reservation_key": reservation_key,
                "payment_key": payment_key,
                "signature": signature,
                "match_method": (
                    "foreign_amount_card4"
                    if signature[1] != "KRW"
                    and left_by_key[reservation_key].card4 is not None
                    and left_by_key[reservation_key].card4
                    == right_by_key[payment_key].card4
                    else "exact_amount"
                ),
            }
            for reservation_key, payment_key in sorted(edges)
        )

        if not universe_sealed:
            held.append({"signature": signature, "reason": "unsealed_universe"})
            continue
        if len(signature_left) != len(signature_right) or not signature_left:
            held.append(
                {
                    "signature": signature,
                    "reason": "unbalanced_amount_candidate_cluster",
                    "reservation_count": len(signature_left),
                    "payment_count": len(signature_right),
                }
            )
            continue
        if any(
            not left_by_key[key].promotion_eligible for key in signature_left
        ) or any(not right_by_key[key].promotion_eligible for key in signature_right):
            held.append(
                {
                    "signature": signature,
                    "reason": "nonpromotable_competitor_in_closed_cluster",
                }
            )
            continue
        if not _has_perfect_matching(signature_left, signature_right, edges):
            held.append(
                {"signature": signature, "reason": "card4_or_graph_conflict"}
            )
            continue

        remaining_left = set(signature_left)
        remaining_right = set(signature_right)
        remaining_edges = set(edges)
        strong_edges = {
            edge
            for edge in edges
            if left_by_key[edge[0]].card4 is not None
            and left_by_key[edge[0]].card4 == right_by_key[edge[1]].card4
        }
        forced_strong_edges: list[tuple[str, str]] = []
        for edge in sorted(strong_edges):
            without = set(edges)
            without.discard(edge)
            if not _has_perfect_matching(signature_left, signature_right, without):
                forced_strong_edges.append(edge)
        if len({left for left, _ in forced_strong_edges}) != len(
            forced_strong_edges
        ) or len({right for _, right in forced_strong_edges}) != len(
            forced_strong_edges
        ):
            raise CandidateGraphError("forced_edge_set_not_disjoint")
        for reservation_key, payment_key in forced_strong_edges:
            individuals.append(
                {
                    "reservation_key": reservation_key,
                    "payment_key": payment_key,
                    "signature": signature,
                    "tier": "foreign_amount_card4_forced",
                }
            )
            remaining_left.discard(reservation_key)
            remaining_right.discard(payment_key)
        remaining_edges = {
            edge
            for edge in remaining_edges
            if edge[0] in remaining_left and edge[1] in remaining_right
        }

        for component_left, component_right in _components(
            remaining_left, remaining_right, remaining_edges
        ):
            component_edges = {
                edge
                for edge in remaining_edges
                if edge[0] in component_left and edge[1] in component_right
            }
            if not component_left and not component_right:
                continue
            if not _has_perfect_matching(
                component_left, component_right, component_edges
            ):
                held.append(
                    {
                        "signature": signature,
                        "reason": "residual_component_not_closed",
                        "reservation_count": len(component_left),
                        "payment_count": len(component_right),
                    }
                )
            elif len(component_left) == 1:
                individuals.append(
                    {
                        "reservation_key": next(iter(component_left)),
                        "payment_key": next(iter(component_right)),
                        "signature": signature,
                        "tier": "universe_unique_exact_amount",
                    }
                )
            else:
                groups.append(
                    {
                        "group_id": _group_id(
                            signature, component_left, component_right
                        ),
                        "signature": signature,
                        "reservation_keys": tuple(sorted(component_left)),
                        "payment_keys": tuple(sorted(component_right)),
                        "member_count_each_side": len(component_left),
                        "individual_pair_asserted": False,
                    }
                )

    noncompeting = [node for node in left if not node.competes_for_payment]
    held.extend(
        {
            "reservation_key": node.key,
            "signature": node.signature,
            "reason": node.hold_reason or "reservation_does_not_compete_for_agoda_charge",
        }
        for node in sorted(noncompeting, key=lambda item: item.key)
    )
    return {
        "amount_candidates": tuple(candidates),
        "confirmed_individuals": tuple(
            sorted(
                individuals,
                key=lambda item: (
                    str(item["reservation_key"]), str(item["payment_key"])
                ),
            )
        ),
        "confirmed_groups": tuple(
            sorted(groups, key=lambda item: str(item["group_id"]))
        ),
        "held": tuple(
            sorted(
                held,
                key=lambda item: (
                    str(item.get("signature")),
                    str(item.get("reservation_key")),
                    str(item.get("reason")),
                ),
            )
        ),
    }
