"""Verified Hana usage and IBK print layouts; source cells stay untouched."""
import re

from .normalize import (AmountUnreadable, is_cancel_text, normalize_approval_number,
                        to_amount_krw, to_date, to_decimal)


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


def _source_document(conn, batch_id, cache):
    """Read verified original layout metadata once per operation."""
    import hashlib
    from .import_card import ParseError, parse_card_file
    if batch_id not in cache:
        cache[batch_id] = None
        source = conn.execute(
            'SELECT parser,filename,content_bytes,content_sha256 FROM import_batches WHERE batch_id=?',
            (batch_id,)).fetchone()
        if source and source[2] and hashlib.sha256(source[2]).hexdigest() == source[3]:
            try:
                parsed = parse_card_file(source[2], source[1])
                if parsed.parser == source[0]:
                    cache[batch_id] = parsed
            except (ParseError, ValueError, TypeError):
                pass  # Unavailable or changed provenance cannot discharge a conflict.
    return cache[batch_id]


def _posting_was_defaulted(conn, batch_id, cache):
    """Prove the legacy source omitted posting dates; never infer from equality."""
    from .import_card import _build_header_map
    parsed = _source_document(conn, batch_id, cache)
    return bool(parsed and parsed.parser.endswith(':headered')
                and 'posting_date' not in _build_header_map(parsed.headers))


def _merchant_number(conn, batch_id, row_index, expected_hash, cache):
    """Only the explicit merchant-number column in an intact source is evidence."""
    from .review import source_hash_of
    parsed = _source_document(conn, batch_id, cache)
    if not parsed or parsed.parser.split(':',1)[-1] not in ('headered','hana_usage'):
        return ''
    headers = [_text(header) for header in parsed.headers]
    if headers.count('가맹점번호') != 1:
        return ''
    source = next((r for r in parsed.rows if r.row_index == row_index), None)
    index = headers.index('가맹점번호')
    if not source or source_hash_of(source) != expected_hash or index >= len(source.source_row):
        return ''
    value = str(source.source_row[index] or '').strip()
    return value if re.fullmatch(r'[A-Za-z0-9]{3,}', value) and set(value) != {'0'} else ''


def existing_purchase(store, batch_id, parser, row, *, source_cache=None):
    """Reuse a verified purchase across views, or preserve a source conflict.

    Missing posting/currency details in a compact view cannot erase the fuller
    source. Refunds and repeated rows within the same file retain multiplicity.
    """
    layout = parser.split(':', 1)[-1]
    if layout not in ('hana_usage', 'hana_foreign', 'ibk_print'):
        # Hana approval-source downloads arrive as a generic headered sheet and
        # describe the same purchases as the acquired views, so they join the
        # cross-view matching too. Other issuers' headered sheets are untouched.
        if not (layout == 'headered' and row.issuer == '하나'):
            return None
    # Leading-zero padding differs between views (`00001111` vs `1111`); compare
    # the normalized key, never rewriting the stored approval number. An all-zero
    # number is meaningless and cannot establish a match.
    approval_key = normalize_approval_number(row.approval_number)
    if (row.transaction_direction != 'purchase' or row.parse_error
            or not approval_key or not row.card_tail or not row.approval_date):
        return None
    candidates = store.conn.execute(
        "SELECT t.transaction_id,t.merchant_normalized,t.amount_krw,t.foreign_amount,t.foreign_currency,"
        "t.posting_date,t.batch_id,t.row_index,t.source_hash,b.parser "
        "FROM transactions t JOIN import_batches b ON b.batch_id=t.batch_id "
        "WHERE t.issuer=? AND t.card_tail=? AND LTRIM(t.approval_number,'0')=? "
        "AND t.approval_date=? AND t.transaction_direction='purchase' AND t.batch_id<>? "
        "AND t.parse_error='' AND t.conflict_reason='' AND t.duplicate_of IS NULL",
        (row.issuer, row.card_tail, approval_key, row.approval_date, batch_id)).fetchall()
    if len(candidates) != 1:
        return None
    (identity, merchant, amount, foreign, currency, posting_date, original_batch, original_index,
     original_hash, original_parser) = candidates[0]
    # An approval number can be reused by different purchases on one card/day. A
    # normal FX/fee ratio corroborates one purchase; a wide multiple alone means a
    # different transaction. But an overseas gas pre-auth hold is a small approval
    # next to the final billed total, so a compatible merchant keeps it one purchase
    # even at a wide ratio — the same criteria as the cleanup tool (SRC-009).
    if amount and row.amount_krw and amount > 0 and row.amount_krw > 0:
        from .card_hana_duplicate_repair import RATIO_MIN, RATIO_MAX, _merchant_compatible
        ratio_ok = RATIO_MIN <= amount / row.amount_krw <= RATIO_MAX
        overseas = layout == 'hana_foreign' or str(original_parser or '').split(':', 1)[-1] == 'hana_foreign'
        if not ratio_ok and not (overseas and _merchant_compatible(merchant, row.merchant_normalized)):
            return None
    cache = source_cache if source_cache is not None else {}
    same_merchant = merchant == row.merchant_normalized
    if not same_merchant and merchant and row.merchant_normalized and (
            merchant in row.merchant_normalized or row.merchant_normalized in merchant):
        from .review import source_hash_of
        number = _merchant_number(store.conn, original_batch, original_index, original_hash, cache)
        same_merchant = bool(number and number == _merchant_number(
            store.conn, batch_id, row.row_index, source_hash_of(row), cache))
    same = same_merchant and amount == row.amount_krw
    if posting_date and row.posting_date:
        same_date = posting_date == row.posting_date
        if not same_date and posting_date == row.approval_date:
            same_date = _posting_was_defaulted(store.conn, original_batch, cache)
        same = same and same_date
    if foreign and row.foreign_amount:
        try:
            same = same and to_decimal(foreign) == to_decimal(row.foreign_amount)
        except AmountUnreadable:
            same = False
    if currency and row.foreign_currency:
        same = same and currency == row.foreign_currency
    return identity, same


