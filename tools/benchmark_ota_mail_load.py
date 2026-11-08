"""Fixed synthetic input, fresh process per phase; no operating source is opened."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
import time

args = argparse.ArgumentParser()
args.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
args.add_argument('--fixture', required=True, help='Dedicated synthetic fixture directory; create refuses existing directories')
args.add_argument('--phase', choices=['create', 'catalog', 'reconcile'], required=True)
args.add_argument('--output')
opts = args.parse_args()
sys.path.insert(0, opts.root)
fixture = Path(opts.fixture).resolve()
if opts.phase == 'create':
    fixture.mkdir(parents=True, exist_ok=False)
elif not (fixture / 'manifest.json').is_file():
    raise SystemExit('SYNTHETIC_MANIFEST_REQUIRED')
source = fixture / 'sources.sqlite'
board_path = fixture / 'board.sqlite'
sources = {'mail_directories': [str(source)], 'portal_databases': [], 'reference_documents': []}

if opts.phase == 'create':
    if source.exists():
        raise SystemExit('FIXTURE_EXISTS_DO_NOT_REGENERATE')
    from tests.card_pipeline.test_booking_mail import message
    from tests.card_pipeline.test_ota_sources_registry import write_mail
    from app.ota_store import OtaStore
    from webapp.ledger_store import LedgerStore
    from webapp.card_flow import CardFlow
    store = OtaStore(source)
    for index in range(4):
        messages = []
        for number in range(80):
            item = message(f'예약번호: BOOK{12345000+number}\n총 금액 30,000원',
                subject='[Trip.com] 결제 완료 안내', identity=f'synthetic-{number}')
            item['attachment_metadata'] = 'x' * (128 * 1024)
            messages.append(item)
        directory = write_mail(fixture / f'mail-{index}', messages)
        store.import_mail(directory)
    store.close()
    board = LedgerStore(board_path, seed_demo=False)
    CardFlow(board)
    board.close()
    (fixture / 'manifest.json').write_text(json.dumps({'synthetic_ota_mail_benchmark': True, 'unique_messages': 80, 'source_scopes': 4,
        'observations': 320, 'padding_per_message': 128*1024,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}), encoding='utf-8')
    print('SYNTHETIC_FIXED_INPUT_CREATED')
    raise SystemExit(0)

manifest = json.loads((fixture / 'manifest.json').read_text(encoding='utf-8'))
if manifest.get('synthetic_ota_mail_benchmark') is not True:
    raise SystemExit('SYNTHETIC_MANIFEST_REQUIRED')
if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['source_sha256']:
    raise SystemExit('SYNTHETIC_SOURCE_CHANGED')

os.environ['WEBLEDGER_OTA_SOURCES_JSON'] = json.dumps(sources)
os.environ['WEBLEDGER_OTA_REVIEW_DB'] = str(fixture / 'review.sqlite')
for key in ['WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', 'WEBLEDGER_REVIEW_CONFIG', 'WEBLEDGER_TRIP_AUTHORITY']:
    os.environ.pop(key, None)
request = fixture / (opts.phase + '.request')
result = fixture / (opts.phase + '.result')
if opts.phase == 'catalog':
    from webapp import ota_catalog_sources_child
    request.write_bytes(pickle.dumps(sources))
    run = lambda: ota_catalog_sources_child.run(board_path, request, result)
else:
    from webapp import ota_reconcile_child
    request.write_bytes(pickle.dumps({'authority': None}))
    run = lambda: ota_reconcile_child.run(opts.root, board_path, request, result)

wall = time.perf_counter()
cpu = time.process_time()
run()
elapsed = time.perf_counter() - wall
cpu_seconds = time.process_time() - cpu

class Memory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
        ('PrivateUsage', ctypes.c_size_t)]

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = wintypes.HANDLE
psapi = ctypes.WinDLL('psapi', use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
memory = Memory()
memory.cb = ctypes.sizeof(memory)
if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb):
    raise ctypes.WinError(ctypes.get_last_error())
peak_private = memory.PeakPagefileUsage
peak_working = memory.PeakWorkingSetSize

payload = pickle.loads(result.read_bytes())
from app import ota_mail
report = {'phase': opts.phase, 'status': payload[0], 'wall_seconds': elapsed,
    'cpu_seconds': cpu_seconds, 'peak_private_bytes': peak_private,
    'peak_working_set_bytes': peak_working, 'retained_body_entries': len(ota_mail._BODY_TEXT),
    'input': json.loads((fixture / 'manifest.json').read_text(encoding='utf-8')),
    'source_unchanged': hashlib.sha256(source.read_bytes()).hexdigest() ==
        json.loads((fixture / 'manifest.json').read_text(encoding='utf-8'))['source_sha256']}
if payload[0] == 'ok':
    if opts.phase == 'catalog':
        report['rows'] = len(payload[1])
        normalized = [(key, sorted(value['labels']), sorted(value['periods']), sorted(value['statuses']))
                      for key, value in sorted(payload[1].items())]
    else:
        report['rows'] = len(payload[1]['results'])
        normalized = {key: payload[1][key] for key in ['results', 'links', 'queue_summary']}
    report['result_sha256'] = hashlib.sha256(json.dumps(normalized, sort_keys=True,
        ensure_ascii=False, default=str).encode()).hexdigest()
else:
    report['error_type'] = payload[1]
if opts.output:
    Path(opts.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))

