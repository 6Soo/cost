"""정리 완료 기간의 자료는 보존하되 신규 검토 목록에서 제외한다."""
import os
from datetime import date, datetime


def _day(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date()


def cutoff():
    return os.environ.get('WEBLEDGER_REVIEW_FROM', '2026-04-01')


def preserved_periods(periods):
    boundary = cutoff()
    if not boundary or not periods:
        return False
    for start, end in periods:
        values = [v for v in (start, end) if v]
        if not values:
            return False
        try:
            if any(_day(v) >= _day(boundary) for v in values):
                return False
        except (TypeError, ValueError):
            return False
    return True
