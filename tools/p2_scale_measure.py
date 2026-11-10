"""Reproducible synthetic scale measurement for P2 lock and read budgets.

No customer data, no model, no network. Everything lives under --root
(default .local-archive/p2-scale-20261111, git-ignored).

  python tools/p2_scale_measure.py generate --cases 2000 --mail-bytes 1100000000
  python tools/p2_scale_measure.py measure --mode off --label new-off
  python tools/p2_scale_measure.py measure --mode on --label new-on

To measure another checkout with the same data, put it first on PYTHONPATH:
  $env:PYTHONPATH='<checkout>'; python tools/p2_scale_measure.py measure ...
Each measurement copies the pristine ledger, so runs are independent.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / '.local-archive' / 'p2-scale-20261111'
PORT = '12345'


def _env(route=None):
    os.environ.update(WEBLEDGER_UNIFIED_DB='1', WEBLEDGER_CARD_FLOW='1', WEBLEDGER_REVIEW_FROM='',
                      WEBLEDGER_OTA_REVIEW_MODE='legacy')
    os.environ.pop('WEBLEDGER_AUTONOMOUS_AI_REVIEW', None)
    if route:
        os.environ.update(WEBLEDGER_DEPLOYMENT_ROUTE=str(route), WEBLEDGER_DEPLOYMENT_PORT=PORT)


def _helpers():
    if str(ROOT) not in sys.path:
        sys.path.append(str(ROOT))  # test helpers only; code under test comes first on sys.path
    from webapp.card_flow import CardFlow
    CardFlow.trip_valid = lambda self, target: True
    from webapp.tests import test_autonomous_cleanup as helpers
    return helpers


def _message(rng, identity, subject, body):
    data = base64.urlsafe_b64encode(body.encode('utf-8')).decode('ascii')
    return dict(id=identity, internalDate=str(1791000000000 + rng.randrange(10**8)),
                payload=dict(mimeType='text/plain', headers=[
                    dict(name='Subject', value=subject), dict(name='From', value='synthetic@example.invalid'),
                    dict(name='Date', value='Sat, 03 Oct 2026 10:00:00 +0900')], body=dict(data=data)))


def generate(args):
    root = Path(args.root)
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f'{root} is not empty; refusing to overwrite')
    _env()
    helpers = _helpers()
    from webapp.ledger_store import LedgerStore
    data = root / 'pristine'
    data.mkdir(parents=True)
    board = LedgerStore(data / 'ledger.sqlite', seed_demo=False)
    trip = helpers.create_trip(board)
    batch, rows = helpers.receive(board, args.cases)
    ids = helpers.make_weak_rows(board, batch, rows, trip)
    board.close()
    rng = random.Random(20261111)
    vocabulary = [''.join(rng.choice('abcdefghijklmnoprstuvwy') for _ in range(rng.randrange(3, 11)))
                  for _ in range(6000)]
    mail = root / 'mail'
    mail.mkdir()
    (mail / 'collection.json').write_text(json.dumps(dict(after='2026-09-01', before='2026-11-01',
                                                          query_exhausted=True)), encoding='utf-8')
    written, file_no, message_no, relevant = 0, 0, 0, 0
    while written < args.mail_bytes:
        messages = []
        size = 0
        while size < args.file_bytes:
            words = rng.choices(vocabulary, k=args.message_words)
            subject = 'Synthetic newsletter ' + str(message_no)
            if message_no % args.relevant_every == 0 and relevant < args.cases:
                case = (message_no // args.relevant_every) * 7 % args.cases
                subject = f'SYNTHETIC AUTONOMY {case} 예약 확인'
                words[:4] = ['AUTONOMY', str(case), str(10000 + case), '2026-10-03']
                relevant += 1
            message = _message(rng, f'synthetic-{message_no:08d}', subject, ' '.join(words))
            messages.append(message)
            size += len(message['payload']['body']['data']) + 400
            message_no += 1
        path = mail / f'gmail-{file_no:04d}.json'
        path.write_text(json.dumps(dict(responses=messages)), encoding='utf-8')
        written += path.stat().st_size
        file_no += 1
    manifest = dict(cases=len(ids), mail_files=file_no, mail_messages=message_no, relevant_messages=relevant,
                    mail_bytes=sum(p.stat().st_size for p in mail.iterdir()))
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest))


class TimedLock:
    """Records wait and outermost hold time of the worker thread only."""
    def __init__(self, inner, name, stats, owner):
        self.inner, self.name, self.stats, self.owner = inner, name, stats, owner
        self.local = threading.local()

    def acquire(self, *a, **k):
        started = time.perf_counter()
        ok = self.inner.acquire(*a, **k)
        depth = getattr(self.local, 'depth', 0)
        if ok and threading.get_ident() == self.owner[0]:
            if depth == 0:
                self.local.since = time.perf_counter()
                self.stats[self.name]['wait'].append(self.local.since - started)
            self.local.depth = depth + 1
        return ok

    def release(self):
        if threading.get_ident() == self.owner[0]:
            self.local.depth -= 1
            if self.local.depth == 0:
                self.stats[self.name]['hold'].append(time.perf_counter() - self.local.since)
        return self.inner.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _summary(values):
    values = sorted(values)
    if not values:
        return dict(count=0, total_s=0, max_s=0, p95_s=0)
    return dict(count=len(values), total_s=round(sum(values), 4), max_s=round(values[-1], 4),
                p95_s=round(values[min(len(values) - 1, int(len(values) * .95))], 4))


COMPETITOR = r'''
import json, sqlite3, sys, time
from pathlib import Path
from webapp.deployment_role import route_lock
route, db, out, stop = map(Path, sys.argv[1:5])
waits = {"route": [], "db_write": []}
conn = sqlite3.connect(str(db), timeout=60, isolation_level=None)
while not stop.exists():
    t = time.perf_counter()
    with route_lock(route):
        waits["route"].append(time.perf_counter() - t)
    t = time.perf_counter()
    conn.execute("BEGIN IMMEDIATE"); conn.execute("ROLLBACK")
    waits["db_write"].append(time.perf_counter() - t)
    time.sleep(.1)
out.write_text(json.dumps(waits))
'''


def measure(args):
    root = Path(args.root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    run = root / 'runs' / args.label
    if run.exists():
        shutil.rmtree(run)  # owned synthetic run copy only
    (run / 'data').mkdir(parents=True)
    (run / 'config').mkdir()
    shutil.copy2(root / 'pristine' / 'ledger.sqlite', run / 'data' / 'ledger.sqlite')
    (run / 'config' / 'card-flow.json').write_text(json.dumps(dict(
        autonomous_ai_review=args.mode == 'on', autonomous_ai_review_daily_cap=60)), encoding='utf-8')
    route = run / 'route.json'
    route.write_text(json.dumps(dict(paused=False, port=int(PORT))), encoding='utf-8')
    _env(route)
    helpers = _helpers()
    import psutil
    from app import p2_case
    from webapp import deployment_role
    from webapp.autonomous_cleanup_worker import AutonomousCleanupWorker
    from webapp.ledger_store import LedgerStore
    board = LedgerStore(run / 'data' / 'ledger.sqlite', seed_demo=False)
    stats = {name: dict(wait=[], hold=[]) for name in ('route', 'runtime', 'board')}
    owner = [threading.get_ident()]
    raw_board_lock, runtime = board._lock, threading.RLock()
    board._lock = TimedLock(raw_board_lock, 'board', stats, owner)
    original_route_lock = deployment_role.route_lock
    from contextlib import contextmanager

    @contextmanager
    def timed_route_lock(path):
        mine = threading.get_ident() == owner[0]
        started = time.perf_counter()
        with original_route_lock(path):
            since = time.perf_counter()
            if mine:
                stats['route']['wait'].append(since - started)
            try:
                yield
            finally:
                if mine:
                    stats['route']['hold'].append(time.perf_counter() - since)
    deployment_role.route_lock = timed_route_lock

    counts = dict(select_calls=0, assembled_cases=set(), provider_calls=0, provider_cases=0)
    repository = p2_case.Repository(board.conn, {'mail_directories': [root / 'mail']})
    original_select = repository.select

    def select(case, row):
        counts['select_calls'] += 1
        counts['assembled_cases'].add(row['transaction_id'])
        return original_select(case, row)
    repository.select = select

    def provider(request):
        counts['provider_calls'] += 1
        counts['provider_cases'] += len(request['cases'])
        result = helpers.response_for(request)
        result['more_evidence'] = []
        for item in result['results']:
            item.update(service_start='', service_end='', evidence_refs=[], rule_ids=['PROC-001'])
        return result
    worker = AutonomousCleanupWorker(board, TimedLock(runtime, 'runtime', stats, owner),
                                     provider=provider if args.mode == 'on' else None,
                                     evidence_repository=repository)

    competitor = dict(route=[], board=[])
    stop = threading.Event()

    def compete():
        while not stop.is_set():
            started = time.perf_counter()
            with original_route_lock(route):
                with raw_board_lock:
                    competitor['board'].append(time.perf_counter() - started)
            stop.wait(.1)
    thread = threading.Thread(target=compete, daemon=True)
    out, stop_file = run / 'competitor.json', run / 'competitor.stop'
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    process = subprocess.Popen([sys.executable, '-c', COMPETITOR, str(route), str(run / 'data' / 'ledger.sqlite'),
                                str(out), str(stop_file)], env=env)
    me = psutil.Process()
    io_before, started = me.io_counters(), time.perf_counter()
    thread.start()
    sweeps = []
    try:
        for _ in range(args.sweeps):
            io0, t0 = me.io_counters(), time.perf_counter()
            result = worker.sweep_once()
            io1 = me.io_counters()
            sweeps.append(dict(result=result, elapsed_s=round(time.perf_counter() - t0, 3),
                               read_bytes=io1.read_bytes - io0.read_bytes,
                               repository_read_bytes=getattr(repository, 'read_bytes', None)))
    finally:
        stop.set()
        thread.join(10)
        stop_file.write_text('stop', encoding='utf-8')
        process.wait(120)
    io_after = me.io_counters()
    conn = board.conn
    reservations = conn.execute("SELECT COUNT(*) FROM requests WHERE scope='p2_call_reservation'").fetchone()[0]
    applied = conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_source='ai_inference'").fetchone()[0]
    jobs = {}
    for (raw,) in conn.execute("SELECT response_json FROM requests WHERE scope='autonomous_cleanup_job'"):
        job = json.loads(raw)
        key = job.get('status', '?') + (':' + job['reason'] if job.get('reason') else '')
        jobs[key] = jobs.get(key, 0) + 1
    outside = json.loads(out.read_text(encoding='utf-8'))
    report = dict(
        label=args.label, mode=args.mode, code=subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(p2_case.__file__).parents[1],
                                                            capture_output=True, text=True).stdout.strip(),
        cases=manifest['cases'], evidence_bytes_on_disk=manifest['mail_bytes'], mail_messages=manifest['mail_messages'],
        sweeps=sweeps, elapsed_s=round(time.perf_counter() - started, 3),
        process_read_bytes=io_after.read_bytes - io_before.read_bytes,
        process_read_ops=io_after.read_count - io_before.read_count,
        peak_rss_bytes=me.memory_info().peak_wset if hasattr(me.memory_info(), 'peak_wset') else None,
        assembled_cases=len(counts['assembled_cases']), select_calls=counts['select_calls'],
        provider_calls=counts['provider_calls'], provider_cases=counts['provider_cases'],
        reservations=reservations, ai_applied=applied, jobs=jobs,
        worker_locks={name: {k: _summary(v) for k, v in value.items()} for name, value in stats.items()},
        competitor_thread_route_board_wait=_summary(competitor['board']),
        competitor_process_route_wait=_summary(outside['route']),
        competitor_process_db_write_wait=_summary(outside['db_write']))
    board.close()
    text = json.dumps(report, indent=2, ensure_ascii=False)
    (run / 'report.json').write_text(text, encoding='utf-8')
    print(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('generate')
    gen.add_argument('--root', default=str(DEFAULT))
    gen.add_argument('--cases', type=int, default=2000)
    gen.add_argument('--mail-bytes', type=int, default=1_100_000_000)
    gen.add_argument('--file-bytes', type=int, default=50_000_000)
    gen.add_argument('--message-words', type=int, default=12000)
    gen.add_argument('--relevant-every', type=int, default=40)
    mes = sub.add_parser('measure')
    mes.add_argument('--root', default=str(DEFAULT))
    mes.add_argument('--mode', choices=('off', 'on'), required=True)
    mes.add_argument('--label', required=True)
    mes.add_argument('--sweeps', type=int, default=3)
    args = parser.parse_args()
    (generate if args.command == 'generate' else measure)(args)


if __name__ == '__main__':
    main()
