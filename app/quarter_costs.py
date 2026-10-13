"""분기 기타비용의 Google 복사 목적지. 원문·여행 배정·확정은 변경하지 않는다."""
import datetime as dt
import re


def _tab_of(row):
    day = row.get('approval_date') or row.get('posting_date') or ''
    try:
        date_value = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        return None
    return f'quarter:{date_value.year}:{(date_value.month - 1) // 3 + 1}'


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
    quarter = (day.month - 1) // 3 + 1
    return {'id': f'quarter:{day.year}:{quarter}', 'year': day.year, 'quarter': quarter,
            'sheet': f'{quarter}분기_기타비용', 'name': f'{day.year}년 {quarter}분기 기타비용'}


def scope(originals, preview_rows, target):
    if not re.fullmatch(r'quarter:20\d{2}:[1-4]', target):
        raise ValueError('QUARTER_TARGET_INVALID')
    by_id = {row['transaction_id']: row for row in originals}
    # Keep duplicate preview identities for the existing shared duplicate guard.
    return [{**row, 'display_tab_id': target} for row in preview_rows
            if (destination(by_id.get(row.get('transaction_id'), {})) or {}).get('id') == target]
