"""Safety guards for offline P2 suggestions.

The model may suggest a service period only when that date is present in the
evidence excerpts it cited.  A case with no evidence is allowed to retain its
existing trip and period, but cannot invent either one.
"""

from __future__ import annotations

import re


_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일?(?!\d)"),
)


def normalize_dates(text: str) -> set[str]:
    """Return ISO dates represented in arbitrary common date spellings."""
    found: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for year, month, day in pattern.findall(text or ""):
            found.add(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    return found


def guard_result(result: dict, evidence: dict[str, str], *, existing_trip: str = "") -> dict:
    """Sanitize a model result against the text of its cited evidence.

    ``evidence`` maps evidence reference IDs to their excerpt text.  The
    returned object is a copy and never mutates the model's raw response.
    """
    guarded = dict(result)
    refs = [ref for ref in result.get("evidence_refs", []) if ref in evidence]
    dates = normalize_dates("\n".join(evidence[ref] for ref in refs))
    start = guarded.get("service_start") or ""
    end = guarded.get("service_end") or ""
    if not refs:
        guarded["evidence_refs"] = []
        guarded["trip_id"] = existing_trip or "기존 여행 유지"
        guarded["service_start"] = ""
        guarded["service_end"] = ""
        guarded["confidence"] = "낮음"
        guarded["uncertainty"] = _append(guarded.get("uncertainty"), "인용 근거가 없어 여행·이용기간은 기존 값을 유지")
        return guarded
    if (start and start not in dates) or (end and end not in dates):
        guarded["service_start"] = ""
        guarded["service_end"] = ""
        guarded["uncertainty"] = _append(guarded.get("uncertainty"), "제안한 이용기간이 인용 근거 발췌에 없어 미확인으로 유지")
    guarded["evidence_refs"] = refs
    return guarded


def _append(current: str | None, addition: str) -> str:
    return f"{current} · {addition}" if current else addition
