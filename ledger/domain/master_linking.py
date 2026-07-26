"""Safe group-level links from master card rows to classified projections."""
from __future__ import annotations

import re
from collections import defaultdict


def _amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def _approval(value: object) -> str:
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def _merchant(value: object) -> str:
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())


def _compatible_merchant(left: object, right: object) -> bool:
    a, b = _merchant(left), _merchant(right)
    return bool(a and b and (a in b or b in a))


def balanced_master_links(
    master_rows: list[dict[str, str]],
    classified_rows: list[dict[str, str]],
) -> dict[str, str]:
    """Return transaction-key→UID links only for exact balanced role groups."""
    master_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    classified_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    for row in master_rows:
        event_date = str(row.get("승인일") or row.get("매입일") or "")[:10]
        amount = _amount(row.get("원화금액")) or _amount(row.get("현지금액"))
        role = "refund" if "취소" in str(row.get("취소여부") or "") or amount < 0 else "purchase"
        key = (
            str(row.get("카드4") or "")[-4:],
            event_date,
            abs(amount),
            role,
            _merchant(row.get("가맹점")),
        )
        if event_date and amount:
            master_groups[key].append(row)
    for row in classified_rows:
        amount = _amount(row.get("krw"))
        role = "refund" if amount < 0 or "취소" in str(row.get("status") or "") else "purchase"
        key = (
            str(row.get("card4") or "")[-4:],
            str(row.get("use_date") or "")[:10],
            abs(amount),
            role,
            _merchant(row.get("merchant")),
        )
        if key[1] and amount:
            classified_groups[key].append(row)

    links: dict[str, str] = {}
    # Prefer explicit approval lineage when the source provides it.
    classified_purchase_approval: dict[str, list[dict[str, str]]] = defaultdict(list)
    classified_refund_approval: dict[str, list[dict[str, str]]] = defaultdict(list)
    classified_refund_original: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in classified_rows:
        approval = _approval(row.get("appr"))
        original = _approval(row.get("orig_appr"))
        if approval and _amount(row.get("krw")) > 0:
            classified_purchase_approval[approval].append(row)
        if approval and _amount(row.get("krw")) < 0:
            classified_refund_approval[approval].append(row)
        if original and _amount(row.get("krw")) < 0:
            classified_refund_original[original].append(row)
    for master in master_rows:
        role_refund = "취소" in str(master.get("취소여부") or "")
        approval = _approval(master.get("승인번호"))
        original = _approval(master.get("원승인번호"))
        key = approval if approval else original
        if role_refund:
            # A single original approval can have many partial-refund legs.
            # The cancellation approval identifies the event; original
            # approval is only a lifecycle fallback when it remains unique.
            candidates = classified_refund_approval.get(approval, []) if approval else []
            if not candidates and original:
                candidates = classified_refund_original.get(original, [])
                key = original
        else:
            candidates = classified_purchase_approval.get(approval, [])
        master_date = str(master.get("승인일") or master.get("매입일") or "")[:10]
        master_amount = abs(
            _amount(master.get("원화금액")) or _amount(master.get("현지금액"))
        )
        candidates = [
            row
            for row in candidates
            if (
                not master.get("카드4")
                or not row.get("card4")
                or str(master.get("카드4"))[-4:] == str(row.get("card4"))[-4:]
            )
            and str(row.get("use_date") or "")[:10] == master_date
            and abs(_amount(row.get("krw"))) == master_amount
            and _compatible_merchant(master.get("가맹점"), row.get("merchant"))
        ]
        if key and len(candidates) == 1:
            links[str(master.get("거래키") or "")] = str(candidates[0].get("uid") or "")

    for key, masters in master_groups.items():
        classified = classified_groups.get(key, [])
        if not classified or len(masters) != len(classified):
            continue
        # A repeated approval-less group proves coverage/cardinality, but not
        # individual row identity.  Keep it ambiguous until approval lineage is
        # re-ingested.
        if len(masters) > 1:
            continue
        for master, row in zip(
            sorted(masters, key=lambda item: str(item.get("거래키") or "")),
            sorted(classified, key=lambda item: str(item.get("uid") or "")),
        ):
            links.setdefault(
                str(master.get("거래키") or ""),
                str(row.get("uid") or ""),
            )

    # A legacy zero row may intentionally represent one approval + one refund.
    master_by_approval: dict[str, list[dict[str, str]]] = defaultdict(list)
    classified_by_approval: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in master_rows:
        approval = _approval(row.get("승인번호"))
        if approval:
            master_by_approval[approval].append(row)
    for row in classified_rows:
        approval = _approval(row.get("appr"))
        if approval and _amount(row.get("krw")) == 0 and "취소" in str(row.get("status") or ""):
            classified_by_approval[approval].append(row)
    for approval, masters in master_by_approval.items():
        zero_rows = classified_by_approval.get(approval, [])
        amounts = {_amount(row.get("원화금액")) for row in masters}
        roles = {
            "refund" if "취소" in str(row.get("취소여부") or "") else "purchase"
            for row in masters
        }
        if (
            len(masters) == 2
            and len(zero_rows) == 1
            and len({abs(amount) for amount in amounts}) == 1
            and roles == {"purchase", "refund"}
        ):
            for master in masters:
                links.setdefault(
                    str(master.get("거래키") or ""),
                    str(zero_rows[0].get("uid") or ""),
                )
    return links


def balanced_ambiguous_master_keys(
    master_rows: list[dict[str, str]],
    classified_rows: list[dict[str, str]],
) -> set[str]:
    """Return repeated approval-less source keys with balanced cardinality."""
    master_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    classified_groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    for row in master_rows:
        if str(row.get("승인번호") or "").strip():
            continue
        event_date = str(row.get("승인일") or row.get("매입일") or "")[:10]
        amount = _amount(row.get("원화금액")) or _amount(row.get("현지금액"))
        role = "refund" if "취소" in str(row.get("취소여부") or "") or amount < 0 else "purchase"
        master_groups[(
            str(row.get("카드4") or "")[-4:],
            event_date,
            abs(amount),
            role,
            _merchant(row.get("가맹점")),
        )].append(row)
    for row in classified_rows:
        amount = _amount(row.get("krw"))
        role = "refund" if amount < 0 or "취소" in str(row.get("status") or "") else "purchase"
        classified_groups[(
            str(row.get("card4") or "")[-4:],
            str(row.get("use_date") or "")[:10],
            abs(amount),
            role,
            _merchant(row.get("merchant")),
        )].append(row)
    result: set[str] = set()
    for key, masters in master_groups.items():
        classified = classified_groups.get(key, [])
        if len(masters) > 1 and len(masters) == len(classified):
            result.update(str(row.get("거래키") or "") for row in masters)
    return result
