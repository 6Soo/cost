"""저장된 카드 분류 규칙 가운데 다시 작동할 수 없거나 현지 사용 기본 규칙과 같은 결과를 내는 규칙을 정리한다.

규칙은 지우지 않고 status를 retired로 바꾸며, 실행마다 change_log에 남겨 --restore로 되돌릴 수 있다.
기본은 대상만 보여 준다. --apply를 줘야 바꾼다.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.classify import _pattern_for
from app.db import canonical, decided_sql, utc_now

# 장부 기록·사용자 결정 또는 명시한 조회 기간 밖인 거래의 규칙을 구분한다.
CLOSED_TRANSACTION = 'closed-transaction'
# 현지 사용 기본 규칙('*' → 현지경비)과 같은 거래에 같은 항목·여행을 낸다.
SAME_AS_LOCAL_DEFAULT = 'same-as-local-default'
LOCAL_DEFAULT = {'optional': {'travel_country': 'local'}, 'effects': {'item': '현지경비'}}


def _active_rules(conn):
    return [{'rule_id': r[0], 'conditions': json.loads(r[1]), 'effects': json.loads(r[2]),
             'optional': json.loads(r[3]), 'origin': r[4]}
            for r in conn.execute("SELECT rule_id, conditions_json, effects_json, optional_json, origin"
                                  " FROM cost_classification_rules WHERE status='active' ORDER BY rule_id")]


def _local_like(rule):
    return (rule['optional'] == LOCAL_DEFAULT['optional'] and rule['effects'] == LOCAL_DEFAULT['effects']
            and rule['conditions'].get('transaction_direction') == 'purchase')


def candidates(conn, review_from=''):
    """정리할 (rule_id, 사유, 출처) 목록."""
    rules = _active_rules(conn)
    states = collections.defaultdict(set)
    for source, decided, booked, state, day in conn.execute(
            "SELECT source_hash, " + decided_sql('t') + ", EXISTS(SELECT 1 FROM ledger_entries l"
            " WHERE l.transaction_id=t.transaction_id), classification_state,"
            " COALESCE(NULLIF(approval_date,''), posting_date) FROM transactions t"):
        states[source].add(bool(booked or decided or (review_from and day and day < review_from)))
    found = [(r['rule_id'], CLOSED_TRANSACTION, r['origin']) for r in rules
             if r['optional'].get('source_hash') and states.get(r['optional']['source_hash']) == {True}]
    closed = {rule_id for rule_id, _, _ in found}
    remaining = [r for r in rules if r['rule_id'] not in closed]
    if not any(r['conditions'].get('merchant_normalized') == '*' and _local_like(r) for r in remaining):
        return found
    by_merchant = collections.defaultdict(list)
    for rule in remaining:
        by_merchant[rule['conditions']['merchant_normalized']].append(rule)
    categorized = {m for (m,) in conn.execute(
        "SELECT DISTINCT merchant_normalized FROM transactions WHERE description_raw LIKE 'card-category:%'")}
    for merchant, group in by_merchant.items():
        # 업종·가맹점 패턴은 기본 규칙보다 먼저 적용되고, 같은 가맹점의 다른 규칙은 함께 맞으면 충돌한다.
        if merchant == '*' or _pattern_for(merchant) or merchant in categorized or not all(map(_local_like, group)):
            continue
        found += [(rule['rule_id'], SAME_AS_LOCAL_DEFAULT, rule['origin']) for rule in group]
    return found


def apply(conn, found, run_id):
    now = utc_now()
    with conn:
        for rule_id, reason, _ in found:
            changed = conn.execute("UPDATE cost_classification_rules SET status='retired', updated_at=?"
                                   " WHERE rule_id=? AND status='active'", (now, rule_id)).rowcount
            if changed:
                conn.execute("INSERT INTO change_log(at, kind, subject, detail_json) VALUES (?,?,?,?)",
                             (now, 'rule.retired', rule_id, canonical({'reason': reason, 'run': run_id})))


def restore(conn, run_id):
    now = utc_now()
    retired = [subject for subject, detail in conn.execute(
        "SELECT subject, detail_json FROM change_log WHERE kind='rule.retired'") if json.loads(detail).get('run') == run_id]
    with conn:
        for rule_id in retired:
            if conn.execute("UPDATE cost_classification_rules SET status='active', updated_at=?"
                            " WHERE rule_id=? AND status='retired'", (now, rule_id)).rowcount:
                conn.execute("INSERT INTO change_log(at, kind, subject, detail_json) VALUES (?,?,?,?)",
                             (now, 'rule.restored', rule_id, canonical({'run': run_id})))
    return len(retired)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--review-from', default='', help='정리 완료 기간의 끝(card-flow.json의 review_from)')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--restore', metavar='RUN_ID')
    args = parser.parse_args(argv)
    conn = sqlite3.connect(args.db, timeout=30)
    try:
        if args.restore:
            print(json.dumps({'restored': restore(conn, args.restore), 'run': args.restore}, ensure_ascii=False))
            return 0
        found = candidates(conn, args.review_from)
        summary = collections.Counter((reason, origin) for _, reason, origin in found)
        report = {'retire': len(found), 'by_reason_origin': {f'{r} {o}': n for (r, o), n in sorted(summary.items())},
                  'active_before': conn.execute("SELECT COUNT(*) FROM cost_classification_rules WHERE status='active'").fetchone()[0]}
        if args.apply:
            report['run'] = 'consolidate-' + utc_now()
            apply(conn, found, report['run'])
        report['active_after'] = conn.execute("SELECT COUNT(*) FROM cost_classification_rules WHERE status='active'").fetchone()[0]
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
