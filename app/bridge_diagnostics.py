"""reservation 여행과 연결되지 않은 COST 여행의 원인 분류. 진단용이며 연결을 만들지 않는다."""
import collections

from webapp.guide_airfare_review import _code_matches

CATEGORIES = ("SOURCE_KEY_RECOVERABLE", "MANUAL_CODE_NEEDED", "SOURCE_MISSING", "DATE_CONFLICT", "AMBIGUOUS")


def classify_unbridgeable(tours, trips, regions=None):
    """trips: bridge_coverage의 unbridgeable 여행(`display_key`, `starts_on`, `ends_on`, `tab_id`).

    - SOURCE_KEY_RECOVERABLE: 이미 공유하는 안정 키(같은 fldid/코드)가 있으나 연결만 안 된 경우. 키가 없으면 해당 없음.
    - MANUAL_CODE_NEEDED: 날짜가 정확히 같은 reservation 여행이 하나뿐이라 운영자가 코드를 확인해 입력하면 되는 경우.
    - AMBIGUOUS: 날짜가 정확히 같은 reservation 여행이 둘 이상.
    - DATE_CONFLICT: 같은 지역명이 제목에 있고 날짜 범위가 겹치지만 날짜가 정확히 같지는 않음.
    - SOURCE_MISSING: 대응할 reservation 여행이 보이지 않음.
    """
    regions = regions or {}
    result = {name: [] for name in CATEGORIES}
    for trip in trips:
        key = trip["display_key"]
        coded = [tour for tour in tours if _code_matches(tour.get("code"), trip)]
        if coded:
            result["SOURCE_KEY_RECOVERABLE"].append(key)
            continue
        exact = [tour for tour in tours
                 if tour.get("depart_date") == trip["starts_on"] and tour.get("return_date") == trip["ends_on"]]
        region = regions.get(key) or ""
        if len(exact) == 1:
            result["MANUAL_CODE_NEEDED"].append(key)
        elif len(exact) > 1:
            result["AMBIGUOUS"].append(key)
        elif region and any(region in tour.get("title", "") and _overlaps(tour, trip) for tour in tours):
            result["DATE_CONFLICT"].append(key)
        else:
            result["SOURCE_MISSING"].append(key)
    return result


def hold_statistics(snapshot_results):
    """스냅샷의 대장 항공권 판정 코드별 건수. 이름이나 탑승자 정보는 없다."""
    counts = collections.Counter()
    for row in snapshot_results:
        guide = row.get("guide_airfare") or {}
        if guide:
            counts[guide.get("code") or guide.get("status")] += 1
    return dict(counts)


def _overlaps(tour, trip) -> bool:
    start, end = tour.get("depart_date"), tour.get("return_date")
    if not start or not end:
        return False
    return start <= trip["ends_on"] and end >= trip["starts_on"]
