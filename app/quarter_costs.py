"""분기 기타비용의 Google 복사 목적지. 원문·여행 배정은 변경하지 않는다."""
import datetime as dt
import re

#: 현행 여행(0630_오제)부터는 3분기 기타비용이다. 그 앞의 6월 말 거래는 2분기에 남는다.
CURRENT_PERIOD_START = dt.date(2026, 6, 30)
CURRENT_PERIOD_END = dt.date(2026, 9, 30)


def quarter_of(day):
    """(year, quarter) for a cost row's date."""
    if CURRENT_PERIOD_START <= day <= CURRENT_PERIOD_END:
        return day.year, 3
    return day.year, (day.month - 1) // 3 + 1


def _tab_of(row):
    day = row.get('approval_date') or row.get('posting_date') or ''
    try:
        date_value = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        return None
    year, quarter = quarter_of(date_value)
    return f'quarter:{year}:{quarter}'


def destination(row):
    if (row.get('item') != '분기 기타비용'
            or row.get('display_tab_id') not in (None, '', 'unclassified', _tab_of(row))
            or row.get('transaction_direction') != 'purchase'
            or type(row.get('amount_krw')) is not int or row['amount_krw'] <= 0):
        return None
    try:
        day = dt.date.fromisoformat(row.get('approval_date') or row.get('posting_date') or '')
    except (TypeError, ValueError):
        return None
    year, quarter = quarter_of(day)
    return {'id': f'quarter:{year}:{quarter}', 'year': year, 'quarter': quarter,
            'sheet': f'{quarter}분기_기타비용', 'name': f'{year}년 {quarter}분기 기타비용'}


def scope(originals, preview_rows, target):
    if not re.fullmatch(r'quarter:20\d{2}:[1-4]', target):
        raise ValueError('QUARTER_TARGET_INVALID')
    by_id = {row['transaction_id']: row for row in originals}
    # Keep duplicate preview identities for the existing shared duplicate guard.
    return [{**row, 'display_tab_id': target} for row in preview_rows
            if (destination(by_id.get(row.get('transaction_id'), {})) or {}).get('id') == target]
