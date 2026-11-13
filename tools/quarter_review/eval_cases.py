"""Quarter-review correction cases: private aggregation and read-only re-evaluation (SPEC §8-7).

``build`` aggregates the AI reviewer's corrections (``change_log`` kind
``card.ai_review_corrected``) into case *types* -- cause rule IDs, reason,
item/attribution kind before -> after -- with counts only. No transaction id,
amount, merchant, date or card value is written. The file lives under the host's
private backups, never in Git.

``eval --planner rust`` runs the same re-judgment through ``costcore plan`` on a temporary copy
under the host's private backups and prints a per-case Python/Rust comparison (outcome tokens and
counts only; the allow-list below still governs every published value).

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
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
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


class _CopyStore:
    """Minimal store over the in-memory copy for the import classifier."""

    def __init__(self, conn):
        self.conn, self.lock = conn, threading.RLock()

    def log_change(self, *args, **kwargs):
        pass


def _import_classify(copy, tids):
    """Run the import-time classifier (data rules, patterns, card-category table) on the reset rows."""
    from app import classify
    store = _CopyStore(copy)
    batches = {}
    for tid in tids:
        for (batch,) in copy.execute('SELECT batch_id FROM import_batch_rows WHERE transaction_id=?', (tid,)):
            batches.setdefault(batch, []).append(tid)
    # Refund pairing is the plan's job (it inherits the original's judgment); keep it out of the input.
    pair_refunds, classify.pair_refunds = classify.pair_refunds, lambda *args, **kwargs: 0
    try:
        for batch, batch_ids in sorted(batches.items()):
            classify._classify_batch(store, batch, transaction_ids=batch_ids)
    finally:
        classify.pair_refunds = pair_refunds
    # A row the import step left without an attribution still awaits the completion plan.
    copy.execute("UPDATE transactions SET classification_state='needs_review' WHERE transaction_id IN "
                 "(SELECT value FROM json_each(?)) AND COALESCE(display_tab_id,'') IN ('','unclassified')",
                 (json.dumps(tids),))


def _python_plan(copy, trips, ids, nets, evidence):
    from app import automatic_classification as policy
    return policy.plan(copy, trips, nets=nets, transaction_ids=ids, reconsider=False, evidence=evidence or {})


def rejudge(conn, trips, cases, *, nets=None, evidence=None, plan_fn=_python_plan):
    """Re-judge each case from raw inputs with the current P1 code on an in-memory copy.

    Every case row is reset to a freshly imported state (no item, attribution,
    source or projection), so the result is what today's rules decide without
    leaning on the earlier, possibly wrong, answer. The import-time classifier runs
    first, then the completion plan, as in production.
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
        _import_classify(copy, [t for t in ids if t not in protected])
        plan = plan_fn(copy, trips, ids, nets, evidence)
        judged = {t['id']: dict(zip(policy.FIELDS, t['values'])) for t in plan['targets']}
        # No plan target means the import classification already stands as the judgment.
        for tid in ids:
            if tid in judged or tid in protected:
                continue
            row = copy.execute('SELECT ' + ','.join(policy.FIELDS) +
                               ' FROM transactions WHERE transaction_id=?', (tid,)).fetchone()
            if row and row[0] == 'classified':
                judged[tid] = dict(zip(policy.FIELDS, row))
    finally:
        copy.close()
    return [compare(c, judged.get(c['tid']), protected.get(c['tid'])) for c in cases]


def compare(case, judged, protected=None):
    """Compare every corrected field (item, attribution, trip) with the code's fresh judgment.

    Outcomes: MATCH (all fields equal), MISMATCH (one or more reasons), NOT_REJUDGED (code left
    the row alone). The item is always re-derived (import classification, then plan).
    """
    a = case['after']['transaction']
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
    if (judged.get('item') or '') != (a.get('item') or ''):
        reasons.append('ITEM_DIFFERS')
    if reasons:
        return dict(outcome='MISMATCH', reasons=reasons)
    return dict(outcome='MATCH', reasons=[])


OUTCOMES = ('MATCH', 'MISMATCH', 'NOT_REJUDGED', 'ITEM_NOT_REEVALUATED')
_KINDS = ('NONE', 'TRIP', 'QUARTER')
REASON_TOKENS = frozenset(
    {'ATTRIBUTION_TRIP_DIFFERS', 'ATTRIBUTION_QUARTER_DIFFERS', 'TRIP_ID_DIFFERS', 'ITEM_DIFFERS',
     'NOT_REJUDGED_SOURCE_PROTECTED', 'NOT_REJUDGED_PROTECTED_OR_UNCHANGED'}
    | {'ATTRIBUTION_%s_VS_%s' % (a, b) for a in _KINDS for b in _KINDS})
PLANNERS = ('python', 'rust')


def validate_token(token):
    """A published result token is an outcome plus fixed reason codes, e.g. ``MISMATCH[ITEM_DIFFERS]``."""
    match = re.fullmatch(r'([A-Z_]+)(?:\[([A-Z_+]+)\])?', token)
    if not match or match.group(1) not in OUTCOMES or not (
            set((match.group(2) or '').split('+')) - {''} <= REASON_TOKENS):
        raise ValueError('PUBLIC_VALUE_NOT_ALLOWED')


