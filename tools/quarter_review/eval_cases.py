"""Quarter-review correction cases: private aggregation and read-only re-evaluation (SPEC §8-7).

``build`` aggregates the AI reviewer's corrections (``change_log`` kind
``card.ai_review_corrected``) into case *types* -- cause rule IDs, reason,
item/attribution kind before -> after -- with counts only. No transaction id,
amount, merchant, date or card value is written. The file lives under the host's
private backups, never in Git.

``eval`` re-judges every corrected row from its raw inputs with the *current*
P1 classification code on an in-memory copy of the database and prints how many
results differ from the reviewer's correction, by reason. The production
database is opened ``mode=ro``; nothing is written, no server is started.
"""
from __future__ import annotations

import argparse
import faulthandler
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

KIND = 'card.ai_review_corrected'
RESTORE_KIND = 'card.ai_review_restored'
SCHEMA = 1
DEFAULT_HOST = Path('D:/WebLedgerHost')
CASES_SUBPATH = Path('data/backups/quarter-review-2026Q3/eval-cases')
# Derived booking evidence carries transaction ids: it lives beside, never inside, the case folder.
EVIDENCE_CACHE = Path('data/backups/quarter-review-2026Q3/evidence-cache/evidence.json')
ITEM_VOCABULARY = frozenset({
    '주차비', '주유비', '통행료', '항공료', '렌터카', '숙박비', '식비', '편의점', '교통비', '입장료',
    '여행경비', '취소·환불', '현지경비', '기타경비', '분기 기타비용', '통신비', '소프트웨어구독료',
    '사무용품비', '소모품비', '대중교통', '기타비용', ''})
SOURCE_VOCABULARY = frozenset({
    'inference', 'ai_inference', 'rule', 'pattern', 'code_inference', 'refund_original', 'user_exception',
    'owner_booking', 'card_category', 'owner_card_residual', 'auto_inferred', 'booking_evidence_needed', ''})
ATTRIBUTION_VOCABULARY = frozenset({'none', 'trip', 'quarter'})
# Reviewer text is never copied. A reason is published only as these fixed codes, chosen by
# generic keywords; a customer name or merchant in the free text cannot reach the file.
REASON_CODES = (
    ('NO_BOOKING_PERIOD_EVIDENCE', ('근거 없음',)),
    ('OUTSIDE_TRIP_PERIOD', ('여행 기간 밖', '종료된 해외 여행')),
    ('QUARTER_OTHER_COST', ('분기 기타비용',)),
    ('ITEM_FROM_MERCHANT_OR_INDUSTRY', ('가맹점 이름', '카드사 업종')),
    ('OVERLAPPING_FOREIGN_TRIPS_COUNTRY', ('사용 국가',)),
    ('DOMESTIC_FOREIGN_MISMATCH', ('국내 현장', '해외·온라인', '국내 여객선', '해외 여행에 귀속')),
    ('DESIGNATED_CARD_RESIDUAL', ('지정 카드 잔여',)),
    ('BOOKING_PERIOD_EVIDENCE', ('예약 이용기간 근거(', '출발일이 이 여행', '예약 메일상')),
    ('REPLACES_PAYMENT_DATE_PROXIMITY', ('결제일 근접',)),
)
INDIVIDUAL_REASON = 'INDIVIDUAL_CORRECTION'
REASON_VOCABULARY = frozenset({code for code, _ in REASON_CODES} | {INDIVIDUAL_REASON})
RULE_VOCABULARY = re.compile(r'[A-Z]{2,6}-\d{3}|DECISION_POLICY §[\d.]+')
REVIEW_ID = re.compile(r'[A-Za-z0-9._-]{1,80}')
# Sources written by import-time rules; the P1 plan cannot reproduce their item.
IMPORT_SOURCES = frozenset({'rule', 'pattern', 'user_exception', 'owner_booking', 'refund_original'})
RULE_ID = re.compile(r'\b[A-Z]{2,6}-\d{3}\b|DECISION_POLICY §[\d.]+')
BASIS = re.compile(r'^AI_REVIEW · \{[^{}]*\} · (.*)$', re.S)
FRESH = dict(classification_state='needs_review', classification_source='', classification_basis='',
             description='', trip_id='', display_tab_id='')


def attribution_kind(tab):
    tab = tab or ''
    if tab in ('', 'unclassified'):
        return 'none'
    return 'quarter' if tab.startswith('quarter:') else 'trip'


def item_label(item):
    item = item or ''
    return item if item in ITEM_VOCABULARY else '기타(목록 밖)'


