"""ota-evidence.sqlite에 이미 쌓인 메일 근거 중복을 압축한다 (A-2).

같은 (예약 키·entry_key·사실 내용) 그룹에서 처음 관측된 행(rowid 최소) 하나만 남기고 나머지를 지운다.
지워지는 행의 관측 정보(판 범위·관측 시각·횟수)는 ota_row_seen에 합쳐 남긴다(#905 의미). 관측(ota_reservation_observations)은
같은 원천(source) 안에서만 같은 그룹으로 본다. 원문 표(ota_raw_blobs, ota_messages)와 ota_raw_entries는 건드리지 않는다.

--apply는 한 트랜잭션(BEGIN IMMEDIATE)에서 압축 전후 읽기 결과(direct_facts·catalog_rows·OTA 결제 이벤트·core_bridge
links 출력)의 바이트 해시와 고유 사실 수를 대조하고, 다르면 롤백한다. 고객 원문·ID는 출력하지 않는다(건수·해시 앞자리만).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_HOST = Path('D:/WebLedgerHost')
BATCH = 5000
TABLES = (
    # 표, 소유자 열, 행 종류, 같은 그룹 조건에 원천을 포함할지, 표에 붙는 인덱스 개수
    dict(table='ota_booking_evidence', owner='booking_id', kind='evidence', by_source=False,
         where="evidence_kind='mail'"),
    dict(table='ota_reservation_observations', owner='observation_id', kind='observation', by_source=True,
         where='1=1'),
)


class Refused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def require_backup(host, evidence):
    """운영 파일 apply 전: 신선(1시간)하고 ota-evidence.sqlite를 덮는 #906 범위 백업 증거."""
    from tools.verify_operational_backup_restore import backup_covers
    if not evidence:
        raise Refused('BACKUP_EVIDENCE_REQUIRED')
    try:
        saved = json.loads(Path(evidence).read_text(encoding='utf-8-sig'))
        recorded = datetime.fromisoformat(saved['recorded_at'])
        directory = Path(saved['backup_directory']).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused('BACKUP_RESTORE_NOT_VERIFIED') from None
    if any(saved.get(key) is not True for key in ('live_state_unchanged', 'restored_review_binding_equal')) \
            or not backup_covers(saved, host, ['ota-evidence.sqlite']):
        raise Refused('BACKUP_RESTORE_NOT_VERIFIED')
    if recorded.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - recorded).total_seconds() < 3600:
        raise Refused('BACKUP_NOT_FRESH')
    if not directory.is_relative_to((host / 'data/backups').resolve()):
        raise Refused('BACKUP_LOCATION_INVALID')


def is_operational(db, host):
    return Path(db).resolve().is_relative_to((Path(host) / 'data').resolve())


def _revisions(conn):
    return {r[0]: (r[1], r[2]) for r in conn.execute('SELECT revision_id,source_id,observed_at FROM ota_source_revisions')}


def _merge(parts):
    """같은 대상 키의 관측 조각을 하나로: 가장 이른 첫 관측, 가장 늦은 마지막 관측, 횟수 합."""
    first = min(parts, key=lambda p: (p['first_at'], p['first']))
    last = max(parts, key=lambda p: (p['last_at'], p['last']))
    return dict(first=first['first'], first_at=first['first_at'], last=last['last'], last_at=last['last_at'],
                count=sum(p['count'] for p in parts))


def _bucket_groups(rows, by_source, revisions):
    """한 (소유자, entry_key) 안에서 사실이 같은 그룹을 돌려준다. rows는 rowid 순."""
    groups = {}
    for rowid, revision, fact in rows:
        key = (fact, revisions[revision][0]) if by_source else fact
        groups.setdefault(key, []).append((rowid, revision))
    return list(groups.values())