def result_token(result):
    token = result['outcome'] + ('[' + '+'.join(result['reasons']) + ']' if result['reasons'] else '')
    validate_token(token)
    return token


def compare_planners(cases, python_results, rust_results):
    """Per-case Python vs Rust comparison, published as counts of fixed tokens by case type."""
    differing, by_transition, by_type = 0, Counter(), Counter()
    for case, py, rs in zip(cases, python_results, rust_results):
        py_token, rs_token = result_token(py), result_token(rs)
        if py_token == rs_token:
            continue
        differing += 1
        by_transition[py_token + '->' + rs_token] += 1
        by_type[_type_key(dict(case_type(case), python=py_token, rust=rs_token))] += 1
    types = [dict(json.loads(k), count=n) for k, n in sorted(by_type.items())]
    for t in types:
        validate_public([{k: v for k, v in t.items() if k not in ('python', 'rust', 'count')}])
    return dict(cases=len(cases), same=len(cases) - differing, different=differing,
                by_transition=dict(sorted(by_transition.items())), by_type=types)


def _protected_workdir(host):
    backups = (host / 'data/backups').resolve()
    if not backups.is_dir() or backups.is_relative_to(REPO_ROOT):
        raise ValueError('CASES_LOCATION_INVALID')
    work = Path(tempfile.mkdtemp(prefix='eval-rust-', dir=backups)).resolve()
    if not work.is_relative_to(backups):
        shutil.rmtree(work, ignore_errors=True)
        raise ValueError('CASES_LOCATION_INVALID')
    return work


def find_costcore(explicit=None):
    found = explicit or os.environ.get('COSTCORE_BIN') or shutil.which('costcore')
    if not found:
        raise ValueError('COSTCORE_NOT_FOUND')
    return str(found)


def make_rust_plan(host, costcore):
    """plan_fn that runs ``costcore plan`` on a private temporary file copy of the re-judgment copy."""
    from tools.core_bridge.commands import canonical

    def rust_plan(copy, trips, ids, nets, evidence):
        work = _protected_workdir(host)
        try:
            path = work / 'rejudge-copy.sqlite'
            with closing(sqlite3.connect(path)) as target:
                copy.backup(target)
            request = canonical(dict(transaction_ids=ids, reconsider=False, trips=trips, nets=nets,
                                     evidence=evidence or {}))
            done = subprocess.run([costcore, 'plan', '--db', str(path)], input=json.dumps(request),
                                  capture_output=True, text=True, encoding='utf-8', timeout=3600)
        except OSError:
            raise ValueError('COSTCORE_NOT_STARTED')
        finally:
            shutil.rmtree(work, ignore_errors=True)
        try:
            response = json.loads(done.stdout.strip().splitlines()[0])
        except (IndexError, json.JSONDecodeError):
            raise ValueError('COSTCORE_RESPONSE_INVALID')
        if response.get('ok') is not True:
            code = str((response.get('error') or {}).get('code', ''))
            raise ValueError(code if re.fullmatch(r'[A-Z_]{1,60}', code) else 'COSTCORE_FAILED')
        return response['result']
    return rust_plan


def evaluate(conn, trips, *, review_id=None, nets=None, evidence=None, planner='python', rust_plan=None):
    cases = collect_cases(conn, review_id)
    python_results = rejudge(conn, trips, cases, nets=nets, evidence=evidence) if cases else []
    results = python_results
    if planner == 'rust':
        if rust_plan is None:
            raise ValueError('RUST_PLANNER_NOT_CONFIGURED')
        results = (rejudge(conn, trips, cases, nets=nets, evidence=evidence, plan_fn=rust_plan)
                   if cases else [])
    reasons = {'MISMATCH': Counter(), 'ITEM_NOT_REEVALUATED': Counter(), 'NOT_REJUDGED': Counter()}
    by_type = Counter()
    for case, result in zip(cases, results):
        if result['outcome'] == 'MATCH':
            continue
        reasons[result['outcome']].update(result['reasons'])
        by_type[_type_key(dict(case_type(case), result='+'.join(result['reasons'])))] += 1
    count = Counter(r['outcome'] for r in results)
    extra = (dict(planner='rust', comparison=compare_planners(cases, python_results, results))
             if planner == 'rust' else {})
    return dict(extra, cases=len(cases), matched=count['MATCH'], mismatched=count['MISMATCH'],
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
    parser.add_argument('--planner', choices=PLANNERS, default='python',
                        help='rust also runs `costcore plan` and prints a per-case Python/Rust comparison.')
    parser.add_argument('--costcore', type=Path, help='costcore executable (default: $COSTCORE_BIN or PATH).')
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
            rust_plan = make_rust_plan(host, find_costcore(args.costcore)) if args.planner == 'rust' else None
            report = evaluate(conn, trips, review_id=args.review_id, nets=nets, evidence=evidence,
                              planner=args.planner, rust_plan=rust_plan)
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
                                                   or report['item_not_reevaluated']
                                                   or report.get('comparison', {}).get('different')) else 0
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__
        print(json.dumps(dict(status='FAILED', code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
