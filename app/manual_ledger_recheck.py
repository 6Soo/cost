"""Re-read original manual ledgers for explicit cross-quarter source review.

The amount/date-or-payee rule identifies existing rows; it creates neither
payment links nor trips. Conflicting destinations and actual decisions stay out.
"""
import io
import json
import re
import unicodedata

import openpyxl

from .google_expense_rows import day, read


def merchant_part(left, right):
    def normalize(value):
        value = unicodedata.normalize('NFKC', str(value or '')).casefold()
        for old, new in (('trip.com', '트립닷컴'), ('agoda', '아고다'),
                         ('rakuten', '라쿠텐'), ('booking.com', '부킹닷컴')):
            value = value.replace(old, new)
        return re.sub(r'[^a-z0-9가-힣]', '', value)
    a, b = normalize(left), normalize(right)
    generic = {'hotel', 'hotels', '호텔', '주식회사', '유한회사', '이니시스',
               '나이스', '나이스정보통신', '숙박', '숙박비', '식당', '식비',
               '택시', '교통비', '항공료', '기타', '온라인', 'the', 'and'}
    for size in range(min(len(a), len(b)), 1, -1):
        for index in range(len(a) - size + 1):
            part = a[index:index + size]
            if (not any(part in word for word in generic) and part in b
                    and (re.search('[가-힣]', part) or size >= 4)):
                return part
    return ''


def same_transaction(card, original):
    return (card['amount_krw'] == original['amount'] and
            (card.get('approval_date') == day(original['cells'].get('B'), 2026)
             or bool(merchant_part(card.get('merchant'), original['cells'].get('C')))))


def _workbook_rows(content, *, historical, valid):
    values = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    formulas = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    result = []
    try:
        for sheet in values.sheetnames:
            if historical and '행사경비총괄표' in sheet:
                continue
            trip = next((t for t in valid.values() if t.get('display_key') == sheet
                         and not t.get('deleted')), None)
            if not historical and (not trip or not '2026-07-01' <= (trip.get('starts_on') or '') <= '2026-12-31'):
                continue
            parsed = read(formulas[sheet], values[sheet])
            if parsed['status'] != 'readable':
                raise ValueError('SOURCE_RECHECK_LEDGER_UNREADABLE')
            result.extend(dict(row, sheet=sheet, trip_id=None if historical else
                               (trip.get('trip_id') or trip.get('tab_id')))
                          for row in parsed['rows'])
    finally:
        values.close()
        formulas.close()
    return result


def attribution(conn, row, trips, originals):
    from .automatic_classification import _read
    from .google_authority import SPREADSHEET_IDS
    valid = {t.get('trip_id') or t.get('tab_id'): t for t in trips}
    books = {}
    for original, content in originals:
        role = original.get('ledger_source')
        if (role not in ('archive', 'main') or role in books
                or original.get('spreadsheet_id') != SPREADSHEET_IDS[role]):
            raise ValueError('SOURCE_RECHECK_LEDGER_INVALID')
        books[role] = _workbook_rows(content, historical=role == 'archive', valid=valid)
    if set(books) != {'archive', 'main'}:
        raise ValueError('SOURCE_RECHECK_LEDGER_INVALID')
    if any(same_transaction(row, original) for original in books['archive']):
        raise ValueError('SOURCE_RECHECK_LEDGER_ALREADY_PRESENT')
    matches = [original for original in books['main'] if same_transaction(row, original)]
    if len(matches) != 1:
        raise ValueError('SOURCE_RECHECK_LEDGER_AMBIGUOUS')
    original = matches[0]
    # An ambiguous card identity is not an authorization to move several rows.
    if sum(same_transaction(card, original) for card in _read(conn)) != 1:
        raise ValueError('SOURCE_RECHECK_LEDGER_AMBIGUOUS')
    trip = valid[original['trip_id']]
    period = re.fullmatch(r'(\d{2})(\d{2})[~_\-](\d{2})(\d{2})',
                          str(original['cells'].get('E') or '').strip())
    if not period:
        raise ValueError('SOURCE_RECHECK_LEDGER_PERIOD_INVALID')
    from datetime import date
    try:
        starts = date(2026, int(period[1]), int(period[2])).isoformat()
        ends = date(2026, int(period[3]), int(period[4])).isoformat()
    except ValueError:
        raise ValueError('SOURCE_RECHECK_LEDGER_PERIOD_INVALID') from None
    if not ('2026-07-01' <= starts <= ends <= '2026-12-31'
            and trip['starts_on'] <= starts and ends <= trip.get('ends_on', '')):
        raise ValueError('SOURCE_RECHECK_LEDGER_PERIOD_INVALID')
    description = str(original['cells'].get('D') or '')
    item = next((value for marker, value in (('항공', '항공료'), ('숙박', '숙박비'),
                 ('렌터카', '렌터카'), ('교통', '교통비')) if description.startswith(marker)), None)
    if not item:
        raise ValueError('SOURCE_RECHECK_LEDGER_ITEM_INVALID')
    return dict(display_tab_id=original['trip_id'], item=item,
                google_sheet=original['sheet'], google_row=original['row'],
                ledger_period=dict(starts_on=starts, ends_on=ends),
                ledger_match='amount+date' if row['approval_date'] == day(original['cells'].get('B'), 2026)
                             else 'amount+merchant_part')


def legacy_owner_import(conn, row):
    """Only the original import without any selected trip, never a later edit."""
    revisions = conn.execute('SELECT actor,prev_json,new_json,client_request_id '
        'FROM board_revisions WHERE row_id=? ORDER BY id', ('card-' + row['transaction_id'],)).fetchall()
    if not revisions:
        return False
    actor, previous, new, request = revisions[0]
    payload = json.loads(new or '{}')
    return (actor == 'owner' and previous in (None, '', '{}', 'null')
            and request == 'card-' + row['transaction_id']
            and payload.get('confirmed_by') == 'owner'
            and payload.get('display_tab_id') in (None, '', 'unclassified')
            and payload.get('trip_id') in (None, '', 'unclassified')
            and payload.get('source_event_id') == row['transaction_id']
            and payload.get('amount_krw') == row['amount_krw']
            and payload.get('source_fact_digest') == row['source_hash']
            and all(r[0] == 'automatic' for r in revisions[1:]))