def acquired_supersedes_approval(store, parser, row, identity):
    """The overseas acquired (billed) view is the financial canonical (SRC-005/009).

    When the overseas billed view (`hana_foreign`, 청구금액) arrives after its
    approval-source download was already stored, the acquired row must stay
    canonical regardless of import order. The caller inserts the acquired row and
    marks the approval-source row as its duplicate — never the reverse, which would
    leave the approval-time amount as the cost and push the billed total into a
    conflict. Domestic `hana_usage` keeps its merchant-number conflict protection.
    """
    if row.issuer != '하나' or parser.split(':', 1)[-1] != 'hana_foreign':
        return False
    existing = store.conn.execute(
        "SELECT b.parser FROM transactions t JOIN import_batches b ON b.batch_id=t.batch_id"
        " WHERE t.transaction_id=? AND t.conflict_reason='' AND t.duplicate_of IS NULL",
        (identity,)).fetchone()
    return bool(existing and existing[0].split(':', 1)[-1] == 'headered')


def approval_superseded_by_acquired(store, parser, row, identity):
    """Billed-first mirror of `acquired_supersedes_approval` (SRC-005/009).

    When the overseas billed view (`hana_foreign`) was stored first and its
    approval-source download (`headered`) arrives afterwards, the incoming approval
    row is the redundant view: the caller marks it a duplicate of the billed
    canonical instead of leaving a source conflict, so both import orders agree.
    The approval row is new and unbooked, so no ledger amount changes. Domestic
    `hana_usage` keeps its merchant-number conflict protection in both orders.
    """
    if row.issuer != '하나' or parser.split(':', 1)[-1] != 'headered':
        return False
    existing = store.conn.execute(
        "SELECT b.parser FROM transactions t JOIN import_batches b ON b.batch_id=t.batch_id"
        " WHERE t.transaction_id=? AND t.conflict_reason='' AND t.duplicate_of IS NULL",
        (identity,)).fetchone()
    return bool(existing and existing[0].split(':', 1)[-1] == 'hana_foreign')


def redundant_purchase_conflicts(conn):
    """Read-only duplicate projection for conflicts created by older importers.

    Keep every source and conflict flag. Only an unchanged export source with
    one clean canonical purchase can be omitted from the duplicate work queue.
    Explicit date/amount/merchant differences and manual actions stay protected.
    """
    from types import SimpleNamespace
    from .import_card import ParsedRow
    from .review import source_hash_of
    has_board = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_rows'").fetchone()
    board_guard = (" AND NOT EXISTS(SELECT 1 FROM board_rows r WHERE r.row_id='card-'||t.transaction_id)"
                   if has_board else '')
    cursor = conn.execute(
        "SELECT t.*,b.parser AS import_parser FROM transactions t"
        " JOIN import_batches b ON b.batch_id=t.batch_id"
        " WHERE t.transaction_id LIKE '%:conflict:%'"
        " AND t.conflict_reason='같은 거래 ID인데 원문 금액·가맹점이 달라요'"
        " AND t.transaction_direction='purchase' AND t.amount_krw>0"
        " AND COALESCE(t.parse_error,'')='' AND COALESCE(t.duplicate_of,'')=''"
        " AND COALESCE(t.classification_source,'') NOT IN ('user_decision','user_exception','manual')"
        " AND NOT EXISTS(SELECT 1 FROM review_decisions d WHERE d.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id)"
        " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id)"
        + board_guard)
    columns = [field[0] for field in cursor.description]
    records = [dict(zip(columns, record)) for record in cursor.fetchall()]
    result, cache = [], {}
    for record in records:
        fields = {key:record[key] for key in ParsedRow.__dataclass_fields__
                  if key in record and key not in ('raw','source_row')}
        row = ParsedRow(**fields, raw={}, source_row=[])
        if source_hash_of(row) != record['source_hash']:
            continue
        match = existing_purchase(SimpleNamespace(conn=conn), record['batch_id'],
                                  record['import_parser'], row, source_cache=cache)
        if match == (record['transaction_id'].split(':conflict:')[0], True):
            result.append(record['transaction_id'])
    return result