def plan_table(conn, spec, revisions):
    """삭제할 rowid와 ota_row_seen 변경을 만든다. 쓰기 없음."""
    table, owner_col, kind = spec['table'], spec['owner'], spec['kind']
    plan = dict(spec=spec, delete=[], seen_delete=[], seen_insert=[], groups=0, rows=0, synthesized=0,
                est_bytes=0, distinct=0, total=0)
    bucket_key, bucket = None, []

    def flush():
        if not bucket:
            return
        owner, entry = bucket_key
        groups = _bucket_groups([(r[0], r[1], r[2]) for r in bucket], spec['by_source'], revisions)
        plan['distinct'] += len({(r[2], revisions[r[1]][0]) if spec['by_source'] else r[2] for r in bucket})
        plan['total'] += len(bucket)
        by_rowid = {r[0]: r for r in bucket}
        seen = defaultdict(list)
        for row in conn.execute('SELECT home_revision,source_id,first_revision,last_revision,first_observed_at,'
                                'last_observed_at,seen_count FROM ota_row_seen WHERE kind=? AND owner_id=? '
                                'AND entry_key=?', (kind, owner, entry)):
            seen[row[0]].append(row)
        for members in groups:
            keep_rowid, keep_revision = members[0]
            if len(members) == 1 and any(r[1] == revisions[keep_revision][0] for r in seen.get(keep_revision, ())):
                continue
            parts = defaultdict(list)
            for rowid, revision in members:
                source, observed = revisions[revision]
                own = False
                for home, src, first, last, first_at, last_at, count in seen.get(revision, ()):
                    parts[src].append(dict(first=first, first_at=first_at, last=last, last_at=last_at, count=count))
                    plan['seen_delete'].append((kind, owner, entry, home, src))
                    own |= src == source
                if not own:
                    parts[source].append(dict(first=revision, first_at=observed, last=revision, last_at=observed,
                                              count=1))
                    plan['synthesized'] += 1
            for src, items in parts.items():
                m = _merge(items)
                plan['seen_insert'].append((kind, owner, entry, keep_revision, src, m['first'], m['last'],
                                            m['first_at'], m['last_at'], m['count']))
            plan['groups'] += len(members) > 1
            for rowid, _ in members[1:]:
                _, _, fact, extra = by_rowid[rowid]
                plan['delete'].append(rowid)
                plan['rows'] += 1
                plan['est_bytes'] += extra + len(fact.encode('utf-8'))

    query = ('SELECT rowid,' + owner_col + ',revision_id,entry_key,fact_json FROM ' + table + ' WHERE ' + spec['where']
             + ' ORDER BY ' + owner_col + ',entry_key,rowid')
    for rowid, owner, revision, entry, fact in conn.execute(query):
        if (owner, entry) != bucket_key:
            flush()
            bucket_key, bucket = (owner, entry), []
        # 행 고정 크기 추정: 표 행(소유자·판·키·종류) + 인덱스 2개(소유자+판+키, 소유자+키)
        extra = 3 * len(owner) + 2 * len(revision) + 3 * len(entry) + 60
        bucket.append((rowid, revision, fact, extra))
    flush()
    return plan


def make_plan(conn):
    revisions = _revisions(conn)
    return [plan_table(conn, spec, revisions) for spec in TABLES]


def summarize(plans):
    out = {}
    for plan in plans:
        name = plan['spec']['table']
        out[name] = dict(rows_total=plan['total'], distinct_facts=plan['distinct'], groups_compacted=plan['groups'],
                         rows_to_delete=plan['rows'])
    out['seen_rows_rewritten'] = sum(len(p['seen_insert']) for p in plans)
    out['seen_rows_synthesized'] = sum(p['synthesized'] for p in plans)
    out['estimated_bytes_saved'] = sum(p['est_bytes'] for p in plans)
    return out


