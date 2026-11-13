"""M3 U7 골든 생산기(읽기 전용): 합성 입력으로 Python 날짜·분기·완료 기간 함수를 직접 호출해 기대값을 JSONL로 만든다.

사용: python -I tools/core_dates_golden.py --out core/golden/synthetic/dates.jsonl [--check]
`--check`는 파일을 쓰지 않고 현재 Python 동작이 이미 기록된 골든과 같은지만 확인한다(다르면 종료 코드 1).
골든 재생성은 이 함수들의 Python 판정이 바뀐 PR에서만 하고 차이 유형을 PR에 적는다. DB·네트워크·운영 포트를 쓰지 않는다.
"""
import argparse
import itertools
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import classification_correction as cc  # noqa: E402
from app import closed_period as cp  # noqa: E402
from app import quarter_costs as qc  # noqa: E402
from app import reconciliation as rec  # noqa: E402

TRIP_FIXTURES = {
    'T': [
        {'trip_id': 'T-open', 'starts_on': '2026-07-01', 'ends_on': '2026-07-10'},
        {'trip_id': 'T-boundary', 'starts_on': '2026-06-30', 'ends_on': '2026-07-05'},
        {'trip_id': 'T-before', 'starts_on': '2026-06-29', 'ends_on': '2026-07-05'},
        {'trip_id': 'T-closed25', 'starts_on': '2025-06-01', 'ends_on': '2025-06-10'},
        {'trip_id': 'T-q1', 'starts_on': '2026-03-31', 'ends_on': '2026-04-05'},
        {'trip_id': 'T-deleted', 'starts_on': '2026-08-01', 'ends_on': '2026-08-09', 'deleted': True},
        {'tab_id': 'tab-open', 'starts_on': '2026-09-01', 'ends_on': '2026-09-09'},
        {'trip_id': 'T-archived', 'starts_on': '2026-10-01', 'ends_on': '2026-10-09', 'archived': True},
        {'trip_id': 'T-noend', 'starts_on': '2026-11-01'},
        {'trip_id': 'T-first2025', 'starts_on': '2025-01-01', 'ends_on': '2025-01-05'},
        {'trip_id': 'T-eve2025', 'starts_on': '2024-12-31', 'ends_on': '2025-01-02'},
        {'starts_on': '2026-12-01', 'ends_on': '2026-12-05'},
    ],
    'EMPTY': [],
    'DUP': [
        {'trip_id': 'D', 'starts_on': '2025-02-01', 'ends_on': '2025-02-03'},
        {'trip_id': 'D', 'starts_on': '2026-07-01', 'ends_on': '2026-07-03'},
    ],
}

BOUNDARY_DAYS = [
    '2024-12-31', '2025-01-01', '2025-06-30', '2025-12-31', '2026-01-01', '2026-02-28', '2026-03-31',
    '2026-04-01', '2026-06-29', '2026-06-30', '2026-07-01', '2026-09-29', '2026-09-30', '2026-10-01',
    '2026-12-31', '2027-01-01', '2024-02-29', '2028-02-29', '2028-03-01', '2100-02-28', '2100-03-01',
    '2000-02-29', '0001-01-01', '9999-12-31',
]
ODD_FORMS = ['20260630', '2026-W27-2', '2026W272', '2026-W27', '2025-02-29', '2026-6-30', '0000-01-01',
             '2026-13-01', '2026-00-10', 'garbage', ' 2026-06-30', '2026-06-30T00:00', '2100-02-29', '2026-W53-1']
LINES = []


def emit(fn, args, call):
    try:
        out = {'out': call()}
    except (ValueError, OverflowError):
        out = {'err': True}
    LINES.append({'fn': fn, 'in': args, **out})


def quarter_days():
    days = set(BOUNDARY_DAYS)
    for year in range(2024, 2029):
        for month in range(1, 13):
            first = date(year, month, 1)
            days.add(first.isoformat())
            days.add(((first + timedelta(days=31)).replace(day=1) - timedelta(days=1)).isoformat())
    return sorted(days)


