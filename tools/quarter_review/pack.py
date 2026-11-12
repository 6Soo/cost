"""Read-only, repeatable quarter review export. No server or Google writes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import date, datetime
import io
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.quarter_costs import quarter_of
from webapp.board_read_projection import shown_amount, trip_profit
from webapp.sheets_export import guard_text

MANUAL = {'user_decision', 'user_exception', 'previous_decision', 'manual',
          'manual_hold', 'owner_booking'}
RECENT_KINDS = {'card.classification_corrected', 'card.dist141_provenance_corrected',
                'card.closed_period_grouped'}
TRANSACTION_FIELDS = ('transaction_id source_hash amount_krw trip_id display_tab_id approval_date posting_date '
                      'transaction_direction transaction_kind merchant item classification_state '
                      'classification_source classification_basis decided_at duplicate_of conflict_reason parse_error').split()


def read_database(path, recent_since='2026-11-11'):
    """A single SQLite snapshot; no schema initializers or writable Store constructors."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro',
                                uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'transactions', 'trip_tabs', 'board_rows', 'change_log'}
        if not required <= names:
            raise ValueError('REQUIRED_TABLE_MISSING')
        data = {}
        for table in required:
            columns = '*'
            if table == 'transactions':
                available = {r[1] for r in conn.execute('PRAGMA table_info(transactions)')}
                columns = ','.join(k for k in TRANSACTION_FIELDS if k in available)
            query = 'SELECT ' + columns + ' FROM ' + table
            params = ()
            if table == 'change_log':
                query += ' WHERE at>=? AND kind IN (' + ','.join('?' for _ in RECENT_KINDS) + ')'
                params = (recent_since, *sorted(RECENT_KINDS))
            data[table] = [dict(r) for r in conn.execute(query, params)]
        data['manual_ids'] = set()
        data['manual_fields'] = defaultdict(set)
        data['company_exclusions'] = set()
        if 'transaction_company_exclusions' in names:
            data['company_exclusions'] = {(r['transaction_id'], r['source_hash']) for r in conn.execute(
                'SELECT transaction_id,source_hash FROM transaction_company_exclusions WHERE excluded=1')}
        if 'board_manual_overrides' in names:
            for r in conn.execute('SELECT row_id,field FROM board_manual_overrides'):
                data['manual_ids'].add(r['row_id'])
                data['manual_fields'][r['row_id']].add(r['field'])
        if 'review_decisions' in names:
            from app.decision_provenance import active_decision_sql
            for r in conn.execute('SELECT transaction_id,item,display_tab_id FROM review_decisions d WHERE '
                                  + active_decision_sql(conn=conn)):
                if r['item'] or r['display_tab_id'] not in ('', None, 'unclassified'):
                    data['manual_ids'].add('card-' + r['transaction_id'])
        # Reuse the screen's read projection for non-card rows, including bank corrections.
        from webapp.ledger_store import LedgerStore
        reader = object.__new__(LedgerStore)
        reader.conn = conn
        data['board_projected'] = []
        for record in data['board_rows']:
            row = json.loads(record['payload_json'])
            row.update(row_id=record['row_id'], row_kind=record['row_kind'],
                       display_tab_id=record['display_tab_id'])
            data['board_projected'].append(reader.projected(row))
        data['read_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
        conn.rollback()
    return data


def load_income(host, trips):
    """Use the same verified Google snapshot, copy choice and row totals as the UI."""
    from app import google_authority
    from app.participant_income import income_rows_from_trip
    from webapp import google_ledger_page as google
    path = Path(host) / 'data/google-authority/snapshot.json'
    result, reasons = {}, {}
    try:
        snapshot, rows = google_authority.load_consistent(path, path.with_name('rows.json'))
        mapping = google.load_mapping(path)
        payload = google.owner_payload(google.snapshot_for_display(snapshot), google.load_choices(path))
    except (OSError, ValueError, KeyError, google_authority.SnapshotError):
        return {}, {t['tab_id']: 'Google 수입 자료를 읽을 수 없음' for t in trips}, ''
    for tab in trips:
        keys = [key for key, value in mapping.items() if value == tab['tab_id']]
        matches = [t for t in payload['trips'] if t['key'] in keys]
        reason = 'Google 여행 연결이 하나로 확인되지 않음'
        if len(keys) == len(matches) == 1:
            trip = matches[0]
            source = trip.get('chosen_source')
            detail = google.owner_rows(rows, trip['key'], source) if source in google_authority.SPREADSHEET_IDS else None
            block = ((trip.get('copies') or {}).get(source) or {}).get('income') or {}
            current = (payload['sources'].get(source) or {})
            blockers = set(trip.get('review') or [])
            if 'LAYOUT_NOT_STANDARD' in blockers:
                reason = 'Google 탭은 있으나 비표준 양식이라 수입 표와 합계를 검증하지 못함(동기화 정상)'
                if current.get('status') != 'ok' or current.get('stale'):
                    reason = 'Google 탭의 비표준 양식과 동기화 상태를 확인해야 함'
            elif current.get('status') != 'ok' or current.get('stale'):
                reason = 'Google 수입 동기화가 최신 정상 상태가 아님'
            elif detail is None:
                reason = 'Google 탭의 수입 행을 읽을 수 없음'
            elif not block.get('verified'):
                reason = 'Google 수입 표의 양식·합계 검증이 완료되지 않음'
            elif blockers & google.OWNER_CHOICE_BLOCKERS or trip.get('blocked_by'):
                reason = 'Google 수입 사본의 선택·검증 문제로 합계를 확정할 수 없음'
            else:
                reason = 'Google 수입 행 합계와 검증 합계가 일치하지 않음'
            if (detail is not None and block.get('verified') and current.get('status') == 'ok'
                    and not current.get('stale') and not (set(trip.get('review') or []) & google.OWNER_CHOICE_BLOCKERS)
                    and not trip.get('blocked_by')):
                income = income_rows_from_trip(index=None, amount_rows=detail['income'],
                                              source=source, sheet=trip['key'])
                try:
                    total = sum(int(r['amount']) for r in income)
                    expected = trip.get('income_total')
                    if expected is None:
                        expected = block.get('total')
                    if expected is not None and total == int(expected):
                        result[tab['tab_id']] = total
                        continue
                except (TypeError, ValueError):
                    pass
        reasons[tab['tab_id']] = reason
    return result, reasons, snapshot.get('synced_at', '')


def trip_in_quarter(trip, year, quarter):
    if trip.get('deleted') or trip.get('tab_kind', 'trip') != 'trip':
        return False
    try:
        return quarter_of(date.fromisoformat(trip['starts_on'])) == (year, quarter)
    except (KeyError, TypeError, ValueError):
        return False


def source_label(row):
    from app.classification_provenance import label
    source = row.get('classification_source')
    if row.get('manual') or source in MANUAL:
        return '수동'
    if source == 'ai_inference':
        return 'AI 판정'
    if source in {'inference', 'auto_inferred', 'code_inference', 'guide_airfare_evidence'}:
        return '자동'
    return label(row)


def prepare_rows(data, year, quarter, recent_since='2026-11-11'):
    trips = [t for t in data['trip_tabs'] if trip_in_quarter(t, year, quarter)]
    trips.sort(key=lambda t: (t['starts_on'], t['tab_id']))
    target = {t['tab_id']: t for t in trips}
    all_trip_ids = {t['tab_id'] for t in data['trip_tabs']}
    quarter_id = f'quarter:{year}:{quarter}'
    recent = set()
    for event in data['change_log']:
        if event['at'] >= recent_since and event['kind'] in RECENT_KINDS:
            detail = json.loads(event['detail_json'])
            after = detail.get('after') or {}
            if after.get('classification_source') not in MANUAL:
                recent.add('card-' + event['subject'])
    board = {r['row_id']: r for r in data['board_projected']}
    rows, excluded = [], Counter()
    transactions = {r['transaction_id']: r for r in data['transactions']}
    candidates = []
    for raw in transactions.values():
        row_id = 'card-' + raw['transaction_id']
        row = dict(board.get(row_id, {}))
        # Card source amounts/signs remain authoritative; do not add ledger copies.
        row.update(raw, row_id=row_id, row_kind='expense', occurred_on=raw.get('approval_date') or raw.get('posting_date') or '')
        for field in data.get('manual_fields', {}).get(row_id, ()):
            if field in {'item', 'display_tab_id', 'trip_id', 'service_period'} and field in board.get(row_id, {}):
                row[field] = board[row_id][field]
                if field == 'display_tab_id':
                    row['trip_id'] = row[field]
        row.pop('display_amount_krw', None)
        candidates.append(row)
    candidates.extend(dict(r) for r in board.values() if r['row_kind'] == 'expense'
                      and not r['row_id'].startswith('card-'))
    for row in candidates:
        identity = row.get('display_tab_id')
        if identity in (None, '', 'unclassified', 'refunds'):
            identity = row.get('trip_id')
        # Only stored quarter destinations count; an unassigned normal row is a metric,
        # never silently reclassified into a new expense destination.
        if identity not in target and identity != quarter_id:
            if identity in all_trip_ids:
                excluded['other_trip'] += 1
            continue
        if row.get('duplicate_of') or row.get('conflict_reason') or row.get('parse_error') or type(row.get('amount_krw')) is not int:
            excluded['protected'] += 1
            if row.get('duplicate_of'):
                excluded['duplicate'] += 1
            elif row.get('conflict_reason'):
                excluded['conflict'] += 1
            else:
                excluded['invalid'] += 1
            continue
        if (row.get('transaction_id'), row.get('source_hash')) in data.get('company_exclusions', set()):
            excluded['company_excluded'] += 1
            continue
        row['display_tab_id'] = identity
        row['trip'] = target[identity]['display_key'] if identity in target else f'{year}년 {quarter}분기 기타비용'
        row['amount_krw'] = shown_amount(row)
        row['manual'] = row['row_id'] in data.get('manual_ids', set()) or row.get('decided_at') is not None or row.get('classification_source') in MANUAL
        row['recent_auto_change'] = row['row_id'] in recent and not row['manual']
        row['source_label'] = source_label(row)
        saved = board.get(row['row_id'])
        row['projection_difference'] = bool(saved and any(saved.get(k) != row.get(k) for k in ('item', 'display_tab_id')))
        rows.append(row)
    return trips, rows, excluded


def write_csv(path, headers, rows):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([guard_text(v) if isinstance(v, str) else v for v in row])


def undecided_normal_rows(data, year, quarter, rows):
    """Persisted decisions only. Date fallback scopes unassigned normal purchases."""
    included = {r['row_id'] for r in rows}
    result = []
    for row in data['transactions']:
        if (row.get('duplicate_of') or row.get('conflict_reason') or row.get('parse_error')
                or type(row.get('amount_krw')) is not int or row.get('transaction_direction') != 'purchase'):
            continue
        if (row.get('transaction_id'), row.get('source_hash')) in data.get('company_exclusions', set()):
            continue
        identity = row.get('display_tab_id') or row.get('trip_id')
        in_scope = 'card-' + row['transaction_id'] in included
        if identity in (None, '', 'unclassified'):
            try:
                in_scope = quarter_of(date.fromisoformat(row.get('approval_date') or row.get('posting_date') or '')) == (year, quarter)
            except ValueError:
                continue
        if in_scope and (not row.get('classification_source') or row.get('classification_state') != 'classified'
                         or not row.get('item') or identity in (None, '', 'unclassified')):
            result.append(row)
    return result


def undecided_normal(data, year, quarter, rows):
    return len(undecided_normal_rows(data, year, quarter, rows))


def diagnostics(data, rows, excluded, year, quarter):
    """Counts and nature only; never emit identifiers, merchants or amounts."""
    from app.classification_provenance import origin
    board = {r['row_id']: r for r in data['board_projected']}
    differences = Counter()
    for row in rows:
        if not row['projection_difference']:
            continue
        saved = board[row['row_id']]
        if saved.get('display_tab_id') == 'refunds':
            reason = ('환불 건(화면은 취소·환불 묶음)' if row.get('classification_source') == 'refund_original'
                      else '원래 결제 건(화면은 취소·환불 묶음)')
        else:
            reason = '항목·여행 배정 표시 차이'
        differences[reason] += 1
    unknown = Counter()
    for row in rows:
        if not row.get('manual') and origin(row) == 'unknown':
            kind = ('카드' if row['row_id'].startswith('card-') else
                    '비카드 수기 지출' if row['row_id'].startswith('man-') else '비카드 지출')
            detail = '출처 기록 없음' if not row.get('classification_source') else '출처 코드 해석 불가'
            unknown[f'{kind} {detail}'] += 1
    undecided = Counter()
    for row in undecided_normal_rows(data, year, quarter, rows):
        identity = row.get('display_tab_id') or row.get('trip_id')
        reason = ('수동 출처·항목은 있으나 여행 미배정' if row.get('classification_source') in MANUAL
                  and row.get('item') and identity in (None, '', 'unclassified') else '저장 판정 일부 누락')
        undecided[reason] += 1
    return dict(projection=dict(differences), unknown_sources=dict(unknown),
                undecided=dict(undecided), excluded={key: excluded[key] for key in
                ('duplicate', 'conflict', 'invalid', 'company_excluded')})


def build_pack(data, year, quarter, out, incomes=None, income_reasons=None, google_at='', basis_note='',
               recent_since='2026-11-11'):
    from tools.quarter_review.priority import prioritize, review_reasons, WEIGHTS
    from tools.quarter_review.render import render_trip_summary_csv, render_review_list_csv
    trips, rows, excluded = prepare_rows(data, year, quarter, recent_since=recent_since)
    incomes, income_reasons = incomes or {}, income_reasons or {}
    # The offline pack cannot read the screen's in-memory reservation projection.
    # Do not turn its different warning count into a review reason.
    for row in rows:
        row['allow_service_reason'] = False
        row['service_date_unknown'] = False
    review = prioritize(rows)
    reasons = Counter(reason for r in review for reason in review_reasons(r))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['display_tab_id']].append(row)
    summaries = []
    for trip in trips:
        key = trip['tab_id']
        expense = sum(r['amount_krw'] for r in grouped[key])
        income = incomes.get(key)
        trip_review = [r for r in review if r['display_tab_id'] == key]
        trip_reasons = Counter(reason for r in trip_review for reason in r['review_reasons'])
        reason_order = ('AI 판정', '추론 귀속', '이용일 미확인', '포괄 항목', '최근 자동 변경', '불확실성 기록')
        reason_summary = ' · '.join(f'{name} {trip_reasons[name]}건' for name in reason_order if trip_reasons[name])
        summaries.append(dict(trip=trip['display_key'], starts_on=trip['starts_on'],
                              ends_on=trip.get('ends_on', ''), income=income, expense=expense,
                              profit=trip_profit(income, expense) if income is not None else None,
                              expense_count=len(grouped[key]), review_count=len(trip_review),
                              review_reason_summary=reason_summary))
    trip_review_total = sum(s['review_count'] for s in summaries)
    quarter_other_review = len(review) - trip_review_total
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'trips.csv').write_text(render_trip_summary_csv(summaries, full_review_count=len(review)),
                                   encoding='utf-8-sig', newline='')
    (out / 'review-list.csv').write_text(render_review_list_csv(review), encoding='utf-8-sig', newline='')
    other = grouped[f'quarter:{year}:{quarter}']
    other_groups = defaultdict(list)
    for row in other:
        other_groups[row.get('item') or '항목 없음'].append(row)
    write_csv(out / 'quarter-other.csv', ['항목', '건수', '합계'],
              [(item, len(values), sum(r['amount_krw'] for r in values)) for item, values in sorted(other_groups.items())])
    undecided = undecided_normal(data, year, quarter, rows)
    sources = Counter(r['source_label'] for r in rows)
    write_csv(out / 'sources.csv', ['판정주체', '건수'], [*sorted(sources.items()), ('판정 없는 정상 거래', undecided)])
    summary = dict(trips=len(trips), income_trips=len(incomes.keys() & {t['tab_id'] for t in trips}),
                   expense_rows=len(rows), review_rows=len(review), reasons=dict(reasons),
                   undecided_normal=undecided, quarter_other_rows=len(other), service_date_unknown=None)
    detail = diagnostics(data, rows, excluded, year, quarter)
    summary['diagnostics'] = detail
    def counts(values):
        return ' · '.join(f'{key} {value}건' for key, value in values.items() if value) or '없음'
    reason_summary = counts({name: reasons[name] for name in WEIGHTS})
    missing_income = [f"{t['display_key']}: {income_reasons.get(t['tab_id'], '수입 자료를 확인하지 못함')}"
                      for t in trips if t['tab_id'] not in incomes]
    exclusions = {'중복': excluded['duplicate'], '원본 충돌': excluded['conflict'],
                  '금액·파싱 오류': excluded['invalid'], '회사 비용 제외': excluded['company_excluded']}
    notes = [
        f"{year}년 {quarter}분기 검수 / 장부 조회 {data['read_at']} / Google 수입 조회 {google_at or '확인 불가'}",
        'review-pack.xlsx만 여세요. 먼저 볼 50건에서 사유를 보고 장부 화면에서 교정한 뒤 다시 생성하세요.',
        f'여행별 손익에서 수입·지출·차액과 사유별 검수 건수를 보세요. 검수 대상 {len(review)}건: {reason_summary}(사유 중복 가능). 여행별 검수 합계 {trip_review_total}건은 여행 행만 세며, 나머지 {quarter_other_review}건은 분기 기타비용 행입니다.',
        f'{quarter}분기 기타비용에서 항목별 건수·합계를, 판정 주체에서 자동·AI·수동 건수를 확인하세요.',
        '수입 미확인: ' + (' · '.join(missing_income) if missing_income else '없음') + '. 미확인 여행과 전체 합계의 수입·차액은 빈칸입니다.',
        f"카드 기록과 화면 표시가 다른 {sum(detail['projection'].values())}건: {counts(detail['projection'])}. 화면은 취소·환불을 묶어 보여주고 장부는 따로 기록해서 생기는 차이입니다. 합계는 카드에 저장된 판정으로 계산하고 직접 고친 값을 먼저 쓰며, 화면의 묶음 표시도 틀린 것이 아닙니다.",
        f"출처 미확인 {sum(detail['unknown_sources'].values())}건: {counts(detail['unknown_sources'])}. 판정 없는 정상 거래 {undecided}건: {counts(detail['undecided'])}(미배정 거래는 손익 합계 밖).",
        f"합계 제외 {sum(exclusions.values())}건: " + ' · '.join(f'{key} {value}건' for key, value in exclusions.items()) + '. 다른 분기 여행은 범위 밖입니다.',
        '이용일 경고는 장부 화면에서 확인하세요. 예약 근거를 함께 읽는 화면 기준을 이 파일에서 재현하지 않아 점수·건수에서 뺐습니다. 전체 검수 목록은 review-list.csv에 있습니다.',
        (basis_note or '이번 실행의 준비 비용 귀속 폐지 반영 여부는 운영 기록에서 확인하고 기준을 지정해 재생성하세요.') + ' 파일 생성은 장부·Google을 바꾸지 않습니다. 검수 후 기존 장부 복사 기능으로 Google에 붙여넣으세요.',
    ]
    (out / 'notes.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')
    try:
        from openpyxl import Workbook
    except ImportError:
        pass
    else:
        workbook = Workbook()
        workbook.remove(workbook.active)
        numeric_columns = {'trips': {3, 4, 5, 6, 7}, 'review-list': {0, 5},
                           'quarter-other': {1, 2}, 'sources': {1}}
        sheets = [('먼저 볼 50건', 'review-list', render_review_list_csv(review[:50])),
                  ('여행별 손익', 'trips', render_trip_summary_csv(summaries, full_review_count=len(review))),
                  (f'{quarter}분기 기타비용', 'quarter-other', None), ('판정 주체', 'sources', None)]
        for sheet_name, filename, rendered in sheets:
            sheet = workbook.create_sheet(sheet_name)
            source = rendered or (out / (filename + '.csv')).read_text(encoding='utf-8-sig')
            for index, values in enumerate(csv.reader(io.StringIO(source))):
                if index:
                    values = [int(value) if column in numeric_columns[filename] and value.lstrip('-').isdigit()
                              else value for column, value in enumerate(values)]
                sheet.append(values)
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
        workbook.save(out / 'review-pack.xlsx')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--quarter', type=int, choices=range(1, 5), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--basis-note', default='', help='이번 실행의 기준·변경 전후 안내')
    parser.add_argument('--recent-since', default='2026-11-11', help='최근 자동 변경으로 볼 감사 이력 기준일')
    args = parser.parse_args()
    # Customer artifacts may never be exported inside a Git working tree.
    if args.out.resolve().is_relative_to(ROOT):
        parser.error('출력은 저장소 밖의 비공개 폴더를 지정하세요.')
    data = read_database(args.host_root / 'data/board.sqlite', recent_since=args.recent_since)
    trips = [t for t in data['trip_tabs'] if trip_in_quarter(t, args.year, args.quarter)]
    income, reasons, at = load_income(args.host_root, trips)
    print(json.dumps(build_pack(data, args.year, args.quarter, args.out, income, reasons, at,
                               args.basis_note, recent_since=args.recent_since), ensure_ascii=False))


if __name__ == '__main__':
    main()