def parse_basis(basis):
    """Return (rule_ids, reason_text) from an AI_REVIEW basis; both may be empty."""
    match = BASIS.match(basis or '')
    text = match.group(1) if match else ''
    rules = sorted(set(RULE_ID.findall(text)))
    parts = [p.strip() for p in text.split(' · ') if p.strip() and not RULE_ID.fullmatch(p.strip())]
    return rules, ' · '.join(parts)


def collect_cases(conn, review_id=None):
    """Private, in-memory cases (they carry ids); never serialise these."""
    restored = {json.loads(raw).get('release_entry_id') for (raw,) in conn.execute(
        'SELECT detail_json FROM change_log WHERE kind=?', (RESTORE_KIND,))}
    cases = []
    for entry, tid, raw in conn.execute(
            'SELECT entry_id,subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (KIND,)):
        if entry in restored:
            continue
        detail = json.loads(raw)
        if review_id and detail.get('request_id') != review_id:
            continue
        before, after = detail['before'], detail['after']
        rules, reason = parse_basis(after['transaction'].get('classification_basis'))
        cases.append(dict(entry=entry, tid=tid, review_id=detail.get('request_id'), before=before,
                          after=after, rules=rules, reason=reason))
    return cases


def reason_codes(text):
    """Fixed reason codes for reviewer text; the text itself is never kept."""
    codes = [code for code, words in REASON_CODES if any(w in (text or '') for w in words)]
    return codes or [INDIVIDUAL_REASON]


def case_type(case):
    b, a = case['before']['transaction'], case['after']['transaction']
    b_tab, a_tab = b.get('display_tab_id') or b.get('trip_id'), a.get('display_tab_id') or a.get('trip_id')
    source = b.get('classification_source') or ''
    return dict(rules=[r for r in case['rules'] if RULE_VOCABULARY.fullmatch(r)],
                reason=reason_codes(case['reason']),
                before_source=source if source in SOURCE_VOCABULARY else 'other',
                item=('unchanged' if (b.get('item') or '') == (a.get('item') or '')
                      else item_label(b.get('item')) + '→' + item_label(a.get('item'))),
                attribution=('unchanged' if b_tab == a_tab
                             else attribution_kind(b_tab) + '→' + attribution_kind(a_tab)))


def _type_key(t):
    return json.dumps(t, ensure_ascii=False, sort_keys=True)


def validate_public(types):
    """Every published value must come from a fixed vocabulary (allow-list); raise otherwise."""
    for t in types:
        if not (set(t) >= {'rules', 'reason', 'before_source', 'item', 'attribution'}
                and all(RULE_VOCABULARY.fullmatch(r) for r in t['rules'])
                and set(t['reason']) <= REASON_VOCABULARY and t['before_source'] in SOURCE_VOCABULARY | {'other'}):
            raise ValueError('PUBLIC_VALUE_NOT_ALLOWED')
        sides = [t['item']] if t['item'] == 'unchanged' else t['item'].split('→')
        labels = ITEM_VOCABULARY | {'기타(목록 밖)'}
        arrows = [t['attribution']] if t['attribution'] == 'unchanged' else t['attribution'].split('→')
        if (len(sides) not in (1, 2) or any(x not in labels | {'unchanged'} for x in sides)
                or any(x not in ATTRIBUTION_VOCABULARY | {'unchanged'} for x in arrows)):
            raise ValueError('PUBLIC_VALUE_NOT_ALLOWED')


def aggregate(cases):
    types = Counter(_type_key(case_type(c)) for c in cases)
    result = [dict(json.loads(k), count=n) for k, n in sorted(types.items())]
    validate_public(result)
    return result


def build_case_file(cases, review_id):
    if not REVIEW_ID.fullmatch(review_id or ''):
        raise ValueError('REVIEW_ID_INVALID')
    types = aggregate(cases)
    return dict(schema=SCHEMA, review_id=review_id, source=KIND, total=len(cases), types=types,
                by_rule=dict(sorted(Counter(r for t in types for r in (t['rules'] or ['(규칙 ID 없음)'])
                                            for _ in range(t['count'])).items())),
                by_attribution=dict(sorted(Counter(t['attribution'] for t in types for _ in range(t['count'])).items())),
                note='식별값·금액 없음. 허용 목록의 값(사유 코드·항목 어휘·귀속 종류)과 건수만 담은 비공개 파일(Git 금지).')


def rejudge(conn, trips, cases, *, nets=None, evidence=None):
    """Re-judge each case from raw inputs with the current P1 code on an in-memory copy.

    Every case row is reset to a freshly imported state (no item, attribution,
    source or projection), so the result is what today's rules decide without
    leaning on the earlier, possibly wrong, answer.
    """
    from app import automatic_classification as policy
    copy = sqlite3.connect(':memory:', isolation_level=None)
    try:
        conn.backup(copy)
        ids = [c['tid'] for c in cases]
        for case in cases:
            tid = case['tid']
            # The corrected item must never leak into the input, whatever the old source.
            fresh = dict(FRESH, item='')
            copy.execute('UPDATE transactions SET ' + ','.join(k + '=?' for k in fresh) +
                         ' WHERE transaction_id=?', (*fresh.values(), tid))
            copy.execute('DELETE FROM ledger_entries WHERE transaction_id=?', (tid,))
            copy.execute('DELETE FROM board_rows WHERE row_id=?', ('card-' + tid,))
        protected = {}
        for tid, duplicate, conflict, parse_error in copy.execute(
                'SELECT transaction_id,duplicate_of,conflict_reason,parse_error FROM transactions '
                'WHERE transaction_id IN (SELECT value FROM json_each(?))', (json.dumps(ids),)):
            if duplicate or conflict or parse_error:
                # Source protection (e.g. a later duplicate cleanup) keeps P1 from judging the row.
                protected[tid] = 'NOT_REJUDGED_SOURCE_PROTECTED'
        plan = policy.plan(copy, trips, nets=nets, transaction_ids=ids, reconsider=False, evidence=evidence or {})
        judged = {t['id']: dict(zip(policy.FIELDS, t['values'])) for t in plan['targets']}
    finally:
        copy.close()
    return [compare(c, judged.get(c['tid']), protected.get(c['tid'])) for c in cases]


def compare(case, judged, protected=None):
    """Compare every corrected field (item, attribution, trip) with the code's fresh judgment.

    Outcomes: MATCH (all fields equal), MISMATCH (one or more reasons),
    ITEM_NOT_REEVALUATED (attribution equal, item differs but the item came from an import-time
    rule P1 does not run), NOT_REJUDGED (code left the row alone).
    """
    b, a = case['before']['transaction'], case['after']['transaction']
    if judged is None:
        return dict(outcome='NOT_REJUDGED', reasons=[protected or 'NOT_REJUDGED_PROTECTED_OR_UNCHANGED'])
    expected_tab, got_tab = a.get('display_tab_id') or '', judged.get('display_tab_id') or ''
    reasons = []
    if got_tab != expected_tab:
        got, want = attribution_kind(got_tab), attribution_kind(expected_tab)
        reasons.append('ATTRIBUTION_TRIP_DIFFERS' if got == want == 'trip' else (
            'ATTRIBUTION_QUARTER_DIFFERS' if got == want == 'quarter' else
            'ATTRIBUTION_' + got.upper() + '_VS_' + want.upper()))
    elif (judged.get('trip_id') or '') != (a.get('trip_id') or ''):
        reasons.append('TRIP_ID_DIFFERS')
    item_equal = (judged.get('item') or '') == (a.get('item') or '')
    if not item_equal and (b.get('classification_source') or '') not in IMPORT_SOURCES:
        reasons.append('ITEM_DIFFERS')
    if reasons:
        return dict(outcome='MISMATCH', reasons=reasons)
    if not item_equal:
        return dict(outcome='ITEM_NOT_REEVALUATED', reasons=['ITEM_FROM_IMPORT_RULE_NOT_REEVALUATED'])
    return dict(outcome='MATCH', reasons=[])


def evaluate(conn, trips, *, review_id=None, nets=None, evidence=None):
    cases = collect_cases(conn, review_id)
    results = rejudge(conn, trips, cases, nets=nets, evidence=evidence) if cases else []
    reasons = {'MISMATCH': Counter(), 'ITEM_NOT_REEVALUATED': Counter(), 'NOT_REJUDGED': Counter()}
    by_type = Counter()
    for case, result in zip(cases, results):
        if result['outcome'] == 'MATCH':
            continue
        reasons[result['outcome']].update(result['reasons'])
        by_type[_type_key(dict(case_type(case), result='+'.join(result['reasons'])))] += 1
    count = Counter(r['outcome'] for r in results)
    return dict(cases=len(cases), matched=count['MATCH'], mismatched=count['MISMATCH'],
                by_reason=dict(sorted(reasons['MISMATCH'].items())),
                item_not_reevaluated=count['ITEM_NOT_REEVALUATED'],
                item_not_reevaluated_by_reason=dict(sorted(reasons['ITEM_NOT_REEVALUATED'].items())),
                not_rejudged=count['NOT_REJUDGED'],
                not_rejudged_by_reason=dict(sorted(reasons['NOT_REJUDGED'].items())),
                by_type=[dict(json.loads(k), count=n) for k, n in sorted(by_type.items())],
                type_counts_match_case_file=None)


def _cases_dir(host, override):
    directory = (override or host / CASES_SUBPATH).resolve()
    if directory.is_relative_to(REPO_ROOT):
        raise ValueError('CASES_IN_REPOSITORY')
    if override is None:
        return directory
    if not directory.is_relative_to((host / 'data/backups').resolve()):
        raise ValueError('CASES_LOCATION_INVALID')
    return directory


def _open_ro(db):
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)
    conn.execute('PRAGMA query_only=ON')
    return conn


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'eval'))
    parser.add_argument('--host-root', type=Path, default=DEFAULT_HOST)
    parser.add_argument('--db', type=Path, help='Database path (default: <host>/data/board.sqlite); a copy is fine.')
    parser.add_argument('--cases-dir', type=Path, help='Private case folder under <host>/data/backups.')
    parser.add_argument('--review-id', default='ai-quarter-review-2026Q3')
    parser.add_argument('--evidence-cache', type=Path,
                        help='Derived booking-evidence cache under host backups '
                             '(default: <host>/' + str(EVIDENCE_CACHE) + ').')
    parser.add_argument('--max-seconds', type=int, default=3600,
                        help='Hard time limit for eval; the process dumps its stack and exits when exceeded.')
    parser.add_argument('--no-evidence', action='store_true', help='Skip booking/mail evidence (faster, less faithful).')
    parser.add_argument('--fail-on-mismatch', action='store_true')
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    db = args.db or host / 'data/board.sqlite'
    try:
        if not REVIEW_ID.fullmatch(args.review_id):
            raise ValueError('REVIEW_ID_INVALID')
        cases_dir = _cases_dir(host, args.cases_dir)
        case_path = cases_dir / ('cases-' + args.review_id + '.json')
        with closing(_open_ro(db)) as conn:
            if args.command == 'build':
                cases = collect_cases(conn, args.review_id)
                if not cases:
                    raise ValueError('NO_CASES')
                cases_dir.mkdir(parents=True, exist_ok=True)
                payload = build_case_file(cases, args.review_id)
                case_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                                     encoding='utf-8')
                print(json.dumps(dict(status='BUILT', cases=payload['total'], types=len(payload['types']),
                                      case_file=str(case_path)), ensure_ascii=False))
                return 0
            from tools.complete_card_classification import load_context, load_review_evidence
            started = time.monotonic()
            if args.max_seconds > 0:
                faulthandler.dump_traceback_later(args.max_seconds, exit=True, file=sys.__stderr__)
            timings = {}
            trips, nets = load_context(conn, host)
            timings['context'] = time.monotonic() - started
            evidence, cache, cache_state = {}, None, 'not_used'
            if not args.no_evidence:
                cache = args.evidence_cache or host / EVIDENCE_CACHE
                if not cache.resolve().is_relative_to((host / 'data/backups').resolve()):
                    raise ValueError('CACHE_LOCATION_INVALID')
                cache.parent.mkdir(parents=True, exist_ok=True)
                mark = time.monotonic()
                try:
                    evidence = load_review_evidence(conn, host, trips, cache)[0]
                except ValueError as exc:
                    if str(exc) != 'EVIDENCE_CACHE_STALE':
                        raise
                    # The derived cache is keyed on live source state; production keeps changing, so rebuild it.
                    cache_state = 'rebuilt_stale'
                    cache.unlink()
                    evidence = load_review_evidence(conn, host, trips, cache)[0]
                timings['evidence'] = time.monotonic() - mark
            mark = time.monotonic()
            report = evaluate(conn, trips, review_id=args.review_id, nets=nets, evidence=evidence)
            timings['rejudge'] = time.monotonic() - mark
            faulthandler.cancel_dump_traceback_later()
            report.update(evidence_mode='none' if args.no_evidence else 'booking_and_mail',
                          evidence_rows=len(evidence), evidence_cache=cache_state,
                          timings_seconds={k: round(v, 1) for k, v in timings.items()},
                          elapsed_seconds=round(time.monotonic() - started, 1))
            if case_path.is_file():
                saved = json.loads(case_path.read_text(encoding='utf-8'))
                report['type_counts_match_case_file'] = (
                    saved.get('types') == aggregate(collect_cases(conn, args.review_id)))
            print(json.dumps(dict(status='EVALUATED', **report), ensure_ascii=False, sort_keys=True))
            return 2 if args.fail_on_mismatch and (report['mismatched'] or report['not_rejudged']
                                                   or report['item_not_reevaluated']) else 0
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__
        print(json.dumps(dict(status='FAILED', code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
