# -*- coding: utf-8 -*-
"""Link approval evidence to the acquired transactions it describes.

Roles are fixed:

* An **approval** says an event happened (card, date, approval number, merchant).
* An **acquired** row (국내/해외 매입) says what was finally billed. Only acquired rows
  are transactions and only they can reach the ledger.

Linking never changes either side. It only says which approval and which acquired
transaction are the same payment, and it is recomputed from the stored sets every time,
so the result does not depend on which file arrived first.

Domestic payments are matched on card + approval number, which is unique. Overseas
acquired rows carry no approval number, so they are matched in groups of
card + approval date + USD amount. A group is linked one-to-one only when each side has
exactly one member; equal larger groups are linked as a group, and unequal ones are left
as partial. Two payments of the same amount on the same day are never paired by position.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

OVERSEAS_COLUMNS = 17

LINKED = "linked"
GROUP_LINKED = "group_linked"
GROUP_PARTIAL = "group_partial"
APPROVAL_ONLY = "approval_only"
AMBIGUOUS = "ambiguous"
CANCELLED_BEFORE = "cancelled_before_acquisition"
CANCELLED_AFTER = "cancelled_after_acquisition"

_EXCLUDED_KINDS = ("리버설", "취소")


def _usd(value) -> str:
    try:
        return format(Decimal(str(value).replace(",", "").replace("$", "")).quantize(Decimal("0.01")), "f")
    except (InvalidOperation, ValueError):
        return ""


def _overseas_usd(raw_json: str) -> str:
    """미화환산금액 of an overseas acquired row (c12 of the 17-column layout), or ''."""
    try:
        raw = json.loads(raw_json)
    except ValueError:
        return ""
    if not isinstance(raw, dict) or len([k for k in raw if k.startswith("c")]) != OVERSEAS_COLUMNS:
        return ""
    currency = str(raw.get("c10") or "")
    if len(currency) != 3 or not currency.isalpha():
        return ""
    return _usd(raw.get("c12"))


def group_key(card_tail: str, approval_date: str, usd: str) -> str:
    return "|".join((card_tail, approval_date, usd))


def _acquired(conn) -> tuple[dict, dict, dict]:
    """Domestic rows by reference and exact approval date, plus overseas groups."""
    domestic: dict[tuple, list[str]] = {}
    domestic_by_date: dict[tuple, list[str]] = {}
    overseas: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT transaction_id, card_tail, approval_number, approval_date, transaction_kind, raw_row_json"
        " FROM transactions WHERE issuer='국민' AND transaction_direction='purchase' AND parse_error=''"
        " AND transaction_id NOT LIKE '%:conflict:%' ORDER BY created_at, transaction_id")
    for transaction_id, card, number, approved, kind, raw_json in rows:
        if any(word in str(kind or "") for word in _EXCLUDED_KINDS):
            continue
        if number:
            domestic.setdefault((card, number), []).append(transaction_id)
            domestic_by_date.setdefault((card, number, approved), []).append(transaction_id)
            continue
        usd = _overseas_usd(raw_json)
        if usd and approved:
            overseas.setdefault(group_key(card, approved, usd), []).append(transaction_id)
    return domestic, domestic_by_date, overseas


def reconcile(store) -> dict:
    """Recompute the link state of every approval row and return counts. Idempotent."""
    conn = store.conn
    approvals = conn.execute(
        "SELECT approval_key, card_tail, card_kind, transaction_direction, approval_number, approval_date,"
        " foreign_amount, link_state, linked_transaction_id, link_group, link_note"
        " FROM approval_evidence ORDER BY approval_date, approval_number, approval_key").fetchall()
    summary = {"approvals": len(approvals)}
    if not approvals:
        return summary
    domestic, domestic_by_date, overseas = _acquired(conn)
    cancelled_numbers = {(row[1], row[4]) for row in approvals if row[3] == "cancellation"}
    results: dict[str, tuple] = {}

    overseas_groups: dict[str, list[tuple]] = {}
    for key, card, kind, direction, number, approved, foreign, *_ in approvals:
        if direction == "cancellation":
            continue
        if kind == "국내":
            found = domestic_by_date.get((card, number, approved), [])
            if len(found) == 1:
                results[key] = (LINKED, found[0], "", "승인번호·카드·승인일이 같은 국내 매입 1건")
            elif len(found) > 1:
                results[key] = (AMBIGUOUS, None, "", "같은 승인번호의 매입 거래가 여러 건이라 확정하지 않았습니다")
            elif domestic.get((card, number)):
                results[key] = (AMBIGUOUS, None, "", "카드와 승인번호는 같지만 승인일이 다른 매입 후보가 있어 확정하지 않았습니다")
            elif (card, number) in cancelled_numbers:
                results[key] = (CANCELLED_BEFORE, None, "", "매입 전에 승인 취소됨")
            else:
                results[key] = (APPROVAL_ONLY, None, "", "매입 내역에서 아직 확인되지 않음")
        else:
            usd = _usd(foreign)
            overseas_groups.setdefault(group_key(card, approved, usd), []).append((key, card, number))

    for group, members in overseas_groups.items():
        acquired = overseas.get(group, [])
        n = len(acquired)
        if n == 0:
            for key, card, number in members:
                if (card, number) in cancelled_numbers:
                    results[key] = (CANCELLED_BEFORE, None, group, "매입 전에 승인 취소됨")
                else:
                    results[key] = (APPROVAL_ONLY, None, group, "매입 내역에서 아직 확인되지 않음")
        elif n == len(members) == 1:
            results[members[0][0]] = (LINKED, acquired[0], group, "카드·승인일·미화 금액이 같은 해외 매입 1건")
        elif n == len(members):
            for key, _, _ in members:
                results[key] = (GROUP_LINKED, None, group,
                                "같은 속성의 거래 %d건이 승인과 매입에서 같은 수로 확인됨(개별 대응은 확정하지 않음)" % n)
        elif n > len(members):
            for key, _, _ in members:
                results[key] = (GROUP_LINKED, None, group, "매입이 승인보다 많습니다. 승인 내역 기간 밖 거래가 있을 수 있음")
        else:
            for key, _, _ in members:
                results[key] = (GROUP_PARTIAL, None, group,
                                "승인 %d건 중 매입 %d건이 확인됨(남은 승인은 매입 대기)" % (len(members), n))

    for key, card, kind, direction, number, *_ in approvals:
        if direction != "cancellation":
            continue
        original = next((r for r in approvals if r[1] == card and r[4] == number and r[3] != "cancellation"), None)
        state = results.get(original[0])[0] if original is not None and original[0] in results else ""
        if state in (LINKED, GROUP_LINKED, CANCELLED_AFTER):
            results[key] = (CANCELLED_AFTER, None, "", "매입된 거래의 승인 취소. 환불은 취소매입 내역으로 확인")
        else:
            results[key] = (CANCELLED_BEFORE, None, "", "매입 전에 승인 취소됨. 환불 비용으로 기록하지 않음")

    counts: dict[str, int] = {}
    with store.lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in approvals:
                key = row[0]
                new = results.get(key, ("unreconciled", None, "", ""))
                counts[new[0]] = counts.get(new[0], 0) + 1
                if (row[7], row[8], row[9], row[10]) != (new[0], new[1], new[2], new[3]):
                    conn.execute("UPDATE approval_evidence SET link_state=?, linked_transaction_id=?,"
                                 " link_group=?, link_note=? WHERE approval_key=?", (*new, key))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    summary["states"] = counts
    return summary


def source_notes(conn, transaction_ids) -> dict:
    """What other channels say about each acquired transaction, for the review screen."""
    ids = [t for t in transaction_ids if t]
    if not ids:
        return {}
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approval_evidence'").fetchone()
    if not exists:
        return {}
    notes: dict[str, dict] = {}
    marks = ",".join("?" * len(ids))
    for transaction_id, number, group in conn.execute(
            "SELECT linked_transaction_id, approval_number, link_group FROM approval_evidence"
            " WHERE linked_transaction_id IN (%s)" % marks, ids):
        notes[transaction_id] = {"state": LINKED, "approval_number": number,
                                 "text": "승인내역과 매입내역에서 각각 확인됐습니다. 최종 회계 금액은 매입내역을 사용합니다."}
    rows = conn.execute(
        "SELECT transaction_id, card_tail, approval_date, raw_row_json FROM transactions"
        " WHERE transaction_id IN (%s) AND approval_number=''" % marks, ids).fetchall()
    for transaction_id, card, approved, raw_json in rows:
        if transaction_id in notes:
            continue
        usd = _overseas_usd(raw_json)
        if not usd:
            continue
        group = group_key(card, approved, usd)
        found = conn.execute(
            "SELECT link_state, COUNT(*) FROM approval_evidence WHERE link_group=? AND link_state IN (?,?)"
            " GROUP BY link_state", (group, GROUP_LINKED, GROUP_PARTIAL)).fetchall()
        if found:
            total = sum(c for _, c in found)
            notes[transaction_id] = {
                "state": found[0][0],
                "text": "동일한 속성의 거래가 %d건 있어 승인과 개별로 대응시킬 수 없습니다. "
                        "최종 회계 금액은 매입내역을 사용합니다." % total}
    return notes


def audit(conn) -> dict:
    """Read-only counts for operators."""
    out = {"states": {}}
    for state, count in conn.execute("SELECT link_state, COUNT(*) FROM approval_evidence GROUP BY link_state"):
        out["states"][state] = count
    out["approvals"] = sum(out["states"].values())
    return out