def rows_dates():
    approvals = [None, '', '2025-01-01', '2025-12-31', '2026-03-31', '2026-04-01', '2026-06-30', 'garbage', '20260630']
    postings = [None, '', '2024-12-31', '2026-01-01', '2026-06-29', '2026-09-30', '2026-10-01', '2028-02-29']
    out = [{'approval_date': a, 'posting_date': p} for a, p in itertools.product(approvals, postings)]
    out += [{'approval_date': d, 'posting_date': None} for d in ODD_FORMS]
    return out


def build():
    for day in quarter_days():
        emit('quarter_of', {'day': day}, lambda day=day: list(qc.quarter_of(date.fromisoformat(day))))
    for row in rows_dates():
        emit('tab_of', {'row': row}, lambda row=row: qc._tab_of(row))
        emit('completed_period', {'row': row}, lambda row=row: cp.completed_period(row))
    for service, payment in itertools.product([None, '', '2026-06-30'], [None, '', '2026-07-01']):
        emit('ledger_date_for_booking', {'service': service, 'payment': payment},
             lambda s=service, p=payment: rec.ledger_date_for_booking(s, p))
    for start, nxt in itertools.product(
            [None, '', '2026-06-30', '2028-02-28', '2025-12-30', '2026-12-31'],
            [None, '', '2026-06-30', '2026-07-01', '2028-03-01', '2026-01-01', '2026-01-02', 'bad', '2025-01-01']):
        emit('open_trip_end', {'starts_on': start, 'next_starts_on': nxt},
             lambda s=start, n=nxt: rec.open_trip_end(s, n))
    for value in [None, '', '2026-06-30']:
        emit('card_use_date', {'approval_date': value}, lambda v=value: rec.card_use_date({'approval_date': v}))

    span_sets = {
        'chain': [{'starts_on': '2026-06-30', 'ends_on': '2026-07-10'}, {'starts_on': '2026-07-10', 'ends_on': '2026-07-20'},
                  {'starts_on': '2026-07-21', 'ends_on': '2026-07-25'}],
        'gap': [{'starts_on': '2026-06-30', 'ends_on': '2026-07-10'}, {'starts_on': '2026-07-12', 'ends_on': '2026-07-20'}],
        'solo_bad_end': [{'starts_on': '2026-06-30', 'ends_on': 'bad'}],
        'two_bad_end': [{'starts_on': '2026-06-30', 'ends_on': 'bad'}, {'starts_on': '2026-08-01', 'ends_on': '2026-08-02'}],
        'leap': [{'starts_on': '2028-02-20', 'ends_on': '2028-02-28'}, {'starts_on': '2028-02-29', 'ends_on': '2028-03-05'}],
        'year': [{'starts_on': '2025-12-20', 'ends_on': '2025-12-31'}, {'starts_on': '2026-01-01', 'ends_on': '2026-01-04'}],
        'noends': [{'starts_on': '2026-06-30'}, {'starts_on': '2026-07-01', 'ends_on': ''}],
        'same_day': [{'starts_on': '2026-07-05', 'ends_on': '2026-07-05'}, {'starts_on': '2026-07-05'}],
    }
    for name, spans in span_sets.items():
        emit('handover_days', {'trips': spans}, lambda spans=spans: sorted(rec.handover_days(spans)))
    prep_sets = {
        'unique': [{'starts_on': '2026-07-10'}, {'starts_on': '2026-08-01'}, {'starts_on': '2026-06-01'}],
        'tie': [{'starts_on': '2026-07-10'}, {'starts_on': '2026-07-10'}],
        'none': [{'starts_on': '2026-06-01'}, {'starts_on': ''}],
        'empty': [],
    }
    for spans, check_out in itertools.product(prep_sets.values(), ['2026-07-10', '2026-07-09', '2026-07-11', '2026-08-02', '']):
        def prep(spans=spans, check_out=check_out):
            found = rec.prep_trip(spans, '2026-06-30', check_out)
            return None if found is None else next(i for i, t in enumerate(spans) if t is found)
        emit('prep_trip', {'trips': spans, 'check_out': check_out}, prep)

    trips = [('2026-06-30', '2026-07-10'), ('2025-12-28', '2026-01-02'), ('2028-02-27', '2028-03-02'),
             ('', '2026-07-10'), ('2026-06-30', ''), ('2026-06-30', 'bad')]
    stays = [('2026-06-30', '2026-07-01'), ('2026-06-29', '2026-07-02'), ('2026-07-09', '2026-07-10'),
             ('2026-07-09', '2026-07-11'), ('2026-07-10', '2026-07-11'), ('2025-12-31', '2026-01-02'),
             ('2025-12-27', '2025-12-28'), ('2026-01-02', '2026-01-03'), ('2028-02-28', '2028-03-01'),
             ('2028-02-29', '2028-03-02'), ('2026-07-05', '2026-07-05'), ('2026-07-06', '2026-07-04'),
             ('2026-07-05', 'bad')]
    for (start, end), (check_in, check_out), service, handover in itertools.product(
            trips, stays, [False, True], [False, True]):
        ho = [end] if handover and end else []
        args = {'trip_start': start, 'trip_end': end, 'check_in': check_in, 'check_out': check_out,
                'service': service, 'handover': ho}
        for fn in ('covers_stay', 'overlaps_stay', 'shared_days'):
            emit(fn, args, lambda fn=fn: getattr(rec, fn)(start, end, check_in, check_out, service=service,
                                                           handover=set(ho)))

    LINES.append({'fn': '_fixtures', 'trips': TRIP_FIXTURES})
    for trip in TRIP_FIXTURES['T'] + [{'trip_id': 'x', 'starts_on': None}, {'trip_id': 'y'}]:
        emit('open_trip', {'trip': trip}, lambda t=trip: cp.open_trip(t))
        emit('completed_trip', {'trip': trip}, lambda t=trip: cp.completed_trip(t))
    for start, flags in itertools.product(
            ['2024-12-31', '2025-01-01', '2026-03-31', '2026-04-01', '2026-06-29', '2026-06-30', '', None],
            [(False, False), (True, False), (False, True)]):
        trip = {'trip_id': 't', 'starts_on': start, 'deleted': flags[0], 'archived': flags[1]}
        emit('open_trip', {'trip': trip}, lambda t=trip: cp.open_trip(t))
        emit('completed_trip', {'trip': trip}, lambda t=trip: cp.completed_trip(t))

    dates = [{'approval_date': '2025-03-01', 'posting_date': None}, {'approval_date': '2025-12-31', 'posting_date': None},
             {'approval_date': None, 'posting_date': '2026-03-31'}, {'approval_date': '2026-04-01', 'posting_date': None},
             {'approval_date': '2026-06-29', 'posting_date': None}, {'approval_date': '2026-06-30', 'posting_date': None},
             {'approval_date': '', 'posting_date': ''}]
    trip_ids = [None, '', 'T-open', 'T-boundary', 'T-closed25', 'quarter:2025:3', 'quarter:2026:2', 'T-q1', 'tab-open',
                'T-before', 'T-deleted', 'None']
    display_ids = [None, 'tab-open', 'T-first2025']
    rows = [{**d, 'trip_id': t, 'display_tab_id': x, 'source_hash': h}
            for d, t, x, h in itertools.product(dates, trip_ids, display_ids, ['h1', None])]
    for row in rows:
        emit('open_scope', {'row': row, 'trips': 'T'}, lambda row=row: cp.open_scope(row, TRIP_FIXTURES['T']))
    period = {'starts_on': '2026-07-02', 'ends_on': '2026-07-08'}
    evidences = [
        None,
        {'trip_id': 'T-open', 'service_period': period, 'formal_link': True, 'source_hash': 'h1'},
        {'trip_id': 'T-open', 'service_period': period, 'formal_link': True, 'source_hash': 'other'},
        {'trip_id': 'T-open', 'service_period': {'starts_on': '2026-06-30', 'ends_on': '2026-07-08'}, 'formal_link': True, 'source_hash': 'h1'},
        {'trip_id': 'T-open', 'service_period': {'starts_on': '2026-07-02', 'ends_on': '2026-07-11'}, 'formal_link': True, 'source_hash': 'h1'},
        {'trip_id': 'T-open', 'service_period': period, 'formal_link': False, 'source_hash': 'h1'},
        {'trip_id': 'T-noend', 'service_period': period, 'formal_link': True, 'source_hash': 'h1'},
        {'trip_id': 'tab-open', 'service_period': {'starts_on': '2026-09-01', 'ends_on': '2026-09-09'}, 'formal_link': True, 'source_hash': 'h1'},
    ]
    # 행 조합: A는 도착 ID 변형 전부, B는 표시 탭·원천 해시 변형(증거는 없음·정상 둘)
    core_rows = [r for r in rows if r['display_tab_id'] is None and r['source_hash'] == 'h1'
                 and r['trip_id'] in (None, '', 'T-open', 'T-boundary', 'T-closed25', 'quarter:2025:3', 'T-q1', 'tab-open')
                 and r['approval_date'] != '2025-12-31' and r['posting_date'] != '2026-03-31']
    side_rows = [r for r in rows if r['display_tab_id'] is not None and r['trip_id'] in (None, 'T-open', 'T-closed25')
                 and r['approval_date'] != '2025-12-31' and r['posting_date'] != '2026-03-31']
    for row, evidence, manual in ([(r, e, m) for r in core_rows for e in evidences for m in (False, True)]
                                  + [(r, e, m) for r in side_rows for e in evidences[:2] for m in (False, True)]):
        args = {'row': row, 'trips': 'T', 'evidence': evidence, 'manual': manual}
        both = lambda: {'excluded': cp.excluded(row, TRIP_FIXTURES['T'], evidence=evidence, manual=manual),
                        'exception_trip': cp.exception_trip(row, TRIP_FIXTURES['T'], evidence=evidence, manual=manual)}
        emit('excluded_and_exception_trip', args, both)
    # 같은 id 여행은 뒤의 것이 이긴다
    dup_row = {'approval_date': '2025-03-01', 'posting_date': None, 'trip_id': 'D', 'display_tab_id': None, 'source_hash': 'h'}
    emit('excluded_and_exception_trip', {'row': dup_row, 'trips': 'DUP', 'evidence': None, 'manual': True},
         lambda: {'excluded': cp.excluded(dup_row, TRIP_FIXTURES['DUP'], evidence=None, manual=True),
                  'exception_trip': cp.exception_trip(dup_row, TRIP_FIXTURES['DUP'], evidence=None, manual=True)})
    emit('open_scope', {'row': dup_row, 'trips': 'DUP'}, lambda: cp.open_scope(dup_row, TRIP_FIXTURES['DUP']))

    tab_ids = ['quarter:2026:3', 'quarter:2026:2', 'quarter:2025:4', 'quarter:2027:1', 'quarter:2026-Q3', 'quarter:2026-Q2',
               'quarter:2026: 3', 'quarter:2026: 2', 'quarter:', 'quarter:2026', 'quarter:x:3', 'quarter: 2026:3',
               'quarter:2026:3:4', 'quarter:+2026:+3', 'quarter:2_026:3', 'quarter:2026:03', 'quarter:-1:3',
               'quarter:2026-Q', 'quarter:2026-Q3-Q4', 'quarter:2026:3.0', 'quarter:2026:4', 'quarter:2026:1',
               'quarter:2026:_3', 'quarter:2026:3_', 'quarter:2026:3__0', 'quarter:2026:+', 'quarter:2026:',
               'T-open', 'T-boundary', 'T-before', 'T-deleted', 'T-archived', 'tab-open', 'T-noend', 'nope', '', 'None',
               'D', 'T-q1']
    for tab_id, name in itertools.product(tab_ids, ['T', 'DUP', 'EMPTY']):
        emit('open_p2_tab', {'trips': name, 'trip_id': tab_id}, lambda: cc._open_p2_tab(TRIP_FIXTURES[name], tab_id))


def render():
    build()
    return ''.join(json.dumps(line, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n' for line in LINES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = render()
    path = Path(args.out)
    if args.check:
        current = path.read_bytes().decode('utf-8') if path.exists() else ''
        print('golden cases:', len(LINES) - 1, 'match' if current == text else 'DIFFERENT')
        return 0 if current == text else 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))
    print('wrote', len(LINES) - 1, 'cases to', path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
