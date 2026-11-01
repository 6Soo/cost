"""Verified Hana usage and IBK print layouts; source cells stay untouched."""
import re

from .normalize import AmountUnreadable, is_cancel_text, to_amount_krw, to_date, to_decimal


HANA_USAGE = ('NO', '이용일자', '매입일자', '카드번호', '구분', '매출구분',
              '승인번호', '가맹점명', '', '가맹점번호', '매출금액', '취소구분',
              '환가료', '할인금액', '결제일자', '부가세')
HANA_FOREIGN = ('번호', '이용일', '카드번호', '승인번호', '가맹점명',
                '현지거래금액', '원화금액', '정산금액', '환율', '환가료', '국가명', '청구금액')
IBK_PRINT = ('승인구분', '이용구분', '승인일시', '카드번호', '카드별명',
             '이용가맹점명', '승인금액', '현지외화금액', '제휴카드명', '할부개월',
             '승인금액(USD)', '적용환율', '이용수수료', '승인번호', '컵보증금',
             '할인금액', '취소금액', '취소일자', '매출표접수일자', '결제예정일자', '가맹점사업자번호')


def _text(value):
    return re.sub(r'\s+', '', str(value or ''))


def _foreign(value):
    text = str(value or '').strip()
    match = re.fullmatch(r'([+-]?[\d,.]+)\s*\(?([A-Z]{3})\)?', text)
    if not match:
        try:
            return format(to_decimal(value, 'foreign_amount'), 'f'), ''
        except AmountUnreadable:
            return '', ''  # Never infer a currency from a country or a rate.
    return format(to_decimal(match[1], 'foreign_amount'), 'f'), match[2]


