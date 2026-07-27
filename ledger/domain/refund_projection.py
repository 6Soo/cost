"""Conservative full-refund pairing for the legacy flat projection."""
from __future__ import annotations

import re
from typing import Iterable


def _amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def _merchant(value: object) -> str:
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())


def _compatible(left: object, right: object) -> bool:
    a, b = _merchant(left), _merchant(right)
    return bool(a and b and (a in b or b in a))


def exact_full_refund_pairs(
    payments: Iterable[dict[str, str]],
    cards: Iterable[dict[str, object]],
    used_card_keys: set[str],
) -> list[tuple[dict[str, str], dict[str, object]]]:
    """Pair only unique same-approval, same-amount, same-date refunds."""
    payment_rows = list(payments)
    paired_payment_ids: set[int] = set()
    result: list[tuple[dict[str, str], dict[str, object]]] = []
    for card in cards:
        card_key = f"{card.get('src')}:{card.get('raw_record_id')}"
        approval = re.sub(r"\D", "", str(card.get("appr") or ""))
        # Only Hana rows explicitly expanded into purchase/refund lifecycle legs
        # prove that both events coexist in one source row.  A standalone CORP
        # cancellation must repair the legacy sign, not invent a purchase.
        if (
            card_key in used_card_keys
            or not card.get("cx")
            or not approval
            or card.get("src") != "HAN"
            or not str(card.get("raw_record_id") or "").endswith(":refund")
        ):
            continue
        candidates = [
            payment
            for payment in payment_rows
            if id(payment) not in paired_payment_ids
            and payment.get("src") == card.get("src")
            and _amount(payment.get("krw")) == int(card.get("amt") or 0)
            and re.sub(r"\D", "", str(payment.get("appr") or "")) == approval
            and str(payment.get("use_date") or "")[:10]
            == str(card.get("use") or "")[:10]
            and _compatible(payment.get("merchant"), card.get("mer"))
        ]
        if len(candidates) == 1:
            payment = candidates[0]
            paired_payment_ids.add(id(payment))
            result.append((payment, card))
    return result


def repair_standalone_cancellation_signs(
    payments: Iterable[dict[str, str]],
    cards: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Correct a legacy positive row backed by one standalone cancellation."""
    payment_rows = list(payments)
    updates: list[dict[str, object]] = []
    for card in cards:
        if card.get("src") != "CORP" or not card.get("cx"):
            continue
        approval = re.sub(r"\D", "", str(card.get("appr") or ""))
        candidates = [
            payment
            for payment in payment_rows
            if payment.get("src") == "CORP"
            and _amount(payment.get("krw")) == int(card.get("amt") or 0)
            and re.sub(r"\D", "", str(payment.get("appr") or "")) == approval
            and str(payment.get("use_date") or "")[:10]
            == str(card.get("use") or "")[:10]
            and _compatible(payment.get("merchant"), card.get("mer"))
        ]
        if len(candidates) != 1:
            continue
        payment = candidates[0]
        previous = _amount(payment.get("krw"))
        payment["krw"] = str(-abs(int(card.get("amt") or 0)))
        payment["cancel"] = "True"
        payment["status"] = "취소"
        payment["bucket"] = "취소환불"
        payment["note"] = (
            (payment.get("note") or "")
            + f" | 카드원천 취소부호 교정:{card.get('raw_record_id')}"
        ).strip(" |")
        updates.append(
            {
                "uid": payment.get("uid"),
                "before": previous,
                "after": _amount(payment.get("krw")),
                "source_row": card.get("raw_record_id"),
            }
        )
    return updates
