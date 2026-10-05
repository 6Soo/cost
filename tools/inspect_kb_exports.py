"""국민 승인·국내 매입·해외 매입 원본을 읽기 전용으로 비교한다.

원본과 장부는 바꾸지 않는다. 결과에는 집계와 원본 행 위치만 기록한다.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import xlrd
except ImportError:
    sys.path.insert(0, str(ROOT / '.local-archive/card-downloads/parser-libs'))
    import xlrd
from app.import_card import _approval_parts
from app.normalize import normalize_merchant, to_date


def number(value):
    text = str(value).strip().replace(',', '').replace('$', '').replace('원', '')
    return Decimal(text) if text else None


def approval(value):
    text = str(value).strip().lstrip("'")
    if text.endswith('.0'):
        text = text[:-2]
    primary, _ = _approval_parts(text)
    return primary.lstrip('0') if primary else ''


def read_source(path, role):
    data = path.read_bytes()
    if not data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        raise ValueError(f'{role}: 국민 원본 XLS 형식이 아닙니다')
    book = xlrd.open_workbook(file_contents=data)
    sheet = book.sheet_by_index(0)
    header_index = next(i for i in range(min(20, sheet.nrows))
                        if '승인일' in sheet.row_values(i) and '가맹점명' in sheet.row_values(i))
    headers = [str(v).strip() for v in sheet.row_values(header_index)]
    required = {'카드번호', '승인일', '가맹점명'}
    required |= {'결제방법', '매입일', '현지이용금액', '미화환산금액',
                 '결제원금', '수수료', '총결제금액'} if role == 'overseas_acquired' else {'승인번호', '승인금액', '상태'}
    if not required <= set(headers) or len(headers) != len(set(headers)):
        raise ValueError(f'{role}: 필수 열 누락 또는 중복 열이 있습니다')
    rows = []
    for index in range(header_index + 1, sheet.nrows):
        row = dict(zip(headers, sheet.row_values(index)))
        if not to_date(row['승인일']):
            raise ValueError(f'{role}: {index + 1}행의 승인일을 읽을 수 없습니다')
        row['_row'] = index + 1
        row['_day'] = to_date(row['승인일'])
        row['_posted'] = to_date(row.get('매입일'))
        row['_card'] = str(row['카드번호']).strip()
        row['_merchant'] = normalize_merchant(str(row['가맹점명']))
        row['_cancel'] = '취소' in str(row.get('상태', row.get('결제방법', '')))
        row['_approval'] = approval(row.get('승인번호', ''))
        row['_foreign'] = role == 'overseas_acquired' or '$' in str(row.get('승인금액', ''))
        rows.append(row)
    statuses = Counter(str(r.get('상태', r.get('결제방법', ''))) for r in rows)
    result = dict(path=str(path.resolve()), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                  header_row=header_index + 1, headers=headers, rows=len(rows),
                  statuses=dict(statuses), purchase_rows=sum(not r['_cancel'] for r in rows),
                  cancellation_rows=sum(r['_cancel'] for r in rows),
                  approval_number_present=sum(bool(r['_approval']) for r in rows),
                  approval_date_min=min((r['_day'] for r in rows), default=None),
                  approval_date_max=max((r['_day'] for r in rows), default=None),
                  posting_date_min=min((r['_posted'] for r in rows if r['_posted']), default=None),
                  posting_date_max=max((r['_posted'] for r in rows if r['_posted']), default=None))
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(str(row.get(h, '')) for h in headers)].append(row['_row'])
    result['identical_row_groups'] = [positions for positions in groups.values() if len(positions) > 1]
    result['identical_rows_are_not_deleted'] = True
    if role == 'overseas_acquired':
        result['currencies'] = dict(Counter(str(r['통화코드']) for r in rows))
        result['special_transaction_types'] = {
            status: count for status, count in statuses.items()
            if status not in ('일시불매출', '취소매출')}
        result['special_types_require_review'] = True
        result['positive_raw_cancel_amount_rows'] = sum(r['_cancel'] and number(r['총결제금액']) > 0 for r in rows)
        result['arithmetic_mismatch_rows'] = [r['_row'] for r in rows
            if number(r['결제원금']) + number(r['수수료']) != number(r['총결제금액'])]
        result['totals_krw'] = {label: {field: str(sum((abs(number(r[field])) for r in rows
            if r['_cancel'] == cancel), Decimal(0))) for field in ('결제원금', '수수료', '총결제금액')}
            for label, cancel in (('purchase', False), ('cancellation', True))}
    else:
        result['totals_by_region'] = {region: {label: str(sum((abs(number(r['승인금액'])) for r in rows
            if r['_foreign'] == foreign and r['_cancel'] == cancel), Decimal(0)))
            for label, cancel in (('purchase', False), ('cancellation', True))}
            for region, foreign in (('domestic_krw', False), ('overseas_usd', True))}
    return rows, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--domestic', type=Path, required=True)
    parser.add_argument('--overseas', type=Path, required=True)
    parser.add_argument('--from', dest='start', required=True)
    parser.add_argument('--to', dest='end', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not to_date(args.start) or not to_date(args.end) or args.start > args.end:
        parser.error('조회 기간을 확인하세요')
    approval_rows, approval_report = read_source(args.approval, 'approval')
    domestic_rows, domestic_report = read_source(args.domestic, 'domestic_acquired')
    overseas_rows, overseas_report = read_source(args.overseas, 'overseas_acquired')

    domestic_index = defaultdict(list)
    foreign_index = defaultdict(list)
    for row in approval_rows:
        if row['_approval'] and not row['_foreign']:
            domestic_index[(row['_card'], row['_approval'], row['_day'], row['_cancel'])].append(row)
        if row['_foreign']:
            foreign_index[(row['_card'], row['_day'], row['_merchant'], row['_cancel'],
                           abs(number(row['승인금액'])))].append(row)
    domestic_comparison = Counter()
    missing_domestic_cancel_rows = []
    original_index = defaultdict(list)
    cancel_original_index = defaultdict(list)
    for row in approval_rows:
        if not row['_foreign'] and row['_approval']:
            index = cancel_original_index if row['_cancel'] else original_index
            index[(row['_card'], row['_approval'])].append(row)
    original_comparison = Counter()
    for row in domestic_rows:
        candidates = domestic_index[(row['_card'], row['_approval'], row['_day'], row['_cancel'])] if row['_approval'] else []
        exact = [r for r in candidates if abs(number(r['승인금액'])) == abs(number(row['승인금액']))]
        key = 'cancellation' if row['_cancel'] else 'purchase'
        domestic_comparison[f'{key}_exact_one'] += len(exact) == 1
        domestic_comparison[f'{key}_ambiguous'] += len(exact) > 1
        domestic_comparison[f'{key}_no_exact'] += not exact
        if row['_cancel'] and not exact:
            missing_domestic_cancel_rows.append(row['_row'])
        if row['_cancel']:
            original = approval(_approval_parts(str(row['승인번호']))[1])
            original_key = (row['_card'], original)
            original_comparison['original_approval_number_present'] += bool(original)
            original_comparison['original_purchase_candidate_present'] += bool(original and original_index[original_key])
            original_comparison['approval_cancel_same_original_number'] += bool(original and cancel_original_index[original_key])
            original_comparison['approval_cancel_same_original_and_amount'] += bool(original and any(
                abs(number(r['승인금액'])) == abs(number(row['승인금액']))
                for r in cancel_original_index[original_key]))
    foreign_comparison = Counter()
    for row in overseas_rows:
        candidates = foreign_index[(row['_card'], row['_day'], row['_merchant'], row['_cancel'],
                                    abs(number(row['미화환산금액'])))]
        key = 'cancellation' if row['_cancel'] else 'purchase'
        foreign_comparison[f'{key}_exact_candidate_one'] += len(candidates) == 1
        foreign_comparison[f'{key}_ambiguous'] += len(candidates) > 1
        foreign_comparison[f'{key}_no_exact'] += not candidates
    result = dict(query_period=dict(start=args.start, end=args.end),
                  sources=dict(approval=approval_report, domestic_acquired=domestic_report,
                               overseas_acquired=overseas_report),
                  comparison=dict(domestic=dict(domestic_comparison),
                      domestic_cancel_no_exact_approval_rows=missing_domestic_cancel_rows,
                      domestic_cancel_original_reference=dict(original_comparison),
                      overseas=dict(foreign_comparison),
                      overseas_match_is_candidate_only=True,
                      domestic_rows_with_approval_outside_query=sum(not args.start <= r['_day'] <= args.end for r in domestic_rows),
                      overseas_rows_with_approval_outside_query=sum(not args.start <= r['_day'] <= args.end for r in overseas_rows)),
                  original_files_changed=False, operational_database_changed=False,
                  ledger_posted=False)
    output = args.output.resolve()
    if output in {args.approval.resolve(), args.domestic.resolve(), args.overseas.resolve()}:
        raise ValueError('원본을 결과 파일로 덮어쓸 수 없습니다')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
