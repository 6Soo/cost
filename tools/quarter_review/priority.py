"""Deterministic review ordering for the quarter review pack."""
from __future__ import annotations


REASON_WEIGHTS = (
    ("최근 자동 변경", 35),
    ("AI 판정", 30),
    ("이용일 불명확", 25),
    ("추론 근거", 20),
    ("항목 미확정", 15),
    ("불확실성 기록", 10),
)


def review_reasons(row):
    """Return stable, user-facing reasons contributing to a row's score."""
    reasons = []
    if row.get("recent_auto_change"):
        reasons.append("최근 자동 변경")
    source = row.get("classification_source")
    if source == "ai_inference" or row.get("source_label") == "AI 판정":
        reasons.append("AI 판정")
    if row.get("service_date_unknown"):
        reasons.append("이용일 불명확")
    if source in {"inference", "auto_inferred", "code_inference", "guide_airfare_evidence"}:
        reasons.append("추론 근거")
    if not row.get("item"):
        reasons.append("항목 미확정")
    uncertainty = row.get("uncertainty") or row.get("classification_uncertainty")
    basis = str(row.get("classification_basis") or "")
    if uncertainty or row.get("uncertainty_reason") or "불확실성" in basis:
        reasons.append("불확실성 기록")
    return reasons


def review_score(row):
    score = sum(weight for reason, weight in REASON_WEIGHTS if reason in review_reasons(row))
    amount = row.get("amount_krw")
    try:
        score += min(40, abs(int(amount)) // 100000 * 5)
    except (TypeError, ValueError):
        pass
    return score


def prioritize(rows):
    """Filter manual decisions and sort deterministically by review priority."""
    candidates = [row for row in rows if not row.get("manual")]
    for row in candidates:
        row["review_score"] = review_score(row)
        row["review_reasons"] = review_reasons(row)
    return sorted(candidates, key=lambda row: (
        -row["review_score"], -abs(int(row.get("amount_krw") or 0)), str(row.get("row_id", ""))))