class _Shared:
    """읽기 함수가 같은 쓰기 연결(미커밋 상태)을 보도록 connect_read 자리에 끼우는 닫히지 않는 연결."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args):
        return self._conn.execute(*args)

    def close(self):
        pass


def _feed(digest, value):
    from app.ota_store import encoded
    digest.update(encoded(value).encode('utf-8'))
    digest.update(b'\n')


def read_digest(conn, path):
    """압축 전후 비교용 읽기 출력의 바이트 해시와 고유 사실 수."""
    from app import ota_payments, ota_store
    from tools.core_bridge.commands import canonical, links
    real = ota_store.connect_read
    ota_store.connect_read = lambda _path: _Shared(conn)
    try:
        parts = {}
        digest = hashlib.sha256()
        for booking, fact, conflicts in ota_store.direct_facts(conn):
            _feed(digest, [dict(booking), fact, conflicts])
        parts['direct_facts'] = digest.hexdigest()
        digest = hashlib.sha256()
        for row in ota_store.catalog_rows(conn):
            _feed(digest, row)
        parts['catalog_rows'] = digest.hexdigest()
        sources = {'mail_directories': [path], 'portal_databases': [path],
                   'registered': {'mail_directories': [path], 'portal_databases': [path]}}
        events = [{k: v for k, v in e.items() if k != 'source_inventory'}
                  for e in ota_payments.build_ota_payment_events(sources)]
        digest = hashlib.sha256()
        for event in events:
            _feed(digest, event)
        parts['payment_events'] = digest.hexdigest()
        parts['bridge_links'] = hashlib.sha256(json.dumps(
            canonical(links({'kind': 'ota', 'events': events, 'transactions': []})),
            ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        parts['event_count'] = len(events)
    finally:
        ota_store.connect_read = real
    return parts


def distinct_counts(plans):
    return {p['spec']['table']: (p['total'], p['distinct']) for p in plans}


def open_write(db):
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=rw', uri=True, isolation_level=None, timeout=1)
    conn.row_factory = sqlite3.Row
    return conn


def open_read(db):
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)
    conn.execute('PRAGMA query_only=ON')
    return conn


def _size(db):
    path = Path(db)
    return sum(p.stat().st_size for p in (path, path.with_name(path.name + '-wal')) if p.exists())


def apply_plans(conn, plans):
    for plan in plans:
        table = plan['spec']['table']
        conn.executemany('DELETE FROM ota_row_seen WHERE kind=? AND owner_id=? AND entry_key=? AND home_revision=? '
                         'AND source_id=?', plan['seen_delete'])
        conn.executemany('INSERT INTO ota_row_seen(kind,owner_id,entry_key,home_revision,source_id,first_revision,'
                         'last_revision,first_observed_at,last_observed_at,seen_count) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         plan['seen_insert'])
        for start in range(0, len(plan['delete']), BATCH):
            chunk = plan['delete'][start:start + BATCH]
            conn.execute('DELETE FROM ' + table + ' WHERE rowid IN (' + ','.join('?' * len(chunk)) + ')', chunk)


def seen_totals(conn):
    return tuple(conn.execute('SELECT count(*),coalesce(sum(seen_count),0) FROM ota_row_seen').fetchone())


def run_apply(db):
    started = time.monotonic()

    def phase(name):
        print('phase', name, round(time.monotonic() - started, 1), file=sys.stderr, flush=True)

    conn = open_write(db)
    try:
        try:
            conn.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError:
            raise Refused('WRITE_LOCK_NOT_ACQUIRED') from None
        try:
            plans = make_plan(conn)
            summary = summarize(plans)
            phase('planned')
            before = read_digest(conn, db)
            phase('digest_before')
            before_totals, counts_before = seen_totals(conn), distinct_counts(plans)
            apply_plans(conn, plans)
            phase('applied')
            after = read_digest(conn, db)
            phase('digest_after')
            after_plans = make_plan(conn)
            counts_after = distinct_counts(after_plans)
            if before != after:
                raise Refused('EQUIVALENCE_MISMATCH')
            if {t: v[1] for t, v in counts_before.items()} != {t: v[1] for t, v in counts_after.items()}:
                raise Refused('DISTINCT_FACT_COUNT_CHANGED')
            if any(p['rows'] for p in after_plans):
                raise Refused('COMPACTION_INCOMPLETE')
            expected = before_totals[1] + summary['seen_rows_synthesized']
            if seen_totals(conn)[1] != expected:
                raise Refused('SEEN_COUNT_NOT_CONSERVED')
            if conn.execute('PRAGMA foreign_key_check').fetchall():
                raise Refused('FOREIGN_KEY_CHECK_FAILED')
            conn.execute('COMMIT')
            phase('committed')
        except BaseException:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
    finally:
        conn.close()
    return dict(summary, equivalence='equal', digests={k: v[:12] for k, v in after.items() if k != 'event_count'},
                payment_events=after['event_count'], seconds_apply=round(time.monotonic() - started, 1))


def run_vacuum(db):
    conn = open_write(db)
    try:
        started = time.monotonic()
        conn.execute('VACUUM')
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return round(time.monotonic() - started, 1)
    except sqlite3.OperationalError:
        raise Refused('WRITE_LOCK_NOT_ACQUIRED') from None
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--vacuum', action='store_true', help='압축 뒤(또는 단독으로) VACUUM. 파일 크기를 줄인다.')
    parser.add_argument('--backup-evidence', type=Path)
    parser.add_argument('--host-root', type=Path, default=DEFAULT_HOST)
    args = parser.parse_args(argv)
    try:
        if args.dry_run == (args.apply or args.vacuum):
            raise Refused('MODE_REQUIRED_DRY_RUN_OR_APPLY')
        if not args.db.is_file():
            raise Refused('DB_NOT_FOUND')
        from app.ota_store import is_store
        if not is_store(args.db):
            raise Refused('NOT_AN_OTA_STORE')
        if not args.dry_run and is_operational(args.db, args.host_root):
            require_backup(args.host_root.resolve(), args.backup_evidence)
        size_before = _size(args.db)
        report = {'status': 'DRY_RUN' if args.dry_run else 'APPLIED', 'db_bytes_before': size_before}
        if args.dry_run:
            started = time.monotonic()
            with closing(open_read(args.db)) as conn:
                conn.execute('BEGIN')
                report.update(writes=0, **summarize(make_plan(conn)))
            report['seconds'] = round(time.monotonic() - started, 1)
        else:
            if args.apply:
                report.update(run_apply(args.db))
            if args.vacuum:
                report['seconds_vacuum'] = run_vacuum(args.db)
            report['db_bytes_after'] = _size(args.db)
        print(json.dumps(report))
        return 0
    except Refused as exc:
        code = exc.code
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        code = type(exc).__name__
    print(json.dumps({'status': 'FAILED', 'code': code}))
    return 2 if code.startswith(('BACKUP', 'WRITE_LOCK', 'MODE', 'DB_NOT', 'NOT_AN')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
