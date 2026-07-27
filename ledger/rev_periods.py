"""매출확인자료의 내용/기간 열 분리 규칙."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path


_CATEGORY = {
    "숙박": "숙박",
    "숙박비": "숙박",
    "료칸": "숙박",
    "항공": "항공",
    "항공료": "항공",
    "렌터카": "렌트",
    "렌트": "렌트",
    "여행자보험": "여행자보험",
}


def split_content(value: object) -> tuple[str, str]:
    """`항공_0404_0407_김OO` → (`항공_김OO`, `0404_0407`).

    항공은 날짜가 하나면 편도 출발일, 둘이면 왕복 출발일_도착일로
    기간 열에 기록한다. 숙박은 체크인_체크아웃, 렌터카는
    인수일_반납일 두 날짜가 모두 있을 때 기간으로 기록한다.
    """
    source = str(value or "").strip()
    match = re.match(
        r"^(숙박비|숙박|항공료|항공|렌터카|렌트|료칸|여행자보험)(?:_(.*))?$", source
    )
    if not match:
        return source, ""

    category = _CATEGORY[match.group(1)]
    remainder = match.group(2) or ""
    period_match = re.match(r"^(\d{4})(?:_(\d{4}))?(?:_(.*))?$", remainder)
    if not period_match:
        return category + (f"_{remainder}" if remainder else ""), ""

    departure = period_match.group(1)
    arrival = period_match.group(2)
    detail = period_match.group(3)
    if category == "렌트" and not arrival:
        return category + (f"_{remainder}" if remainder else ""), ""
    period = departure + (f"_{arrival}" if arrival else "")
    content = category + (f"_{detail}" if detail else "")
    return content, period


def resolve_item_period(content: str, period: str, item: object) -> tuple[str, str]:
    """항공 항목명에 명시된 출발일/도착일을 기간으로 사용한다.

    예: ``트립닷컴_0417_0429`` + ``항공_이상희`` → 기간 ``0417_0429``.
    이미 내용 또는 OTA 검증 데이터에서 얻은 기간은 덮어쓰지 않는다.
    """
    if period or not str(content).startswith("항공"):
        return content, period
    match = re.search(r"(?:^|_)(\d{4})(?:_(\d{4}))?(?:_|$)", str(item or ""))
    if not match:
        return content, ""
    departure, arrival = match.groups()
    return content, departure + (f"_{arrival}" if arrival else "")


def normalize_booking_number(value: object) -> str:
    """엑셀 숫자/문자 혼용과 Gmail의 보이지 않는 구분자를 제거한다."""
    text = re.sub(r"[\u200b-\u200d\u2060\ufeff\s]", "", str(value or ""))
    return re.sub(r"\.0$", "", text)


def load_verified_booking_periods(
    path: str | Path = "booking_periods_verified.json",
) -> dict[str, dict[str, str]]:
    """OTA 메일 원문으로 확인된 예약번호별 기간만 읽는다."""
    source = Path(path)
    if not source.exists():
        return {}
    data = json.loads(source.read_text(encoding="utf-8"))
    return {normalize_booking_number(k): v for k, v in data.items()}


def resolve_period(
    content: str,
    embedded_period: str,
    booking_number: object,
    verified: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """내용에 이미 있는 기간을 우선하고, 없을 때만 OTA 검증값을 쓴다."""
    if embedded_period:
        return content, embedded_period
    info = verified.get(normalize_booking_number(booking_number))
    if not info:
        return content, ""
    category = _CATEGORY.get(info.get("category", "").strip(), info.get("category", "").strip())
    if category and content in {"숙박", "항공", "렌트"}:
        content = category
    period = info.get("period", "").strip()
    # 렌터카 기간은 OTA 예약의 인수일과 반납일이 모두 확인된 경우만 채운다.
    if content == "렌트" and not re.fullmatch(r"\d{4}_\d{4}", period):
        return content, ""
    return content, period


def fill_unique_item_periods(rows: list[tuple]) -> list[tuple]:
    """같은 탭 안에서 동일 항목의 확정 기간이 하나뿐일 때만 공란을 승계한다.

    행 구조는 (거래일, 항목, 내용, 기간, 예약번호, 증빙, 금액)이다.
    예약번호가 있는 숙박/렌트 건만 대상으로 하여 일반 가맹점의 우연한 병합을 막는다.
    """
    periods: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        item, content, period = str(row[1]), str(row[2]), str(row[3])
        if period:
            periods[(re.sub(r"\s+", " ", item).strip().upper(), content)].add(period)

    filled = []
    for row in rows:
        if row[3] or not normalize_booking_number(row[4]) or row[2] not in {"숙박", "렌트"}:
            filled.append(row)
            continue
        key = (re.sub(r"\s+", " ", str(row[1])).strip().upper(), str(row[2]))
        candidates = periods.get(key, set())
        if len(candidates) == 1:
            row = row[:3] + (next(iter(candidates)),) + row[4:]
        filled.append(row)
    return filled
