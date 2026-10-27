"""Read-only investigation of a cancelled card transaction and potential originals.

Usage (on the authorised Windows host):
 python tools/trace_airline_cancellation.py --db "D:/.../board.sqlite" --date 2026-07-29 --amount 838600 --merchant 파라타항공

No writes; prints aggregate evidence only, not card numbers or transaction IDs.
"""
import argparse
import sqlite3
from pathlib import Path
from urllib.parse import quote


def inspect(conn, *, merchant, amount, day):
    conn.execute("PRAGMA query_only=ON")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    required = {"transaction_id", "transaction_direction", "merchant",
                "amount_krw", "approval_date", "issuer", "card_tail",
                "original_approval_number", "approval_number"}
    if not required <= columns:
        raise ValueError("Missing columns: " + ", ".join(sorted(required - columns)))
    clean = (" AND duplicate_of IS NULL AND conflict_reason='' AND parse_error=''"
             if {"duplicate_of", "conflict_reason", "parse_error"} <= columns else "")
    rows = conn.execute(
        "SELECT transaction_id,issuer,card_tail,approval_number,original_approval_number,"
        "amount_krw,approval_date,merchant FROM transactions"
        " WHERE transaction_direction='cancellation' AND amount_krw=?"
        " AND substr(approval_date,1,10)=? AND merchant LIKE ?"+clean,
        (-abs(amount), day, "%" + merchant + "%")).fetchall()
    results = []
    for tid, issuer, tail, approval, original, signed, when, label in rows:
        cards = conn.execute(
            "SELECT transaction_id,approval_number,amount_krw,approval_date,merchant "
            "FROM transactions WHERE transaction_direction='purchase' AND issuer=? AND card_tail=?"
            " AND amount_krw>0"+clean,
            (issuer,tail)).fetchall()
        exact_ref = [r for r in cards if original and str(r[1] or "").strip() == str(original).strip()]
        exact_amount = [r for r in cards if r[2] == abs(signed)]
        same_merchant = [r for r in cards if merchant.casefold() in str(r[4] or "").casefold()]
        preceding = [r for r in exact_amount if r[3] and str(r[3])[:10] <= str(when)[:10]]
        linked = None
        try:
            from app.partial_refund import refund_links
            linked = refund_links(conn, [tid]).get(tid)
        except ImportError:
            pass
        results.append({
            "transaction_found": True, "matched_by_existing_engine": bool(linked),
            "original_reference_present": bool(str(original or "").strip()),
            "purchase_count_same_card": len(cards),
            "purchase_count_original_approval": len(exact_ref),
            "purchase_count_exact_KRW": len(exact_amount),
            "purchase_count_exact_KRW_prior": len(preceding),
            "purchase_count_same_merchant": len(same_merchant),
            "ambiguous_exact_amount": len(preceding) > 1,
        })
    return {"matching_cancellations": len(rows), "diagnostics": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--date", default="2026-07-29")
    parser.add_argument("--amount", type=int, default=838600)
    parser.add_argument("--merchant", default="파라타항공")
    args = parser.parse_args()
    path = Path(args.db).resolve()
    uri = "file:" + quote(str(path).replace("\\", "/"), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        import json
        print(json.dumps(inspect(conn, merchant=args.merchant, amount=args.amount, day=args.date),
                         ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
