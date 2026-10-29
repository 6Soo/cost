"""Whole-file validation before the web upload performs any writes."""
import io
from pathlib import PurePath
import re

from .db import StoreError
from .import_card import parse_card_file, read_cells

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 50000


def masked_text(value):
    text = str(value or '')
    text = re.sub(r'(?<!\d)(?:\d[ -]?){12,19}(?!\d)', '[카드번호 숨김]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[이메일 숨김]', text)
    return text[:240]


def validate_upload(content, filename):
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise StoreError('INVALID_UPLOAD_SIZE', '파일 크기를 확인해 주세요 (최대 20MB)')
    suffix = PurePath(str(filename).replace('\\', '/')).suffix.lower()
    if suffix not in {'.xls', '.xlsx', '.csv'}:
        raise StoreError('INVALID_UPLOAD_TYPE', 'XLS·XLSX·CSV 파일을 선택해 주세요')
    from .import_card import ParseError
    try:
        parsed = parse_card_file(content, filename)
        fmt, cells = read_cells(content)
    except ParseError as exc:
        raise StoreError(exc.code, exc.message) from None
    if len(parsed.rows) > MAX_ROWS:
        raise StoreError('UPLOAD_ROW_LIMIT', '거래 50,000행 이하로 나누어 올려 주세요')
    for row in parsed.rows:
        if not row.issuer or not row.card_tail:
            raise StoreError('CARD_ACCOUNT_REQUIRED', '카드사와 마스킹 카드 식별이 필요합니다')
    # Formula-like strings are never evaluated. Negative amounts are valid data.
    for values in cells:
        for value in values:
            if isinstance(value, str) and (re.match(r'^\s*[=+@]', value)
                    or re.match(r'^\s*-(?![\d,.]+\s*$)', value)):
                raise StoreError('UNSAFE_FORMULA', '수식이 포함된 파일은 올릴 수 없습니다')
    if fmt == 'xlsx':
        from openpyxl import load_workbook
        wb = None
        try:
            wb = load_workbook(io.BytesIO(content), data_only=False, read_only=True)
            for r in wb[wb.sheetnames[0]].iter_rows(values_only=True):
                for val in r:
                    if isinstance(val, str) and (re.match(r'^\s*[=+@]', val)
                            or re.match(r'^\s*-(?![\d,.]+\s*$)', val)):
                        raise StoreError('UNSAFE_FORMULA', '수식이 포함된 파일은 올릴 수 없습니다')
        except StoreError:
            raise
        except Exception:
            raise StoreError('INVALID_UPLOAD_CONTENT', '파일 내용을 검증하지 못했습니다') from None
        finally:
            if wb is not None:
                wb.close()
    return parsed, {'format': fmt, 'file_rows': len(cells),
                    'transaction_rows': len(parsed.rows),
                    'non_transaction_rows': len(cells) - len({r.row_index for r in parsed.rows})}