def parse_export(cells, fmt, filename):
    """Return None unless the complete, observed layout signature matches."""
    from .import_card import ParsedFile, ParsedRow, _card_tail, _normalize_row

    layout = None
    start = 0
    for i, values in enumerate(cells[:20]):
        headers = tuple(_text(v) for v in values)
        if headers == HANA_USAGE:
            layout, start = 'hana_usage', i + 1
            columns = dict(approval_date=1, posting_date=2, card_mask=3,
                           transaction_type=5, approval_number=6, merchant=7,
                           amount=10, status=11, card_kind=4)
            break
        if headers == HANA_FOREIGN:
            layout, start = 'hana_foreign', i + 1
            columns = dict(approval_date=1, card_mask=2, approval_number=3,
                           merchant=4, foreign_amount=5, krw_amount=11)
            break
        if headers == ('',) + IBK_PRINT or headers == IBK_PRINT:
            layout, start = 'ibk_print', i + 1
            shift = int(headers[0] == '')
            columns = {name: index + shift for name, index in dict(
                status=0, transaction_type=1, approval_date=2, card_mask=3,
                merchant=5, amount=6, foreign_amount=7, approval_number=13,
                posting_date=18).items()}
            cancel_index = 16 + shift
            break
    if layout is None:
        # Headerless IBK print download uses the same 21 columns. Require the
        # currency marker, date, account, amount and merchant, not just width.
        for values in cells[:6]:
            if (19 <= len(values) <= 21 and values[0] in ('원화', '외화')
                    and to_date(values[2]) and _card_tail(values[3])
                    and str(values[5] or '').strip()):
                try:
                    to_amount_krw(values[6])
                except AmountUnreadable:
                    continue
                layout = 'ibk_print'
                columns = dict(status=0, transaction_type=1, approval_date=2,
                               card_mask=3, merchant=5, amount=6, foreign_amount=7,
                               approval_number=13, posting_date=18)
                cancel_index = 16
                break
    if layout is None:
        return None

    rows, issues = [], []
    for offset, values in enumerate(cells[start:], start=start):
        def at(name):
            index = columns.get(name)
            return values[index] if index is not None and index < len(values) else None

        identity = any(str(at(name) or '').strip() for name in
                       ('approval_date', 'card_mask', 'merchant', 'approval_number'))
        summary = any(_text(v) in ('총계', '합계') for v in values[:3])
        if not identity and (summary or not any(str(at(name) or '').strip()
                                               for name in ('amount', 'krw_amount'))):
            continue  # Footer labels are still scanned for unsafe formulas.
        row = ParsedRow(row_index=offset + 1, source_row=list(values),
                        raw={f'c{i}': None if v is None else str(v)
                             for i, v in enumerate(values)})
        _normalize_row(row, values, columns, None)
        if 'posting_date' not in columns:
            row.posting_date = ''  # This compact view supplies no posting date.
        row.issuer = '기업' if layout == 'ibk_print' else '하나'
        # Keep alphanumeric issuer approval IDs intact in these export layouts.
        row.approval_number = str(at('approval_number') or '').strip()
        row.foreign_amount, row.foreign_currency = _foreign(at('foreign_amount'))
        if layout == 'hana_usage':
            # This view separates the principal (매출금액) and exchange fee
            # (환가료); their sum is the overseas view's billed 청구금액.
            try:
                total = to_amount_krw(at('amount')) + to_amount_krw(values[12] or 0, 'fee')
                row.amount_krw = -abs(total) if row.transaction_direction == 'cancellation' else total
            except AmountUnreadable:
                row.amount_krw = None
                row.parse_error = 'usage_amount_unreadable'
        if layout == 'hana_foreign':
            row.card_kind = '해외'
        elif not row.card_kind:
            row.card_kind = '해외' if '해외' in str(at('transaction_type') or '') else '국내'
        if row.amount_krw is not None and row.amount_krw < 0:
            row.transaction_direction = 'cancellation'
        if layout == 'ibk_print' and is_cancel_text(at('status')):
            # The cancellation column, not the original purchase amount, is
            # the financial effect of this cancellation event.
            try:
                row.amount_krw = -abs(to_amount_krw(values[cancel_index], 'cancel_amount'))
            except (IndexError, AmountUnreadable):
                row.amount_krw = None
                row.parse_error = 'cancel_amount_missing'
        if row.parse_error:
            issues.append({'row_index': row.row_index, 'error': row.parse_error})
        rows.append(row)
    return ParsedFile(filename=filename, parser=f'{fmt}:{layout}',
                      headers=list(cells[start - 1]) if start else [], rows=rows,
                      issues=issues, channel='overseas_acquired' if layout == 'hana_foreign'
                      else 'domestic_acquired' if layout == 'hana_usage' else 'statement')


def existing_purchase(store, batch_id, parser, row):
    """Reuse a verified purchase across views, or preserve a source conflict.

    Missing posting/currency details in a compact view cannot erase the fuller
    source. Refunds and repeated rows within the same file retain multiplicity.
    """
    if parser.split(':', 1)[-1] not in ('hana_usage', 'hana_foreign', 'ibk_print'):
        return None
    if (row.transaction_direction != 'purchase' or row.parse_error
            or not row.approval_number or not row.card_tail or not row.approval_date):
        return None
    candidates = store.conn.execute(
        "SELECT transaction_id,merchant_normalized,amount_krw,foreign_amount,foreign_currency,posting_date "
        "FROM transactions WHERE issuer=? AND card_tail=? AND approval_number=? "
        "AND approval_date=? AND transaction_direction='purchase' AND batch_id<>? "
        "AND parse_error='' AND conflict_reason='' AND duplicate_of IS NULL",
        (row.issuer, row.card_tail, row.approval_number, row.approval_date, batch_id)).fetchall()
    if len(candidates) != 1:
        return None
    identity, merchant, amount, foreign, currency, posting_date = candidates[0]
    same = merchant == row.merchant_normalized and amount == row.amount_krw
    if posting_date and row.posting_date:
        same = same and posting_date == row.posting_date
    if foreign and row.foreign_amount:
        try:
            same = same and to_decimal(foreign) == to_decimal(row.foreign_amount)
        except AmountUnreadable:
            same = False
    if currency and row.foreign_currency:
        same = same and currency == row.foreign_currency
    return identity, same
