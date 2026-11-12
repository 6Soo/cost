"""Deterministic reasons and ordering for the quarter review list."""
from __future__ import annotations


MANUAL_SOURCES = frozenset({"user_decision", "user_exception"})
INFERRED_SOURCES = frozenset({"inference", "code_inference", "card_category", "owner_card_residual"})
PERIOD_ITEMS = frozenset({"숙박비", "항공료", "교통비", "입장료"})
GENERIC_ITEMS = frozenset({"기타경비", "현지경비"})
WEIGHTS = {"최근 자동 변경": 35, "AI 판정": 30, "이용일 미확인": 25,
           "추론 귀속": 20, "포괄 항목": 15, "불확실성 기록": 10}


def review_reasons(row):
    """Return stable, user-facing reasons contributing to a row's score."""
    source = row.get("source", row.get("classification_source", ""))
    if source in MANUAL_SOURCES:
        return []
    reasons = []
    if row.get("changed_recently", row.get("recent_auto_change", False)):
        reasons.append("최근 자동 변경")
    if source == "ai_inference" or row.get("source_label") == "AI 판정":
        reasons.append("AI 판정")
    if (row.get("tab_kind", "trip") == "trip" and not row.get("has_service_period", False)
            and row.get("item", "") in PERIOD_ITEMS and row.get("allow_service_reason", False)):
        reasons.append("이용일 미확인")
    if source in INFERRED_SOURCES:
        reasons.append("추론 귀속")
    if row.get("item", "") in GENERIC_ITEMS:
        reasons.append("포괄 항목")
    uncertainty = row.get("uncertainty") or row.get("classification_uncertainty") or ""
    if str(uncertainty).strip() or "불확실성" in str(row.get("classification_basis", "")):
        reasons.append("불확실성 기록")
    return reasons


def review_score(row):
    reasons = review_reasons(row)
    if not reasons:
        return 0
    score = sum(WEIGHTS[reason] for reason in reasons)
    amount = row.get("amount_krw")
    try:
        score += min(40, abs(int(amount)) // 100000 * 5)
    except (TypeError, ValueError):
        pass
    return score


def prioritize(rows):
    """Filter manual decisions and sort deterministically by review priority."""
    scored = []
    for row in rows:
        source = row.get("source", row.get("classification_source", ""))
        if row.get("manual") or source in MANUAL_SOURCES:
            continue
        reasons = review_reasons(row)
        if not reasons:
            continue
        result = dict(row)
        result["review_score"] = review_score(row)
        result["review_reasons"] = reasons
        scored.append((result["review_score"], abs(int(row.get("amount_krw") or 0)),
                       str(row.get("row_id", "")), result))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in scored]
