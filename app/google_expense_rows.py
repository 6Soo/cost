"""Read original expense cells in known workbook layouts without converting sheets.

This is row evidence only: a readable expense block proves neither income nor
the sheet's totals. Unknown or duplicate headers never mean an empty ledger.
"""
import datetime as dt
import math
import re

from openpyxl.utils.datetime import from_excel


HEADERS = (
    ('rev', (2, 3, 4, 5, 6, 7, 8),
     ('거래일자', '항목', '내용', '기간', '예약번호', '증빙유형', '금액(원)')),
    ('europe', (1, 2, 3, 4, 5, 6, 7),
     ('거래일자', '항목', '내용', '기간', '예약번호', '증빙유형', '금액(원)')),
    ('legacy', (2, 4, 6, 8, 9),
     ('거래일자', '항목', '내용', '증빙유형', '금액(원)')),
)


def day(value, year=None):
    """Source date only; year is the explicit ledger year, never today's year."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 40000 < value < 60000:
        return from_excel(value).date().isoformat()
    text = str(value or '').strip()
    match = re.fullmatch(r'(?:(\d{4})[./년\s-]+)?(\d{1,2})[./월\s-]+(\d{1,2})[.일\s]*', text)
    if not match or not (match[1] or year):
        return None
    try:
        return dt.date(int(match[1] or year), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


def read(ws_f, ws_v):
    rows = list(ws_v.iter_rows(values_only=True))
    found = []
    for number, values in enumerate(rows, 1):
        for layout, columns, labels in HEADERS:
            if tuple(str(values[c-1] or '').strip() if c <= len(values) else '' for c in columns) == labels:
                found.append((number, layout, columns, labels))
    if len(found) != 1:
        return {'status': 'unavailable', 'flags': ['EXPENSE_HEADER_UNCLEAR'], 'rows': []}
    header, layout, columns, labels = found[0]
    fields = dict(zip(labels, columns))
    formula_rows = list(ws_f.iter_rows(values_only=True))
    from openpyxl.utils.cell import get_column_letter
    letter = get_column_letter(fields['금액(원)'])
    total = re.compile(r'=\s*SUM\(\s*\$?' + letter + r'\$?(\d+)\s*:\s*\$?' + letter + r'\$?(\d+)\s*\)', re.I)
    stop = len(rows) + 1
    for number, values in enumerate(formula_rows[header:], header+1):
        if any((m := total.fullmatch(v)) and int(m[1]) in (header, header+1) and int(m[2]) < number
               for v in values if isinstance(v, str)):
            stop = number
            break
    canonical = {'B': '거래일자', 'C': '항목', 'D': '내용', 'E': '기간', 'F': '예약번호', 'G': '증빙유형'}
    result, flags = [], set()
    for number in range(header+1, stop):
        values = rows[number-1]
        def cell(label):
            column = fields.get(label)
            return values[column-1] if column and column <= len(values) else None
        payee, description, amount = cell('항목'), cell('내용'), cell('금액(원)')
        if str(payee or '').strip() in ('총 금액', '합계', '총계', '지출 합계', '총 지출'):
            break
        # Summary/formula rows without a payee or expense description are not transactions.
        if payee in (None, '') and description in (None, ''):
            continue
        if amount in (None, ''):
            formula = formula_rows[number-1][fields['금액(원)']-1]
            if isinstance(formula, str) and formula.startswith('='):
                flags.add('AMOUNT_NOT_CACHED')
            continue
        if (isinstance(amount, bool) or not isinstance(amount, (int, float))
                or not math.isfinite(amount) or not float(amount).is_integer()):
            flags.add('AMOUNT_INVALID')
            continue
        cells = {key: cell(label) for key, label in canonical.items()}
        for key, value in cells.items():
            if isinstance(value, (dt.datetime, dt.date)):
                cells[key] = value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
        result.append({'row': number, 'cells': cells, 'amount': int(amount)})
    return {'status': 'readable' if not flags else 'invalid', 'flags': sorted(flags),
            'layout': layout, 'header_row': header, 'rows': result}
