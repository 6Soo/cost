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
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

KIND = 'card.ai_review_corrected'
RESTORE_KIND = 'card.ai_review_restored'
SCHEMA = 1
DEFAULT_HOST = Path('D:/WebLedgerHost')
CASES_SUBPATH = Path('data/backups/quarter-review-2026Q3/eval-cases')
ITEM_VOCABULARY = frozenset({
    '주차비', '주유비', '통행료', '항공료', '렌터카', '숙박비', '식비', '편의점', '교통비', '입장료',
    '여행경비', '취소·환불', '현지경비', '기타경비', '분기 기타비용', ''})
# Sources written by import-time rules; the P1 plan cannot reproduce their item.
IMPORT_SOURCES = frozenset({'rule', 'pattern', 'user_exception', 'owner_booking', 'refund_original'})
RULE_ID = re.compile(r'\b[A-Z]{2,6}-\d{3}\b|DECISION_POLICY §[\d.]+')
BASIS = re.compile(r'^AI_REVIEW · \{[^{}]*\} · (.*)$', re.S)
MIN_GROUP = 3  # reason text is published only when at least this many rows share it
GENERIC_REASON = '건별 교정'
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


def case_type(case, reasons_ok):
    b, a = case['before']['transaction'], case['after']['transaction']
    b_tab, a_tab = b.get('display_tab_id') or b.get('trip_id'), a.get('display_tab_id') or a.get('trip_id')
    return dict(rules=case['rules'],
                reason=case['reason'] if case['reason'] in reasons_ok else GENERIC_REASON,
                before_source=b.get('classification_source') or '',
                item=('unchanged' if (b.get('item') or '') == (a.get('item') or '')
                      else item_label(b.get('item')) + '→' + item_label(a.get('item'))),
                attribution=('unchanged' if b_tab == a_tab
                             else attribution_kind(b_tab) + '→' + attribution_kind(a_tab)))


def _type_key(t):
    return json.dumps(t, ensure_ascii=False, sort_keys=True)


def reasons_allowed(cases):
    """k-anonymity for reviewer-authored text: digits/latin or rare phrases are not published."""
    counts = Counter(c['reason'] for c in cases)
    return {r for r, n in counts.items() if r and n >= MIN_GROUP and not re.search(r'[0-9A-Za-z]', r)
            and len(r) <= 120}


def aggregate(cases):
    reasons_ok = reasons_allowed(cases)
    types = Counter(_type_key(case_type(c, reasons_ok)) for c in cases)
    return [dict(json.loads(k), count=n) for k, n in sorted(types.items())]


def build_case_file(cases, review_id):
    types = aggregate(cases)
    return dict(schema=SCHEMA, review_id=review_id, source=KIND, total=len(cases), types=types,
                by_rule=dict(sorted(Counter(r for c in cases for r in (c['rules'] or ['(규칙 ID 없음)'])).items())),
                by_attribution=dict(sorted(Counter(t['attribution'] for t in types for _ in range(t['count'])).items())),
                note='식별값·금액 없음. 사례 유형별 건수만 담은 비공개 파일(Git 금지).')


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
            tid, source = case['tid'], case['before']['transaction'].get('classification_source') or ''
            fresh = dict(FRESH)
            if source not in IMPORT_SOURCES:
                fresh['item'] = ''
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
    """Outcome and reason for one case; ``judged`` is None when the code left it unjudged."""
    b, a = case['before']['transaction'], case['after']['transaction']
    expected_tab = a.get('display_tab_id') or a.get('trip_id') or ''
    if judged is None:
        return dict(outcome='NOT_REJUDGED', reason=protected or 'NOT_REJUDGED_PROTECTED_OR_UNCHANGED')
    got_tab = judged.get('display_tab_id') or ''
    if got_tab != expected_tab:
        got, want = attribution_kind(got_tab), attribution_kind(expected_tab)
        reason = 'ATTRIBUTION_TRIP_DIFFERS' if got == want == 'trip' else (
            'ATTRIBUTION_QUARTER_DIFFERS' if got == want == 'quarter' else
            'ATTRIBUTION_' + got.upper() + '_VS_' + want.upper())
        return dict(outcome='MISMATCH', reason=reason)
    item_compared = ((b.get('item') or '') != (a.get('item') or '') and a.get('item') != '분기 기타비용'
                     and (b.get('classification_source') or '') not in IMPORT_SOURCES)
    if item_compared and (judged.get('item') or '') != (a.get('item') or ''):
        return dict(outcome='MISMATCH', reason='ITEM_DIFFERS')
    return dict(outcome='MATCH', reason='')


def evaluate(conn, trips, *, review_id=None, nets=None, evidence=None):
    cases = collect_cases(conn, review_id)
    results = rejudge(conn, trips, cases, nets=nets, evidence=evidence) if cases else []
    reasons_ok = reasons_allowed(cases)
    mismatch, not_rejudged = Counter(), Counter()
    by_type = Counter()
    for case, result in zip(cases, results):
        if result['outcome'] == 'MATCH':
            continue
        t = case_type(case, reasons_ok)
        (mismatch if result['outcome'] == 'MISMATCH' else not_rejudged)[result['reason']] += 1
        by_type[_type_key(dict(t, result=result['reason']))] += 1
    return dict(cases=len(cases), matched=sum(r['outcome'] == 'MATCH' for r in results),
                mismatched=sum(mismatch.values()), by_reason=dict(sorted(mismatch.items())),
                not_rejudged=sum(not_rejudged.values()), not_rejudged_by_reason=dict(sorted(not_rejudged.items())),
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
    parser.add_argument('--evidence-cache', type=Path, help='Derived booking-evidence cache under host backups.')
    parser.add_argument('--no-evidence', action='store_true', help='Skip booking/mail evidence (faster, less faithful).')
    parser.add_argument('--fail-on-mismatch', action='store_true')
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    db = args.db or host / 'data/board.sqlite'
    try:
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
            trips, nets = load_context(conn, host)
            evidence = {} if args.no_evidence else load_review_evidence(conn, host, trips, args.evidence_cache)[0]
            report = evaluate(conn, trips, review_id=args.review_id, nets=nets, evidence=evidence)
            if case_path.is_file():
                saved = json.loads(case_path.read_text(encoding='utf-8'))
                report['type_counts_match_case_file'] = (
                    saved.get('types') == aggregate(collect_cases(conn, args.review_id)))
            print(json.dumps(dict(status='EVALUATED', **report), ensure_ascii=False, sort_keys=True))
            return 2 if args.fail_on_mismatch and (report['mismatched'] or report['not_rejudged']) else 0
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__
        print(json.dumps(dict(status='FAILED', code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
