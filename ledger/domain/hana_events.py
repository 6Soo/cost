"""Expand a Hana lifecycle row into lossless purchase/refund events."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable


def _amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def expand_hana_row(
    source_row_id: str,
    values: list[str],
    normalize_date: Callable[[object], str],
) -> list[dict[str, object]]:
    """Return one purchase plus a refund when a row contains both lifecycle legs."""
    row = list(values) + [""] * max(0, 20 - len(values))
    approved = abs(_amount(row[5]))
    billed = abs(_amount(row[14]))
    cancelled = abs(_amount(row[15])) or abs(_amount(row[6]))
    status_cancelled = "취소" in str(row[17] or "")
    if not approved and not billed and not cancelled:
        return []

    merchant = str(row[7] or "")
    common = {
        "co": "하나",
        "use": normalize_date(row[1]),
        "c4": str(row[3] or "")[-4:],
        "mer": merchant,
        "fx": "",
        "cur": "",
        "sub": "해외" if "해외" in str(row[11] or "") else "국내",
        "src": "HAN",
        "appr": re.sub(r"\D", "", str(row[4] or "")),
        "approved_amt": approved,
        "billed_amt": billed,
    }
    # For a captured transaction, the accounting event is the billed amount.
    # A cancelled captured row often leaves 매입금액 blank, so 매출취소금액 is
    # the best evidence of the original posted amount.
    purchase_amount = billed or cancelled or approved
    events: list[dict[str, object]] = [
        dict(
            common,
            raw_record_id=f"{source_row_id}:purchase",
            amt=purchase_amount,
            cx=False,
        )
    ]
    if cancelled or status_cancelled:
        events.append(
            dict(
                common,
                raw_record_id=f"{source_row_id}:refund",
                amt=cancelled or purchase_amount,
                cx=True,
            )
        )
    return events


def _merchant(value: object) -> str:
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())


def _compatible(left: object, right: object) -> bool:
    a, b = _merchant(left), _merchant(right)
    return bool(a and b and (a in b or b in a))


def _approval(value: object) -> str:
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def reconcile_hana_billing_projection(
    classified_rows: list[dict[str, str]],
    card_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Align legacy Hana approval projections to the billed card event."""
    purchases: dict[str, list[dict[str, object]]] = defaultdict(list)
    refunds: dict[str, list[dict[str, object]]] = defaultdict(list)
    for card in card_rows:
        if card.get("src") != "HAN" or not card.get("appr"):
            continue
        target = refunds if card.get("cx") else purchases
        target[_approval(card["appr"])].append(card)

    updated: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    consumed_card_keys: set[str] = set()
    for row in classified_rows:
        if row.get("src") != "HAN":
            continue
        approval = _approval(row.get("appr"))
        if not approval:
            continue
        if not _amount(row.get("krw")):
            if "취소" not in str(row.get("status") or ""):
                continue
            purchase_pool = [
                card
                for card in purchases.get(approval, [])
                if _compatible(row.get("merchant"), card.get("mer"))
            ]
            refund_pool = [
                card
                for card in refunds.get(approval, [])
                if _compatible(row.get("merchant"), card.get("mer"))
            ]
            if (
                len(purchase_pool) == 1
                and len(refund_pool) == 1
                and purchase_pool[0].get("amt") == refund_pool[0].get("amt")
            ):
                for card in (purchase_pool[0], refund_pool[0]):
                    consumed_card_keys.add(
                        f"{card.get('src')}:{card.get('raw_record_id')}"
                    )
            else:
                conflicts.append(
                    {
                        "uid": row.get("uid"),
                        "approval": approval,
                        "reason": "zero_net_lifecycle_not_unique",
                        "purchase_count": len(purchase_pool),
                        "refund_count": len(refund_pool),
                    }
                )
            continue
        pool = [
            card
            for card in purchases.get(approval, [])
            if _compatible(row.get("merchant"), card.get("mer"))
        ]
        current = abs(_amount(row.get("krw")))
        strong = [
            card
            for card in pool
            if current
            in {
                int(card.get("amt") or 0),
                int(card.get("approved_amt") or 0),
            }
        ]
        candidates = strong if strong else pool if len(pool) == 1 else []
        if len(candidates) != 1:
            if pool:
                conflicts.append(
                    {
                        "uid": row.get("uid"),
                        "approval": approval,
                        "candidate_count": len(pool),
                    }
                )
            continue
        card = candidates[0]
        before = {"use_date": row.get("use_date"), "krw": row.get("krw")}
        sign = -1 if _amount(row.get("krw")) < 0 else 1
        row["use_date"] = str(card.get("use") or row.get("use_date") or "")
        row["krw"] = str(sign * int(card.get("amt") or 0))
        raw_key = f"{card.get('src')}:{card.get('raw_record_id')}"
        row["source_event_id"] = f"card:{raw_key}"
        row["source_event_members"] = raw_key
        row["source_event_disposition"] = "raw_card_linked"
        consumed_card_keys.add(raw_key)
        after = {"use_date": row["use_date"], "krw": row["krw"]}
        if before != after:
            updated.append(
                {
                    "uid": row.get("uid"),
                    "approval": approval,
                    "before": before,
                    "after": after,
                    "source_row": card.get("raw_record_id"),
                }
            )
    return {
        "updated": updated,
        "conflicts": conflicts,
        "consumed_card_keys": consumed_card_keys,
    }
