"""Maps one trip's card preview rows to the Google 7-column paste text.

Field mapping, from the existing ledger and the business rules: Google C 지급처 is the merchant,
Google D 내용 is the classified expense item (for example 숙박비). The free-text description is
not pasted. Rows the preview blocked are listed with the preview's own reason, never pasted. Rows
that are already in the COST ledger are still pasted, because the destination is Google.
"""

from app.google_tsv import expense_tsv


def tsv_for_tab(preview_rows: list[dict], tab_id: str) -> dict:
    if not tab_id:
        raise ValueError("TAB_REQUIRED")
    rows, blocked = [], []
    for row in preview_rows:
        if (row.get("display_tab_id") or "") != tab_id:
            continue
        if row.get("blocked"):
            blocked.append({"transaction_id": row.get("transaction_id"), "reason": row["blocked"]})
            continue
        rows.append({
            "transaction_id": row.get("transaction_id"),
            "date": row.get("occurred_on") or "",
            "payee": row.get("merchant") or "",
            "category": row.get("item") or "",
            "period": row.get("service_period") or "",
            "reservation_no": row.get("booking_ref") or "",
            "evidence": "card",
            "amount_krw": row.get("amount_krw"),
            "status": "ready",
        })
    result = expense_tsv(rows, layout="rev")
    return {**result, "held": blocked + result["held"], "tab_id": tab_id}
