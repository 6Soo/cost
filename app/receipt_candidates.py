"""Japanese receipt candidates from one A4 scan with several receipts. Synthetic-fed; no OCR engine.

An OCR engine is not approved, so this module takes the regions an engine would report and does
everything after that: split, hold unclear regions, convert cash and private-card totals at the
simple ledger rate (1 JPY = 10 KRW), match corporate-card receipts to a single card transaction
as evidence, and keep user confirmation separate from the machine reading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

JPY_TO_KRW = 10  # Simple internal ledger rate (JPY 100 = KRW 1,000). Not a tax or card rate.
MIN_CONFIDENCE = 0.8
PAYMENTS = ("cash", "private_card", "corporate_card")
BOX_OVERLAP_HOLD = 0.2  # Overlap share of the smaller box that makes two regions unclear.


@dataclass
class Region:
    page_id: str
    box: tuple  # (x0, y0, x1, y1) in page units
    merchant: str | None
    date: str | None
    currency: str | None
    total: int | None
    payment: str | None
    confidence: float


def _overlap(a: tuple, b: tuple) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return (w * h) / smaller


def _identity(region: Region) -> str:
    # page_id is the scanned image's content fingerprint, so a re-upload of the same image has the same identity.
    raw = json.dumps([region.page_id, list(region.box), region.merchant, region.date, region.total, region.payment],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def split_page(regions: list[Region]) -> dict:
    """Keeps clear receipts and holds unclear ones with a reason. Never splits one receipt into items."""
    holds, clear = [], []
    for index, region in enumerate(regions):
        reason = None
        if region.confidence < MIN_CONFIDENCE:
            reason = "LOW_CONFIDENCE"
        elif region.currency != "JPY":
            reason = "CURRENCY_UNKNOWN"
        elif region.total is None or region.total <= 0:
            reason = "TOTAL_UNCLEAR"
        elif region.payment not in PAYMENTS:
            reason = "PAYMENT_UNKNOWN"
        elif not region.date or not region.merchant:
            reason = "FIELD_MISSING"
        elif any(_identity(other) != _identity(region) and _overlap(region.box, other.box) > BOX_OVERLAP_HOLD
                 for other in regions):
            reason = "OVERLAP"
        if reason:
            holds.append({"identity": _identity(region), "reason": reason})
        else:
            clear.append(region)
    return {"clear": clear, "holds": holds}


@dataclass
class Candidate:
    identity: str
    date: str
    merchant: str
    total_jpy: int
    payment: str
    amount_krw: int | None
    card_transaction_id: str | None = None
    category: str | None = None
    payee: str | None = None
    history: list = field(default_factory=list)


def build_candidates(regions: list[Region], card_rows: list[dict], known: set | frozenset = frozenset()) -> dict:
    """card_rows: [{transaction_id, date, merchant, original_jpy}] for corporate-card receipts.
    known: identities already stored. A repeated scan of the same receipt adds nothing."""
    split = split_page(regions)
    candidates, holds = [], list(split["holds"])
    seen = set()
    for region in split["clear"]:
        identity = _identity(region)
        if identity in seen or identity in known:
            continue  # the same receipt scanned again is still one candidate
        seen.add(identity)
        if region.payment == "corporate_card":
            matches = [r for r in card_rows
                       if r["date"] == region.date and r["merchant"] == region.merchant
                       and r.get("original_jpy") is not None
                       and float(r["original_jpy"]) == float(region.total)]
            if len(matches) == 1:
                candidates.append(Candidate(identity, region.date, region.merchant, region.total,
                                            region.payment, None, card_transaction_id=matches[0]["transaction_id"]))
            else:
                holds.append({"identity": identity,
                              "reason": "CARD_MATCH_AMBIGUOUS" if matches else "CARD_NOT_FOUND"})
        else:
            candidates.append(Candidate(identity, region.date, region.merchant, region.total, region.payment,
                                        region.total * JPY_TO_KRW))
    return {"candidates": candidates, "holds": holds}


def confirm(candidate: Candidate, *, payee: str, category: str, note: str = "") -> Candidate:
    """A person sets payee and category. The machine reading is never called confirmed."""
    if not payee.strip() or not category.strip():
        raise ValueError("FIELD_MISSING")
    candidate.history.append({"from": {"payee": candidate.payee, "category": candidate.category},
                              "to": {"payee": payee, "category": category}, "note": note})
    candidate.payee, candidate.category = payee.strip(), category.strip()
    return candidate


def to_expense_rows(candidates: list[Candidate]) -> list[dict]:
    """Rows for app.google_tsv.expense_tsv. Card-matched receipts are evidence, not a second expense."""
    rows = []
    for c in candidates:
        # A corporate-card receipt is either the card purchase it matches (already a cost) or held.
        if c.payment == "corporate_card" or c.card_transaction_id:
            continue
        rows.append({
            "transaction_id": f"receipt:{c.identity}",
            "date": c.date,
            "payee": c.payee or "",
            "category": c.category or "",
            "period": "",
            "reservation_no": "",
            "evidence": "receipt",
            "amount_krw": c.amount_krw,
            "status": "ready" if c.payee and c.category else "not_ready",
        })
    return rows
