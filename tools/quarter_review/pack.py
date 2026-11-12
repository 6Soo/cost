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


def read_database(path):
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
                params = ('2026-11-11', *sorted(RECENT_KINDS))
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
            reason = 'Google 수입의 최신 동기화·양식·합계를 확인할 수 없음'
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


def prepare_rows(data, year, quarter):
    trips = [t for t in data['trip_tabs'] if trip_in_quarter(t, year, quarter)]
    trips.sort(key=lambda t: (t['starts_on'], t['tab_id']))
    target = {t['tab_id']: t for t in trips}
    all_trip_ids = {t['tab_id'] for t in data['trip_tabs']}
    quarter_id = f'quarter:{year}:{quarter}'
    recent = set()
    for event in data['change_log']:
        if event['at'] >= '2026-11-11' and event['kind'] in RECENT_KINDS:
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


def undecided_normal(data, year, quarter, rows):
    """Persisted decisions only. Date fallback scopes unassigned normal purchases."""
    included = {r['row_id'] for r in rows}
    count = 0
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
            count += 1
    return count


def build_pack(data, year, quarter, out, incomes=None, income_reasons=None, google_at='', basis_note=''):
    from tools.quarter_review.priority import prioritize, review_reasons
    from tools.quarter_review.render import render_trip_summary_csv, render_review_list_csv
    trips, rows, excluded = prepare_rows(data, year, quarter)
    incomes, income_reasons = incomes or {}, income_reasons or {}
    # The actual screen warning function, with volatile OTA state explicitly unavailable.
    from tools.p2_batch.scope import service_warnings
    warnings_data = dict(data)
    warnings_data['trip_tabs'] = [t for t in data['trip_tabs'] if not t.get('deleted')]
    cards = [r for r in rows if r['row_id'].startswith('card-')]
    warning_summary, unknown = service_warnings(warnings_data, cards)
    unknown = set(unknown)
    for row in rows:
        row['service_date_unknown'] = row.get('transaction_id') in unknown
    review = prioritize([r for r in rows if not r['manual']])
    review_counts = Counter(r['display_tab_id'] for r in review)
    reasons = Counter(reason for r in review for reason in review_reasons(r))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['display_tab_id']].append(row)
    summaries = []
    for trip in trips:
        key = trip['tab_id']
        expense = sum(r['amount_krw'] for r in grouped[key])
        income = incomes.get(key)
        summaries.append(dict(trip=trip['display_key'], starts_on=trip['starts_on'],
                              ends_on=trip.get('ends_on', ''), income=income, expense=expense,
                              profit=trip_profit(income, expense) if income is not None else None,
                              expense_count=len(grouped[key]), review_count=review_counts[key]))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'trips.csv').write_text(render_trip_summary_csv(summaries), encoding='utf-8-sig', newline='')
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
                   undecided_normal=undecided, quarter_other_rows=len(other),
                   service_date_unknown=warning_summary['count'])
    notes = [f'# {year}년 {quarter}분기 검수 자료', '',
             f"기준: 장부 조회 {data['read_at']} / Google 수입 동기화 {google_at or '읽지 못함'}.",
             basis_note or '조회 후 판정이 바뀌면 같은 명령으로 자료를 다시 만드세요.', '',
             '1. trips.csv에서 여행별 수입·지출·차액을 봅니다. 수입이 빈칸이면 차액도 빈칸입니다.',
             '2. review-list.csv를 위에서부터 봅니다. 최근 자동 변경, AI 판정 등 여러 사유가 겹칠수록 앞에 나옵니다. 금액도 순위에 반영됩니다.',
             '3. quarter-other.csv에서 여행에 속하지 않은 비용을 항목별로 봅니다.',
             '4. sources.csv에서 누가 판정했는지와 판정 없는 정상 거래 수를 봅니다.',
             '5. 잘못된 판정은 기존 장부 화면에서 교정하고 자료를 다시 만듭니다. 검수 후 기존 Google 지출표 복사 기능으로 붙여넣습니다.', '',
             '이 자료는 검수용 요약이며 Google 지출표의 양식을 바꾸지 않습니다. 파일 생성은 장부와 Google에 쓰지 않습니다.',
             '지출은 저장된 귀속 기준입니다. 선결제와 음수 환불을 함께 합산하며 카드 한 건을 한 번만 셉니다. 지출 건수에는 환불 행도 포함됩니다.',
             f"저장된 카드 판정과 화면 표시행의 항목·귀속 차이가 있는 행은 {sum(r['projection_difference'] for r in rows)}건입니다. 이 자료는 카드의 현재 저장 판정을 사용하며 수동으로 고친 표시값은 우선합니다.",
             '6월 30일 출발 여행은 3분기에 포함합니다. 다른 분기 여행은 결제일이 이번 분기여도 포함하지 않습니다.',
             '수동 교정은 지출 합계·판정 주체 건수에 포함하고 우선 검수 목록에서는 제외합니다. 보호된 수동 판정과 닫힌 분기 의심 건의 별도 검수는 기존 기록을 참고하세요.',
             f"이용일 미확인 {warning_summary['count']}건은 저장된 화면 행 기준입니다. 서버 메모리의 최신 예약 근거를 읽지 않아 실시간 화면과 다를 수 있습니다.",
             f"원본 충돌·중복·금액 오류로 합계에서 제외한 행은 {excluded['protected']}건입니다. 검수 목록 길이는 오류 건수가 아닙니다.",
             f"사용자가 회사 비용에서 제외한 거래 {excluded['company_excluded']}건도 합계에 넣지 않습니다.",
             '판정 없는 정상 거래 수에는 여행·분기 귀속이 없는 이번 분기 정상 구매도 포함합니다.', '',
             '## 수입 빈칸 사유']
    notes.extend(f"- {t['display_key']}: {income_reasons.get(t['tab_id'], '검증된 수입 자료 없음')}" for t in trips if t['tab_id'] not in incomes)
    notes.extend(['', '교정 내용과 걸린 시간을 기록해 다음 검수 때 비교합니다. 같은 원인의 교정은 규칙집에 반영합니다.'])
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
        for filename in ('trips', 'review-list', 'quarter-other', 'sources'):
            sheet = workbook.create_sheet(filename)
            for index, values in enumerate(csv.reader(io.StringIO((out / (filename + '.csv')).read_text(encoding='utf-8-sig')))):
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
    args = parser.parse_args()
    # Customer artifacts may never be exported inside a Git working tree.
    if args.out.resolve().is_relative_to(ROOT):
        parser.error('출력은 저장소 밖의 비공개 폴더를 지정하세요.')
    data = read_database(args.host_root / 'data/board.sqlite')
    trips = [t for t in data['trip_tabs'] if trip_in_quarter(t, args.year, args.quarter)]
    income, reasons, at = load_income(args.host_root, trips)
    print(json.dumps(build_pack(data, args.year, args.quarter, args.out, income, reasons, at,
                               args.basis_note), ensure_ascii=False))


if __name__ == '__main__':
    main()
